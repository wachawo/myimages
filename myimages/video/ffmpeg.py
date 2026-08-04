"""A thin, testable wrapper around the ffmpeg and ffprobe command-line tools.

The rest of the video code speaks to ffmpeg only through here, which keeps the
argument-building in one place and lets tests inject a fake command runner. All
runs are non-destructive to the caller: ffmpeg is always invoked with ``-y`` so
it overwrites its own output rather than blocking on a prompt.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from myimages.system import ffmpeg_hint, quiet_subprocess_flags

CommandRunner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


class FfmpegError(RuntimeError):
    """Raised when ffmpeg/ffprobe is missing or returns a non-zero status."""


@dataclass(frozen=True)
class VideoInfo:
    """The handful of stream facts the UI needs about a clip."""

    duration: float
    width: int
    height: int
    fps: float


def ffmpeg_path() -> str | None:
    return shutil.which("ffmpeg")


def ffprobe_path() -> str | None:
    return shutil.which("ffprobe")


def is_available() -> bool:
    return ffmpeg_path() is not None and ffprobe_path() is not None


def require_ffmpeg() -> None:
    if ffmpeg_path() is None or ffprobe_path() is None:
        raise FfmpegError(
            "FFmpeg is not installed. Install it with your system package "
            f"manager: {ffmpeg_hint()}"
        )


def default_runner(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    """Run a command capturing text output, without raising on failure."""
    return subprocess.run(  # noqa: S603 - command is app-controlled
        list(command),
        capture_output=True,
        text=True,
        check=False,
        creationflags=quiet_subprocess_flags(),
    )


def run_ffmpeg(
    arguments: Sequence[str],
    *,
    runner: CommandRunner = default_runner,
) -> subprocess.CompletedProcess[str]:
    """Invoke ffmpeg with sensible defaults, raising on any failure."""
    require_ffmpeg()
    binary = ffmpeg_path()
    assert binary is not None  # guaranteed by require_ffmpeg
    command = [binary, "-y", "-hide_banner", "-loglevel", "error", *arguments]
    completed = runner(command)
    if completed.returncode != 0:
        raise FfmpegError(completed.stderr.strip() or "ffmpeg failed")
    return completed


def parse_frame_rate(text: str) -> float:
    """Turn ffprobe's ``"num/den"`` frame-rate string into frames per second."""
    if "/" in text:
        numerator, separator, denominator = text.partition("/")
        try:
            den = float(denominator)
            return float(numerator) / den if den else 0.0
        except ValueError:
            return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def probe_video(
    path: str | Path,
    *,
    runner: CommandRunner = default_runner,
) -> VideoInfo:
    """Read duration, dimensions and frame rate of the first video stream."""
    probe = ffprobe_path()
    if probe is None:
        raise FfmpegError("ffprobe is not installed.")
    command = [
        probe,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    completed = runner(command)
    if completed.returncode != 0:
        raise FfmpegError(completed.stderr.strip() or "ffprobe failed")
    payload = json.loads(completed.stdout or "{}")
    streams = payload.get("streams", [])
    video_stream = next(
        (item for item in streams if item.get("codec_type") == "video"), None
    )
    if video_stream is None:
        raise FfmpegError("no video stream found")
    duration_text = video_stream.get("duration") or payload.get("format", {}).get(
        "duration", "0"
    )
    return VideoInfo(
        duration=float(duration_text or 0.0),
        width=int(video_stream.get("width", 0)),
        height=int(video_stream.get("height", 0)),
        fps=parse_frame_rate(str(video_stream.get("avg_frame_rate", "0/0"))),
    )
