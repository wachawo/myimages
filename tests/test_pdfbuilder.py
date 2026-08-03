"""Tests for the PDF builder.

These drive real Pillow encode/decode round-trips on real files: a genuine PDF
is written to disk and its bytes and page count are inspected. The size controls
are exercised against a heavy, noise-filled image whose JPEG payload is large
enough that lowering quality has a measurable effect, which a solid-colour test
image (compressible to almost nothing) could never demonstrate.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from PIL import Image

from myimages.imaging import pdfbuilder
from myimages.imaging.pdfbuilder import PdfOptions


def write_noisy_image(path: Path, size: tuple[int, int] = (1000, 750)) -> Path:
    """Write an incompressible random-noise image so its JPEG size is non-trivial."""
    width, height = size
    Image.frombytes("RGB", size, os.urandom(width * height * 3)).save(path)
    return path


def test_three_images_make_a_real_pdf(image_dir: Path, tmp_path: Path) -> None:
    sources = sorted(image_dir.glob("*"))
    progress_calls: list[tuple[int, int]] = []
    result = pdfbuilder.build_pdf(
        sources,
        tmp_path / "album.pdf",
        PdfOptions(),
        progress=lambda done, total: progress_calls.append((done, total)),
    )
    assert result.path.read_bytes().startswith(b"%PDF")
    assert result.page_count == 3
    assert result.size_bytes > 0
    assert result.size_bytes == result.path.stat().st_size
    assert progress_calls[-1] == (3, 3)


def test_grayscale_option_produces_valid_pdf(image_dir: Path, tmp_path: Path) -> None:
    sources = sorted(image_dir.glob("*"))
    result = pdfbuilder.build_pdf(
        sources, tmp_path / "grey.pdf", PdfOptions(grayscale=True)
    )
    assert result.path.read_bytes().startswith(b"%PDF")
    assert result.page_count == 3


def test_small_target_lowers_quality_and_shrinks(tmp_path: Path) -> None:
    source = write_noisy_image(tmp_path / "noise.png")
    options = PdfOptions()
    baseline = pdfbuilder.build_pdf([source], tmp_path / "full.pdf", options)

    # A full-scale render at the quality floor is the smallest the sweep can
    # reach before it resorts to shrinking. Aiming between that and the baseline
    # guarantees the target is met by *lowering quality* alone (not shedding
    # pixels), so quality_used must drop below the requested quality. This is
    # robust to incompressible noise, whose size is not monotonic in quality.
    floor = pdfbuilder.build_pdf(
        [source], tmp_path / "floor.pdf", PdfOptions(quality=pdfbuilder.QUALITY_FLOOR)
    )
    assert floor.size_bytes < baseline.size_bytes
    target_bytes = (baseline.size_bytes + floor.size_bytes) // 2
    bounded = pdfbuilder.build_pdf(
        [source],
        tmp_path / "small.pdf",
        PdfOptions(target_mib=target_bytes / (1024 * 1024)),
    )
    assert bounded.path.read_bytes().startswith(b"%PDF")
    assert bounded.quality_used < options.quality
    assert bounded.size_bytes < baseline.size_bytes
    assert bounded.size_bytes <= target_bytes


def test_impossible_target_returns_smallest_effort(tmp_path: Path) -> None:
    source = write_noisy_image(tmp_path / "noise.png")
    # A one-byte budget can never be met, so the builder must exhaust the quality
    # sweep and all shrink rounds and hand back its smallest rendering.
    result = pdfbuilder.build_pdf(
        [source], tmp_path / "tiny.pdf", PdfOptions(target_mib=0.000001)
    )
    assert result.path.read_bytes().startswith(b"%PDF")
    assert result.quality_used == pdfbuilder.QUALITY_FLOOR
    assert result.size_bytes > 0


def test_empty_sources_raises(tmp_path: Path) -> None:
    with pytest.raises(pdfbuilder.PdfError):
        pdfbuilder.build_pdf([], tmp_path / "none.pdf", PdfOptions())


def test_original_mode_full_size_pages(tmp_path):
    from PIL import Image

    from myimages.imaging.pdfbuilder import ORIGINAL_QUALITY, PdfOptions, build_pdf

    sources = []
    for index in range(3):
        path = tmp_path / f"noise{index}.png"
        Image.effect_noise((640, 480), 40 + index).convert("RGB").save(path)
        sources.append(path)

    seen: list[tuple[int, int]] = []
    result = build_pdf(
        sources,
        tmp_path / "orig.pdf",
        PdfOptions(jpeg_pages=False),
        progress=lambda done, total: seen.append((done, total)),
    )
    assert result.path.read_bytes().startswith(b"%PDF")
    assert result.page_count == 3
    assert result.quality_used == ORIGINAL_QUALITY
    assert seen == [(1, 3), (2, 3), (3, 3)]

    # The same sources through the JPEG pipeline come out smaller.
    jpeg = build_pdf(sources, tmp_path / "jpeg.pdf", PdfOptions(quality=80))
    assert result.size_bytes > jpeg.size_bytes


def test_original_mode_grayscale_and_alpha(tmp_path):
    from PIL import Image

    from myimages.imaging.pdfbuilder import PdfOptions, build_pdf

    rgba = tmp_path / "overlay.png"
    Image.new("RGBA", (60, 40), (200, 30, 30, 128)).save(rgba)

    colour = build_pdf([rgba], tmp_path / "c.pdf", PdfOptions(jpeg_pages=False))
    assert colour.page_count == 1  # RGBA flattened to a storable mode

    grey = build_pdf(
        [rgba], tmp_path / "g.pdf", PdfOptions(jpeg_pages=False, grayscale=True)
    )
    assert grey.path.read_bytes().startswith(b"%PDF")
