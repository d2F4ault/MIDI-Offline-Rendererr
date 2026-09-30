"""
Configuration management with environment and CLI override support.
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# Default upstream canvas visualizer web app engine (obfuscated base64 for privacy)
_DEFAULT_BACKEND_ENC = "aHR0cHM6Ly9hcHAubWlkaWFuby5jb20="


def _find_repo_root() -> Path:
    """Dynamically discover the repository root directory."""
    current = Path(__file__).resolve().parent
    while current.parent != current:
        if (current / "pyproject.toml").exists() or (current / ".git").exists() or (current / "midis").exists():
            return current
        current = current.parent
    cwd = Path.cwd()
    if (cwd / "pyproject.toml").exists() or (cwd / ".git").exists() or (cwd / "midis").exists():
        return cwd
    return Path(__file__).resolve().parent.parent


@dataclass
class Config:
    # ── Workspace Directories ─────────────────────────────────────────────────
    base_dir: Path = field(default_factory=_find_repo_root)
    midi_dir: Path = field(init=False)
    output_dir: Path = field(init=False)
    data_dir: Path = field(init=False)
    processed_log: Path = field(init=False)
    failed_log: Path = field(init=False)

    # ── Visualizer & Web Engine ───────────────────────────────────────────────
    app_url: str = field(
        default_factory=lambda: os.getenv("RENDER_BACKEND_URL")
        or os.getenv("PIANOFALL_APP_URL")
        or base64.b64decode(_DEFAULT_BACKEND_ENC).decode("utf-8")
    )
    viewport_w: int = 1920
    viewport_h: int = 1200
    xvfb_display: str = ":99"

    # ── Framerate & Video Timing ──────────────────────────────────────────────
    capture_fps: int = 30  # Real-time capture framerate (halves CPU load on runner)
    output_fps: int = 60   # Target output framerate after retiming pass
    start_delay_s: float = 2.5  # Upstream lookahead buffer delay

    # ── Encoding Settings (CPU libx264) ───────────────────────────────────────
    ffmpeg_bin: str = "ffmpeg"
    ffprobe_bin: str = "ffprobe"
    capture_preset: str = "ultrafast"  # Minimizes CPU impact during live screen scraping
    capture_crf: int = 17
    render_preset: str = "fast"        # High-quality offline retime pass (all cores free)
    render_crf: int = 18               # Visually lossless CRF for piano visualizer
    render_pix_fmt: str = "yuv420p"
    max_bitrate: str = "10M"           # Safeguard ensuring output files stay well under 100MB
    buffer_size: str = "20M"

    # ── Execution Budget & Batch Control ──────────────────────────────────────
    max_videos_per_run: int = 1        # Keep runs safe and predictable within time budget
    max_piece_duration_seconds: float = 360.0  # 6-minute cap for standard scheduling
    test_seconds: Optional[float] = None
    max_job_seconds: float = 7200.0    # 2-hour soft safety ceiling

    def __post_init__(self) -> None:
        self.midi_dir = self.base_dir / "midis"
        self.output_dir = self.base_dir / "outputs"
        self.data_dir = self.base_dir / "data"
        self.processed_log = self.data_dir / "processed.txt"
        self.failed_log = self.data_dir / "failed_pieces.txt"

        # Apply Environment Overrides
        if os.getenv("MIDI_DIR"):
            self.midi_dir = Path(os.getenv("MIDI_DIR"))
        if os.getenv("OUTPUT_DIR"):
            self.output_dir = Path(os.getenv("OUTPUT_DIR"))
        if os.getenv("DATA_DIR"):
            self.data_dir = Path(os.getenv("DATA_DIR"))
        if os.getenv("PROCESSED_LOG"):
            self.processed_log = Path(os.getenv("PROCESSED_LOG"))
        if os.getenv("FAILED_LOG"):
            self.failed_log = Path(os.getenv("FAILED_LOG"))

        if os.getenv("RENDER_VIEWPORT_W"):
            self.viewport_w = int(os.getenv("RENDER_VIEWPORT_W"))
        if os.getenv("RENDER_VIEWPORT_H"):
            self.viewport_h = int(os.getenv("RENDER_VIEWPORT_H"))
        if os.getenv("RENDER_OUTPUT_FPS"):
            self.output_fps = int(os.getenv("RENDER_OUTPUT_FPS"))
        if os.getenv("RENDER_CAPTURE_FPS"):
            self.capture_fps = int(os.getenv("RENDER_CAPTURE_FPS"))

        if os.getenv("RENDER_CRF"):
            self.render_crf = int(os.getenv("RENDER_CRF"))
        if os.getenv("RENDER_PRESET"):
            self.render_preset = os.getenv("RENDER_PRESET")
        if os.getenv("FFMPEG_BIN"):
            self.ffmpeg_bin = os.getenv("FFMPEG_BIN")
        if os.getenv("FFPROBE_BIN"):
            self.ffprobe_bin = os.getenv("FFPROBE_BIN")

        if os.getenv("MAX_VIDEOS_PER_RUN"):
            self.max_videos_per_run = int(os.getenv("MAX_VIDEOS_PER_RUN"))
        if os.getenv("MAX_PIECE_DURATION"):
            self.max_piece_duration_seconds = float(os.getenv("MAX_PIECE_DURATION"))
        if os.getenv("TEST_SECONDS"):
            val = os.getenv("TEST_SECONDS").strip()
            if val:
                self.test_seconds = float(val)

        # Ensure base subdirectories exist
        self.midi_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)


config = Config()
