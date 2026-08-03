"""Tests for the image transform helpers."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from myimages.imaging import transform


def test_crop_rect_geometry_and_clamp() -> None:
    rect = transform.CropRect(left=5, top=10, width=20, height=30)
    assert rect.right == 25
    assert rect.bottom == 40
    clamped = transform.CropRect(-5, -5, 999, 999).clamped(100, 80)
    assert (clamped.left, clamped.top) == (0, 0)
    assert (clamped.width, clamped.height) == (100, 80)


def test_load_applies_exif_orientation(tmp_path: Path) -> None:
    tall = Image.new("RGB", (20, 40), (10, 20, 30))
    path = tmp_path / "exif.jpg"
    tall.save(path, exif=orientation_exif(6))
    loaded = transform.load_image(path)
    # Orientation 6 means rotate 90°, so width and height swap.
    assert loaded.size == (40, 20)


def orientation_exif(value: int) -> Image.Exif:
    exif = Image.Exif()
    exif[0x0112] = value
    return exif


def test_save_png_and_jpeg(tmp_path: Path) -> None:
    image = Image.new("RGB", (30, 30), (100, 150, 200))
    png = transform.save_image(image, tmp_path / "out.png")
    jpg = transform.save_image(image, tmp_path / "out.jpg", quality=60)
    assert png.exists() and jpg.exists()


def test_grayscale_is_single_channel() -> None:
    image = Image.new("RGB", (10, 10), (200, 50, 50))
    grey = transform.to_grayscale(image)
    assert grey.mode == "L"


@pytest.mark.parametrize(
    "degrees,expected",
    [(0, (30, 10)), (90, (10, 30)), (180, (30, 10)), (270, (10, 30))],
)
def test_rotate_right_angles(degrees: int, expected: tuple[int, int]) -> None:
    image = Image.new("RGB", (30, 10), (0, 0, 0))
    assert transform.rotate_image(image, degrees).size == expected


def test_rotate_arbitrary_expands() -> None:
    image = Image.new("RGB", (30, 10), (0, 0, 0))
    rotated = transform.rotate_image(image, 45)
    assert rotated.size[1] > 10  # expand grows the short edge


def test_crop_image_respects_bounds() -> None:
    image = Image.new("RGB", (40, 40), (1, 2, 3))
    cropped = transform.crop_image(image, transform.CropRect(10, 10, 100, 100))
    assert cropped.size == (30, 30)


@pytest.mark.parametrize(
    "width,height,aw,ah,expected",
    [
        (100, 100, 16, 9, (100, 56)),  # square source, wide target -> limited by width
        (200, 100, 1, 1, (100, 100)),  # wide source, square target
        (100, 200, 1, 1, (100, 100)),  # tall source, square target
    ],
)
def test_aspect_crop_rect_dimensions(
    width: int, height: int, aw: int, ah: int, expected: tuple[int, int]
) -> None:
    rect = transform.aspect_crop_rect(width, height, aw, ah)
    assert (rect.width, rect.height) == expected


@pytest.mark.parametrize(
    "anchor", ["center", "top", "bottom", "left", "right", "topleft"]
)
def test_aspect_crop_rect_anchors_stay_in_bounds(anchor: str) -> None:
    rect = transform.aspect_crop_rect(200, 100, 1, 1, anchor)
    assert rect.left >= 0 and rect.top >= 0
    assert rect.right <= 200 and rect.bottom <= 100


def test_aspect_crop_rect_rejects_bad_ratio() -> None:
    with pytest.raises(ValueError):
        transform.aspect_crop_rect(100, 100, 0, 9)


def test_crop_to_aspect() -> None:
    image = Image.new("RGB", (200, 100), (0, 0, 0))
    assert transform.crop_to_aspect(image, 1, 1).size == (100, 100)


def test_scale_max_edge_downscales_and_never_upscales() -> None:
    big = Image.new("RGB", (400, 200), (0, 0, 0))
    assert transform.scale_image(big, max_edge=100).size == (100, 50)
    small = Image.new("RGB", (40, 20), (0, 0, 0))
    assert transform.scale_image(small, max_edge=100).size == (40, 20)


def test_scale_by_width_height_and_none() -> None:
    image = Image.new("RGB", (100, 50), (0, 0, 0))
    assert transform.scale_image(image, width=50).size == (50, 25)
    assert transform.scale_image(image, height=25).size == (50, 25)
    assert transform.scale_image(
        image, width=10, height=10, keep_aspect=False
    ).size == (10, 10)
    assert transform.scale_image(image).size == (100, 50)


def test_flip_mirrors_horizontally_and_vertically() -> None:
    image = Image.new("RGB", (4, 2))
    image.putpixel((0, 0), (255, 0, 0))  # a marker in the top-left corner

    mirrored = transform.flip_image(image, horizontal=True)
    assert mirrored.getpixel((3, 0)) == (255, 0, 0)  # moved to the top-right
    assert mirrored.size == image.size

    flipped = transform.flip_image(image, horizontal=False)
    assert flipped.getpixel((0, 1)) == (255, 0, 0)  # moved to the bottom-left


def test_flipping_twice_restores_the_original() -> None:
    image = Image.new("RGB", (5, 3), (10, 20, 30))
    image.putpixel((1, 2), (200, 100, 50))
    once = transform.flip_image(image, horizontal=True)
    twice = transform.flip_image(once, horizontal=True)
    assert twice.tobytes() == image.tobytes()
