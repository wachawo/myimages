"""Crop and scale videos through ffmpeg's geometric video filters.

Cropping and scaling are the two shape edits the viewer offers on a clip, and
both reduce to a single ``-vf`` filter expression, so they are grouped here.
This module reuses :mod:`myimages.video.ffmpeg` so every bit of process
handling and error reporting stays in one place, and it deliberately imports no
Qt so the filter maths can be exercised headlessly in tests.
"""

from __future__ import annotations

from pathlib import Path

from myimages.video import ffmpeg


def crop_video(
    source: str | Path,
    dest: str | Path,
    *,
    left: int,
    top: int,
    width: int,
    height: int,
    runner: ffmpeg.CommandRunner | None = None,
) -> Path:
    """Write a ``width``x``height`` crop of ``source`` to ``dest``.

    A crop whose width or height is not positive describes no pixels at all, so
    we reject it as caller error up front rather than letting ffmpeg fail later
    with an opaque message. ``runner`` is injectable purely so tests can drive
    the argument-building without spawning a real process.
    """
    if width <= 0 or height <= 0:
        raise ValueError(f"invalid crop size: width={width}, height={height}")
    video_filter = f"crop={width}:{height}:{left}:{top}"
    arguments = ["-i", str(source), "-vf", video_filter, str(dest)]
    ffmpeg.run_ffmpeg(arguments, runner=runner or ffmpeg.default_runner)
    return Path(dest)


def scale_video(
    source: str | Path,
    dest: str | Path,
    *,
    width: int | None = None,
    height: int | None = None,
    runner: ffmpeg.CommandRunner | None = None,
) -> Path:
    """Resize ``source`` to ``dest``, optionally preserving the aspect ratio.

    At least one of ``width`` or ``height`` must be given; with neither there is
    no target size to scale toward, so that is rejected as caller error. When
    only one dimension is supplied the other is set to ``-2`` so ffmpeg derives
    it from the source aspect ratio while forcing it even, because many codecs
    reject odd dimensions. ``runner`` is injectable purely so tests can drive
    the argument-building without spawning a real process.
    """
    if width is None and height is None:
        raise ValueError("scale_video needs at least one of width or height")
    if width is not None and height is not None:
        video_filter = f"scale={width}:{height}"
    elif width is not None:
        video_filter = f"scale={width}:-2"
    else:
        video_filter = f"scale=-2:{height}"
    arguments = ["-i", str(source), "-vf", video_filter, str(dest)]
    ffmpeg.run_ffmpeg(arguments, runner=runner or ffmpeg.default_runner)
    return Path(dest)
