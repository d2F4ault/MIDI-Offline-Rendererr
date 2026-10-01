"""
Optional remote MIDI downloader for public domain classical piano pieces.
"""

from __future__ import annotations

import logging
import urllib.parse
import urllib.request
from pathlib import Path
from typing import List

logger = logging.getLogger("pianofall.downloader")

# Public domain classical preview pieces hosted on open GitHub repositories
PREVIEW_PIECES = [
    "Chopin, Frédéric, Études, Op.10, g0hoN6_HDVU.mid",
    "Handel, George Frideric, Air in E major, HWV 425, bNzVz5byPqk.mid",
    "Liszt, Franz, Hungarian Rhapsody No.2, S.244_2, LdH1hSWGFGU.mid",
    "Ravel, Maurice, Jeux d'eau, v-QmwrhO3ec.mid",
]

PREVIEW_BASE_URL = (
    "https://raw.githubusercontent.com/bytedance/GiantMIDI-Piano/master/midis_preview"
)


def download_public_preview_midis(dest_dir: Path) -> List[Path]:
    """
    Download verified classical preview MIDIs if the local collection has no pending files.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    downloaded = []

    for fname in PREVIEW_PIECES:
        out_file = dest_dir / fname
        if not out_file.exists():
            encoded = urllib.parse.quote(fname)
            url = f"{PREVIEW_BASE_URL}/{encoded}"
            try:
                logger.info(f"Fetching public domain piece: {fname}...")
                req = urllib.request.Request(
                    url,
                    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) PianoFall/1.0"},
                )
                with urllib.request.urlopen(req, timeout=20) as resp:
                    content = resp.read()

                if len(content) > 100 and content.startswith(b"MThd"):
                    out_file.write_bytes(content)
                    logger.info(f"Saved: {out_file.name} ({len(content)} bytes)")
                else:
                    logger.warning(f"Downloaded content for {fname} was not a valid MIDI.")
            except Exception as e:
                logger.warning(f"Could not download {fname}: {e}")
                continue

        if out_file.exists() and out_file.stat().st_size > 100:
            downloaded.append(out_file)

    return downloaded


def download_from_url(url: str, dest_path: Path) -> Path:
    """Download a specific MIDI from a public direct URL."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    logger.info(f"Downloading MIDI from {url} -> {dest_path}...")
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) PianoFall/1.0"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        content = resp.read()

    if not content.startswith(b"MThd"):
        raise ValueError(f"Content downloaded from {url} is not a valid standard MIDI file.")

    dest_path.write_bytes(content)
    logger.info(f"Saved {dest_path.name} ({len(content)} bytes)")
    return dest_path
