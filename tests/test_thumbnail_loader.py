"""Tests for :mod:`myimages.gui.thumbnail_loader`.

Constructing ``QPixmap`` and using Qt signals needs a ``QApplication``, so every
test requests ``qtbot``. The ``media_file`` fixture provides a real on-disk image
so thumbnails are generated for real rather than mocked; a cache hit emits
``thumbnail_ready`` synchronously, while a cold ``request`` runs a retained
worker task on the loader's own pool.
"""

from __future__ import annotations

from pathlib import Path

from myimages.core import thumbnails
from myimages.core.media import build_media_file
from myimages.gui.thumbnail_loader import ThumbnailLoader


def test_load_now_returns_pixmap_and_caches(qtbot, media_file):
    loader = ThumbnailLoader(size=64)

    pixmap = loader.load_now(media_file)

    assert pixmap is not None
    assert not pixmap.isNull()
    key = str(media_file.path)
    assert key in loader.cache
    assert loader.cache[key] is pixmap


def test_load_now_other_kind_returns_none(qtbot, tmp_path: Path):
    text_file = tmp_path / "note.txt"
    text_file.write_text("hello", encoding="utf-8")
    media = build_media_file(text_file)

    loader = ThumbnailLoader(size=64)

    assert loader.load_now(media) is None
    assert str(text_file) not in loader.cache


def test_request_with_cached_pixmap_emits_synchronously(qtbot, media_file):
    loader = ThumbnailLoader(size=64)
    pixmap = loader.load_now(media_file)
    assert pixmap is not None

    with qtbot.waitSignal(loader.thumbnail_ready, timeout=1000) as blocker:
        loader.request(media_file)

    assert blocker.args[0] == str(media_file.path)
    emitted = blocker.args[1]
    assert not emitted.isNull()
    assert emitted.cacheKey() == pixmap.cacheKey()


def test_request_generates_thumbnail_via_worker(qtbot, media_file):
    loader = ThumbnailLoader(size=64)

    with qtbot.waitSignal(loader.thumbnail_ready, timeout=5000) as blocker:
        loader.request(media_file)

    assert blocker.args[0] == str(media_file.path)
    assert str(media_file.path) in loader.cache
    loader.pool.waitForDone(3000)


def test_request_other_kind_emits_nothing(qtbot, tmp_path: Path):
    text_file = tmp_path / "note.txt"
    text_file.write_text("x", encoding="utf-8")
    media = build_media_file(text_file)
    loader = ThumbnailLoader(size=64)
    emissions: list[tuple[object, ...]] = []
    loader.thumbnail_ready.connect(lambda *args: emissions.append(args))

    loader.request(media)
    loader.pool.waitForDone(3000)
    qtbot.wait(50)

    assert emissions == []


def test_deliver_emits_for_real_thumbnail(qtbot, media_file, make_image):
    loader = ThumbnailLoader(size=64)
    thumbnail = make_image("thumb.png", (32, 24), (10, 20, 30))
    source = str(media_file.path)

    with qtbot.waitSignal(loader.thumbnail_ready, timeout=1000) as blocker:
        loader.deliver(source, str(thumbnail))

    assert blocker.args[0] == source
    assert source in loader.cache
    assert not loader.cache[source].isNull()


def test_deliver_ignores_none_and_unreadable(qtbot, media_file):
    loader = ThumbnailLoader(size=64)
    source = str(media_file.path)
    emissions: list[tuple[object, ...]] = []
    loader.thumbnail_ready.connect(lambda *args: emissions.append(args))

    loader.deliver(source, None)  # nothing generated
    loader.deliver(source, str(media_file.path.parent / "missing.png"))  # null pixmap

    assert emissions == []
    assert source not in loader.cache


