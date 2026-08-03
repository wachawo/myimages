"""Filesystem locations for settings, the thumbnail cache and plugins.

Everything the app persists lives under a single per-user data directory so it
is trivial to find, back up or delete. Tests point ``MYIMAGES_DATA_DIR`` at a
temporary folder to stay isolated from a developer's real data.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

DATA_DIR_ENV = "MYIMAGES_DATA_DIR"


def is_frozen() -> bool:
    """True when running from a PyInstaller/AppImage bundle rather than source."""
    return bool(getattr(sys, "frozen", False))


def data_dir() -> Path:
    """Root directory for all persisted state; created on first access."""
    override = os.environ.get(DATA_DIR_ENV)
    base = Path(override).expanduser() if override else Path.home() / ".myimages"
    base.mkdir(parents=True, exist_ok=True)
    return base


def cache_dir() -> Path:
    """Directory holding the on-disk thumbnail cache."""
    path = data_dir() / "thumbnails"
    path.mkdir(parents=True, exist_ok=True)
    return path


def plugins_dir() -> Path:
    """Directory scanned for user-supplied plugin modules."""
    path = data_dir() / "plugins"
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_file() -> Path:
    """Path of the rotating log file used by packaged (windowless) builds."""
    return data_dir() / "myimages.log"


def default_media_dir() -> Path:
    """A sensible folder to open on first launch."""
    for name in ("Pictures", "Изображения", "Photos"):
        candidate = Path.home() / name
        if candidate.is_dir():
            return candidate
    return Path.home()
