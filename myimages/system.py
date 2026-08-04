"""What the host is, for the handful of places that must ask.

Kept in one module so the answers cannot drift: the install advice a user reads
and the console-window flag a subprocess needs are both "which platform is
this", and answering them separately is how one of them ends up telling a
Windows user to run apt.
"""

from __future__ import annotations

import subprocess
import sys

# The package manager command for each platform we ship an artifact for, so the
# advice a user reads is one they can actually paste.
FFMPEG_HINTS: dict[str, str] = {
    "linux": "sudo apt install ffmpeg",
    "darwin": "brew install ffmpeg",
    "win32": "winget install Gyan.FFmpeg",
}


def is_linux() -> bool:
    """Whether the desktop-integration machinery can mean anything here."""
    return sys.platform.startswith("linux")


def ffmpeg_hint() -> str:
    """The command that installs FFmpeg on this platform."""
    for prefix, hint in FFMPEG_HINTS.items():
        if sys.platform.startswith(prefix):
            return hint
    return "see https://ffmpeg.org/download.html"


def quiet_subprocess_flags() -> int:
    """Creation flags that keep a console window from flashing on Windows.

    Every ffprobe call would otherwise pop a black window, and a gallery of
    videos makes one per thumbnail as it scrolls. Zero everywhere else, where
    the flag does not exist.
    """
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
