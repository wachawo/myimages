"""Tests for the batch-rename dialog's live preview and validation."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtWidgets import QAbstractButton, QDialogButtonBox

from myimages.core.media import MediaFile, build_media_file
from myimages.gui.rename_dialog import RenameDialog


def build_files(make_image: Callable[..., Path], names: list[str]) -> list[MediaFile]:
    return [build_media_file(make_image(name)) for name in names]


def ok_button(dialog: RenameDialog) -> QAbstractButton:
    button = dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)
    assert button is not None
    return button


def test_default_pattern_produces_plan_and_rows(qtbot, make_image):
    files = build_files(make_image, ["alpha.png", "bravo.png", "charlie.png"])
    dialog = RenameDialog(files)
    qtbot.addWidget(dialog)

    assert len(dialog.plan()) == 3
    assert dialog.preview_table.rowCount() == 3
    current = dialog.preview_table.item(0, 0)
    new = dialog.preview_table.item(0, 1)
    assert current is not None and new is not None
    assert current.text() == "alpha.png"
    assert new.text() == "alpha_001.png"
    assert "3 file(s) will be renamed." in dialog.status_label.text()
    assert ok_button(dialog).isEnabled() is True


def test_invalid_pattern_disables_ok_and_empties_plan(qtbot, make_image):
    files = build_files(make_image, ["a.png", "b.png"])
    dialog = RenameDialog(files)
    qtbot.addWidget(dialog)

    dialog.pattern_edit.setText("{nope}")

    assert dialog.plan() == []
    assert dialog.preview_table.rowCount() == 0
    assert "Invalid pattern" in dialog.status_label.text()
    assert ok_button(dialog).isEnabled() is False


def test_colliding_pattern_disables_ok(qtbot, make_image):
    files = build_files(make_image, ["a.png", "b.png", "c.png"])
    dialog = RenameDialog(files)
    qtbot.addWidget(dialog)

    dialog.pattern_edit.setText("same.png")

    assert "collision" in dialog.status_label.text()
    assert len(dialog.plan()) == 3
    assert ok_button(dialog).isEnabled() is False


def test_unique_pattern_enables_ok(qtbot, make_image):
    files = build_files(make_image, ["a.png", "b.png"])
    dialog = RenameDialog(files)
    qtbot.addWidget(dialog)

    dialog.pattern_edit.setText("photo_{n}.{ext}")

    targets = [item.target.name for item in dialog.plan()]
    assert targets == ["photo_1.png", "photo_2.png"]
    assert ok_button(dialog).isEnabled() is True


def test_start_and_step_update_plan(qtbot, make_image):
    files = build_files(make_image, ["a.png", "b.png", "c.png"])
    dialog = RenameDialog(files)
    qtbot.addWidget(dialog)

    dialog.start_spin.setValue(10)
    dialog.step_spin.setValue(5)

    targets = [item.target.name for item in dialog.plan()]
    assert targets == ["a_010.png", "b_015.png", "c_020.png"]
