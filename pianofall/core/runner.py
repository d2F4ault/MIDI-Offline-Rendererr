"""
High-level rendering orchestration for individual pieces and batch pipelines.

Employs headless Chromium, deterministic frame-stepping, virtual audio clocks,
in-page canvas compositing, and direct libx264 pipe streaming for pristine 60 FPS video.
Organizes side-by-side MP4 and MIDI outputs and manages the 5-hour runtime budget.
"""

from __future__ import annotations

import asyncio
import datetime
import hashlib
import json
import logging
import os
import shutil
import tempfile
import time
import traceback
from pathlib import Path
from typing import List, Optional, Tuple

from ..config import Config
from ..utils.logging import fmt_bytes, fmt_hms
from ..utils.midi_info import get_midi_duration
from .backend import (
    DETERMINISTIC_CLOCK_JS,
    capture_debug_screenshot,
    capture_one_frame,
    configure_piano_display,
    dismiss_popups,
    hide_navigation_overlays,
    trigger_playback,
    upload_midi_file,
    wait_canvas_ready,
)
from .browser import get_headless_chromium_args, start_xvfb, stop_xvfb
from .recorder import (
    FrameWriter,
    get_png_dimensions,
    get_recorder_error_text,
    start_ffmpeg_pipe,
    stop_ffmpeg_pipe,
    validate_raw_recording,
)

logger = logging.getLogger("pianofall.runner")


