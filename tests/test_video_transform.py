"""Tests for cropping and scaling videos.

These run real ffmpeg filters on the generated sample clip (skipped when ffmpeg
is absent) and then probe the result, so a wrong filter string or argument order
surfaces as wrong output dimensions rather than a passing mock. The pure
validation paths are exercised separately because they must fail fast without
touching ffmpeg at all.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from myimages.video import ffmpeg, transform


def test_crop_produces_requested_dimensions(sample_video: Path, tmp_path: Path) -> None:
    out = transform.crop_video(
        sample_video, tmp_path / "cropped.mp4", left=0, top=0, width=64, height=48
    )
    assert out.exists()
    info = ffmpeg.probe_video(out)
    assert (info.width, info.height) == (64, 48)


def test_scale_by_both_dimensions(sample_video: Path, tmp_path: Path) -> None:
    out = transform.scale_video(
        sample_video, tmp_path / "both.mp4", width=48, height=32
    )
    assert out.exists()
    info = ffmpeg.probe_video(out)
    assert (info.width, info.height) == (48, 32)


def test_scale_by_width_keeps_even_height(sample_video: Path, tmp_path: Path) -> None:
    out = transform.scale_video(sample_video, tmp_path / "wide.mp4", width=64)
    assert out.exists()
    info = ffmpeg.probe_video(out)
    assert info.width == 64
    assert info.height % 2 == 0


def test_scale_by_height_keeps_even_width(sample_video: Path, tmp_path: Path) -> None:
    out = transform.scale_video(sample_video, tmp_path / "tall.mp4", height=48)
    assert out.exists()
    info = ffmpeg.probe_video(out)
    assert info.height == 48
    assert info.width % 2 == 0


def test_non_positive_crop_size_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        transform.crop_video(
            "in.mp4", tmp_path / "out.mp4", left=0, top=0, width=0, height=48
        )


def test_scale_without_any_dimension_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        transform.scale_video("in.mp4", tmp_path / "out.mp4")
