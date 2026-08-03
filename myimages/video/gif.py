"""Build animated GIFs, either from a video clip or from a list of stills.

The viewer offers two very different ways to reach the same artefact, so they
live side by side here. Turning a *video* into a GIF is a re-encoding job best
left to ffmpeg's two-pass palette filters, which is why that path reuses
:mod:`myimages.video.ffmpeg` and never opens the clip in Python. Turning a set
of *still frames* into a GIF is pure image assembly with no timeline decoding to
do, so that path uses Pillow directly and deliberately avoids ffmpeg -- it keeps
the frames feature working even on machines without ffmpeg installed.

No Qt is imported: both operations are plain data transforms so they can be
exercised headlessly in tests.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from PIL import Image

from myimages.video import ffmpeg


class GifError(ValueError):
    """Raised when GIF inputs are unusable before any encoding is attempted.

    It subclasses :class:`ValueError` because an empty frame list is bad input
    from the caller, not a failure of an underlying tool; genuine ffmpeg
    failures surface separately as :class:`myimages.video.ffmpeg.FfmpegError`.
    """


def gif_from_video(
    source: str | Path,
    dest: str | Path,
    *,
    start: float = 0.0,
    duration: float | None = None,
    fps: int = 12,
    width: int = 480,
    runner: ffmpeg.CommandRunner | None = None,
) -> Path:
    """Encode a span of ``source`` into an animated GIF at ``dest``.

    A naive single-pass GIF export quantises every frame against the default
    216-colour web palette and looks muddy, so we use ffmpeg's two-pass
    ``palettegen``/``paletteuse`` filter chain: the stream is split, an optimal
    palette is generated from it, and the same frames are then mapped through
    that palette. ``fps`` and ``width`` are baked into the same filtergraph so
    the clip is thinned and downscaled (with the high-quality Lanczos filter)
    before palette work, keeping the output small. ``start`` and ``duration``
    are placed before ``-i`` so ffmpeg seeks by input rather than decoding the
    whole clip. ``runner`` is injectable purely so tests can inspect the built
    arguments without spawning a real process.
    """
    filtergraph = (
        f"fps={fps},scale={width}:-1:flags=lanczos,"
        "split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse"
    )
    arguments: list[str] = [
        "-ss",
        str(start),
        *(["-t", str(duration)] if duration is not None else []),
        "-i",
        str(source),
        "-filter_complex",
        filtergraph,
        "-loop",
        "0",
        str(dest),
    ]
    ffmpeg.run_ffmpeg(arguments, runner=runner or ffmpeg.default_runner)
    return Path(dest)


def prepare_frame(source: str | Path, width: int | None) -> Image.Image:
    """Load one still and normalise it for inclusion in a GIF.

    Frames are forced to ``"RGB"`` because GIF is a paletted format and letting
    Pillow quantise from a consistent mode gives predictable colours across a
    mix of source formats (PNG with alpha, JPEG, and so on). When ``width`` is
    requested the frame is scaled to it while preserving aspect ratio, so a
    caller can shrink oversized photos to a uniform GIF width without distorting
    them; the height is derived from the source ratio.
    """
    loaded = Image.open(source)
    if width is None:
        return loaded.convert("RGB")
    scaled_height = round(loaded.height * width / loaded.width)
    resized = loaded.resize((width, scaled_height), Image.Resampling.LANCZOS)
    return resized.convert("RGB")


def gif_from_frames(
    image_paths: Sequence[str | Path],
    dest: str | Path,
    *,
    fps: int = 12,
    width: int | None = None,
    loop: int = 0,
) -> Path:
    """Assemble ``image_paths`` into an animated GIF written to ``dest``.

    An empty sequence has no first frame to anchor the animation on, so we
    reject it up front rather than letting Pillow raise an opaque index error.
    The per-frame delay is derived from ``fps`` and rounded to whole
    milliseconds because that is the granularity the GIF format stores. Frames
    are written with ``disposal=2`` so each is cleared to the background before
    the next is drawn, which prevents earlier frames from bleeding through when
    the stills differ in size or transparency.
    """
    if not image_paths:
        raise GifError("gif_from_frames needs at least one image")
    frames = [prepare_frame(path, width) for path in image_paths]
    frame_duration_ms = round(1000 / fps)
    first_frame, *remaining_frames = frames
    first_frame.save(
        dest,
        format="GIF",
        save_all=True,
        append_images=remaining_frames,
        duration=frame_duration_ms,
        loop=loop,
        disposal=2,
    )
    return Path(dest)
