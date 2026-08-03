"""Tests for the frames-to-GIF options dialog (myimages.gui.gif_dialog).

The dialog collects frame rate, width and destination and returns them as
``GifParameters``. The save picker is monkeypatched (``getSaveFileName`` returns
a (path, filter) tuple) so no real file dialog ever opens.
"""

from __future__ import annotations

from PySide6.QtWidgets import QFileDialog

from myimages.gui.gif_dialog import GifFromFramesDialog, GifParameters


def make_dialog(qtbot, tmp_path, frame_count=3, **kwargs) -> GifFromFramesDialog:
    """A GifFromFramesDialog wired into qtbot with ``a.gif`` as its default path."""
    dialog = GifFromFramesDialog(frame_count, tmp_path / "a.gif", **kwargs)
    qtbot.addWidget(dialog)
    return dialog


def test_defaults(qtbot, tmp_path):
    dialog = make_dialog(qtbot, tmp_path)
    assert dialog.fps_spin.value() == 12
    assert dialog.width_spin.value() == 480


def test_custom_defaults(qtbot, tmp_path):
    dialog = make_dialog(qtbot, tmp_path, default_fps=30, default_width=720)
    assert dialog.fps_spin.value() == 30
    assert dialog.width_spin.value() == 720


def test_parameters_reflect_widgets(qtbot, tmp_path):
    dialog = make_dialog(qtbot, tmp_path)
    out = tmp_path / "movie.gif"
    dialog.fps_spin.setValue(24)
    dialog.width_spin.setValue(640)
    dialog.path_edit.setText(str(out))

    assert dialog.parameters() == GifParameters(
        destination=out,
        fps=24,
        width=640,
    )


def test_browse_path_sets_destination(qtbot, tmp_path, monkeypatch):
    dialog = make_dialog(qtbot, tmp_path)
    chosen = tmp_path / "picked.gif"
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *a, **k: (str(chosen), "GIF files (*.gif)")),
    )
    dialog.browse_path()
    assert dialog.path_edit.text() == str(chosen)


def test_browse_path_cancel_keeps_text(qtbot, tmp_path, monkeypatch):
    dialog = make_dialog(qtbot, tmp_path)
    before = dialog.path_edit.text()
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *a, **k: ("", "")),
    )
    dialog.browse_path()
    assert dialog.path_edit.text() == before
