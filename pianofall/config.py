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
        if (
            (current / "pyproject.toml").exists()
            or (current / ".git").exists()
            or (current / "midis_pool").exists()
            or (current / "midis").exists()
        ):
            return current
        current = current.parent
    cwd = Path.cwd()
    if (
        (cwd / "pyproject.toml").exists()
        or (cwd / ".git").exists()
        or (cwd / "midis_pool").exists()
        or (cwd / "midis").exists()
    ):
        return cwd
    return Path(__file__).resolve().parent.parent


@dataclass
class Config:
    # ── Workspace Directories ─────────────────────────────────────────────────
    base_dir: Path = field(default_factory=_find_repo_root)
    midi_pool_dir: Path = field(init=False)
    midi_dir: Path = field(init=False)  # Alias for midi_pool_dir
    output_dir: Path = field(init=False)
    data_dir: Path = field(init=False)
    processed_log: Path = field(init=False)
    failed_log: Path = field(init=False)
    deletion_log: Path = field(init=False)
    cleanup_log: Path = field(init=False)

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
    capture_fps: int = 60  # Live-capture at true 60 fps
    output_fps: int = 60   # Target output framerate
    start_delay_s: float = 2.5  # Upstream lookahead buffer delay
    align_video_to_midi_t0: bool = False  # Keep 2.5s approaching notes intro

    # ── Capture Engine & Keyboard View ────────────────────────────────────────
    capture_mode: str = "canvas_composite"  # 'canvas_composite' (recommended) or 'page_screenshot'
    show_all_88_keys: bool = True           # Enforce full 88-key piano keyboard layout
    pipe_preset: str = "faster"             # Balanced CPU libx264 encoding preset for piped frames

    # ── Encoding Settings (CPU libx264) ───────────────────────────────────────
    ffmpeg_bin: str = "ffmpeg"
    ffprobe_bin: str = "ffprobe"
    capture_preset: str = "ultrafast"
    capture_crf: int = 12
    render_preset: str = "slow"
    render_crf: int = 14               # Visually transparent — studio quality
    render_pix_fmt: str = "yuv420p"
    max_bitrate: str = "50M"
    buffer_size: str = "100M"

    # ── Execution Budget & Batch Control ──────────────────────────────────────
    target_videos: int = 30            # Exact target number of videos per manual batch
    clean_previous_outputs: bool = True # Automatically clean previous outputs on new batch
    max_piece_duration_seconds: float = 600.0  # 10-minute cap for classical pieces
    test_seconds: Optional[float] = None
    max_job_seconds: float = 18000.0   # 5-hour hard execution ceiling
    safety_margin_seconds: float = 900.0  # 15-minute margin for clean shutdown & commit
    run_id: Optional[str] = None

    def __post_init__(self) -> None:
        # Resolve directories: midis_pool takes precedence, fallback to midis
        pool_candidate = self.base_dir / "midis_pool"
        legacy_candidate = self.base_dir / "midis"
        self.midi_pool_dir = pool_candidate if pool_candidate.exists() or not legacy_candidate.exists() else legacy_candidate
        self.midi_dir = self.midi_pool_dir
        self.output_dir = self.base_dir / "outputs"
        self.data_dir = self.base_dir / "data"
        self.processed_log = self.data_dir / "processed.txt"
        self.failed_log = self.data_dir / "failed_pieces.txt"
        self.deletion_log = self.data_dir / "deletion_history.csv"
        self.cleanup_log = self.data_dir / "cleanup_log.md"

        # Apply Environment Overrides
        if os.getenv("MIDI_POOL_DIR"):
            self.midi_pool_dir = Path(os.getenv("MIDI_POOL_DIR"))
            self.midi_dir = self.midi_pool_dir
        elif os.getenv("MIDI_DIR"):
            self.midi_pool_dir = Path(os.getenv("MIDI_DIR"))
            self.midi_dir = self.midi_pool_dir

        if os.getenv("OUTPUT_DIR"):
            self.output_dir = Path(os.getenv("OUTPUT_DIR"))
        if os.getenv("DATA_DIR"):
            self.data_dir = Path(os.getenv("DATA_DIR"))
            self.processed_log = self.data_dir / "processed.txt"
            self.failed_log = self.data_dir / "failed_pieces.txt"
            self.deletion_log = self.data_dir / "deletion_history.csv"
            self.cleanup_log = self.data_dir / "cleanup_log.md"

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
        if os.getenv("PIPE_PRESET"):
            self.pipe_preset = os.getenv("PIPE_PRESET")
        if os.getenv("RENDER_CAPTURE_MODE"):
            self.capture_mode = os.getenv("RENDER_CAPTURE_MODE").strip()
        if os.getenv("RENDER_SHOW_ALL_88_KEYS"):
            self.show_all_88_keys = os.getenv("RENDER_SHOW_ALL_88_KEYS").strip().lower() in {"1", "true", "yes"}
        if os.getenv("ALIGN_VIDEO_TO_MIDI_T0"):
            self.align_video_to_midi_t0 = os.getenv("ALIGN_VIDEO_TO_MIDI_T0").strip().lower() in {"1", "true", "yes"}
        if os.getenv("FFMPEG_BIN"):
            self.ffmpeg_bin = os.getenv("FFMPEG_BIN")
        if os.getenv("FFPROBE_BIN"):
            self.ffprobe_bin = os.getenv("FFPROBE_BIN")

        # Batch & Target Count
        target_val = os.getenv("TARGET_VIDEOS") or os.getenv("INPUT_TARGET_VIDEOS") or os.getenv("MAX_VIDEOS_PER_RUN")
        if target_val:
            self.target_videos = int(target_val)

        clean_val = os.getenv("CLEAN_PREVIOUS_OUTPUTS") or os.getenv("INPUT_CLEAN_PREVIOUS")
        if clean_val is not None:
            self.clean_previous_outputs = str(clean_val).strip().lower() in {"1", "true", "yes"}

        if os.getenv("MAX_PIECE_DURATION"):
            self.max_piece_duration_seconds = float(os.getenv("MAX_PIECE_DURATION"))
        if os.getenv("MAX_JOB_SECONDS"):
            self.max_job_seconds = float(os.getenv("MAX_JOB_SECONDS"))
        elif os.getenv("INPUT_MAX_HOURS"):
            try:
                self.max_job_seconds = float(os.getenv("INPUT_MAX_HOURS")) * 3600.0
            except ValueError:
                pass

        if os.getenv("RUN_ID"):
            self.run_id = os.getenv("RUN_ID").strip()
        if os.getenv("TEST_SECONDS") or os.getenv("INPUT_TEST_SECONDS"):
            val = (os.getenv("TEST_SECONDS") or os.getenv("INPUT_TEST_SECONDS")).strip()
            if val:
                try:
                    self.test_seconds = float(val)
                except ValueError:
                    self.test_seconds = None

        # Ensure base directories exist
        self.midi_pool_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)


config = Config()
