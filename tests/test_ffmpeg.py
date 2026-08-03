"""Tests for the ffmpeg/ffprobe wrapper."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Sequence

import pytest

from myimages.video import ffmpeg


def completed(
    returncode: int, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["x"], returncode=returncode, stdout=stdout, stderr=stderr
    )


@pytest.mark.parametrize(
    "text,expected",
    [
        ("30/1", 30.0),
        ("30000/1001", pytest.approx(29.97, abs=0.01)),
        ("0/0", 0.0),
        ("24", 24.0),
        ("bad", 0.0),
        ("1/x", 0.0),
    ],
)
def test_parse_frame_rate(text: str, expected: float) -> None:
    assert ffmpeg.parse_frame_rate(text) == expected


def test_require_ffmpeg_raises_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ffmpeg.shutil, "which", lambda name: None)
    assert ffmpeg.ffmpeg_path() is None
    assert ffmpeg.is_available() is False
    with pytest.raises(ffmpeg.FfmpegError):
        ffmpeg.require_ffmpeg()


def test_run_ffmpeg_success_and_failure() -> None:
    if not ffmpeg.is_available():
        pytest.skip("ffmpeg not available")

    def ok_runner(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        assert command[0] == ffmpeg.ffmpeg_path()
        assert "-y" in command
        return completed(0, stdout="done")

    assert ffmpeg.run_ffmpeg(["-i", "x"], runner=ok_runner).stdout == "done"

    def bad_runner(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        return completed(1, stderr="boom")

    with pytest.raises(ffmpeg.FfmpegError, match="boom"):
        ffmpeg.run_ffmpeg(["-i", "x"], runner=bad_runner)


def test_probe_video_with_fake_runner() -> None:
    payload = {
        "streams": [
            {"codec_type": "audio"},
            {
                "codec_type": "video",
                "width": 320,
                "height": 240,
                "avg_frame_rate": "30/1",
                "duration": "2.5",
            },
        ],
        "format": {"duration": "2.5"},
    }

    def runner(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        return completed(0, stdout=json.dumps(payload))

    info = ffmpeg.probe_video("x.mp4", runner=runner)
    assert (info.width, info.height, info.fps) == (320, 240, 30.0)
    assert info.duration == 2.5


def test_probe_video_no_stream_and_failure() -> None:
    def empty_runner(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        return completed(0, stdout=json.dumps({"streams": []}))

    with pytest.raises(ffmpeg.FfmpegError, match="no video stream"):
        ffmpeg.probe_video("x.mp4", runner=empty_runner)

    def fail_runner(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        return completed(1, stderr="nope")

    with pytest.raises(ffmpeg.FfmpegError, match="nope"):
        ffmpeg.probe_video("x.mp4", runner=fail_runner)


def test_probe_real_video(sample_video) -> None:
    info = ffmpeg.probe_video(sample_video)
    assert info.width == 128 and info.height == 96
    assert info.duration > 0


def test_default_runner_executes() -> None:
    result = ffmpeg.default_runner(["python3", "-c", "print('hi')"])
    assert result.returncode == 0
    assert "hi" in result.stdout
