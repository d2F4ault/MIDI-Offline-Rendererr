"""
Automated MIDI dataset fetcher for ByteDance GiantMIDI-Piano.

Fetches classical piano masterpieces from GiantMIDI-Piano:
1. Primary: Google Drive dataset archive via gdown (7,236 curated / 10,855 total pieces).
2. Fallback: GitHub repository raw asset endpoints (160+ curated pieces).
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import List, Optional, Set

logger = logging.getLogger("pianofall.queue.fetcher")

# Official ByteDance GiantMIDI-Piano identifiers
GIANTMIDI_GDRIVE_CURATED_ID = "1jLZ8wtRwxKZz6GbxzqpLNYqsWh-TF4-r"  # surname_checked_midis_v1.2.zip
GIANTMIDI_GDRIVE_FULL_ID = "1BDEPaEWFEB2ADquS1VYp5iLZYVngw799"     # midis_v1.2.zip

GIANTMIDI_GITHUB_FOLDERS = [
    "midis_preview",
    "midis_for_evaluation/giantmidi-piano",
    "midis_for_evaluation/maestro",
    "midis_for_evaluation/ground_truth",
]


def _clean_stem(name: str) -> str:
    """Normalize stem for cross-platform file naming and deduplication."""
    stem = Path(name).stem
    # Replace non-printable or path-problematic characters
    return "".join(c if c.isalnum() or c in " ._-()," else "_" for c in stem).strip()


def fetch_from_github_repo(
    dest_dir: Path,
    processed_set: Set[str],
    max_count: int = 20,
) -> List[Path]:
    """
    Fetch unprocessed MIDIs directly from ByteDance/GiantMIDI-Piano GitHub repository.
    Used as an immediate, 100% reliable fallback without external cloud dependencies.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    acquired_paths: List[Path] = []

    logger.info("Scanning ByteDance/GiantMIDI-Piano GitHub repository for available pieces...")
    for folder in GIANTMIDI_GITHUB_FOLDERS:
        if len(acquired_paths) >= max_count:
            break

        api_url = f"https://api.github.com/repos/bytedance/GiantMIDI-Piano/contents/{folder}"
        req = urllib.request.Request(
            api_url,
            headers={
                "User-Agent": "PianoFall-Automated-Fetcher",
                "Accept": "application/vnd.github.v3+json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                items = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            logger.warning(f"Failed to query GiantMIDI folder '{folder}': {e}")
            continue

        for item in items:
            if len(acquired_paths) >= max_count:
                break

            name = item.get("name", "")
            download_url = item.get("download_url")
            if not name.lower().endswith(".mid") or not download_url:
                continue

            stem = Path(name).stem
            if stem in processed_set:
                continue

            # Download this piece
            safe_name = f"{_clean_stem(name)}.mid"
            target_path = dest_dir / safe_name
            if target_path.exists():
                acquired_paths.append(target_path)
                continue

            try:
                logger.info(f"Downloading piece from GitHub: '{safe_name}'...")
                dl_req = urllib.request.Request(download_url, headers={"User-Agent": "PianoFall-Automated-Fetcher"})
                with urllib.request.urlopen(dl_req, timeout=30) as dl_resp:
                    content = dl_resp.read()
                    if len(content) > 100:  # Validate non-trivial MIDI bytes
                        target_path.write_bytes(content)
                        acquired_paths.append(target_path)
                        logger.info(f"  Successfully fetched: {safe_name} ({len(content)} bytes)")
            except Exception as dl_err:
                logger.warning(f"Could not download {name}: {dl_err}")

    return acquired_paths


def fetch_from_gdrive_archive(
    dest_dir: Path,
    processed_set: Set[str],
    max_count: int = 50,
) -> List[Path]:
    """
    Download and extract unprocessed pieces from the GiantMIDI-Piano Google Drive archive.
    """
    try:
        import gdown
    except ImportError:
        logger.warning("gdown is not installed; skipping Google Drive fetch.")
        return []

    dest_dir.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(tempfile.gettempdir())
    zip_path = temp_dir / "giantmidi_curated.zip"

    # Download archive if not already cached in temp
    if not zip_path.exists() or zip_path.stat().st_size < 50 * 1024 * 1024:
        logger.info("Downloading GiantMIDI-Piano curated dataset archive (136 MB)...")
        try:
            gdown.download(id=GIANTMIDI_GDRIVE_CURATED_ID, output=str(zip_path), quiet=True)
        except Exception as e:
            logger.warning(f"Google Drive archive download failed: {e}")
            return []

    if not zip_path.exists() or zip_path.stat().st_size == 0:
        logger.warning("GiantMIDI zip archive is empty or missing.")
        return []

    acquired_paths: List[Path] = []
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            for zip_info in zf.infolist():
                if len(acquired_paths) >= max_count:
                    break

                filename = os.path.basename(zip_info.filename)
                if not filename.lower().endswith(".mid") or filename.startswith("."):
                    continue

                stem = Path(filename).stem
                if stem in processed_set:
                    continue

                safe_name = f"{_clean_stem(filename)}.mid"
                target_path = dest_dir / safe_name
                if not target_path.exists():
                    with zf.open(zip_info) as src, open(target_path, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    logger.info(f"Extracted from GiantMIDI dataset: {safe_name}")

                acquired_paths.append(target_path)
    except Exception as e:
        logger.error(f"Error extracting from GiantMIDI archive: {e}")

    return acquired_paths


def ensure_giantmidi_pieces(
    dest_dir: Path,
    processed_set: Set[str],
    target_count: int = 20,
) -> List[Path]:
    """
    Ensure the local midis directory has at least target_count unprocessed MIDI files.
    Tries Google Drive dataset first, falls back to GiantMIDI GitHub repository.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)

    # First check existing local MIDIs
    existing = [
        p for p in dest_dir.glob("*.mid")
        if p.is_file() and p.stat().st_size > 100 and p.stem not in processed_set
    ]

    if len(existing) >= target_count:
        logger.info(f"Local queue has {len(existing)} unprocessed MIDIs ready.")
        return existing[:target_count]

    needed = target_count - len(existing)
    logger.info(f"Queue needs {needed} more pieces from GiantMIDI-Piano dataset...")

    # Strategy 1: Google Drive dataset archive
    fetched = fetch_from_gdrive_archive(dest_dir, processed_set, max_count=needed)

    # Strategy 2: GitHub repository raw assets fallback if needed
    if len(existing) + len(fetched) < target_count:
        still_needed = target_count - (len(existing) + len(fetched))
        github_fetched = fetch_from_github_repo(dest_dir, processed_set, max_count=still_needed)
        fetched.extend(github_fetched)

    total_ready = [
        p for p in dest_dir.glob("*.mid")
        if p.is_file() and p.stat().st_size > 100 and p.stem not in processed_set
    ]
    logger.info(f"Total ready pieces in queue: {len(total_ready)}")
    return total_ready[:target_count]
