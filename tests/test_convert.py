"""Tests for the image format-conversion helpers.

These exercise real encode/decode round-trips on real files (not mocks) so the
tests fail if Pillow's format handling or our alpha flattening ever regresses.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from PIL import Image

from myimages.imaging import convert


def test_png_to_jpg_round_trip(make_image: Callable[..., Path], tmp_path: Path) -> None:
    source = make_image("src.png")
    dest = convert.convert_image(source, tmp_path / "out.jpg", quality=70)
    assert dest.exists()
    with Image.open(dest) as opened:
        opened.load()
        assert opened.format == "JPEG"


def test_jpg_to_png_round_trip(make_image: Callable[..., Path], tmp_path: Path) -> None:
    source = make_image("photo.jpg")
    dest = convert.convert_image(source, tmp_path / "out.png")
    assert dest.exists()
    with Image.open(dest) as opened:
        opened.load()
        assert opened.format == "PNG"


def test_grayscale_flag_produces_grey_image(
    make_image: Callable[..., Path], tmp_path: Path
) -> None:
    source = make_image("colour.png", colour=(200, 90, 40))
    dest = convert.convert_image(source, tmp_path / "grey.png", grayscale=True)
    with Image.open(dest) as opened:
        red, green, blue = opened.convert("RGB").getpixel((0, 0))[:3]
    # Equal channels across the board is the definition of a neutral grey.
    assert red == green == blue


def test_rgba_png_to_jpg_flattens(tmp_path: Path) -> None:
    transparent = Image.new("RGBA", (20, 20), (10, 20, 30, 0))
    source = tmp_path / "transparent.png"
    transparent.save(source)
    dest = convert.convert_image(source, tmp_path / "flat.jpg")
    with Image.open(dest) as opened:
        assert opened.format == "JPEG"
        assert opened.mode == "RGB"
        corner = opened.getpixel((0, 0))
    # Fully transparent pixels should take the default white background.
    assert min(corner) > 250


def test_unsupported_extension_raises(
    make_image: Callable[..., Path], tmp_path: Path
) -> None:
    source = make_image()
    with pytest.raises(convert.ConversionError):
        convert.convert_image(source, tmp_path / "out.xyz")


def test_convert_many_writes_all_and_reports_progress(
    image_dir: Path, tmp_path: Path
) -> None:
    sources = sorted(image_dir.glob("*"))
    calls: list[tuple[int, int]] = []
    outputs = convert.convert_many(
        sources,
        tmp_path / "converted",
        ".png",
        progress=lambda done, total: calls.append((done, total)),
    )
    assert len(outputs) == len(sources)
    assert all(path.exists() for path in outputs)
    assert len(calls) == len(sources)
    assert calls[-1] == (len(sources), len(sources))


def test_convert_many_without_progress_callback(
    make_image: Callable[..., Path], tmp_path: Path
) -> None:
    source = make_image("only.png")
    outputs = convert.convert_many([source], tmp_path / "out", ".jpg")
    assert len(outputs) == 1
    assert outputs[0].exists()


def test_convert_many_rejects_extension_without_dot(
    make_image: Callable[..., Path], tmp_path: Path
) -> None:
    source = make_image()
    with pytest.raises(convert.ConversionError):
        convert.convert_many([source], tmp_path, "png")


def test_register_heif_returns_bool() -> None:
    assert isinstance(convert.register_heif(), bool)


def test_register_heif_activates_when_dependency_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Simulate the optional pillow-heif extra being installed by injecting a
    # stand-in module, so the success branch is covered without the real codec.
    import sys
    import types

    registrations: list[str] = []

    def fake_register() -> None:
        registrations.append("registered")

    fake_module = types.ModuleType("pillow_heif")
    fake_module.register_heif_opener = fake_register
    monkeypatch.setitem(sys.modules, "pillow_heif", fake_module)

    assert convert.register_heif() is True
    assert registrations == ["registered"]
