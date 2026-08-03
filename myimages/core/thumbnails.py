"""On-disk thumbnail cache for the gallery grid.

Decoding a full-resolution photo or seeking a video frame is far too slow to do
while scrolling, so every item gets a small PNG rendered once and reused from
disk. Cache filenames are derived from a content-sensitive digest (path plus its
modified time, the requested size and the suffix) so the thumbnail is
transparently invalidated whenever the source file is edited or a different size
is requested, without ever having to compare pixels.

The module deliberately holds no Qt imports: the widgets only need the returned
:class:`~pathlib.Path`, which keeps thumbnail generation testable without a
display and reusable from headless batch tools.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from myimages import paths
from myimages.core.media import MediaFile, MediaKind
from myimages.imaging import transform
from myimages.video import ffmpeg

DEFAULT_THUMBNAIL_SIZE = 128


def thumbnail_cache_key(media_file: MediaFile, size: int) -> str:
    """Return a stable cache identifier for one source file at one size.

    The digest folds in the modified time so an edited file yields a new key
    (the stale thumbnail is simply never looked up again), and the size and
    suffix so requests for different dimensions or file types never collide.
    """
    fingerprint = "\0".join(
        (
            str(media_file.path.resolve()),
            repr(media_file.modified_time),
            str(size),
            media_file.suffix,
        )
    )
    return hashlib.sha1(fingerprint.encode("utf-8"), usedforsecurity=False).hexdigest()


def cache_path_for(media_file: MediaFile, size: int) -> Path:
    """Locate where a given file's thumbnail lives inside the cache directory."""
    return paths.cache_dir() / f"{thumbnail_cache_key(media_file, size)}.png"


def generate_image_thumbnail(source: str | Path, dest: str | Path, size: int) -> bool:
    """Render a downscaled PNG copy of an image, reporting success as a bool.

    Failures (a missing file, an unreadable image) are swallowed and reported as
    ``False`` rather than raised, because a single bad file must never break the
    rendering of an entire gallery.
    """
    try:
        scaled = transform.scale_image(transform.load_image(source), max_edge=size)
        # PNG cannot store palette/animation quirks the loader may hand back, and
        # the grid only ever shows opaque colour, so normalise to plain RGB.
        if scaled.mode != "RGB":
            scaled = scaled.convert("RGB")
        transform.save_image(scaled, dest)
        return True
    except Exception:
        return False


def generate_video_thumbnail(
    source: str | Path,
    dest: str | Path,
    size: int,
    *,
    runner: ffmpeg.CommandRunner | None = None,
) -> bool:
    """Extract a single poster frame from a video into a PNG, if ffmpeg exists.

    The runner is injectable so tests can drive the success and failure paths
    without spawning a real process. Absence of ffmpeg is an expected condition
    on minimal installs, so it reports ``False`` instead of raising.
    """
    if not ffmpeg.is_available():
        return False
    arguments = [
        "-ss",
        "1",
        "-i",
        str(source),
        "-frames:v",
        "1",
        "-vf",
        f"scale={size}:-1",
        str(dest),
    ]
    try:
        ffmpeg.run_ffmpeg(arguments, runner=runner or ffmpeg.default_runner)
        return True
    except ffmpeg.FfmpegError:
        return False


def ensure_thumbnail(
    media_file: MediaFile, size: int = DEFAULT_THUMBNAIL_SIZE
) -> Path | None:
    """Return a cached thumbnail path, generating it on first request.

    This is the single entry point the UI calls per grid cell: a cache hit is
    an existence check and nothing more, so repeated scrolling stays cheap. It
    returns ``None`` for kinds it cannot render or when generation fails, so the
    caller can fall back to a placeholder icon.
    """
    path = cache_path_for(media_file, size)
    if path.exists():
        return path
    if media_file.kind is MediaKind.IMAGE:
        created = generate_image_thumbnail(media_file.path, path, size)
    elif media_file.kind is MediaKind.VIDEO:
        created = generate_video_thumbnail(media_file.path, path, size)
    else:
        return None
    return path if created else None


def clear_cache() -> int:
    """Delete every cached thumbnail and return how many files were removed.

    Exposed so the settings screen can reclaim disk space; the count gives the
    UI something honest to report back to the user.
    """
    removed = 0
    for thumbnail in paths.cache_dir().glob("*.png"):
        thumbnail.unlink()
        removed += 1
    return removed
