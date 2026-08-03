"""Tests for building animated GIFs from videos and from still frames.

The frames path is assembled and read back with Pillow on real files so a
regression in frame count, ordering or sizing surfaces as a wrong image rather
than a passing mock. The video path is covered two ways: a real end-to-end
encode on the generated sample clip (skipped when ffmpeg is absent) proves the
whole chain works, while an injected runner asserts the exact ffmpeg arguments
so the filtergraph and seek flags stay correct even on machines without ffmpeg.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest
from PIL import Image

from myimages.video import ffmpeg, gif


def count_frames(animation: Image.Image) -> int:
    """Count GIF frames by seeking until the format reports end-of-file."""
    frames = 0
    while True:
        try:
            animation.seek(frames)
        except EOFError:
            return frames
        frames += 1


def test_gif_from_frames_creates_three_frame_gif(
    make_image: Callable[..., Path], tmp_path: Path
) -> None:
    paths = [
        make_image("one.png", (30, 30), (255, 0, 0)),
        make_image("two.png", (30, 30), (0, 255, 0)),
        make_image("three.png", (30, 30), (0, 0, 255)),
    ]
    out = gif.gif_from_frames(paths, tmp_path / "anim.gif")
    assert out.exists()
    with Image.open(out) as animation:
        assert animation.format == "GIF"
        assert count_frames(animation) == 3


def test_empty_frames_raises(tmp_path: Path) -> None:
    with pytest.raises(gif.GifError):
        gif.gif_from_frames([], tmp_path / "out.gif")


def test_width_scaling_changes_frame_size(
    make_image: Callable[..., Path], tmp_path: Path
) -> None:
    paths = [
        make_image("wide-a.png", (100, 50), (200, 0, 0)),
        make_image("wide-b.png", (100, 50), (0, 200, 0)),
    ]
    out = gif.gif_from_frames(paths, tmp_path / "scaled.gif", width=40)
    with Image.open(out) as animation:
        # 100x50 scaled to width 40 keeps the 2:1 ratio, so height becomes 20.
        assert animation.size == (40, 20)


def test_gif_from_video_creates_gif(sample_video: Path, tmp_path: Path) -> None:
    # No explicit duration exercises the "encode the whole clip" argument path.
    out = gif.gif_from_video(sample_video, tmp_path / "clip.gif", fps=8, width=64)
    assert out.exists()
    with Image.open(out) as animation:
        assert animation.format == "GIF"


def test_gif_from_video_builds_expected_arguments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Pretend the tools exist so run_ffmpeg reaches the injected runner without
    # a real ffmpeg install, and capture the command it would have executed.
    monkeypatch.setattr(ffmpeg, "ffmpeg_path", lambda: "/usr/bin/ffmpeg")
    monkeypatch.setattr(ffmpeg, "ffprobe_path", lambda: "/usr/bin/ffprobe")
    captured: dict[str, list[str]] = {}

    def fake_runner(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        captured["command"] = list(command)
        return subprocess.CompletedProcess(list(command), 0, "", "")

    out = gif.gif_from_video(
        "in.mp4",
        tmp_path / "out.gif",
        start=1.0,
        duration=2.0,
        fps=8,
        width=320,
        runner=fake_runner,
    )
    assert out == tmp_path / "out.gif"
    command = captured["command"]
    filtergraph = command[command.index("-filter_complex") + 1]
    assert filtergraph == (
        "fps=8,scale=320:-1:flags=lanczos,"
        "split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse"
    )
    assert command[command.index("-ss") + 1] == "1.0"
    assert command[command.index("-t") + 1] == "2.0"
    assert command[command.index("-loop") + 1] == "0"
