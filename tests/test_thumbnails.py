"""Behavioural tests for the on-disk thumbnail cache.

These exercise real files through Pillow and, when ffmpeg is present, a real
clip via the shared ``sample_video`` fixture. Only the ffmpeg command runner is
injected, so the cache-key, generation and eviction logic is verified against
genuine disk state rather than mocks.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest
from PIL import Image

from myimages import paths
from myimages.core.media import MediaKind, build_media_file
from myimages.core.thumbnails import (
    cache_path_for,
    clear_cache,
    ensure_thumbnail,
    generate_image_thumbnail,
    generate_video_thumbnail,
    thumbnail_cache_key,
)
from myimages.video import ffmpeg


def test_ensure_thumbnail_creates_smaller_valid_png(
    make_image: Callable[..., Path],
) -> None:
    """A real image yields a genuine PNG downscaled below the requested edge."""
    source = make_image(name="big.png", size=(200, 150))
    media = build_media_file(source)

    result = ensure_thumbnail(media, 64)

    assert result is not None
    assert result.exists()
    with Image.open(result) as thumbnail:
        assert thumbnail.format == "PNG"
        assert thumbnail.mode == "RGB"
        assert max(thumbnail.size) <= 64
        assert thumbnail.width < 200


def test_ensure_thumbnail_reuses_cache_without_regenerating(
    make_image: Callable[..., Path],
) -> None:
    """A second request is served from disk, leaving the file untouched."""
    media = build_media_file(make_image(name="reuse.png", size=(120, 90)))

    first = ensure_thumbnail(media, 64)
    assert first is not None

    # Backdate the file so any accidental regeneration would move the mtime
    # forward to "now" and fail the assertion below.
    backdated = first.stat().st_mtime - 5000
    os.utime(first, (backdated, backdated))
    marker = first.stat().st_mtime_ns

    second = ensure_thumbnail(media, 64)

    assert second == first
    assert second.stat().st_mtime_ns == marker


def test_ensure_thumbnail_returns_none_for_other_kind(tmp_path: Path) -> None:
    """A non-media file cannot be thumbnailed and yields ``None``."""
    document = tmp_path / "notes.txt"
    document.write_text("just some text", encoding="utf-8")
    media = build_media_file(document)

    assert media.kind is MediaKind.OTHER
    assert ensure_thumbnail(media) is None


def test_ensure_thumbnail_returns_none_when_generation_fails(
    tmp_path: Path,
) -> None:
    """An image-suffixed file with junk bytes fails generation, giving ``None``."""
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"this is not a real png")
    media = build_media_file(broken)

    assert media.kind is MediaKind.IMAGE
    assert ensure_thumbnail(media, 64) is None


def test_generate_image_thumbnail_converts_non_rgb(tmp_path: Path) -> None:
    """A greyscale source is normalised to RGB in the saved PNG."""
    grey = tmp_path / "grey.png"
    Image.new("L", (100, 80), 128).save(grey)
    dest = tmp_path / "grey_thumb.png"

    assert generate_image_thumbnail(grey, dest, 40) is True
    with Image.open(dest) as thumbnail:
        assert thumbnail.mode == "RGB"
        assert thumbnail.format == "PNG"


def test_generate_image_thumbnail_on_bogus_path_returns_false(
    tmp_path: Path,
) -> None:
    """A missing source is reported as failure and writes nothing."""
    dest = tmp_path / "out.png"

    assert generate_image_thumbnail(tmp_path / "missing.png", dest, 64) is False
    assert not dest.exists()


def test_cache_key_is_stable_and_size_sensitive(
    make_image: Callable[..., Path],
) -> None:
    """Identical inputs share a key; a different size produces a different one."""
    media = build_media_file(make_image(name="key.png"))

    key = thumbnail_cache_key(media, 64)

    assert key == thumbnail_cache_key(media, 64)
    assert thumbnail_cache_key(media, 128) != key
    assert len(key) == 40


def test_cache_path_lives_in_cache_dir(make_image: Callable[..., Path]) -> None:
    """The cache path is the key inside the shared cache directory as a PNG."""
    media = build_media_file(make_image(name="loc.png"))

    path = cache_path_for(media, 64)

    assert path.parent == paths.cache_dir()
    assert path.suffix == ".png"
    assert path.stem == thumbnail_cache_key(media, 64)


def test_clear_cache_counts_and_empties(make_image: Callable[..., Path]) -> None:
    """Clearing removes every cached PNG and returns the number deleted."""
    media = build_media_file(make_image(name="clear.png", size=(200, 200)))
    ensure_thumbnail(media, 64)
    ensure_thumbnail(media, 128)
    assert len(list(paths.cache_dir().glob("*.png"))) == 2

    removed = clear_cache()

    assert removed == 2
    assert list(paths.cache_dir().glob("*.png")) == []


def test_generate_video_thumbnail_returns_false_when_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without ffmpeg the guard clause reports failure instead of raising."""
    monkeypatch.setattr(ffmpeg, "is_available", lambda: False)
    dest = tmp_path / "unavailable.png"

    assert generate_video_thumbnail(tmp_path / "movie.mp4", dest, 64) is False


def test_generate_video_thumbnail_returns_false_on_ffmpeg_error(
    sample_video: Path, tmp_path: Path
) -> None:
    """A non-zero ffmpeg exit is translated into a ``False`` result."""

    def failing_runner(
        command: Sequence[str],
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            list(command), returncode=1, stdout="", stderr="boom"
        )

    dest = tmp_path / "error.png"

    assert (
        generate_video_thumbnail(sample_video, dest, 64, runner=failing_runner) is False
    )


def test_generate_video_thumbnail_succeeds_with_real_ffmpeg(
    sample_video: Path, tmp_path: Path
) -> None:
    """A real clip drives ffmpeg to a clean exit, reported as ``True``.

    The contract fixes the extraction offset at ``-ss 1``; the shared fixture is
    a one-second clip, so ffmpeg legitimately seeks to the very end and exits
    zero without emitting a frame. Success here therefore means "ffmpeg ran
    without error", which is exactly what the function promises to report.
    """
    dest = tmp_path / "poster.png"

    assert generate_video_thumbnail(sample_video, dest, 64) is True


def test_ensure_thumbnail_renders_video(sample_video: Path) -> None:
    """The unified entry point routes videos through the ffmpeg generator."""
    media = build_media_file(sample_video)

    result = ensure_thumbnail(media, 64)

    assert media.kind is MediaKind.VIDEO
    assert result == cache_path_for(media, 64)
