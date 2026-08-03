"""Behavioural tests for duplicate and near-duplicate detection.

These exercise real files on disk (real image bytes, real hashing) rather than
mocks, because the whole point of the module is how it behaves on actual media.
Perceptual-hash cases deliberately use *patterned* images: a flat colour hashes
to zero for everyone (no pixel beats the mean), so structure is required to tell
images apart.
"""

from __future__ import annotations

import hashlib
import shutil
from collections.abc import Callable
from pathlib import Path

from PIL import Image

from myimages.core.duplicates import (
    DuplicateGroup,
    average_hash,
    difference_hash,
    file_hash,
    find_exact_duplicates,
    find_similar_images,
    hamming_distance,
)
from myimages.core.media import MediaKind, build_media_file


def gradient_image(
    path: Path, *, bright_on_left: bool, size: tuple[int, int] = (64, 64)
) -> Path:
    """Write a horizontal grayscale gradient so images have real content.

    A flat colour hashes to zero for every image (no pixel beats the mean, and
    no pixel exceeds its neighbour), so the perceptual-hash tests need genuine
    structure. A horizontal sweep exercises both hashes: aHash sees the
    dark/bright halves, dHash sees the left-vs-right slope. Flipping the sweep
    direction flips both hashes, producing a clearly different image.
    """
    width, height = size
    row = [
        int(255 * ((width - 1 - column) if bright_on_left else column) / (width - 1))
        for column in range(width)
    ]
    # Every row is identical for a horizontal gradient, so repeat the one row.
    pixels = row * height
    image = Image.new("L", size)
    image.putdata(pixels)
    image.convert("RGB").save(path)
    return path


def bright_left_gradient(path: Path) -> Path:
    """An image that fades from bright on the left to dark on the right."""
    return gradient_image(path, bright_on_left=True)


def bright_right_gradient(path: Path) -> Path:
    """The mirror image: dark on the left, bright on the right."""
    return gradient_image(path, bright_on_left=False)


def test_file_hash_matches_hashlib_and_is_deterministic(
    make_image: Callable[..., Path],
) -> None:
    path = make_image("hash.png")
    expected = hashlib.sha256(path.read_bytes()).hexdigest()
    assert file_hash(path) == expected
    # Repeating the call, and streaming in tiny chunks, must not change the digest.
    assert file_hash(path) == expected
    assert file_hash(path, chunk_size=4) == expected


def test_find_exact_duplicates_groups_identical_bytes(
    make_image: Callable[..., Path], tmp_path: Path
) -> None:
    original = make_image("original.png", colour=(10, 20, 30))
    copy = tmp_path / "copy.png"
    shutil.copyfile(original, copy)
    different = make_image("different.png", colour=(200, 100, 50))

    files = [build_media_file(p) for p in (original, copy, different)]
    groups = find_exact_duplicates(files)

    assert len(groups) == 1
    group = groups[0]
    assert isinstance(group, DuplicateGroup)
    assert group.reason == "identical bytes"
    assert group.paths == [original, copy]
    # The representative is the first-seen file, the "keep this one" default.
    assert group.representative == original


def test_find_exact_duplicates_returns_nothing_when_all_unique(
    make_image: Callable[..., Path],
) -> None:
    files = [
        build_media_file(make_image("a.png", colour=(1, 2, 3))),
        build_media_file(make_image("b.png", colour=(4, 5, 6))),
    ]
    assert find_exact_duplicates(files) == []


def test_perceptual_hashes_agree_for_identical_images(tmp_path: Path) -> None:
    first = bright_left_gradient(tmp_path / "grad_one.png")
    second = bright_left_gradient(tmp_path / "grad_two.png")
    assert average_hash(first) == average_hash(second)
    assert difference_hash(first) == difference_hash(second)


def test_perceptual_hashes_differ_for_different_images(tmp_path: Path) -> None:
    leftward = bright_left_gradient(tmp_path / "leftward.png")
    rightward = bright_right_gradient(tmp_path / "rightward.png")
    assert average_hash(leftward) != average_hash(rightward)
    assert difference_hash(leftward) != difference_hash(rightward)


def test_hamming_distance_basics() -> None:
    assert hamming_distance(0, 0) == 0
    assert hamming_distance(0b1010, 0b0000) == 2
    assert hamming_distance(0xFF, 0x00) == 8
    assert hamming_distance(0b1100, 0b0110) == 2


def test_find_similar_images_groups_lookalikes_and_excludes_others(
    tmp_path: Path,
) -> None:
    similar_one = bright_left_gradient(tmp_path / "similar_one.png")
    similar_two = bright_left_gradient(tmp_path / "similar_two.png")
    very_different = bright_right_gradient(tmp_path / "very_different.png")
    # A non-image must be ignored outright, never fingerprinted.
    note = tmp_path / "note.txt"
    note.write_text("not an image")

    files = [
        build_media_file(similar_one),
        build_media_file(similar_two),
        build_media_file(very_different),
        build_media_file(note),
    ]
    assert files[3].kind is not MediaKind.IMAGE

    groups = find_similar_images(files)

    assert len(groups) == 1
    group = groups[0]
    assert group.reason == "visually similar"
    assert group.paths == [similar_one, similar_two]
    assert very_different not in group.paths


def test_find_similar_images_skips_unreadable_files_without_raising(
    tmp_path: Path,
) -> None:
    good_one = bright_left_gradient(tmp_path / "good_one.png")
    good_two = bright_left_gradient(tmp_path / "good_two.png")
    # A file that claims to be a PNG but is garbage: opening it raises, and the
    # scan must survive that and still group the readable pair.
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"this is not a real image")

    files = [
        build_media_file(broken),
        build_media_file(good_one),
        build_media_file(good_two),
    ]
    groups = find_similar_images(files)

    assert len(groups) == 1
    assert groups[0].paths == [good_one, good_two]
    assert broken not in groups[0].paths
