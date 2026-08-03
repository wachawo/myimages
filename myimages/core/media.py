"""The media model: how a file on disk is described to the rest of the app.

``MediaFile`` is an immutable snapshot of one photo or video. It carries only
cheap-to-read metadata (kind, byte size, modified time) plus optional pixel
dimensions, which are filled in lazily because probing them can be slow for
videos.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path

IMAGE_EXTENSIONS: frozenset[str] = frozenset(
    {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff", ".heic"}
)
VIDEO_EXTENSIONS: frozenset[str] = frozenset(
    {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".mpg", ".mpeg", ".wmv"}
)
DOCUMENT_EXTENSIONS: frozenset[str] = frozenset({".pdf"})


class MediaKind(Enum):
    """Top-level category the app treats a file as."""

    IMAGE = "image"
    VIDEO = "video"
    DOCUMENT = "document"
    OTHER = "other"


def classify(path: str | Path) -> MediaKind:
    """Decide a file's kind purely from its extension (no disk access)."""
    suffix = Path(path).suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        return MediaKind.IMAGE
    if suffix in VIDEO_EXTENSIONS:
        return MediaKind.VIDEO
    if suffix in DOCUMENT_EXTENSIONS:
        return MediaKind.DOCUMENT
    return MediaKind.OTHER


@dataclass(frozen=True)
class MediaFile:
    """An immutable description of a single media file."""

    path: Path
    kind: MediaKind
    size_bytes: int
    modified_time: float
    width: int | None = None
    height: int | None = None

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def suffix(self) -> str:
        return self.path.suffix.lower()

    @property
    def pixel_count(self) -> int:
        """Total pixels, or 0 when dimensions are not yet known."""
        if self.width is None or self.height is None:
            return 0
        return self.width * self.height

    @property
    def resolution_label(self) -> str:
        if self.width is None or self.height is None:
            return "—"
        return f"{self.width}×{self.height}"

    def with_dimensions(self, width: int | None, height: int | None) -> MediaFile:
        """Return a copy carrying the given pixel dimensions."""
        return replace(self, width=width, height=height)


def build_media_file(path: str | Path) -> MediaFile:
    """Create a ``MediaFile`` from a path, reading only ``stat`` metadata."""
    resolved = Path(path)
    stat = resolved.stat()
    return MediaFile(
        path=resolved,
        kind=classify(resolved),
        size_bytes=stat.st_size,
        modified_time=stat.st_mtime,
    )
