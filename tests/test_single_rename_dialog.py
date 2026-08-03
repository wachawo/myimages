"""Tests for :mod:`myimages.gui.single_rename_dialog`.

The validation lives in a module-level function so the interesting cases can be
checked without building a dialog at all; the dialog tests then only cover the
wiring between that function, the text box and the accept button.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QDialogButtonBox

from myimages.gui.single_rename_dialog import SingleRenameDialog, problem_with


@pytest.fixture()
def photo(tmp_path: Path) -> Path:
    path = tmp_path / "holiday.jpg"
    path.write_bytes(b"not really a jpeg")
    return path


# -- validation --------------------------------------------------------------


def test_a_plain_name_is_accepted(photo: Path):
    assert problem_with("beach", photo) == ""


def test_keeping_the_same_name_is_not_a_collision(photo: Path):
    """Opening the box and pressing Rename unchanged must not look like an error."""
    assert problem_with("holiday", photo) == ""


def test_an_empty_name_is_refused(photo: Path):
    assert "empty" in problem_with("   ", photo)


def test_a_slash_is_refused(photo: Path):
    """A name with a separator would move the file, not rename it."""
    assert "slash" in problem_with("../elsewhere", photo)
    assert "slash" in problem_with("sub/name", photo)


def test_an_existing_neighbour_is_refused(photo: Path):
    (photo.parent / "taken.jpg").write_bytes(b"x")
    assert "already exists" in problem_with("taken", photo)


def test_a_neighbour_with_another_extension_is_fine(photo: Path):
    """Only the name plus this file's own extension can collide."""
    (photo.parent / "taken.png").write_bytes(b"x")
    assert problem_with("taken", photo) == ""


# -- the dialog --------------------------------------------------------------


def accept_button(dialog: SingleRenameDialog):
    return dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)


def test_the_box_opens_on_the_name_without_its_extension(qtbot, photo: Path):
    dialog = SingleRenameDialog(photo)
    qtbot.addWidget(dialog)
    assert dialog.name_edit.text() == "holiday"
    assert ".jpg" in dialog.suffix_label.text()
    assert accept_button(dialog).text() == "Rename"


def test_the_extension_is_kept(qtbot, photo: Path):
    dialog = SingleRenameDialog(photo)
    qtbot.addWidget(dialog)
    dialog.name_edit.setText("beach")
    assert dialog.new_path() == photo.parent / "beach.jpg"


def test_surrounding_spaces_are_trimmed(qtbot, photo: Path):
    dialog = SingleRenameDialog(photo)
    qtbot.addWidget(dialog)
    dialog.name_edit.setText("  beach  ")
    assert dialog.new_path().name == "beach.jpg"


def test_a_bad_name_disables_rename_and_says_why(qtbot, photo: Path):
    dialog = SingleRenameDialog(photo)
    qtbot.addWidget(dialog)

    dialog.name_edit.setText("")

    assert accept_button(dialog).isEnabled() is False
    assert dialog.problem_label.text()

    dialog.name_edit.setText("beach")

    assert accept_button(dialog).isEnabled() is True
    assert dialog.problem_label.text() == ""


def test_a_file_with_no_extension_still_works(qtbot, tmp_path: Path):
    path = tmp_path / "README"
    path.write_text("x")
    dialog = SingleRenameDialog(path)
    qtbot.addWidget(dialog)
    assert dialog.name_edit.text() == "README"
    assert "same" in dialog.suffix_label.text()
    dialog.name_edit.setText("NOTES")
    assert dialog.new_path().name == "NOTES"
