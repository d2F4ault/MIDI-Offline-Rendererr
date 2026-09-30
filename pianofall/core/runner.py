"""
High-level rendering orchestration for individual pieces and batch pipelines.
"""

from __future__ import annotations

import asyncio
import datetime
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
    AC_CAPTURE_SCRIPT,
    capture_debug_screenshot,
    dismiss_popups,
    hide_navigation_overlays,
    trigger_playback,
    upload_midi_file,
    wait_canvas_ready,
)
from .browser import get_chromium_args, start_xvfb, stop_xvfb
from .postprocess import retime_and_master_video
from .recorder import (
    get_recorder_error_text,
    start_screen_recorder,
    stop_screen_recorder,
    validate_raw_recording,
)

logger = logging.getLogger("pianofall.runner")


async def render_single_midi(
    context,
    midi_path: Path,
    output_dir: Path,
    cfg: Config,
    item_idx: int = 1,
    total_items: int = 1,
    test_seconds: Optional[float] = None,
) -> Tuple[Path, float, int]:
    """
    Render a single MIDI file into a silent, 60 FPS 1920x1200 MP4.
    Reuses the persistent browser context to maintain window dimensions.
    """
    duration_s = get_midi_duration(midi_path)
    if not duration_s or duration_s <= 0.1:
        raise ValueError(f"Could not read valid duration from MIDI file: {midi_path.name}")

    if test_seconds is not None and test_seconds > 0:
        duration_s = min(duration_s, float(test_seconds))
        logger.info(f"Test mode active: rendering first {duration_s:.1f}s of {midi_path.name}")

    target_frames = max(1, int(round(duration_s * cfg.output_fps)))

    today_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    dated_out_dir = output_dir / today_str
    dated_out_dir.mkdir(parents=True, exist_ok=True)
    final_output_path = dated_out_dir / f"{midi_path.stem}.mp4"

    logger.info(f"[{item_idx}/{total_items}] Commencing render: '{midi_path.name}'")
    logger.info(
        f"  Target duration: {fmt_hms(duration_s)} ({duration_s:.2f}s) | "
        f"{cfg.viewport_w}x{cfg.viewport_h} @ {cfg.output_fps} FPS | Silent output"
    )

    page = await context.new_page()
    await page.bring_to_front()
    await page.add_init_script(AC_CAPTURE_SCRIPT)

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
    raw_capture_path = scratch_dir / f"{midi_path.stem}_raw_capture.mp4"
    if raw_capture_path.exists():
        raw_capture_path.unlink(missing_ok=True)

    recorder_proc = None
    t0 = time.time()

    try:
        logger.info("  Loading canvas visualizer web app...")
        await page.goto(cfg.app_url, wait_until="domcontentloaded", timeout=60_000)
        await dismiss_popups(page)
        await wait_canvas_ready(page)

        logger.info("  Injecting MIDI file into player...")
        await upload_midi_file(page, midi_path)

        logger.info("  Hiding UI overlays and controls (waiting for fade)...")
        await hide_navigation_overlays(page, cfg.viewport_w, cfg.viewport_h)

        logger.info(f"  Starting screen recorder -> {raw_capture_path.name}")
        recorder_proc = start_screen_recorder(
            output_path=raw_capture_path,
            display=cfg.xvfb_display,
            width=cfg.viewport_w,
            height=cfg.viewport_h,
            fps=cfg.capture_fps,
            ffmpeg_bin=cfg.ffmpeg_bin,
            preset=cfg.capture_preset,
            crf=cfg.capture_crf,
        )

        # Allow recorder a 300ms warmup to hook into the display
        await asyncio.sleep(0.3)
        if recorder_proc.poll() is not None:
            err = get_recorder_error_text(recorder_proc)
            raise RuntimeError(f"FFmpeg recorder exited prematurely ({recorder_proc.returncode}):\n{err}")

        logger.info("  Triggering playback start...")
        playback_start_time = time.time()
        await trigger_playback(page)

        # Progress monitor loop
        elapsed = 0.0
        heartbeat_interval = 5.0

        while elapsed < duration_s:
            await asyncio.sleep(min(heartbeat_interval, duration_s - elapsed))
            elapsed = time.time() - playback_start_time

            if recorder_proc.poll() is not None:
                err = get_recorder_error_text(recorder_proc)
                raise RuntimeError(f"FFmpeg recorder exited during performance ({recorder_proc.returncode}):\n{err}")

            pct = 100.0 * min(elapsed, duration_s) / duration_s
            logger.info(
                f"  [{item_idx}/{total_items}] {midi_path.stem} | "
                f"Capturing: {fmt_hms(elapsed)} / {fmt_hms(duration_s)} ({pct:.1f}%)"
            )

        logger.info("  Playback finished; finalizing screen capture...")
        rc = stop_screen_recorder(recorder_proc)
        recorder_proc = None
        if rc != 0:
            raise RuntimeError(f"FFmpeg recorder failed with exit code {rc}")

        validate_raw_recording(raw_capture_path, duration_s)

        # Offline retiming and CPU libx264 mastering pass
        logger.info("  Initiating offline retiming pass...")
        retime_and_master_video(
            src_raw=raw_capture_path,
            dst_final=final_output_path,
            target_duration_s=duration_s,
            target_fps=cfg.output_fps,
            preset=cfg.render_preset,
            crf=cfg.render_crf,
            max_bitrate=cfg.max_bitrate,
            buffer_size=cfg.buffer_size,
            ffmpeg_bin=cfg.ffmpeg_bin,
            ffprobe_bin=cfg.ffprobe_bin,
        )

        total_elapsed = time.time() - t0
        final_size = final_output_path.stat().st_size
        logger.info(
            f"  SUCCESS: Generated '{final_output_path.name}' "
            f"({fmt_bytes(final_size)}, render time: {fmt_hms(total_elapsed)})"
        )
        return final_output_path, duration_s, target_frames

    except Exception as e:
        logger.error(f"Render failed for {midi_path.name}: {e}")
        # Capture on-failure screenshot for remote diagnostics
        debug_path = cfg.data_dir / f"debug_{midi_path.stem}.png"
        await capture_debug_screenshot(page, debug_path)

        if recorder_proc is not None and recorder_proc.poll() is None:
            try:
                recorder_proc.kill()
            except Exception:
                pass
        raise
    finally:
        if raw_capture_path.exists():
            raw_capture_path.unlink(missing_ok=True)
        try:
            if not page.is_closed():
                await page.close()
        except Exception:
            pass


