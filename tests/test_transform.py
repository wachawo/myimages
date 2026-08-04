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


def test_saving_transparency_to_a_jpeg_leaves_the_original_intact(
    tmp_path: Path,
) -> None:
    """The regression this whole guard exists for.

    Pillow opens the destination for writing before it asks the encoder whether
    the mode can be written, so the unguarded call truncated the photograph to
    zero bytes and only then raised. Asserting the exception alone would pass
    against the broken code; the byte comparison is the real assertion.
    """
    photo = tmp_path / "photo.jpg"
    Image.new("RGB", (40, 30), (200, 90, 40)).save(photo, quality=95)
    before = photo.read_bytes()
    assert before

    cutout = Image.new("RGBA", (40, 30), (200, 90, 40, 0))
    with pytest.raises(transform.AlphaFormatError):
        transform.save_image(cutout, photo)

    assert photo.read_bytes() == before


@pytest.mark.parametrize("suffix", [".jpg", ".jpeg", ".bmp", ".gif"])
def test_transparency_is_refused_by_every_format_that_cannot_hold_it(
    tmp_path: Path, suffix: str
) -> None:
    cutout = Image.new("RGBA", (8, 8), (1, 2, 3, 0))
    with pytest.raises(transform.AlphaFormatError):
        transform.save_image(cutout, tmp_path / f"out{suffix}")


@pytest.mark.parametrize("suffix", [".png", ".webp", ".tiff", ".tif"])
def test_transparency_is_written_by_every_format_that_can_hold_it(
    tmp_path: Path, suffix: str
) -> None:
    cutout = Image.new("RGBA", (8, 8), (1, 2, 3, 0))
    written = transform.save_image(cutout, tmp_path / f"out{suffix}")
    reopened = Image.open(written).convert("RGBA")
    assert reopened.getchannel("A").getextrema() == (0, 0)


def test_an_opaque_alpha_mode_is_flattened_rather_than_refused(
    tmp_path: Path,
) -> None:
    """RGBA with nothing see-through can still not be written as JPEG.

    Pillow rejects the mode regardless of the pixels, so the guard would be a
    dead end here. Nothing visible is lost by flattening, so the save proceeds.
    """
    opaque = Image.new("RGBA", (8, 8), (10, 20, 30, 255))
    written = transform.save_image(opaque, tmp_path / "out.jpg")
    assert Image.open(written).convert("RGB").getpixel((0, 0)) == (10, 20, 30)


def test_flattening_uses_the_requested_background(tmp_path: Path) -> None:
    opaque = Image.new("RGBA", (8, 8), (10, 20, 30, 255))
    written = transform.save_image(opaque, tmp_path / "out.bmp", background=(0, 0, 255))
    assert Image.open(written).convert("RGB").getpixel((0, 0)) == (10, 20, 30)


def dpi_of(path: Path) -> tuple[int, int] | None:
    """The density a saved file reports, rounded, or None when it has none."""
    value = Image.open(path).info.get("dpi")
    if value is None:
        return None
    return (round(float(value[0])), round(float(value[1])))


@pytest.mark.parametrize("suffix", [".jpg", ".png", ".tiff", ".bmp"])
def test_saving_carries_the_source_resolution_across(
    tmp_path: Path, suffix: str
) -> None:
    """Pillow reads dpi from the save arguments, never from the image's info.

    Before this, every format lost it -- and TIFF and BMP wrote a *wrong* one,
    1 and 96, so a 300 dpi scan came back out claiming something it was not.
    """
    source = tmp_path / f"in{suffix}"
    Image.new("RGB", (40, 30), (200, 90, 40)).save(source, dpi=(300, 300))

    written = transform.save_image(
        transform.load_image(source), tmp_path / f"out{suffix}"
    )
    assert dpi_of(written) == (300, 300)


def test_an_explicit_resolution_overrides_the_source(tmp_path: Path) -> None:
    source = Image.new("RGB", (40, 30))
    source.info["dpi"] = (72, 72)
    written = transform.save_image(source, tmp_path / "out.png", dpi=(300, 300))
    assert dpi_of(written) == (300, 300)


def test_the_resolution_survives_being_flattened(tmp_path: Path) -> None:
    """Flattening builds a fresh picture whose info is empty.

    Reading the value after that point loses it, which is exactly the trap an
    opaque cut-out saved back over a JPEG would fall into.
    """
    opaque = Image.new("RGBA", (40, 30), (10, 20, 30, 255))
    opaque.info["dpi"] = (300, 300)
    written = transform.save_image(opaque, tmp_path / "out.jpg")
    assert dpi_of(written) == (300, 300)


@pytest.mark.parametrize("suffix", [".webp", ".gif"])
def test_a_format_that_cannot_store_a_resolution_is_left_alone(
    tmp_path: Path, suffix: str
) -> None:
    """Both accept the argument and drop it; asking is pointless, not harmful."""
    source = Image.new("RGB", (40, 30))
    source.info["dpi"] = (300, 300)
    written = transform.save_image(source, tmp_path / f"out{suffix}")
    assert dpi_of(written) is None


def test_scaling_drops_a_resolution_that_no_longer_describes_the_pixels(
    tmp_path: Path,
) -> None:
    """A 128-pixel thumbnail must not claim the density of the photograph."""
    photo = Image.new("RGB", (800, 600))
    photo.info["dpi"] = (300, 300)
    thumbnail = transform.scale_image(photo, max_edge=128)
    assert "dpi" not in thumbnail.info

    written = transform.save_image(thumbnail, tmp_path / "thumb.png")
    assert dpi_of(written) is None
