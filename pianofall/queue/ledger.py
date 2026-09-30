"""
State tracking and failure quarantine ledger management.
"""

from __future__ import annotations

import datetime
import logging
from pathlib import Path
from typing import Dict, Set, Tuple

logger = logging.getLogger("pianofall.ledger")


def load_processed_set(log_path: Path) -> Set[str]:
    """Read the processed ledger and return set of completed MIDI stems/filenames."""
    processed = set()
    if not log_path.exists():
        return processed

    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            fname = parts[0].strip()
            processed.add(fname)
            processed.add(Path(fname).stem)
    return processed


def append_processed_entry(
    log_path: Path,
    midi_filename: str,
    duration_s: float,
    frames: int,
    file_size_bytes: int,
    rel_output_path: str,
) -> None:
    """Record a successfully rendered MIDI into processed.txt."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    entry = f"{midi_filename}\t{duration_s:.2f}s\t{frames}f\t{file_size_bytes}B\t{timestamp}\t{rel_output_path}\n"

    if not log_path.exists() or log_path.stat().st_size == 0:
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("# PianoFall Processed Ledger\n")
            f.write("# filename\tduration\tframes\tsize\ttimestamp\toutput_path\n")

    with open(log_path, "a", encoding="utf-8") as f:
        f.write(entry)
    logger.info(f"Recorded completion for '{midi_filename}' in {log_path.name}")


def load_failed_map(log_path: Path) -> Tuple[Set[str], Dict[str, int]]:
    """Read failed ledger and return set of quarantined stems and failure attempt counts."""
    quarantined = set()
    attempts = {}
    if not log_path.exists():
        return quarantined, attempts

    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            fname = parts[0].strip()
            quarantined.add(fname)
            quarantined.add(Path(fname).stem)
            attempts[fname] = attempts.get(fname, 0) + 1

    return quarantined, attempts


def append_failed_entry(log_path: Path, midi_filename: str, error_msg: str) -> None:
    """Record a failed rendering attempt into the failure quarantine ledger."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    clean_err = error_msg.replace("\t", " ").replace("\n", " ")[:300]
    entry = f"{midi_filename}\t{timestamp}\t{clean_err}\n"

    if not log_path.exists() or log_path.stat().st_size == 0:
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("# PianoFall Failure Quarantine Ledger\n")
            f.write("# filename\ttimestamp\terror_message\n")

    with open(log_path, "a", encoding="utf-8") as f:
        f.write(entry)
    logger.warning(f"Quarantined '{midi_filename}' in {log_path.name}")
