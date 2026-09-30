"""
Structured logging and time/size formatting utilities.
"""

from __future__ import annotations

import logging
import sys
import time
from typing import Optional


class CustomFormatter(logging.Formatter):
    """Clean logging formatter with timestamp and optional ANSI colors."""

    GREY = "\x1b[38;20m"
    GREEN = "\x1b[32;20m"
    YELLOW = "\x1b[33;20m"
    RED = "\x1b[31;20m"
    BOLD_RED = "\x1b[31;1m"
    CYAN = "\x1b[36;20m"
    RESET = "\x1b[0m"

    FORMAT = "[%(asctime)s] [%(levelname)s] %(message)s"
    DATE_FORMAT = "%H:%M:%S"

    def format(self, record: logging.LogRecord) -> str:
        color = self.GREY
        if record.levelno == logging.INFO:
            color = self.GREEN
        elif record.levelno == logging.WARNING:
            color = self.YELLOW
        elif record.levelno == logging.ERROR:
            color = self.RED
        elif record.levelno == logging.CRITICAL:
            color = self.BOLD_RED
        elif record.levelno == logging.DEBUG:
            color = self.CYAN

        formatter = logging.Formatter(
            f"{color}[%(asctime)s] [%(levelname)s]{self.RESET} %(message)s",
            datefmt=self.DATE_FORMAT,
        )
        return formatter.format(record)


def setup_logger(name: str = "pianofall", level: int = logging.INFO) -> logging.Logger:
    """Configure and return the root logger for the application."""
    logger = logging.getLogger(name)
    logger.setLevel(level)

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(level)

        if sys.stdout.isatty():
            handler.setFormatter(CustomFormatter())
        else:
            handler.setFormatter(
                logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
            )

        logger.addHandler(handler)

    logger.propagate = False
    return logger


def fmt_hms(seconds: float) -> str:
    """Format seconds into human-readable HH:MM:SS or MM:SS."""
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m {s:02d}s"
    return f"{m}m {s:02d}s"


def fmt_bytes(num_bytes: int | float) -> str:
    """Format byte count into human-readable MB / GB."""
    if num_bytes < 1024:
        return f"{num_bytes} B"
    elif num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.1f} KB"
    elif num_bytes < 1024 * 1024 * 1024:
        return f"{num_bytes / (1024 * 1024):.2f} MB"
    else:
        return f"{num_bytes / (1024 * 1024 * 1024):.2f} GB"
