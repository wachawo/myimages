"""Tests for the video tools dialog (myimages.gui.video_tool_dialog).

The dialog trims, crops/scales and GIF-exports a single clip through the
ffmpeg-backed helpers, dispatched via an injected runner. The tests run those
operations for real on the tiny generated ``sample_video`` (128x96, ~1s) using
``synchronous_runner`` so ``last_output`` is set immediately, and probe the
outputs on disk rather than mocking. Trim ranges are kept short. Tests needing a
clip request ``sample_video`` (which skips when ffmpeg is absent); the probe
fallback path is covered without ffmpeg. Message boxes are silenced and
``.exec()`` is never called.
"""

from __future__ import annotations

from myimages.core.media import build_media_file
from myimages.gui.task_runner import synchronous_runner
from myimages.gui.video_tool_dialog import VideoToolDialog
from myimages.video import ffmpeg


def raise_ffmpeg_error(*args, **kwargs):
    """Stand-in for probe_video that fails, to drive the fallback path."""
    raise ffmpeg.FfmpegError("simulated missing ffmpeg")


def make_dialog(qtbot, path) -> VideoToolDialog:
    """A VideoToolDialog for the clip at ``path``, wired into qtbot."""
    dialog = VideoToolDialog(build_media_file(path), runner=synchronous_runner)
    qtbot.addWidget(dialog)
    return dialog


def test_probe_returns_real_info(qtbot, sample_video):
    dialog = make_dialog(qtbot, sample_video)
    assert dialog.info.width == 128
    assert dialog.info.height == 96
    assert dialog.info.duration > 0


def test_probe_falls_back_on_error(qtbot, tmp_path, monkeypatch):
    fake = tmp_path / "fake.mp4"
    fake.write_bytes(b"not a real video")
    monkeypatch.setattr(ffmpeg, "probe_video", raise_ffmpeg_error)
    dialog = make_dialog(qtbot, fake)
    assert dialog.info == ffmpeg.VideoInfo(duration=0.0, width=0, height=0, fps=0.0)


def test_output_path_uses_output_folder(qtbot, sample_video):
    dialog = make_dialog(qtbot, sample_video)
    expected = sample_video.parent / f"{sample_video.stem}_x.mp4"
    assert dialog.output_path("_x.mp4") == expected


def test_make_pixel_spin_configures_range_and_suffix(qtbot, sample_video):
    dialog = make_dialog(qtbot, sample_video)
    spin = dialog.make_pixel_spin(100, 20)
    assert spin.maximum() == 100
    assert spin.value() == 20
    assert spin.suffix() == " px"
    # A zero maximum is floored to 1 so the spin box stays valid.
    floored = dialog.make_pixel_spin(0)
    assert floored.maximum() == 1
    assert floored.value() == 0


def test_run_trim_creates_clip(qtbot, silence_dialogs, sample_video):
    dialog = make_dialog(qtbot, sample_video)
    dialog.start_spin.setValue(0.0)
    dialog.end_spin.setValue(0.5)
    dialog.run_trim()
    assert dialog.last_output is not None
    assert dialog.last_output.suffix == ".mp4"
    assert dialog.last_output.exists()


def test_run_trim_failure_leaves_no_output(qtbot, silence_dialogs, sample_video):
    dialog = make_dialog(qtbot, sample_video)
    # end == start is an invalid span; trim_video raises before any ffmpeg run.
    dialog.start_spin.setValue(0.5)
    dialog.end_spin.setValue(0.5)
    dialog.run_trim()
    assert dialog.last_output is None


def test_run_gif_creates_gif(qtbot, silence_dialogs, sample_video):
    dialog = make_dialog(qtbot, sample_video)
    dialog.start_spin.setValue(0.0)
    dialog.end_spin.setValue(0.3)
    dialog.gif_fps.setValue(5)
    dialog.gif_width.setValue(48)
    dialog.run_gif()
    assert dialog.last_output is not None
    assert dialog.last_output.suffix == ".gif"
    assert dialog.last_output.exists()


def test_run_crop_scale_scale_only(qtbot, silence_dialogs, sample_video):
    dialog = make_dialog(qtbot, sample_video)
    # Leave crop spins at their full-frame defaults; only scale width is set.
    dialog.scale_width.setValue(64)
    dialog.run_crop_scale()
    assert dialog.last_output is not None
    assert dialog.last_output.exists()
    assert ffmpeg.probe_video(dialog.last_output).width == 64


def test_run_crop_scale_crop_then_scale(qtbot, silence_dialogs, sample_video):
    dialog = make_dialog(qtbot, sample_video)
    dialog.crop_left.setValue(0)
    dialog.crop_top.setValue(0)
    dialog.crop_width.setValue(64)
    dialog.crop_height.setValue(48)
    dialog.scale_width.setValue(32)
    dialog.run_crop_scale()
    assert dialog.last_output is not None
    assert dialog.last_output.exists()
    assert ffmpeg.probe_video(dialog.last_output).width == 32


def test_run_crop_scale_crop_only(qtbot, silence_dialogs, sample_video):
    dialog = make_dialog(qtbot, sample_video)
    dialog.crop_left.setValue(0)
    dialog.crop_top.setValue(0)
    dialog.crop_width.setValue(64)
    dialog.crop_height.setValue(48)
    dialog.scale_width.setValue(0)  # "keep"
    dialog.run_crop_scale()
    assert dialog.last_output is not None
    assert dialog.last_output.exists()
    info = ffmpeg.probe_video(dialog.last_output)
    assert (info.width, info.height) == (64, 48)


def test_run_crop_scale_no_crop_no_scale(qtbot, silence_dialogs, sample_video):
    dialog = make_dialog(qtbot, sample_video)
    # Full-frame crop defaults and no scaling: a straight re-encode at source size.
    dialog.scale_width.setValue(0)
    dialog.run_crop_scale()
    assert dialog.last_output is not None
    assert dialog.last_output.exists()
    assert ffmpeg.probe_video(dialog.last_output).width == 128
