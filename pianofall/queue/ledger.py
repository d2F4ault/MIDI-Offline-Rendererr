"""
State tracking, failure quarantine, and deletion audit ledger management.
"""

from __future__ import annotations

import datetime
import logging
import shutil
from pathlib import Path
from typing import Dict, List, Set, Tuple

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
    render_time_s: float = 0.0,
) -> None:
    """
    Record a successfully rendered MIDI into multiple tracking logs:
    1. processed.txt (tab-delimited ledger)
    2. processed_midis.txt (clean list of all converted MIDI names)
    3. render_history.csv (structured CSV for metrics)
    4. RENDER_LOG.md (user-facing markdown table)
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.datetime.now(datetime.timezone.utc)
    timestamp = now.isoformat()
    entry = f"{midi_filename}\t{duration_s:.2f}s\t{frames}f\t{file_size_bytes}B\t{timestamp}\t{rel_output_path}\n"

    if not log_path.exists() or log_path.stat().st_size == 0:
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("# PianoFall Processed Ledger\n")
            f.write("# filename\tduration\tframes\tsize\ttimestamp\toutput_path\n")

    with open(log_path, "a", encoding="utf-8") as f:
        f.write(entry)

    # 1. Clean list: processed_midis.txt
    clean_list_path = log_path.parent / "processed_midis.txt"
    if not clean_list_path.exists() or clean_list_path.stat().st_size == 0:
        with open(clean_list_path, "w", encoding="utf-8") as f:
            f.write("# PianoFall — Processed MIDI filenames (one per line, no extension)\n")
            f.write("# This file prevents re-rendering already completed pieces.\n")
            f.write("# Auto-managed by the render pipeline. Do not edit manually.\n")

    with open(clean_list_path, "a", encoding="utf-8") as f:
        f.write(f"{Path(midi_filename).stem}\n")

    # 2. Structured CSV: render_history.csv
    csv_path = log_path.parent / "render_history.csv"
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        with open(csv_path, "w", encoding="utf-8") as f:
            f.write("timestamp_utc,midi_name,duration_seconds,render_time_seconds,file_size_mb,output_path,status\n")

    size_mb = file_size_bytes / (1024 * 1024)
    with open(csv_path, "a", encoding="utf-8") as f:
        f.write(
            f"{timestamp},{midi_filename},{duration_s:.2f},{render_time_s:.2f},{size_mb:.2f},{rel_output_path},SUCCESS\n"
        )

    # 3. User-facing Markdown Table: RENDER_LOG.md
    md_path = log_path.parent / "RENDER_LOG.md"
    if not md_path.exists() or md_path.stat().st_size == 0:
        with open(md_path, "w", encoding="utf-8") as f:
            f.write("# PianoFall Render Log\n\n")
            f.write("> Chronological record of rendered pieces and storage maintenance events.\n\n")
            f.write("| Date / Time (UTC) | Piece Name | Duration | Render Time | File Size | Output Path |\n")
            f.write("|---|---|---|---|---|---|\n")

    date_str = now.strftime("%Y-%m-%d %H:%M:%S")
    with open(md_path, "a", encoding="utf-8") as f:
        f.write(
            f"| {date_str} | `{midi_filename}` | {duration_s:.1f}s | {render_time_s:.1f}s | {size_mb:.2f} MB | [`{Path(rel_output_path).name}`]({rel_output_path}) |\n"
        )

    logger.info(f"Recorded completion for '{midi_filename}' across all data ledgers.")


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


def perform_output_cleanup(output_dir: Path, data_dir: Path) -> Tuple[int, int]:
    """
    Purge previous rendered videos and midis from the outputs directory to preserve repository storage.
    Records comprehensive audit metadata in deletion_history.csv and cleanup_log.md before deletion.
    Returns (total_files_removed, total_bytes_freed).
    """
    if not output_dir.exists():
        return 0, 0

    now = datetime.datetime.now(datetime.timezone.utc)
    cleanup_time_iso = now.isoformat()
    cleanup_date_str = now.strftime("%Y-%m-%d %H:%M:%S UTC")

    # Find all run folders or dated subdirectories
    subdirs = [
        d for d in output_dir.iterdir()
        if d.is_dir() and not d.name.startswith(".") and d.name != "__pycache__"
    ]

    if not subdirs:
        logger.info("No prior output directories found to clean; outputs folder is already clean.")
        return 0, 0

    deleted_records: List[Dict[str, any]] = []
    total_bytes = 0
    folders_to_delete: List[Path] = []

    for d in subdirs:
        folders_to_delete.append(d)
        for f in d.rglob("*"):
            if f.is_file() and not f.name.startswith("."):
                size = f.stat().st_size
                mtime = datetime.datetime.fromtimestamp(f.stat().st_mtime, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                ftype = "MP4 Video" if f.suffix.lower() == ".mp4" else ("MIDI File" if f.suffix.lower() in (".mid", ".midi") else "File")
                deleted_records.append({
                    "run_folder": d.name,
                    "file_type": ftype,
                    "filename": f.name,
                    "size_bytes": size,
                    "size_mb": size / (1024 * 1024),
                    "rendered_date": mtime,
                })
                total_bytes += size

    if not deleted_records:
        for d in folders_to_delete:
            shutil.rmtree(d, ignore_errors=True)
        return 0, 0

    # 1. Update CSV deletion log
    csv_path = data_dir / "deletion_history.csv"
    data_dir.mkdir(parents=True, exist_ok=True)
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        with open(csv_path, "w", encoding="utf-8") as f:
            f.write("cleanup_timestamp_utc,run_folder,file_type,filename,size_bytes,size_mb,rendered_date,deletion_reason\n")

    with open(csv_path, "a", encoding="utf-8") as f:
        for r in deleted_records:
            f.write(
                f"{cleanup_time_iso},{r['run_folder']},{r['file_type']},{r['filename']},{r['size_bytes']},{r['size_mb']:.2f},{r['rendered_date']},storage_preservation_new_batch\n"
            )

    # 2. Append to Markdown cleanup log
    clean_md_path = data_dir / "cleanup_log.md"
    if not clean_md_path.exists() or clean_md_path.stat().st_size == 0:
        with open(clean_md_path, "w", encoding="utf-8") as f:
            f.write("# PianoFall Storage Maintenance & Asset Deletion Log\n\n")
            f.write("> Automatically generated audit trail of purged video and MIDI assets.\n\n")

    total_mb = total_bytes / (1024 * 1024)
    run_names = ", ".join(f"`{d.name}`" for d in folders_to_delete)
    videos_count = sum(1 for r in deleted_records if r["file_type"] == "MP4 Video")
    midis_count = sum(1 for r in deleted_records if r["file_type"] == "MIDI File")

    with open(clean_md_path, "a", encoding="utf-8") as f:
        f.write(f"\n## Maintenance Session: {cleanup_date_str}\n\n")
        f.write(f"- **Reason**: Storage preservation before new manual batch render\n")
        f.write(f"- **Runs Purged**: {run_names}\n")
        f.write(f"- **Total Assets Removed**: {len(deleted_records)} ({videos_count} MP4 videos, {midis_count} MIDIs)\n")
        f.write(f"- **Storage Space Reclaimed**: {total_mb:.2f} MB ({total_bytes:,} bytes)\n\n")
        f.write("| Run Folder | Asset Type | Filename | Size (MB) | Rendered Date |\n")
        f.write("|---|---|---|---|---|\n")
        for r in deleted_records:
            f.write(f"| `{r['run_folder']}` | {r['file_type']} | `{r['filename']}` | {r['size_mb']:.2f} MB | {r['rendered_date']} |\n")
        f.write("\n---\n")

    # 3. Add note to RENDER_LOG.md
    render_md_path = data_dir / "RENDER_LOG.md"
    if render_md_path.exists():
        with open(render_md_path, "a", encoding="utf-8") as f:
            f.write(
                f"\n> **[MAINTENANCE]** Purged {len(deleted_records)} assets ({total_mb:.2f} MB reclaimed across {len(folders_to_delete)} run folders) on {cleanup_date_str}.\n\n"
            )

    # 4. Physically delete the directories
    for d in folders_to_delete:
        try:
            shutil.rmtree(d, ignore_errors=True)
            logger.info(f"Purged previous output folder: {d.name}")
        except Exception as e:
            logger.warning(f"Could not remove folder {d.name}: {e}")

    logger.info(
        f"Output cleanup completed: removed {len(deleted_records)} files ({total_mb:.2f} MB freed) "
        f"across {len(folders_to_delete)} run folder(s)."
    )
    return len(deleted_records), total_bytes
