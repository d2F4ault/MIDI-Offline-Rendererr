"""
FFmpeg screen recording subprocess manager with graceful termination.
"""

from __future__ import annotations

import logging
import platform
import subprocess
import threading
from pathlib import Path
from typing import Optional

logger = logging.getLogger("pianofall.recorder")


def start_screen_recorder(
    output_path: Path,
    display: str,
    width: int,
    height: int,
    fps: int,
    ffmpeg_bin: str = "ffmpeg",
    preset: str = "ultrafast",
    crf: int = 17,
) -> subprocess.Popen:
    """
    Launch FFmpeg subprocess recording from the virtual X11 display.
    Uses pure-CPU libx264 with ultrafast preset to minimize CPU load while Chromium renders.
    Output is strictly silent (-an).
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if platform.system() == "Linux":
        disp_target = display if "." in display else f"{display}.0"
        input_args = [
            "-f", "x11grab",
            "-draw_mouse", "0",
            "-video_size", f"{width}x{height}",
            "-framerate", str(fps),
            "-i", disp_target,
        ]
    elif platform.system() == "Windows":
        # Windows fallback for local development/testing
        input_args = [
            "-f", "gdigrab",
            "-draw_mouse", "0",
            "-framerate", str(fps),
            "-video_size", f"{width}x{height}",
            "-i", "desktop",
        ]
    else:
        raise NotImplementedError(f"Unsupported recording platform: {platform.system()}")

    cmd = [
        ffmpeg_bin,
        "-y",
        "-hide_banner",
        "-loglevel", "error",
        *input_args,
        "-an",  # Pure silence: no audio stream
        "-c:v", "libx264",
        "-preset", preset,
        "-crf", str(crf),
        "-pix_fmt", "yuv420p",
        str(output_path),
    ]

    logger.info(f"Starting screen recorder: {' '.join(cmd[:9])} ... -> {output_path.name}")
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        bufsize=0,
    )
    proc._stderr_buf = []

    def _drain_stderr() -> None:
        try:
            if proc.stderr:
                proc._stderr_buf.append(proc.stderr.read())
        except Exception:
            pass

    t = threading.Thread(target=_drain_stderr, daemon=True)
    t.start()
    proc._stderr_thread = t
    return proc


def get_recorder_error_text(proc: subprocess.Popen) -> str:
    """Flush and return any error output captured from FFmpeg stderr."""
    t = getattr(proc, "_stderr_thread", None)
    if t is not None:
        t.join(timeout=1.0)
    return b"".join(getattr(proc, "_stderr_buf", [])).decode("utf-8", "replace")


def stop_screen_recorder(proc: subprocess.Popen, timeout: float = 25.0) -> int:
    """
    Gracefully terminate FFmpeg by writing 'q' to stdin, ensuring MP4 moov atom is written.
    """
    logger.debug("Sending graceful 'q' stop signal to FFmpeg...")
    try:
        if proc.stdin:
            proc.stdin.write(b"q")
            proc.stdin.flush()
    except Exception as e:
        logger.debug(f"Could not write 'q' to stdin: {e}")

    try:
        return proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        logger.warning(f"FFmpeg did not exit within {timeout}s; attempting interrupt...")
        try:
            import signal
            proc.send_signal(signal.SIGINT)
            return proc.wait(timeout=10)
        except Exception:
            pass
        logger.warning("Terminating FFmpeg...")
        proc.terminate()
        try:
            return proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            logger.warning("FFmpeg unresponsive to terminate; sending kill signal...")
            proc.kill()
            return proc.wait()


def validate_raw_recording(path: Path, expected_duration_s: float) -> None:
    """
    Verify that the raw captured video is non-empty and exceeds a minimal byte threshold.
    Guards against silent recording failures or completely static black screens.
    """
    if not path.exists():
        raise FileNotFoundError(f"Recorded file does not exist: {path}")

    size = path.stat().st_size
    # Expect at least 5% of nominal bitrate (e.g. 20KB absolute minimum)
    min_bytes = max(20_000, int(expected_duration_s * 2_500_000 / 8 * 0.05))
    if size < min_bytes:
        raise RuntimeError(
            f"Recording suspiciously small ({size} bytes for {expected_duration_s:.1f}s, min required: {min_bytes} bytes). "
            "Canvas may have failed to render."
        )
