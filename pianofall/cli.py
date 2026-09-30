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
# Guard against accidentally running from inside the package directory, which
# can cause "import pianofall" to shadow the repo's pianofall/ with itself.
_this_dir = Path(__file__).resolve().parent
_pkg_name = "pianofall"
if _this_dir.name == _pkg_name:
    # We are inside pianofall/; add the parent (repo root) to sys.path[0]
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
    logger.info(f"Xvfb Available   : {'Yes' if find_binary('Xvfb') else 'No (required on Linux runners)'}")

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

    logger.info(f"Render Backend   : {config.app_url[:8]}...{config.app_url[-15:]}")  # partial URL
    logger.info(f"MIDI Queue Dir   : {config.midi_dir}")
    logger.info(f"Output Dir       : {config.output_dir}")
    logger.info(f"Data Dir         : {config.data_dir}")
    logger.info(f"Viewport         : {config.viewport_w}x{config.viewport_h} @ {config.output_fps} FPS")
    logger.info(f"Encoding         : libx264, CRF {config.render_crf}, preset={config.render_preset}")
    logger.info("=" * 60)
    return 0


def cmd_queue_status(args: argparse.Namespace) -> int:
    """List pending, completed, and quarantined MIDI files."""
    processed = load_processed_set(config.processed_log)
    quarantined, attempts = load_failed_map(config.failed_log)
    all_midis = discover_available_midis(config.midi_dir)

    pending = [
        p for p in all_midis
        if p.name not in processed and p.stem not in processed
        and p.name not in quarantined and p.stem not in quarantined
    ]

    logger.info("=" * 60)
    logger.info("PIANOFALL QUEUE STATUS")
    logger.info("=" * 60)
    logger.info(f"Total Local MIDIs : {len(all_midis)}")
    logger.info(f"Completed Pieces  : {len(processed) // 2}")  # set contains both stem and fname
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
    """Download preview pieces or a direct URL into the midis folder."""
    if args.url:
        fname = Path(args.url.split("/")[-1])
        if not fname.suffix.lower().startswith(".mid"):
            fname = fname.with_suffix(".mid")
        target = config.midi_dir / fname.name
        try:
            download_from_url(args.url, target)
            logger.info(f"Downloaded to {target}")
        except Exception as e:
            logger.error(f"Download failed: {e}")
            return 1
    else:
        logger.info("Fetching public domain classical preview pieces...")
        fetched = download_public_preview_midis(config.midi_dir)
        if not fetched:
            logger.error("No preview pieces could be downloaded.")
            return 1
        logger.info(f"Fetched {len(fetched)} pieces.")
    return 0


async def _run_batch_async(args: argparse.Namespace) -> int:
    max_videos = args.max_videos if args.max_videos is not None else config.max_videos_per_run
    max_dur = args.max_duration if args.max_duration is not None else config.max_piece_duration_seconds
    test_sec = args.test_seconds if args.test_seconds is not None else config.test_seconds

    # Environment variable fallbacks for CI workflow dispatch inputs
    if os.getenv("INPUT_MAX_VIDEOS"):
        try:
            max_videos = int(os.getenv("INPUT_MAX_VIDEOS", "1"))
        except ValueError:
            pass

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

    logger.info("=" * 60)
    logger.info("PIANOFALL AUTOMATED CPU RENDERING PIPELINE")
    logger.info("=" * 60)
    logger.info(f"Max videos this run : {max_videos}")
    logger.info(f"Max piece duration  : {fmt_hms(max_dur)}")
    logger.info(f"Test duration cap   : {f'{test_sec}s' if test_sec else 'Disabled (full song)'}")
    logger.info(f"Target filter       : {target_piece or 'None (auto-queue)'}")
    logger.info(f"Force rebuild       : {'Enabled' if force_rebuild else 'Disabled'}")
    logger.info("-" * 60)

    if args.dry_run:
        # Dry-run: only resolve candidates, no rendering, deps warnings are OK
        candidates = select_candidates(
            midi_dir=config.midi_dir,
            processed_log=config.processed_log,
            failed_log=config.failed_log,
            max_duration_seconds=max_dur,
            limit=max_videos,
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

    # Live run - now check hard dependencies
    missing = _check_deps()
    if missing:
        logger.error("Cannot start rendering - critical dependencies are missing:")
        for dep in missing:
            logger.error(f"  MISSING: {dep}")
        logger.error("Install them and retry. See README.md for setup instructions.")
        return 1

    candidates = select_candidates(
        midi_dir=config.midi_dir,
        processed_log=config.processed_log,
        failed_log=config.failed_log,
        max_duration_seconds=max_dur,
        limit=max_videos,
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

    results = await execute_batch(
        midi_files=files_to_render,
        output_dir=config.output_dir,
        cfg=config,
        test_seconds=test_sec,
    )

    # Record ledger updates
    rendered_stems = set()
    for final_path, duration_s, frames in results:
        size = final_path.stat().st_size if final_path.exists() else 0
        try:
            rel_path = final_path.relative_to(config.base_dir).as_posix()
        except ValueError:
            rel_path = final_path.as_posix()

        append_processed_entry(
            log_path=config.processed_log,
            midi_filename=final_path.stem,
            duration_s=duration_s,
            frames=frames,
            file_size_bytes=size,
            rel_output_path=rel_path,
        )
        rendered_stems.add(final_path.stem)

    # Any candidate that was attempted but not in rendered_stems is marked failed
    for path, _ in candidates:
        if path.stem not in rendered_stems:
            append_failed_entry(
                log_path=config.failed_log,
                midi_filename=path.name,
                error_msg="Render execution aborted or failed validation",
            )

    success_count = len(results)
    total_count = len(files_to_render)
    logger.info(f"Batch completed: {success_count}/{total_count} succeeded.")

    # Exit 0 if all succeeded, 1 if any failed (so CI can flag partial failures)
    return 0 if success_count == total_count else 1


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
    batch_parser.add_argument("--max-videos", type=int, default=None,
                              help="Max videos to render this run (overrides config default).")
    batch_parser.add_argument("--max-duration", type=float, default=None,
                              help="Max piece duration in seconds to consider for rendering.")
    batch_parser.add_argument("--test-seconds", type=float, default=None,
                              help="Render only the first N seconds (useful for testing).")
    batch_parser.add_argument("--piece", type=str, default=None,
                              help="Target a specific MIDI filename or substring.")
    batch_parser.add_argument("--allow-exceed-duration", action="store_true",
                              help="Allow targeted piece to exceed --max-duration cap.")
    batch_parser.add_argument("--force", "--force-rebuild", dest="force_rebuild", action="store_true",
                              help="Re-render pieces even if already present in processed ledger.")
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

    # Default to render-batch when invoked with no subcommand (e.g. bare `pianofall`)
    if args.command is None:
        return cmd_render_batch(argparse.Namespace(
            max_videos=None,
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
