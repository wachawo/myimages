"""Trim a video to a chosen span of the timeline.

Trimming is expressed as two independent times on the clip's timeline rather
than a start plus a length, because that is how the UI presents it (a pair of
handles the user drags). This module reuses :mod:`myimages.video.ffmpeg` so all
process handling and error reporting stay in one place, and it stays free of Qt
so the timeline maths can be tested without a display.

Two strategies are offered because they trade speed for accuracy. A stream copy
is near-instant but can only cut on keyframes, so the actual start may drift to
the nearest earlier keyframe; a full re-encode is slower but honours the exact
requested boundaries. The caller decides which matters for a given clip.
"""

from __future__ import annotations

from pathlib import Path

from myimages.video import ffmpeg


class TrimError(ValueError):
    """Raised when the requested trim span is not a valid interval.

    It subclasses :class:`ValueError` because a start/end that do not form a
    positive-length interval is bad input from the caller, not a failure of the
    underlying ffmpeg process (which surfaces as ``FfmpegError`` instead).
    """


def trim_video(
    source: str | Path,
    dest: str | Path,
    start: float,
    end: float,
    *,
    reencode: bool = False,
    runner: ffmpeg.CommandRunner | None = None,
) -> Path:
    """Write the ``start``..``end`` span of ``source`` to ``dest``.

    ``start`` and ``end`` are seconds on the source timeline; the span must have
    a positive length, so we reject anything where ``start`` is negative or
    ``end`` does not lie strictly after ``start`` before spending time on
    ffmpeg. When ``reencode`` is false the frames are copied verbatim for speed;
    when true they are re-encoded so the cut lands exactly on the requested
    boundaries. ``runner`` is injectable purely so tests can drive the
    argument-building without invoking a real process.
    """
    if start < 0 or end <= start:
        raise TrimError(f"invalid trim span: start={start}, end={end}")
    duration = end - start
    if reencode:
        arguments = [
            "-i",
            str(source),
            "-ss",
            str(start),
            "-to",
            str(end),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-c:a",
            "aac",
            str(dest),
        ]
    else:
        arguments = [
            "-ss",
            str(start),
            "-i",
            str(source),
            "-t",
            str(duration),
            "-c",
            "copy",
            str(dest),
        ]
    ffmpeg.run_ffmpeg(arguments, runner=runner or ffmpeg.default_runner)
    return Path(dest)
