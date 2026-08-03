"""Turn cached thumbnail files into QPixmaps without blocking the UI.

The heavy work — decoding a photo or asking ffmpeg for a video frame — happens
on worker threads through :func:`myimages.gui.tasks.run_in_background`, which
retains each task so it cannot be garbage-collected mid-flight. Only the final,
cheap ``QPixmap`` construction runs on the UI thread (Qt requires this) inside
:meth:`deliver`, which the finished callback delivers on the UI thread. Results
are memoised so scrolling back and forth is instant.
"""

from __future__ import annotations

import contextlib
import os

from PySide6.QtCore import QObject, QThreadPool, Signal
from PySide6.QtGui import QPixmap

from myimages.core import thumbnails
from myimages.core.media import MediaFile
from myimages.gui.tasks import run_in_background


class ThumbnailLoader(QObject):
    """Requests thumbnails and emits ready QPixmaps, with an in-memory cache."""

    thumbnail_ready = Signal(str, QPixmap)

    def __init__(self, size: int = 128, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.size = size
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(max(2, (os.cpu_count() or 4) // 2))
        self.cache: dict[str, QPixmap] = {}

    def request(self, media_file: MediaFile) -> None:
        """Ask for a thumbnail; emits ``thumbnail_ready`` now or once generated."""
        key = str(media_file.path)
        cached = self.cache.get(key)
        if cached is not None:
            self.thumbnail_ready.emit(key, cached)
            return
        run_in_background(
            lambda: thumbnails.ensure_thumbnail(media_file, self.size),
            lambda result: self.deliver(key, result),
            pool=self.pool,
        )

    def deliver(self, source: str, result: object) -> None:
        """Wrap a finished thumbnail file into a QPixmap on the UI thread."""
        if result is None:
            return
        pixmap = QPixmap(str(result))
        if pixmap.isNull():
            return
        self.cache[source] = pixmap
        self.thumbnail_ready.emit(source, pixmap)

    def load_now(self, media_file: MediaFile) -> QPixmap | None:
        """Synchronously produce a thumbnail (used by tests and cold starts)."""
        result = thumbnails.ensure_thumbnail(media_file, self.size)
        if result is None:
            return None
        pixmap = QPixmap(str(result))
        if pixmap.isNull():
            return None
        self.cache[str(media_file.path)] = pixmap
        return pixmap

    def forget(self, media_file: MediaFile) -> None:
        """Drop one file's thumbnail from memory and from the on-disk cache.

        Called when a file was deleted or rewritten: the in-memory pixmap is
        keyed by path alone, so without this a re-saved photo would keep showing
        its previous thumbnail, and the superseded PNG would linger on disk
        forever because its cache key can no longer be derived from the file.
        """
        self.cache.pop(str(media_file.path), None)
        cached = thumbnails.cache_path_for(media_file, self.size)
        # A cache we cannot prune is not worth failing a refresh over.
        with contextlib.suppress(OSError):
            cached.unlink(missing_ok=True)

    def clear(self) -> None:
        self.cache.clear()
