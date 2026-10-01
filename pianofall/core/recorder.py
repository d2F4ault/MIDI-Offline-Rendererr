"""
FFmpeg screen recording subprocess manager and pipe-based deterministic frame encoder.
"""

from __future__ import annotations

import logging
import platform
import queue
import struct
import subprocess
import threading
from pathlib import Path
from typing import Optional

logger = logging.getLogger("pianofall.recorder")


def get_png_dimensions(data: bytes) -> tuple[int, int]:
    """Extract (width, height) directly from the 24-byte PNG binary signature/IHDR header."""
    if len(data) >= 24 and data[:8] == b"\x89PNG\r\n\x1a\n":
        return struct.unpack(">II", data[16:24])
    return (0, 0)


def start_ffmpeg_pipe(
    output_path: Path,
    width: int,
    height: int,
    fps: int,
    ffmpeg_bin: str = "ffmpeg",
    preset: str = "faster",
    crf: int = 14,
    pix_fmt: str = "yuv420p",
    max_bitrate: str = "50M",
    bufsize: str = "100M",
    image_format: str = "png",
) -> subprocess.Popen:
    """
    Spawn FFmpeg process that reads image frames continuously from stdin (image2pipe).
    Encodes directly to the target MP4 with libx264 high quality, pure silence (-an),
    and faststart moov atom optimization.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        ffmpeg_bin,
        "-y",
        "-hide_banner",
        "-loglevel", "error",
        "-f", "image2pipe",
        "-framerate", str(fps),
        "-c:v", image_format,
        "-i", "-",
        "-an",  # Pure silence: no audio track
        "-c:v", "libx264",
        "-preset", preset,
        "-crf", str(crf),
        "-maxrate", max_bitrate,
        "-bufsize", bufsize,
        "-pix_fmt", pix_fmt,
        "-profile:v", "high",
        "-s", f"{width}x{height}",
        "-movflags", "+faststart",
        str(output_path),
    ]

    logger.info(
        f"Starting FFmpeg pipe encoder -> {output_path.name} "
        f"({width}x{height} @ {fps}fps, CRF {crf}, preset '{preset}')"
    )
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


class FrameWriter:
    """
    Asynchronous pipe writer that pushes image frame bytes into FFmpeg's stdin
    on a dedicated background thread with bounded queue buffering.
    Ensures that frame capture inside Chromium is never bottlenecked by video encoding.
    """

    def __init__(self, proc: subprocess.Popen, queue_size: int = 128):
        self.proc = proc
        self.q: queue.Queue[Optional[bytes]] = queue.Queue(maxsize=queue_size)
        self.err: Optional[BaseException] = None
        self.t = threading.Thread(target=self._run, daemon=True)
        self.t.start()

    def _run(self) -> None:
        try:
            while True:
                item = self.q.get()
                if item is None:
                    break
                if self.proc.stdin and not self.proc.stdin.closed:
                    self.proc.stdin.write(item)
        except BaseException as e:
            self.err = e

    def push_blocking(self, data: bytes) -> None:
        if self.err:
            raise RuntimeError(f"FFmpeg stdin pipe writer failed: {self.err}")
        self.q.put(data)

    def finish(self, timeout: float = 120.0) -> None:
        self.q.put(None)
        self.t.join(timeout=timeout)
        if self.err:
            raise RuntimeError(f"FFmpeg stdin pipe writer failed during drain: {self.err}")


def stop_ffmpeg_pipe(proc: subprocess.Popen, timeout: float = 60.0) -> int:
    """
    Gracefully finalize FFmpeg pipe by closing stdin and waiting for encoder completion.
    """
    logger.debug("Closing FFmpeg stdin pipe and draining...")
    try:
        if proc.stdin and not proc.stdin.closed:
            proc.stdin.close()
    except Exception as e:
        logger.debug(f"Error closing FFmpeg stdin: {e}")

    try:
        return proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        logger.warning(f"FFmpeg did not finish within {timeout}s; sending terminate...")
        proc.terminate()
        try:
            return proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            logger.warning("FFmpeg unresponsive to terminate; sending kill signal...")
            proc.kill()
            return proc.wait()


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
    Launch FFmpeg subprocess recording from the virtual X11 display (fallback engine).
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
        "-an",
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
    Verify that the recorded video is non-empty and exceeds a minimal byte threshold.
    Guards against silent recording failures or completely static black screens.
    """
    if not path.exists():
        raise FileNotFoundError(f"Recorded file does not exist: {path}")

    size = path.stat().st_size
    min_bytes = max(20_000, int(expected_duration_s * 2_500_000 / 8 * 0.05))
    if size < min_bytes:
        raise RuntimeError(
            f"Recording suspiciously small ({size} bytes for {expected_duration_s:.1f}s, min required: {min_bytes} bytes). "
            "Canvas may have failed to render."
        )
