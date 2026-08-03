"""Discovering and ordering the media files a folder contains.

The scanner turns a directory into a list of ``MediaFile`` snapshots and
supplies the sort orders the gallery offers. It stays deliberately thin: it
reuses ``classify`` and ``build_media_file`` from :mod:`myimages.core.media`
so the rules for what counts as an image or a video live in exactly one place
and never drift between the model and the walker.

Pixel dimensions are handled separately by ``fill_image_dimensions`` because
opening every file to measure it is far slower than the ``stat``-only walk.
Keeping the two phases apart lets callers pay that cost only when a resolution
sort or a resolution label is actually about to be shown.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import Any

from PIL import Image

from myimages.core.media import (
    MediaFile,
    MediaKind,
    build_media_file,
    classify,
)


def readable_entries(root: Path, recursive: bool) -> Iterator[Path]:
    """Yield a folder's entries, treating an unreadable folder as an empty one.

    The window scans whatever folder it was last pointed at as soon as it opens,
    so a directory the user may no longer read (permissions changed, an unmounted
    share) must end the walk quietly rather than take the whole app down with a
    ``PermissionError``. Unreadable *sub*-directories are already skipped by
    ``rglob`` itself, so only the top-level listing needs this guard.

    The guard is in two places because the two interpreters we support disagree
    about *when* the listing happens. Up to 3.12 ``iterdir`` is lazy and the
    failure arrives on the first step; from 3.13 it reads the directory as it is
    called, so the failure arrives before the loop is ever entered. Catching in
    only one place passes on one set of versions and raises on the other.
    """
    try:
        walker = root.rglob("*") if recursive else root.iterdir()
    except OSError:
        return
    while True:
        try:
            yield next(walker)
        except StopIteration:
            return
        except OSError:
            return


def scan_directory(
    directory: str | Path,
    *,
    recursive: bool = False,
    include_images: bool = True,
    include_videos: bool = True,
    include_documents: bool = True,
) -> list[MediaFile]:
    """Walk ``directory`` and return the media files it holds.

    Sub-directories and unrecognised files are skipped so the caller only ever
    sees genuine photos or videos. A ``stat`` failure on a single entry (a file
    vanishing mid-walk, a broken symlink) is swallowed rather than aborting the
    whole scan, because one unreadable item should never hide every other file
    in the folder. Results keep filesystem order; sorting is an explicit,
    separate step so a scan never pays for an order the caller does not want.
    """
    root = Path(directory)
    found: list[MediaFile] = []
    for entry in readable_entries(root, recursive):
        if entry.is_dir():
            continue
        media_kind = classify(entry)
        if media_kind is MediaKind.OTHER:
            continue
        if media_kind is MediaKind.IMAGE and not include_images:
            continue
        if media_kind is MediaKind.VIDEO and not include_videos:
            continue
        if media_kind is MediaKind.DOCUMENT and not include_documents:
            continue
        try:
            found.append(build_media_file(entry))
        except OSError:
            continue
    return found


def sort_media(
    files: Iterable[MediaFile],
    sort_key: str,
    descending: bool = False,
) -> list[MediaFile]:
    """Return ``files`` ordered by one of the gallery's named sort keys.

    An unrecognised key degrades to name order instead of raising, because the
    key often comes from persisted UI state that an older build may reference a
    mode a newer build renamed or dropped. Falling back keeps the gallery
    usable on load rather than crashing over a stale preference. The sort is
    stable, so files sharing a key value keep their incoming relative order.
    """
    orderings: dict[str, Callable[[MediaFile], Any]] = {
        "name": lambda media: media.path.name.lower(),
        "size": lambda media: media.size_bytes,
        "resolution": lambda media: media.pixel_count,
        "modified": lambda media: media.modified_time,
    }
    chosen = orderings.get(sort_key, orderings["name"])
    return sorted(files, key=chosen, reverse=descending)


def probe_image_dimensions(path: str | Path) -> tuple[int | None, int | None]:
    """Read an image's pixel size without decoding its full contents.

    Pillow exposes ``.size`` from the header alone, so this stays cheap even
    for very large photos. Any failure at all -- a truncated file, a codec
    Pillow cannot read, or a path that is not an image -- collapses to
    ``(None, None)`` so callers can treat "unknown" uniformly instead of
    juggling a family of image-library exceptions.
    """
    try:
        with Image.open(path) as image:
            width, height = image.size
        return (width, height)
    except Exception:
        return (None, None)


def reuse_known_dimensions(
    files: Iterable[MediaFile], known: Iterable[MediaFile]
) -> list[MediaFile]:
    """Copy pixel sizes across from an earlier scan of the same files.

    A rescan produces fresh snapshots with no dimensions, so measuring them
    again would re-open every photo in the folder even though only one file
    changed. Sizes are reused only when the path, byte size and modified time
    all still match, which is precisely when the pixels cannot have changed.
    """
    previous = {
        (str(media.path), media.size_bytes, media.modified_time): media
        for media in known
        if media.width is not None
    }
    carried: list[MediaFile] = []
    for media in files:
        match = previous.get((str(media.path), media.size_bytes, media.modified_time))
        if match is None:
            carried.append(media)
        else:
            carried.append(media.with_dimensions(match.width, match.height))
    return carried


def fill_image_dimensions(files: Iterable[MediaFile]) -> list[MediaFile]:
    """Return a new list with missing image dimensions probed and attached.

    Only images that still lack a width are opened, so re-running this over an
    already-measured list is cheap and videos (never probed here) pass straight
    through untouched. A fresh list of fresh ``MediaFile`` copies is returned so
    the immutability the rest of the app relies on is preserved and the input
    is never mutated in place.
    """
    measured: list[MediaFile] = []
    for media in files:
        if media.kind is MediaKind.IMAGE and media.width is None:
            width, height = probe_image_dimensions(media.path)
            measured.append(media.with_dimensions(width, height))
        else:
            measured.append(media)
    return measured