def test_load_now_returns_none_when_pixmap_is_null(
    qtbot, media_file, tmp_path: Path, monkeypatch
):
    # A generated thumbnail that is not a decodable image yields a null QPixmap,
    # which load_now reports as None (never caching it).
    broken = tmp_path / "broken.png"
    broken.write_text("not an image", encoding="utf-8")
    monkeypatch.setattr(thumbnails, "ensure_thumbnail", lambda media, size: broken)

    loader = ThumbnailLoader(size=64)

    assert loader.load_now(media_file) is None
    assert str(media_file.path) not in loader.cache


def test_clear_empties_cache(qtbot, media_file):
    loader = ThumbnailLoader(size=64)
    loader.load_now(media_file)
    assert loader.cache

    loader.clear()

    assert loader.cache == {}


# -- forgetting one file's thumbnail ---------------------------------------


def test_forget_drops_the_pixmap_and_deletes_the_cached_png(qtbot, media_file):
    """Both halves of the cache must go, or the stale preview simply comes back.

    The in-memory pixmap is keyed by path alone and the on-disk PNG outlives
    the app, so dropping only one of the two would still show yesterday's
    picture for a file that has since changed.
    """
    loader = ThumbnailLoader(size=64)
    loader.load_now(media_file)
    cached = thumbnails.cache_path_for(media_file, 64)
    key = str(media_file.path)
    assert key in loader.cache
    assert cached.exists()

    loader.forget(media_file)

    assert key not in loader.cache
    assert not cached.exists()


def test_forget_touches_only_the_named_file(qtbot, make_image):
    kept = build_media_file(make_image("kept.png", (30, 30), (10, 90, 40)))
    dropped = build_media_file(make_image("dropped.png", (24, 18), (90, 10, 40)))
    loader = ThumbnailLoader(size=64)
    loader.load_now(kept)
    loader.load_now(dropped)

    loader.forget(dropped)

    assert str(dropped.path) not in loader.cache
    assert not thumbnails.cache_path_for(dropped, 64).exists()
    # The untouched photo keeps its preview: forgetting one file must never
    # cost a folder-wide re-render.
    assert str(kept.path) in loader.cache
    assert thumbnails.cache_path_for(kept, 64).exists()


def test_forget_a_file_with_no_cached_thumbnail_does_not_raise(qtbot, media_file):
    loader = ThumbnailLoader(size=64)
    assert not thumbnails.cache_path_for(media_file, 64).exists()

    loader.forget(media_file)  # never requested -> nothing to drop or delete

    assert loader.cache == {}


def test_forget_only_prunes_the_requested_size(qtbot, media_file):
    """Sizes have separate cache files, so forgetting one must not orphan another."""
    small = ThumbnailLoader(size=64)
    large = ThumbnailLoader(size=128)
    small.load_now(media_file)
    large.load_now(media_file)

    small.forget(media_file)

    assert not thumbnails.cache_path_for(media_file, 64).exists()
    assert thumbnails.cache_path_for(media_file, 128).exists()


def test_a_forgotten_thumbnail_is_rebuilt_on_the_next_request(qtbot, media_file):
    loader = ThumbnailLoader(size=64)
    loader.load_now(media_file)
    loader.forget(media_file)
    assert not thumbnails.cache_path_for(media_file, 64).exists()

    rebuilt = loader.load_now(media_file)

    assert rebuilt is not None
    assert not rebuilt.isNull()
    assert thumbnails.cache_path_for(media_file, 64).exists()


def test_forget_survives_a_cache_file_it_cannot_delete(qtbot, media_file, monkeypatch):
    """A cache we cannot prune is not worth failing a refresh over."""
    loader = ThumbnailLoader(size=64)
    loader.load_now(media_file)

    def refuse(self, missing_ok=False):
        raise PermissionError("read-only cache directory")

    monkeypatch.setattr(Path, "unlink", refuse)

    loader.forget(media_file)  # must not raise

    # The in-memory half is still dropped, so the screen does not keep showing
    # the stale preview even when the disk half survives.
    assert str(media_file.path) not in loader.cache
