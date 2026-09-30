"""
Queue discovery, candidate selection, and duration filtering.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional, Set, Tuple

from ..utils.midi_info import get_midi_duration
from .downloader import download_public_preview_midis
from .ledger import load_failed_map, load_processed_set

logger = logging.getLogger("pianofall.queue")


def discover_available_midis(midi_dir: Path) -> List[Path]:
    """Scan directory recursively for valid .mid and .midi files."""
    if not midi_dir.exists():
        return []
    files = []
    for ext in ("*.mid", "*.midi", "*.MID", "*.MIDI"):
        files.extend(p for p in midi_dir.rglob(ext) if p.is_file())
    # Return deduplicated, sorted list
    return sorted(list(set(files)), key=lambda p: p.name.lower())


def select_candidates(
    midi_dir: Path,
    processed_log: Path,
    failed_log: Path,
    max_duration_seconds: float = 360.0,
    limit: int = 1,
    target_piece: Optional[str] = None,
    allow_exceed_duration: bool = False,
    auto_fetch_preview: bool = True,
) -> List[Tuple[Path, float]]:
    """
    Select eligible, unprocessed candidate MIDI files for rendering.
    Filters out already processed files and quarantined failures.
    """
    processed_set = load_processed_set(processed_log)
    quarantined_set, _ = load_failed_map(failed_log)

    all_files = discover_available_midis(midi_dir)

    # If no MIDIs exist locally, optionally fetch public domain preview pieces
    if not all_files and auto_fetch_preview:
        logger.info("Local MIDI directory is empty; fetching public classical preview collection...")
        all_files = download_public_preview_midis(midi_dir)

    candidates: List[Tuple[Path, float]] = []

    for path in all_files:
        stem = path.stem
        fname = path.name

        # Check explicit targeting
        if target_piece:
            if target_piece.lower() not in fname.lower() and target_piece.lower() not in stem.lower():
                continue
        else:
            if fname in processed_set or stem in processed_set:
                continue
            if fname in quarantined_set or stem in quarantined_set:
                continue

        dur = get_midi_duration(path)
        if dur is None or dur <= 0.1:
            logger.warning(f"Skipping {fname}: could not read valid duration.")
            continue

        if not allow_exceed_duration and dur > max_duration_seconds:
            logger.debug(f"Skipping {fname}: duration ({dur:.1f}s) exceeds max limit ({max_duration_seconds}s).")
            continue

        candidates.append((path, dur))

    # Sort candidates by duration ascending (shortest first gives fastest turnaround)
    candidates.sort(key=lambda x: (x[1], x[0].name.lower()))

    selected = candidates[:limit]
    logger.info(
        f"Queue evaluated: {len(all_files)} total files, {len(candidates)} eligible, "
        f"{len(selected)} selected for this batch."
    )
    return selected
