"""Tests for trimming a video to a span of its timeline.

These run real ffmpeg cuts on the generated sample clip (skipped when ffmpeg is
absent) so a regression in the argument order or the copy/re-encode choice shows
up as a wrong output duration, not a passing mock. The pure validation path is
exercised separately because it must fail fast without touching ffmpeg at all.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from myimages.video import ffmpeg, trim


def test_copy_trim_produces_shorter_clip(sample_video: Path, tmp_path: Path) -> None:
    original = ffmpeg.probe_video(sample_video).duration
    out = trim.trim_video(sample_video, tmp_path / "cut.mp4", 0.0, 0.5)
    assert out.exists()
    trimmed = ffmpeg.probe_video(out).duration
    assert 0 < trimmed < original


def test_reencode_trim_produces_shorter_clip(
    sample_video: Path, tmp_path: Path
) -> None:
    original = ffmpeg.probe_video(sample_video).duration
    out = trim.trim_video(
        sample_video, tmp_path / "reencoded.mp4", 0.0, 0.5, reencode=True
    )
    assert out.exists()
    trimmed = ffmpeg.probe_video(out).duration
    assert 0 < trimmed < original


def test_negative_start_raises(tmp_path: Path) -> None:
    with pytest.raises(trim.TrimError):
        trim.trim_video("in.mp4", tmp_path / "out.mp4", -1.0, 2.0)


def test_end_not_after_start_raises(tmp_path: Path) -> None:
    with pytest.raises(trim.TrimError):
        trim.trim_video("in.mp4", tmp_path / "out.mp4", 2.0, 2.0)
