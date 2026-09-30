"""
Browser lifecycle and headless Xvfb display management.
"""

from __future__ import annotations

import logging
import os
import platform
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("pianofall.browser")


def start_xvfb(display: str, width: int, height: int, depth: int = 24) -> Optional[subprocess.Popen]:
    """
    Start an Xvfb virtual frame-buffer on Linux.
    Clean up any orphaned Xvfb sockets first to prevent collision.
    """
    if platform.system() != "Linux":
        logger.info(f"Host OS is {platform.system()}; skipping Xvfb initialization.")
        return None

    disp_num = display.lstrip(":").split(".")[0]
    canonical_display = f":{disp_num}"
    os.makedirs("/tmp/.X11-unix", exist_ok=True)
    sock_path = Path(f"/tmp/.X11-unix/X{disp_num}")

    # Terminate any leftover Xvfb process on this display and clean stale socket
    try:
        subprocess.run(
            ["pkill", "-9", "-f", f"Xvfb {canonical_display}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
    except Exception:
        pass

    if sock_path.exists():
        try:
            sock_path.unlink(missing_ok=True)
        except Exception:
            pass

    time.sleep(0.3)

    logger.info(f"Starting Xvfb display on {canonical_display} ({width}x{height}x{depth})...")
    proc = subprocess.Popen(
        ["Xvfb", canonical_display, "-screen", "0", f"{width}x{height}x{depth}", "-ac", "-nolisten", "tcp"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
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

    # Wait for the X11 domain socket to become available
    for _ in range(50):
        if proc.poll() is not None:
            break
        if sock_path.exists():
            break
        time.sleep(0.1)

    if not sock_path.exists() or proc.poll() is not None:
        t.join(timeout=1.0)
        err = b"".join(getattr(proc, "_stderr_buf", [])).decode("utf-8", "replace")
        try:
            proc.kill()
        except Exception:
            pass
        raise RuntimeError(f"Xvfb failed to start on display {display}:\n{err}")

    os.environ["DISPLAY"] = canonical_display
    logger.info(f"Xvfb successfully bound to DISPLAY={canonical_display}")
    return proc


def stop_xvfb(proc: Optional[subprocess.Popen]) -> None:
    """Terminate and reap the Xvfb process."""
    if proc is None:
        return
    logger.debug("Stopping Xvfb display...")
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        logger.warning("Xvfb did not exit on terminate; killing...")
        proc.kill()
        proc.wait()
    except Exception as e:
        logger.warning(f"Error shutting down Xvfb: {e}")


def get_chromium_args(viewport_w: int, viewport_h: int) -> list[str]:
    """
    Construct optimal Chromium launch flags for pure-CPU rendering on virtual display.
    """
    return [
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu-sandbox",
        "--use-gl=swiftshader",  # Reliable pure-CPU software rasterizer
        "--enable-webgl",
        "--mute-audio",
        "--disable-extensions",
        "--disable-background-timer-throttling",
        "--disable-renderer-backgrounding",
        "--disable-backgrounding-occluded-windows",
        "--window-position=0,0",
        f"--window-size={viewport_w},{viewport_h}",
        "--kiosk",
        "--hide-scrollbars",
        "--disable-infobars",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-notifications",
        "--disable-features=Translate,OptimizationHints,MediaRouter",
    ]
