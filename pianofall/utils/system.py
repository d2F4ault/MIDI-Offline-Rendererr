"""
System environment inspection and dependency diagnostics.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from typing import Dict, Optional


def get_system_summary() -> Dict[str, str]:
    """Inspect and return current host OS, CPU core count, and memory."""
    cores = os.cpu_count() or 1
    os_info = f"{platform.system()} {platform.release()} ({platform.machine()})"

    mem_str = "Unknown"
    try:
        if platform.system() == "Linux":
            with open("/proc/meminfo", "r") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        kb = int(line.split()[1])
                        mem_str = f"{kb / (1024 * 1024):.1f} GB"
                        break
        elif platform.system() == "Windows":
            out = subprocess.check_output(
                ["wmic", "computersystem", "get", "TotalPhysicalMemory"],
                text=True,
                stderr=subprocess.DEVNULL,
            )
            lines = [l.strip() for l in out.splitlines() if l.strip().isdigit()]
            if lines:
                bytes_mem = int(lines[0])
                mem_str = f"{bytes_mem / (1024**3):.1f} GB"
    except Exception:
        pass

    return {
        "os": os_info,
        "cpu_cores": str(cores),
        "total_memory": mem_str,
        "python_version": platform.python_version(),
    }


def find_binary(name: str, fallback_path: Optional[str] = None) -> Optional[str]:
    """Locate an executable binary in PATH or return fallback."""
    found = shutil.which(name)
    if found:
        return found
    if fallback_path and os.path.exists(fallback_path):
        return fallback_path
    return None


def get_ffmpeg_version(ffmpeg_bin: str = "ffmpeg") -> Optional[str]:
    """Retrieve the version header string from FFmpeg."""
    try:
        res = subprocess.run(
            [ffmpeg_bin, "-version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if res.returncode == 0:
            lines = res.stdout.strip().splitlines()
            return lines[0] if lines else "Installed"
    except Exception:
        pass
    return None


def check_xvfb_available() -> bool:
    """Check if Xvfb is installed on the host system."""
    return shutil.which("Xvfb") is not None