async def render_single_midi(
    page,
    midi_path: Path,
    output_dir: Path,
    cfg: Config,
    item_idx: int = 1,
    total_items: int = 1,
    test_seconds: Optional[float] = None,
    run_id: Optional[str] = None,
) -> Tuple[Path, float, int, float]:
    """
    Render a single MIDI file into a silent, genuine 60 FPS MP4 with full 88-key piano view.
    Uses deterministic virtual clock stepping and pipes frames directly into FFmpeg stdin.
    Stores the output inside outputs/<run_id>/mp4/<name>.mp4 and outputs/<run_id>/midis/<name>.mid side-by-side.
    Moves the source MIDI from midis_pool into the output directory upon success to guarantee zero duplicates.
    """
    duration_s = get_midi_duration(midi_path)
    if not duration_s or duration_s <= 0.1:
        raise ValueError(f"Could not read valid duration from MIDI file: {midi_path.name}")

    if test_seconds is not None and test_seconds > 0:
        duration_s = min(duration_s, float(test_seconds))
        logger.info(f"Test mode active: rendering first {duration_s:.1f}s of {midi_path.name}")

    target_frames = max(1, int(round(duration_s * cfg.output_fps)))
    frame_interval_s = 1.0 / cfg.output_fps
    preroll_frames = (
        int(round(cfg.start_delay_s * cfg.output_fps))
        if cfg.align_video_to_midi_t0
        else 0
    )

    current_run_id = run_id or cfg.run_id or datetime.datetime.now(datetime.timezone.utc).strftime("run_%Y-%m-%d_%H%M%S")
    run_out_dir = output_dir / current_run_id
    mp4_out_dir = run_out_dir / "mp4"
    midis_out_dir = run_out_dir / "midis"
    mp4_out_dir.mkdir(parents=True, exist_ok=True)
    midis_out_dir.mkdir(parents=True, exist_ok=True)

    final_output_path = mp4_out_dir / f"{midi_path.stem}.mp4"
    final_midi_path = midis_out_dir / f"{midi_path.stem}{midi_path.suffix}"

    logger.info(f"[{item_idx}/{total_items}] Commencing render: '{midi_path.name}'")
    logger.info(
        f"  Target duration: {fmt_hms(duration_s)} ({duration_s:.2f}s) | "
        f"{cfg.viewport_w}x{cfg.viewport_h} @ {cfg.output_fps} FPS | "
        f"Mode: {cfg.capture_mode} | 88 Keys: {cfg.show_all_88_keys} | Silent output"
    )
    logger.info(f"  Target video: outputs/{current_run_id}/mp4/{final_output_path.name}")
    logger.info(f"  Target MIDI : outputs/{current_run_id}/midis/{final_midi_path.name}")

    # Use RAM disk (/dev/shm) on Linux if available with sufficient space, else temp directory
    shm_candidate = Path("/dev/shm")
    scratch_dir = Path(tempfile.gettempdir())
    if shm_candidate.is_dir():
        try:
            free_bytes = shutil.disk_usage(shm_candidate).free
            if free_bytes > 500 * 1024 * 1024:  # At least 500MB free in RAM
                scratch_dir = shm_candidate
        except Exception:
            pass
    active_output_path = scratch_dir / f"{midi_path.stem}_active.mp4"
    if active_output_path.exists():
        active_output_path.unlink(missing_ok=True)

    ffmpeg_proc = None
    writer = None
    t0 = time.time()
    loop = asyncio.get_running_loop()

    try:
        logger.info("  Loading canvas visualizer web app...")
        await page.goto(cfg.app_url, wait_until="domcontentloaded", timeout=60_000)
        await dismiss_popups(page)
        await wait_canvas_ready(page)

        logger.info("  Injecting MIDI file into player...")
        await upload_midi_file(page, midi_path)

        logger.info("  Configuring keyboard view and recalibrating geometries...")
        await configure_piano_display(page, show_all_88_keys=cfg.show_all_88_keys)

        logger.info("  Hiding UI overlays and controls (waiting for fade)...")
        await hide_navigation_overlays(page, cfg.viewport_w, cfg.viewport_h)

        logger.info(f"  Starting FFmpeg pipe encoder -> {active_output_path.name}")
        ffmpeg_proc = start_ffmpeg_pipe(
            output_path=active_output_path,
            width=cfg.viewport_w,
            height=cfg.viewport_h,
            fps=cfg.output_fps,
            ffmpeg_bin=cfg.ffmpeg_bin,
            preset=cfg.pipe_preset,
            crf=cfg.render_crf,
            pix_fmt=cfg.render_pix_fmt,
            max_bitrate=cfg.max_bitrate,
            bufsize=cfg.buffer_size,
            image_format="png",
        )
        writer = FrameWriter(ffmpeg_proc)

        # Enter virtual stepped clock mode and trigger playback
        await page.evaluate("() => window.__enterSteppedMode()")
        await page.evaluate("() => window.__drainNativeRAF()")
        logger.info("  Triggering playback start (Space)...")
        await trigger_playback(page)

        if preroll_frames > 0:
            logger.info(
                f"  Advancing {preroll_frames} preroll frames ({cfg.start_delay_s}s) to first note strike..."
            )
            await page.evaluate(
                "(args) => { for (let i = 0; i < args.n; i++) window.__advanceFrame(args.dt); }",
                {"dt": frame_interval_s, "n": preroll_frames},
            )

        first_hash = None
        hash_check_frame = min(60, target_frames)

        for frame_i in range(1, target_frames + 1):
            if ffmpeg_proc.poll() is not None:
                err = get_recorder_error_text(ffmpeg_proc)
                raise RuntimeError(
                    f"FFmpeg encoder exited prematurely at frame {frame_i}/{target_frames} "
                    f"({ffmpeg_proc.returncode}):\n{err}"
                )
            if writer.err:
                raise RuntimeError(f"FrameWriter pipeline failure: {writer.err}")

            png_bytes = await capture_one_frame(page, cfg.capture_mode, frame_interval_s)

            if frame_i == 1:
                w, h = get_png_dimensions(png_bytes)
                logger.info(f"  First frame captured: {w}x{h} ({len(png_bytes)} bytes)")
                if (w, h) not in ((0, 0), (cfg.viewport_w, cfg.viewport_h)):
                    logger.warning(
                        f"Captured frame size {w}x{h} differs from viewport {cfg.viewport_w}x{cfg.viewport_h}. "
                        "FFmpeg will scale to match target resolution."
                    )
                first_hash = hashlib.sha1(png_bytes).hexdigest()
            elif frame_i == hash_check_frame and first_hash is not None:
                current_hash = hashlib.sha1(png_bytes).hexdigest()
                if current_hash == first_hash:
                    logger.warning(
                        f"Frame {hash_check_frame} hash identical to frame 1. "
                        "Verifying playback movement..."
                    )

            await loop.run_in_executor(None, writer.push_blocking, png_bytes)

            if frame_i % 300 == 0 or frame_i == target_frames:
                elapsed = time.time() - t0
                actual_fps = frame_i / elapsed if elapsed > 0 else 0.0
                pct = 100.0 * frame_i / target_frames
                eta_s = (target_frames - frame_i) / actual_fps if actual_fps > 0 else 0.0
                virt = await page.evaluate("() => window.__virtualAudioSeconds || 0")
                logger.info(
                    f"  [{item_idx}/{total_items}] {midi_path.stem} | "
                    f"Frame {frame_i}/{target_frames} ({pct:.1f}%) | "
                    f"Elapsed: {fmt_hms(elapsed)} | ETA: {fmt_hms(eta_s)} | "
                    f"{actual_fps:.1f} capture-fps | virt: {virt:.2f}s"
                )

        logger.info("  Draining frame buffer into encoder...")
        writer.finish()
        writer = None

        rc = stop_ffmpeg_pipe(ffmpeg_proc)
        ffmpeg_proc = None
        if rc != 0:
            raise RuntimeError(f"FFmpeg pipe encoder exited with error code {rc}")

        validate_raw_recording(active_output_path, duration_s)

        # Move active output video to final target path inside mp4/
        if active_output_path != final_output_path:
            shutil.move(str(active_output_path), str(final_output_path))

        # Move source MIDI to final target path inside midis/ (physically removes from pool)
        if midi_path.exists() and midi_path != final_midi_path:
            try:
                shutil.move(str(midi_path), str(final_midi_path))
                logger.info(f"  Source MIDI archived to: outputs/{current_run_id}/midis/{final_midi_path.name}")
            except Exception as move_err:
                logger.warning(f"  Could not move source MIDI to {final_midi_path}: {move_err}")
                try:
                    shutil.copy2(str(midi_path), str(final_midi_path))
                    midi_path.unlink(missing_ok=True)
                except Exception:
                    pass

        total_elapsed = time.time() - t0
        final_size = final_output_path.stat().st_size
        logger.info(
            f"  SUCCESS: Generated '{final_output_path.name}' "
            f"({fmt_bytes(final_size)}, render time: {fmt_hms(total_elapsed)})"
        )
        return final_output_path, duration_s, target_frames, total_elapsed

    except Exception as e:
        logger.error(f"Render failed for {midi_path.name}: {e}")
        # Capture on-failure screenshot for remote diagnostics
        debug_path = cfg.data_dir / f"debug_{midi_path.stem}.png"
        await capture_debug_screenshot(page, debug_path)

        if writer is not None:
            try:
                writer.finish(timeout=5.0)
            except Exception:
                pass
        if ffmpeg_proc is not None and ffmpeg_proc.poll() is None:
            try:
                ffmpeg_proc.kill()
            except Exception:
                pass
        raise
    finally:
        if active_output_path.exists():
            active_output_path.unlink(missing_ok=True)