async def execute_batch(
    midi_files: List[Path],
    output_dir: Path,
    cfg: Config,
    test_seconds: Optional[float] = None,
) -> List[Tuple[Path, float, int]]:
    """
    Execute rendering for a list of MIDI files using a shared browser instance.
    Includes error containment so individual failures do not abort the whole batch.
    """
    from playwright.async_api import async_playwright

    successful_renders = []
    xvfb_proc = start_xvfb(
        display=cfg.xvfb_display,
        width=cfg.viewport_w,
        height=cfg.viewport_h,
    )

    try:
        async with async_playwright() as p:
            logger.info("Launching Chromium instance...")
            browser = await p.chromium.launch(
                headless=False,  # Headed inside virtual Xvfb display
                args=get_chromium_args(cfg.viewport_w, cfg.viewport_h),
            )

            # Reused context guarantees consistent kiosk geometry across all pieces
            context = await browser.new_context(
                viewport={"width": cfg.viewport_w, "height": cfg.viewport_h},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
            )
            # Pre-grant Web MIDI permissions so no modal interrupts rendering
            await context.grant_permissions(["midi", "midi-sysex"], origin=cfg.app_url)

            # Keep an anchor blank page open so closing render tabs never causes Chromium to exit
            anchor_page = await context.new_page()
            await anchor_page.goto("about:blank")

            try:
                total = len(midi_files)
                for idx, midi_path in enumerate(midi_files, start=1):
                    try:
                        res = await render_single_midi(
                            context=context,
                            midi_path=midi_path,
                            output_dir=output_dir,
                            cfg=cfg,
                            item_idx=idx,
                            total_items=total,
                            test_seconds=test_seconds,
                        )
                        successful_renders.append(res)
                    except Exception:
                        logger.error(f"Error processing '{midi_path.name}':\n{traceback.format_exc()}")
                        logger.info("Containing error and proceeding to next piece...")
            finally:
                try:
                    await anchor_page.close()
                except Exception:
                    pass
                await context.close()
                await browser.close()
    finally:
        stop_xvfb(xvfb_proc)

    logger.info(f"Batch processing finished: {len(successful_renders)}/{len(midi_files)} succeeded.")
    return successful_renders
