"""Behavioural tests for :mod:`myimages.core.scanner`.

Everything here works against real files on disk (real PNGs and JPEGs, a
stub video, a broken symlink) rather than mocks, so the tests exercise the
same ``stat`` and Pillow code paths production does.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from myimages.core.media import MediaFile, MediaKind
from myimages.core.scanner import (
    fill_image_dimensions,
    probe_image_dimensions,
    scan_directory,
    sort_media,
)


def sample_media() -> list[MediaFile]:
    """Three images whose every sortable attribute differs, for sort tests."""
    return [
        MediaFile(Path("Banana.png"), MediaKind.IMAGE, 300, 50.0, width=4, height=4),
        MediaFile(Path("apple.png"), MediaKind.IMAGE, 100, 30.0, width=2, height=2),
        MediaFile(Path("cherry.png"), MediaKind.IMAGE, 200, 40.0, width=3, height=3),
    ]


def test_scan_flat_finds_only_top_level_images(image_dir: Path) -> None:
    found = scan_directory(image_dir)
    assert {media.name for media in found} == {
        "alpha.png",
        "bravo.jpg",
        "charlie.png",
    }
    assert all(media.kind is MediaKind.IMAGE for media in found)


def test_scan_recursive_descends_into_subfolders(image_dir: Path) -> None:
    nested = image_dir / "nested"
    nested.mkdir()
    Image.new("RGB", (10, 10), (1, 2, 3)).save(nested / "deep.png")

    flat = scan_directory(image_dir)
    deep = scan_directory(image_dir, recursive=True)

    assert len(flat) == 3
    assert len(deep) == 4
    assert any(media.name == "deep.png" for media in deep)


def test_include_filters_select_kinds(tmp_path: Path, make_image) -> None:
    make_image("pic.png")
    (tmp_path / "clip.mp4").write_bytes(b"\x00")

    both = scan_directory(tmp_path)
    assert {media.kind for media in both} == {MediaKind.IMAGE, MediaKind.VIDEO}

    images_only = scan_directory(tmp_path, include_videos=False)
    assert [media.kind for media in images_only] == [MediaKind.IMAGE]

    videos_only = scan_directory(tmp_path, include_images=False)
    assert [media.kind for media in videos_only] == [MediaKind.VIDEO]

    neither = scan_directory(tmp_path, include_images=False, include_videos=False)
    assert neither == []


def test_non_media_files_are_skipped(tmp_path: Path, make_image) -> None:
    make_image("keep.png")
    (tmp_path / "notes.txt").write_text("not media")

    found = scan_directory(tmp_path)
    assert [media.name for media in found] == ["keep.png"]


def test_entry_that_fails_to_stat_is_skipped(tmp_path: Path, make_image) -> None:
    make_image("real.png")
    broken = tmp_path / "ghost.png"
    broken.symlink_to(tmp_path / "does-not-exist.png")

    found = scan_directory(tmp_path)
    assert [media.name for media in found] == ["real.png"]


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("name", ["apple.png", "Banana.png", "cherry.png"]),
        ("size", ["apple.png", "cherry.png", "Banana.png"]),
        ("resolution", ["apple.png", "cherry.png", "Banana.png"]),
        ("modified", ["apple.png", "cherry.png", "Banana.png"]),
    ],
)
def test_sort_ascending(key: str, expected: list[str]) -> None:
    ordered = sort_media(sample_media(), key)
    assert [media.name for media in ordered] == expected


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("name", ["apple.png", "Banana.png", "cherry.png"]),
        ("size", ["apple.png", "cherry.png", "Banana.png"]),
        ("resolution", ["apple.png", "cherry.png", "Banana.png"]),
        ("modified", ["apple.png", "cherry.png", "Banana.png"]),
    ],
)
def test_sort_descending(key: str, expected: list[str]) -> None:
    ordered = sort_media(sample_media(), key, descending=True)
    assert [media.name for media in ordered] == list(reversed(expected))


def test_unknown_sort_key_falls_back_to_name() -> None:
    ordered = sort_media(sample_media(), "totally-unknown")
    assert [media.name for media in ordered] == [
        "apple.png",
        "Banana.png",
        "cherry.png",
    ]


def test_probe_reads_dimensions_of_real_image(make_image) -> None:
    path = make_image("probe.png", size=(30, 20))
    assert probe_image_dimensions(path) == (30, 20)


def test_probe_of_non_image_returns_none(tmp_path: Path) -> None:
    junk = tmp_path / "notes.txt"
    junk.write_text("clearly not an image")
    assert probe_image_dimensions(junk) == (None, None)


def test_probe_of_missing_path_returns_none(tmp_path: Path) -> None:
    assert probe_image_dimensions(tmp_path / "nope.png") == (None, None)


def test_fill_attaches_dimensions_and_leaves_input_untouched(
    image_dir: Path,
) -> None:
    scanned = scan_directory(image_dir)
    assert all(media.width is None for media in scanned)

    filled = fill_image_dimensions(scanned)
    by_name = {media.name: media for media in filled}
    assert (by_name["alpha.png"].width, by_name["alpha.png"].height) == (40, 40)
    assert (by_name["bravo.jpg"].width, by_name["bravo.jpg"].height) == (80, 60)
    assert (by_name["charlie.png"].width, by_name["charlie.png"].height) == (
        20,
        20,
    )
    assert all(media.width is None for media in scanned)


def test_fill_passes_non_probed_files_through_unchanged() -> None:
    already = MediaFile(Path("a.png"), MediaKind.IMAGE, 10, 1.0, width=5, height=5)
    video = MediaFile(Path("v.mp4"), MediaKind.VIDEO, 10, 1.0)

    filled = fill_image_dimensions([already, video])
    assert filled[0] is already
    assert filled[1] is video


def test_scan_includes_pdf_documents_and_skips_other(tmp_path):
    from PIL import Image

    from myimages.core import scanner
    from myimages.core.media import MediaKind, classify

    (tmp_path / "doc.pdf").write_bytes(b"%PDF-1.4")
    (tmp_path / "note.txt").write_text("x", encoding="utf-8")
    Image.new("RGB", (10, 10), (0, 0, 0)).save(tmp_path / "p.png")

    assert classify("anything.pdf") is MediaKind.DOCUMENT
    kinds = {f.name: f.kind for f in scanner.scan_directory(tmp_path)}
    assert kinds.get("doc.pdf") is MediaKind.DOCUMENT
    assert "note.txt" not in kinds  # OTHER is skipped

    without = scanner.scan_directory(tmp_path, include_documents=False)
    assert all(f.suffix != ".pdf" for f in without)


def test_unreadable_folder_scans_as_empty(tmp_path):
    """A folder the user cannot read must not take the whole scan down."""
    import os

    from myimages.core import scanner

    locked = tmp_path / "locked"
    locked.mkdir()
    (locked / "hidden.png").write_bytes(b"x")
    os.chmod(locked, 0o000)
    try:
        assert scanner.scan_directory(locked) == []
        assert scanner.scan_directory(locked, recursive=True) == []
    finally:
        os.chmod(locked, 0o755)


def test_readable_entries_lists_a_normal_folder(tmp_path):
    from myimages.core.scanner import readable_entries

    folder = tmp_path / "listing"  # its own folder: tmp_path is shared with fixtures
    folder.mkdir()
    (folder / "one.png").write_bytes(b"x")
    (folder / "two.png").write_bytes(b"x")
    names = sorted(p.name for p in readable_entries(folder, recursive=False))
    assert names == ["one.png", "two.png"]


def test_reuse_known_dimensions_avoids_reopening_unchanged_photos(tmp_path):
    """A rescan must not re-measure every photo just because one file changed."""
    from PIL import Image

    from myimages.core import scanner

    for name in ("a.png", "b.png"):
        Image.new("RGB", (30, 20), (10, 20, 30)).save(tmp_path / name)
    measured = scanner.fill_image_dimensions(scanner.scan_directory(tmp_path))
    assert all(media.width == 30 for media in measured)

    fresh = scanner.scan_directory(tmp_path)  # a rescan knows no dimensions
    assert all(media.width is None for media in fresh)

    carried = scanner.reuse_known_dimensions(fresh, measured)
    assert all(media.width == 30 for media in carried)


def test_reuse_known_dimensions_re_measures_a_rewritten_photo(tmp_path):
    from PIL import Image

    from myimages.core import scanner

    path = tmp_path / "changed.png"
    Image.new("RGB", (30, 20), (10, 20, 30)).save(path)
    measured = scanner.fill_image_dimensions(scanner.scan_directory(tmp_path))

    Image.new("RGB", (60, 40), (90, 20, 30)).save(path)  # different size on disk
    carried = scanner.reuse_known_dimensions(scanner.scan_directory(tmp_path), measured)

    # The stale dimensions are refused, so the file gets measured again.
    assert carried[0].width is None
