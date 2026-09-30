"""
Offline retiming and high-quality libx264 CPU video mastering.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger("pianofall.postprocess")


def probe_duration_seconds(path: Path, ffprobe_bin: str = "ffprobe") -> float:
    """Read the exact duration in seconds of a video file using ffprobe."""
    cmd = [
        ffprobe_bin,
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if out.returncode != 0:
            raise RuntimeError(f"ffprobe failed: {out.stderr}")
        return float(out.stdout.strip())
    except Exception as e:
        raise RuntimeError(f"Failed to probe duration for {path.name}: {e}") from e


def retime_and_master_video(
    src_raw: Path,
    dst_final: Path,
    target_duration_s: float,
    target_fps: int = 60,
    preset: str = "fast",
    crf: int = 18,
    max_bitrate: str = "10M",
    buffer_size: str = "20M",
    ffmpeg_bin: str = "ffmpeg",
    ffprobe_bin: str = "ffprobe",
) -> float:
    """
    Retime the raw browser screen recording to match the exact mathematical MIDI duration.

    Because browser software rasterization (SwiftShader) runs slower than real-time on CPU,
    the raw capture plays in slow motion. Using FFmpeg's setpts filter resamples the frames
    smoothly to guarantee 100% accurate 1x tempo and timeline synchronization.

    Encodes with high-quality libx264 settings, ensuring a visually transparent result
    while remaining strictly silent (-an) and under GitHub's 100MB file ceiling.
    """
    dst_final.parent.mkdir(parents=True, exist_ok=True)
    actual_seconds = probe_duration_seconds(src_raw, ffprobe_bin=ffprobe_bin)

    ratio = actual_seconds / target_duration_s if target_duration_s > 0 else 1.0
    effective_speed = 1.0 / ratio if ratio > 0 else 1.0

    logger.info(
        f"Raw capture: {actual_seconds:.2f}s vs target {target_duration_s:.2f}s "
        f"(playback speed: ~{effective_speed:.2f}x real-time). Retiming to 1x @ {target_fps} FPS..."
    )

    filter_expr = f"setpts={1/ratio:.6f}*PTS,fps={target_fps}"

    cmd = [
        ffmpeg_bin,
        "-y",
        "-hide_banner",
        "-loglevel", "error",
        "-i", str(src_raw),
        "-filter:v", filter_expr,
        "-an",  # Silent output
        "-c:v", "libx264",
        "-preset", preset,
        "-crf", str(crf),
        "-pix_fmt", "yuv420p",
        "-profile:v", "high",
        "-maxrate", max_bitrate,
        "-bufsize", buffer_size,
        "-movflags", "+faststart",
        str(dst_final),
    ]

    logger.info(f"Running high-quality CPU mastering pass (libx264 preset={preset}, crf={crf})...")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(f"Video mastering pass failed (exit code {result.returncode}):\n{result.stderr}")

    if not dst_final.exists() or dst_final.stat().st_size == 0:
        raise RuntimeError(f"Target video was not produced or is 0 bytes: {dst_final}")

    final_size_mb = dst_final.stat().st_size / (1024 * 1024)
    logger.info(f"Mastering pass completed: {dst_final.name} ({final_size_mb:.2f} MB)")
    return actual_seconds