async def execute_batch(
    midi_files: List[Path],
    output_dir: Path,
    cfg: Config,
    test_seconds: Optional[float] = None,
) -> List[Tuple[Path, float, int, float]]:
    """
    Execute rendering for a list of MIDI files using a shared headless Chromium browser.
    Enforces exact target video count and the 5-hour runtime budget ceiling.
    Performs storage cleanup of previous outputs before starting when configured.
    """
    from playwright.async_api import async_playwright
    from ..queue.ledger import append_failed_entry, append_processed_entry, perform_output_cleanup

    # Perform storage cleanup of previous batch outputs if requested
    if cfg.clean_previous_outputs:
        logger.info("Storage management: inspecting outputs directory for previous run assets to purge...")
        n_purged, b_freed = perform_output_cleanup(output_dir, cfg.data_dir)
        if n_purged > 0:
            logger.info(f"Cleaned {n_purged} prior assets ({b_freed / (1024 * 1024):.2f} MB freed).")

    successful_renders: List[Tuple[Path, float, int, float]] = []
    run_id = cfg.run_id or datetime.datetime.now(datetime.timezone.utc).strftime("run_%Y-%m-%d_%H%M%S")
    batch_start_time = time.time()
    max_budget_s = cfg.max_job_seconds
    safety_margin_s = cfg.safety_margin_seconds
    target_count = cfg.target_videos

    logger.info("=" * 60)
    logger.info(f"Batch run ID        : {run_id}")
    logger.info(f"Target video count  : {target_count} (exact)")
    logger.info(f"Runtime budget      : {fmt_hms(max_budget_s)} (safety margin: {fmt_hms(safety_margin_s)})")
    logger.info(f"Candidate pieces    : {len(midi_files)}")
    logger.info("=" * 60)

    xvfb_proc = None
    if cfg.capture_mode == "xvfb_screen":
        xvfb_proc = start_xvfb(
            display=cfg.xvfb_display,
            width=cfg.viewport_w,
            height=cfg.viewport_h,
        )

    try:
        async with async_playwright() as p:
            logger.info("Launching headless Chromium instance with deterministic clock...")
            browser = await p.chromium.launch(
                headless=True if cfg.capture_mode != "xvfb_screen" else False,
                args=get_headless_chromium_args(cfg.viewport_w, cfg.viewport_h),
            )

            context = await browser.new_context(
                viewport={"width": cfg.viewport_w, "height": cfg.viewport_h},
                device_scale_factor=1,
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
            )
            # Pre-grant Web MIDI permissions so no modal interrupts rendering
            await context.grant_permissions(["midi", "midi-sysex"], origin=cfg.app_url)
            await context.add_init_script(DETERMINISTIC_CLOCK_JS)

            page = await context.new_page()

            try:
                for idx, midi_path in enumerate(midi_files, start=1):
                    # Check if exact target count has already been reached
                    if len(successful_renders) >= target_count:
                        logger.info("=" * 60)
                        logger.info(f"Exact target of {target_count} videos reached! Halting batch cleanly.")
                        logger.info("=" * 60)
                        break

                    # Check 5-hour runtime budget before beginning each piece
                    elapsed_run = time.time() - batch_start_time
                    piece_dur = get_midi_duration(midi_path) or 180.0
                    est_render_s = piece_dur * 2.5 + 60.0  # Conservative estimate

                    if (elapsed_run + est_render_s) > (max_budget_s - safety_margin_s):
                        logger.info("=" * 60)
                        logger.info(
                            f"Execution time budget limit reached: {fmt_hms(elapsed_run)} elapsed "
                            f"(budget ceiling: {fmt_hms(max_budget_s)})."
                        )
                        logger.info(f"5th-hour threshold reached. Declaring current status: {len(successful_renders)}/{target_count} completed.")
                        logger.info("Gracefully concluding this run to allow clean video finalization and repository push.")
                        logger.info("=" * 60)
                        break

                    try:
                        res = await render_single_midi(
                            page=page,
                            midi_path=midi_path,
                            output_dir=output_dir,
                            cfg=cfg,
                            item_idx=len(successful_renders) + 1,
                            total_items=target_count,
                            test_seconds=test_seconds,
                            run_id=run_id,
                        )
                        successful_renders.append(res)
                        final_path, duration_s, frames, render_time_s = res
                        size = final_path.stat().st_size if final_path.exists() else 0
                        try:
                            rel_path = final_path.relative_to(cfg.base_dir).as_posix()
                        except ValueError:
                            rel_path = final_path.as_posix()

                        append_processed_entry(
                            log_path=cfg.processed_log,
                            midi_filename=final_path.stem,
                            duration_s=duration_s,
                            frames=frames,
                            file_size_bytes=size,
                            rel_output_path=rel_path,
                            render_time_s=render_time_s,
                        )
                    except Exception as err:
                        logger.error(f"Error processing '{midi_path.name}':\n{traceback.format_exc()}")
                        append_failed_entry(
                            log_path=cfg.failed_log,
                            midi_filename=midi_path.name,
                            error_msg=str(err),
                        )
                        logger.info("Containing error and proceeding to next candidate...")
            finally:
                try:
                    if not page.is_closed():
                        await page.close()
                except Exception:
                    pass
                await context.close()
                await browser.close()
    finally:
        if xvfb_proc is not None:
            stop_xvfb(xvfb_proc)

    total_batch_time = time.time() - batch_start_time
    remaining = max(0, target_count - len(successful_renders))

    # Write batch summary JSON for downstream GitHub Actions workflow steps
    summary_data = {
        "run_id": run_id,
        "target_videos": target_count,
        "successful_this_run": len(successful_renders),
        "remaining": remaining,
        "total_batch_seconds": total_batch_time,
        "completed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    summary_file = cfg.data_dir / "run_summary.json"
    try:
        summary_file.write_text(json.dumps(summary_data, indent=2), encoding="utf-8")
        logger.info(f"Batch summary state saved to {summary_file.name}")
    except Exception as e:
        logger.warning(f"Could not write run_summary.json: {e}")

    logger.info("=" * 60)
    logger.info(
        f"Batch processing concluded: {len(successful_renders)}/{target_count} piece(s) completed "
        f"in {fmt_hms(total_batch_time)} (remaining: {remaining})."
    )
    logger.info("=" * 60)
    return successful_renders
