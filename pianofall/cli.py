"""
Command-line interface (CLI) for PianoFall.

Entry point:  python -m pianofall [command] [options]
              pianofall [command] [options]   (if installed via pip install .)
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Optional

# ── Preflight: ensure this is importable from any CWD ────────────────────────
_this_dir = Path(__file__).resolve().parent
_pkg_name = "pianofall"
if _this_dir.name == _pkg_name:
    _repo_root = str(_this_dir.parent)
    if _repo_root not in sys.path:
        sys.path.insert(0, _repo_root)
# ─────────────────────────────────────────────────────────────────────────────

from .config import config
from .core.runner import execute_batch
from .queue.downloader import download_from_url, download_public_preview_midis
from .queue.ledger import (
    append_failed_entry,
    append_processed_entry,
    load_failed_map,
    load_processed_set,
)
from .queue.manager import discover_available_midis, select_candidates
from .utils.logging import fmt_bytes, fmt_hms, setup_logger
from .utils.midi_info import get_midi_duration
from .utils.system import find_binary, get_ffmpeg_version, get_system_summary

logger = setup_logger("pianofall")


# ── Dependency checks ─────────────────────────────────────────────────────────

def _check_deps() -> list[str]:
    """Return list of missing critical runtime dependencies."""
    missing = []
    if not find_binary("ffmpeg") and not find_binary(config.ffmpeg_bin):
        missing.append("ffmpeg")
    if not find_binary("ffprobe") and not find_binary(config.ffprobe_bin):
        missing.append("ffprobe")
    try:
        import playwright  # noqa: F401
    except ImportError:
        missing.append("playwright (pip install playwright)")
    return missing


def _warn_missing_deps(context: str = "") -> None:
    """Log warnings for any missing dependencies (non-fatal for dry runs)."""
    missing = _check_deps()
    if missing:
        logger.warning(
            f"Missing dependencies{f' ({context})' if context else ''}: {', '.join(missing)}"
        )
        logger.warning("Run:  pip install -r requirements.txt")
        logger.warning("      python -m playwright install --with-deps chromium")
        if "ffmpeg" in missing:
            logger.warning("      sudo apt-get install -y ffmpeg   (Linux)")


# ── Subcommand handlers ───────────────────────────────────────────────────────

def cmd_inspect_system(args: argparse.Namespace) -> int:
    """Print system diagnostics, CPU cores, RAM, and binary dependencies."""
    summary = get_system_summary()
    logger.info("=" * 60)
    logger.info("PIANOFALL SYSTEM DIAGNOSTICS")
    logger.info("=" * 60)
    logger.info(f"Operating System : {summary['os']}")
    logger.info(f"CPU Cores        : {summary['cpu_cores']}")
    logger.info(f"Physical Memory  : {summary['total_memory']}")
    logger.info(f"Python Version   : {summary['python_version']}")

    ffmpeg_path = find_binary(config.ffmpeg_bin)
    ffprobe_path = find_binary(config.ffprobe_bin)
    ffmpeg_ver = get_ffmpeg_version(config.ffmpeg_bin) if ffmpeg_path else None

    logger.info(f"FFmpeg Binary    : {ffmpeg_path or 'NOT FOUND'}{f'  ({ffmpeg_ver})' if ffmpeg_ver else ''}")
    logger.info(f"FFprobe Binary   : {ffprobe_path or 'NOT FOUND'}")
    logger.info(f"Xvfb Available   : {'Yes' if find_binary('Xvfb') else 'No (headless canvas mode default)'}")

    try:
        import playwright
        pw_ver = getattr(playwright, "__version__", "installed")
        logger.info(f"Playwright       : {pw_ver}")
    except ImportError:
        logger.info("Playwright       : NOT FOUND - run: pip install playwright")

    try:
        import mido
        logger.info(f"mido             : {getattr(mido, '__version__', 'installed')}")
    except ImportError:
        logger.info("mido             : NOT FOUND - run: pip install mido")

    logger.info(f"Render Backend   : {config.app_url[:8]}...{config.app_url[-15:]}")
    logger.info(f"Capture Engine   : Deterministic Headless ({config.capture_mode})")
    logger.info(f"Keyboard Layout  : Full 88-key piano (show_all_88_keys={config.show_all_88_keys})")
    logger.info(f"MIDI Pool Dir    : {config.midi_pool_dir}")
    logger.info(f"Output Dir       : {config.output_dir}")
    logger.info(f"Data Dir         : {config.data_dir}")
    logger.info(f"Target Batch     : {config.target_videos} videos (exact)")
    logger.info(f"Auto-Cleanup     : {'Enabled' if config.clean_previous_outputs else 'Disabled'}")
    logger.info(f"Viewport         : {config.viewport_w}x{config.viewport_h} @ {config.output_fps} FPS")
    logger.info(f"Encoding         : libx264, CRF {config.render_crf}, pipe_preset={config.pipe_preset}")
    logger.info("=" * 60)
    return 0


def cmd_queue_status(args: argparse.Namespace) -> int:
    """List pending, completed, and quarantined MIDI files."""
    processed = load_processed_set(config.processed_log)
    quarantined, attempts = load_failed_map(config.failed_log)
    all_midis = discover_available_midis(config.midi_pool_dir)

    pending = [
        p for p in all_midis
        if p.name not in processed and p.stem not in processed
        and p.name not in quarantined and p.stem not in quarantined
    ]

    logger.info("=" * 60)
    logger.info("PIANOFALL QUEUE STATUS")
    logger.info("=" * 60)
    logger.info(f"Total in Pool     : {len(all_midis)}")
    logger.info(f"Completed Pieces  : {len(processed) // 2}")
    logger.info(f"Quarantined Files : {len(quarantined) // 2}")
    logger.info(f"Pending in Queue  : {len(pending)}")
    logger.info("-" * 60)

    if pending:
        logger.info("Next Pending Pieces:")
        for p in pending[:10]:
            dur = get_midi_duration(p)
            dur_str = fmt_hms(dur) if dur else "unknown duration"
            logger.info(f"  * {p.name} ({dur_str})")
        if len(pending) > 10:
            logger.info(f"  ... and {len(pending) - 10} more.")
    else:
        logger.info("No pending files in local queue.")
    logger.info("=" * 60)
    return 0


def cmd_fetch_midi(args: argparse.Namespace) -> int:
    """Download preview pieces or a direct URL into the midis pool."""
    if args.url:
        fname = Path(args.url.split("/")[-1])
        if not fname.suffix.lower().startswith(".mid"):
            fname = fname.with_suffix(".mid")
        target = config.midi_pool_dir / fname.name
        try:
            download_from_url(args.url, target)
            logger.info(f"Downloaded to {target}")
        except Exception as e:
            logger.error(f"Download failed: {e}")
            return 1
    else:
        logger.info("Fetching public domain classical preview pieces...")
        fetched = download_public_preview_midis(config.midi_pool_dir)
        if not fetched:
            logger.error("No preview pieces could be downloaded.")
            return 1
        logger.info(f"Fetched {len(fetched)} pieces.")
    return 0


async def _run_batch_async(args: argparse.Namespace) -> int:
    # Resolve target video count
    target_count = getattr(args, "target_videos", None)
    if target_count is None:
        target_count = getattr(args, "max_videos", None)
    if target_count is None:
        target_count = config.target_videos

    if os.getenv("INPUT_TARGET_VIDEOS"):
        try:
            target_count = int(os.getenv("INPUT_TARGET_VIDEOS"))
        except ValueError:
            pass
    elif os.getenv("INPUT_MAX_VIDEOS"):
        try:
            target_count = int(os.getenv("INPUT_MAX_VIDEOS"))
        except ValueError:
            pass
    config.target_videos = target_count

    # Resolve cleanup preference
    if getattr(args, "clean_previous", None) is not None:
        config.clean_previous_outputs = args.clean_previous
    if os.getenv("INPUT_CLEAN_PREVIOUS") is not None:
        config.clean_previous_outputs = os.getenv("INPUT_CLEAN_PREVIOUS").strip().lower() in ("true", "1", "yes")

    max_dur = args.max_duration if args.max_duration is not None else config.max_piece_duration_seconds
    test_sec = args.test_seconds if args.test_seconds is not None else config.test_seconds

    if os.getenv("INPUT_TEST_SECONDS"):
        raw = os.getenv("INPUT_TEST_SECONDS", "").strip()
        if raw:
            try:
                test_sec = float(raw)
            except ValueError:
                pass

    target_piece = args.piece or (os.getenv("INPUT_PIECE_NAME") or "").strip() or None

    force_rebuild = getattr(args, "force_rebuild", False)
    if os.getenv("INPUT_FORCE_REBUILD", "").strip().lower() in ("true", "1", "yes"):
        force_rebuild = True

    if getattr(args, "capture_mode", None):
        config.capture_mode = args.capture_mode
    if getattr(args, "show_88_keys", None) is not None:
        config.show_all_88_keys = args.show_88_keys
    if getattr(args, "viewport_w", None):
        config.viewport_w = args.viewport_w
    if getattr(args, "viewport_h", None):
        config.viewport_h = args.viewport_h

    logger.info("=" * 60)
    logger.info("PIANOFALL OFFLINE MIDI RENDERING PIPELINE")
    logger.info("=" * 60)
    logger.info(f"Target videos count : {target_count} (exact)")
    logger.info(f"Clean previous runs : {'Enabled' if config.clean_previous_outputs else 'Disabled'}")
    logger.info(f"Max piece duration  : {fmt_hms(max_dur)}")
    logger.info(f"Test duration cap   : {f'{test_sec}s' if test_sec else 'Disabled (full song)'}")
    logger.info(f"Target filter       : {target_piece or 'None (auto-queue from pool)'}")
    logger.info(f"Force rebuild       : {'Enabled' if force_rebuild else 'Disabled'}")
    logger.info("-" * 60)

    if args.dry_run:
        candidates = select_candidates(
            midi_dir=config.midi_pool_dir,
            processed_log=config.processed_log,
            failed_log=config.failed_log,
            max_duration_seconds=max_dur,
            limit=target_count,
            target_piece=target_piece,
            allow_exceed_duration=getattr(args, "allow_exceed_duration", False),
            auto_fetch_preview=True,
            force_rebuild=force_rebuild,
        )
        if not candidates:
            logger.info("No eligible pieces found in queue.")
            return 0
        logger.info(f"Selected {len(candidates)} piece(s) for rendering:")
        for path, dur in candidates:
            logger.info(f"  * {path.name} ({fmt_hms(dur)})")
        logger.info("Dry run flag set; skipping rendering execution.")
        return 0

    missing = _check_deps()
    if missing:
        logger.error("Cannot start rendering - critical dependencies are missing:")
        for dep in missing:
            logger.error(f"  MISSING: {dep}")
        logger.error("Install them and retry. See README.md for setup instructions.")
        return 1

    candidates = select_candidates(
        midi_dir=config.midi_pool_dir,
        processed_log=config.processed_log,
        failed_log=config.failed_log,
        max_duration_seconds=max_dur,
        limit=target_count,
        target_piece=target_piece,
        allow_exceed_duration=getattr(args, "allow_exceed_duration", False),
        auto_fetch_preview=True,
        force_rebuild=force_rebuild,
    )

    if not candidates:
        logger.info("No eligible pieces found in queue. Pipeline complete.")
        return 0

    files_to_render = [c[0] for c in candidates]
    logger.info(f"Selected {len(files_to_render)} piece(s) for rendering:")
    for path, dur in candidates:
        logger.info(f"  * {path.name} ({fmt_hms(dur)})")

    if hasattr(args, "max_hours") and args.max_hours is not None:
        config.max_job_seconds = float(args.max_hours) * 3600.0
    if os.getenv("INPUT_MAX_HOURS"):
        try:
            config.max_job_seconds = float(os.getenv("INPUT_MAX_HOURS")) * 3600.0
        except ValueError:
            pass

    results = await execute_batch(
        midi_files=files_to_render,
        output_dir=config.output_dir,
        cfg=config,
        test_seconds=test_sec,
    )

    success_count = len(results)
    logger.info(f"Batch execution finished: {success_count}/{target_count} piece(s) completed.")
    return 0


def cmd_render_batch(args: argparse.Namespace) -> int:
    """Run the batch rendering pipeline."""
    return asyncio.run(_run_batch_async(args))


# ── Argument parser ───────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pianofall",
        description=(
            "PianoFall - Automated offline MIDI piano visualization pipeline.\n"
            "Renders silent 1920x1200 @ 60 FPS falling-notes videos from MIDI files."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # render-batch
    batch_parser = subparsers.add_parser(
        "render-batch",
        help="Process queued MIDI files and save rendered videos.",
    )
    batch_parser.add_argument("--target-videos", "--max-videos", dest="target_videos", type=int, default=None,
                              help="Exact target number of videos to render (default: 30).")
    batch_parser.add_argument("--clean-previous", dest="clean_previous", action="store_true", default=None,
                              help="Purge prior output videos and midis before starting to preserve disk space.")
    batch_parser.add_argument("--no-clean-previous", dest="clean_previous", action="store_false",
                              help="Retain existing outputs and append new renders.")
    batch_parser.add_argument("--max-duration", type=float, default=None,
                              help="Max piece duration in seconds to consider for rendering.")
    batch_parser.add_argument("--test-seconds", type=float, default=None,
                              help="Render only the first N seconds (useful for testing).")
    batch_parser.add_argument("--piece", type=str, default=None,
                              help="Target a specific MIDI filename or substring.")
    batch_parser.add_argument("--allow-exceed-duration", action="store_true",
                              help="Allow targeted piece to exceed --max-duration cap.")
    batch_parser.add_argument("--max-hours", type=float, default=None,
                              help="Maximum runtime budget in hours (default: 5.0 hours).")
    batch_parser.add_argument("--force", "--force-rebuild", dest="force_rebuild", action="store_true",
                              help="Re-render pieces even if already present in processed ledger.")
    batch_parser.add_argument("--capture-mode", type=str, choices=["canvas_composite", "page_screenshot", "xvfb_screen"], default=None,
                              help="Capture engine ('canvas_composite' recommended, 'page_screenshot', or 'xvfb_screen').")
    batch_parser.add_argument("--show-88-keys", dest="show_88_keys", action="store_true", default=None,
                              help="Enforce full 88-key piano keyboard layout (A0-C8).")
    batch_parser.add_argument("--no-88-keys", dest="show_88_keys", action="store_false",
                              help="Do not enforce 88-key layout; auto-fit to song range.")
    batch_parser.add_argument("--viewport-w", type=int, default=None,
                              help="Rendering canvas width in pixels (e.g. 1920 or 2560).")
    batch_parser.add_argument("--viewport-h", type=int, default=None,
                              help="Rendering canvas height in pixels (e.g. 1080, 1200, or 1440).")
    batch_parser.add_argument("--dry-run", action="store_true",
                              help="Inspect candidate selection without rendering.")

    # queue
    subparsers.add_parser("queue", help="Display current queue and ledger statistics.")

    # inspect-system
    subparsers.add_parser("inspect-system", help="Inspect system CPU, memory, FFmpeg, and dependencies.")

    # fetch-midi
    fetch_parser = subparsers.add_parser("fetch-midi", help="Download public domain MIDI files.")
    fetch_parser.add_argument("--url", type=str, default=None,
                              help="Direct HTTPS URL to a .mid file to download.")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    # Default to render-batch when invoked with no subcommand
    if args.command is None:
        return cmd_render_batch(argparse.Namespace(
            target_videos=None,
            max_videos=None,
            clean_previous=None,
            max_duration=None,
            test_seconds=None,
            piece=None,
            allow_exceed_duration=False,
            force_rebuild=False,
            dry_run=False,
        ))

    dispatch = {
        "render-batch": cmd_render_batch,
        "queue": cmd_queue_status,
        "inspect-system": cmd_inspect_system,
        "fetch-midi": cmd_fetch_midi,
    }

    handler = dispatch.get(args.command)
    if handler is None:
        parser.print_help()
        return 1

    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
