"""
Queue discovery, candidate selection, and duration filtering.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional, Set, Tuple

from ..utils.midi_info import get_midi_duration, save_duration_cache
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
    max_duration_seconds: float = 600.0,
    limit: int = 30,
    target_piece: Optional[str] = None,
    allow_exceed_duration: bool = False,
    auto_fetch_preview: bool = True,
    force_rebuild: bool = False,
) -> List[Tuple[Path, float]]:
    """
    Select eligible candidate MIDI files for rendering.
    Filters out already processed files unless force_rebuild is enabled.
    Sorts candidates by duration ascending (shortest first).
    """
    processed_set = load_processed_set(processed_log)
    quarantined_set, _ = load_failed_map(failed_log)

    all_files = discover_available_midis(midi_dir)

    def _evaluate(files: List[Path]) -> List[Tuple[Path, float]]:
        res = []
        for path in files:
            stem = path.stem
            fname = path.name

            # Check explicit targeting
            if target_piece:
                if target_piece.lower() not in fname.lower() and target_piece.lower() not in stem.lower():
                    continue
            elif not force_rebuild:
                if fname in processed_set or stem in processed_set:
                    continue
                if fname in quarantined_set or stem in quarantined_set:
                    continue

            dur = get_midi_duration(path)
            if dur is None or dur <= 0.1:
                logger.warning(f"Skipping {fname}: could not read valid duration.")
                continue

            if not allow_exceed_duration and not target_piece and dur > max_duration_seconds:
                logger.debug(f"Skipping {fname}: duration ({dur:.1f}s) exceeds max limit ({max_duration_seconds}s).")
                continue

            res.append((path, dur))
        return res

    candidates = _evaluate(all_files)
    save_duration_cache()

    # If local pieces are exhausted or insufficient, auto-fetch from GiantMIDI-Piano dataset
    if (len(candidates) < limit) and not target_piece and auto_fetch_preview:
        logger.info("Auto-fetching new unprocessed pieces from ByteDance GiantMIDI-Piano dataset...")
        from .fetcher import ensure_giantmidi_pieces
        needed_count = max(limit * 3, 10)
        new_files = ensure_giantmidi_pieces(midi_dir, processed_set, target_count=needed_count)
        if new_files:
            all_files = discover_available_midis(midi_dir)
            candidates = _evaluate(all_files)
            save_duration_cache()

    # Sort candidates by duration ascending (shortest pieces render fastest)
    candidates.sort(key=lambda x: (x[1], x[0].name.lower()))

    selected = candidates[:limit]
    if candidates:
        logger.info(
            f"Queue evaluated: {len(all_files)} total files in pool, {len(candidates)} eligible, "
            f"{len(selected)} selected for this batch."
        )
    else:
        logger.info(
            f"Queue evaluated: {len(all_files)} total files in pool, 0 eligible pending pieces. "
            f"All existing pieces have already been rendered. "
            f"(To re-render, enable force_rebuild or add new MIDI files to midis_pool/)"
        )
    return selected
