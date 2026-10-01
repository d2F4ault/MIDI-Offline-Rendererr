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


import shutil

_GLOBAL_WM_PROC: Optional[subprocess.Popen] = None


def start_xvfb(display: str, width: int, height: int, depth: int = 24) -> Optional[subprocess.Popen]:
    """
    Start an Xvfb virtual frame-buffer on Linux.
    Clean up any orphaned Xvfb sockets first to prevent collision.
    Also starts matchbox-window-manager if available to enforce borderless kiosk geometry.
    """
    global _GLOBAL_WM_PROC

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

    # Start lightweight kiosk window manager if present (enforces 100% full-screen without titlebar/borders)
    if shutil.which("matchbox-window-manager"):
        try:
            logger.info("Starting matchbox-window-manager (titlebars disabled)...")
            _GLOBAL_WM_PROC = subprocess.Popen(
                ["matchbox-window-manager", "-use_titlebar", "no"],
                env=os.environ,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            logger.warning(f"Could not launch matchbox-window-manager: {e}")

    return proc


def stop_xvfb(proc: Optional[subprocess.Popen]) -> None:
    """Terminate and reap the Xvfb and window manager processes."""
    global _GLOBAL_WM_PROC
    if _GLOBAL_WM_PROC is not None:
        try:
            _GLOBAL_WM_PROC.terminate()
            _GLOBAL_WM_PROC.wait(timeout=2)
        except Exception:
            try:
                _GLOBAL_WM_PROC.kill()
            except Exception:
                pass
        _GLOBAL_WM_PROC = None

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


def get_chromium_args(viewport_w: int, viewport_h: int, app_url: Optional[str] = None) -> list[str]:
    """
    Construct optimal Chromium launch flags for pure-CPU rendering on virtual display.
    Guarantees borderless, full-bleed (0,0) to (viewport_w, viewport_h) rendering with zero chrome.
    """
    args = [
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
        "--start-fullscreen",
        "--hide-scrollbars",
        "--disable-infobars",
        "--noerrdialogs",
        "--disable-session-crashed-bubble",
        "--disable-restore-session-state",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-notifications",
        "--disable-blink-features=AutomationControlled",
        "--disable-features=Translate,OptimizationHints,MediaRouter",
        "--force-device-scale-factor=1",
    ]
    if app_url:
        args.append(f"--app={app_url}")
    return args


def get_headless_chromium_args(viewport_w: int, viewport_h: int) -> list[str]:
    """
    Construct optimal Chromium launch flags for headless deterministic page rendering.
    Completely eliminates all OS window chrome, tab bars, omnibox, and borders.
    """
    return [
        "--headless=new",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu-sandbox",
        "--use-gl=swiftshader",
        "--enable-webgl",
        "--mute-audio",
        "--disable-extensions",
        "--hide-scrollbars",
        "--disable-background-timer-throttling",
        "--disable-renderer-backgrounding",
        "--disable-backgrounding-occluded-windows",
        f"--window-size={viewport_w},{viewport_h}",
        "--force-device-scale-factor=1",
    ]

