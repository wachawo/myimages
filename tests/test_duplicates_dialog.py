"""Tests for the duplicate-finder dialog (myimages.gui.duplicates_dialog).

The dialog scans a file set (via ``myimages.core.duplicates``), presents the
groups in a tree with the first member kept and the rest pre-checked, and
deletes the checked files through an injected ``delete_function``. The tests use
byte-identical *video* files: they hash to one exact-duplicate group, while the
perceptual pass ignores non-images, giving a single deterministic group without
the flat-colour aHash collisions that plague identical solid images. Scans run
through ``synchronous_runner`` so results are observable at once, and message
boxes are silenced so nothing blocks.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

from myimages.core.duplicates import DuplicateGroup
from myimages.core.media import MediaFile, build_media_file
from myimages.gui.duplicates_dialog import DuplicatesDialog
from myimages.gui.task_runner import synchronous_runner


def build_dupe_files(
    tmp_path,
) -> tuple[list[MediaFile], tuple[Path, Path, Path]]:
    """Two byte-identical videos plus a unique one; returns files and paths."""
    first = tmp_path / "a.mp4"
    first.write_bytes(b"identical video bytes")
    copy = tmp_path / "b.mp4"
    shutil.copyfile(first, copy)
    unique = tmp_path / "c.mp4"
    unique.write_bytes(b"a wholly different set of bytes")
    files = [build_media_file(p) for p in (first, copy, unique)]
    return files, (first, copy, unique)


def build_unique_files(
    tmp_path,
) -> tuple[list[MediaFile], tuple[Path, Path]]:
    """A pair of non-duplicate videos (no group is ever produced)."""
    first = tmp_path / "x.mp4"
    first.write_bytes(b"one")
    second = tmp_path / "y.mp4"
    second.write_bytes(b"two")
    return [build_media_file(p) for p in (first, second)], (first, second)


def unlink_all(paths) -> list[Path]:
    """A delete_function that hard-unlinks each path and reports them removed."""
    removed = []
    for raw in paths:
        target = Path(raw)
        target.unlink()
        removed.append(target)
    return removed


def test_scan_now_finds_exact_group(qtbot, tmp_path):
    files, (first, copy, _unique) = build_dupe_files(tmp_path)
    dialog = DuplicatesDialog(files, runner=synchronous_runner)
    qtbot.addWidget(dialog)
    groups = dialog.scan_now()
    assert len(groups) == 1
    assert groups[0].reason == "identical bytes"
    assert groups[0].paths == [first, copy]


def test_populate_checks_extras_only(qtbot, tmp_path):
    files, (_first, copy, _unique) = build_dupe_files(tmp_path)
    dialog = DuplicatesDialog(files, runner=synchronous_runner)
    qtbot.addWidget(dialog)
    dialog.populate(dialog.scan_now())

    assert dialog.tree.topLevelItemCount() == 1
    parent = dialog.tree.topLevelItem(0)
    assert parent is not None
    assert parent.childCount() == 2
    kept = parent.child(0)
    extra = parent.child(1)
    assert kept is not None and extra is not None
    assert kept.checkState(0) == Qt.CheckState.Unchecked
    assert extra.checkState(0) == Qt.CheckState.Checked

    assert dialog.checked_paths() == [str(copy)]
    assert "group(s)" in dialog.status_label.text()
    assert "extra" in dialog.status_label.text()


def test_populate_no_duplicates_status(qtbot, tmp_path):
    files, paths = build_unique_files(tmp_path)
    dialog = DuplicatesDialog(files, runner=synchronous_runner)
    qtbot.addWidget(dialog)
    dialog.populate(dialog.scan_now())
    assert dialog.tree.topLevelItemCount() == 0
    assert dialog.status_label.text() == "No duplicates found."


def test_populate_missing_file_shows_dash(qtbot, tmp_path):
    dialog = DuplicatesDialog([], runner=synchronous_runner)
    qtbot.addWidget(dialog)
    present = tmp_path / "here.mp4"
    present.write_bytes(b"present")
    missing = tmp_path / "gone.mp4"  # never created on disk
    group = DuplicateGroup(reason="identical bytes", paths=[present, missing])
    dialog.populate([group])

    parent = dialog.tree.topLevelItem(0)
    assert parent is not None
    extra = parent.child(1)
    assert extra is not None
    assert extra.text(1) == "—"


def test_start_scan_populates_synchronously(qtbot, tmp_path):
    files, paths = build_dupe_files(tmp_path)
    dialog = DuplicatesDialog(files, runner=synchronous_runner)
    qtbot.addWidget(dialog)
    dialog.start_scan()
    assert dialog.tree.topLevelItemCount() == 1
    # populate() re-enables the button that start_scan() disabled.
    assert dialog.scan_button.isEnabled()


def test_on_scan_failed_sets_status(qtbot, tmp_path):
    files, paths = build_unique_files(tmp_path)
    dialog = DuplicatesDialog(files, runner=synchronous_runner)
    qtbot.addWidget(dialog)
    dialog.scan_button.setEnabled(False)
    dialog.on_scan_failed("boom")
    assert dialog.scan_button.isEnabled()
    assert dialog.status_label.text() == "Scan failed: boom"


def test_delete_checked_unlinks_emits_and_rescans(qtbot, silence_dialogs, tmp_path):
    files, (_first, copy, _unique) = build_dupe_files(tmp_path)
    dialog = DuplicatesDialog(
        files, runner=synchronous_runner, delete_function=unlink_all
    )
    qtbot.addWidget(dialog)

    emitted: list[list[str]] = []
    dialog.files_deleted.connect(emitted.append)

    dialog.start_scan()
    assert dialog.checked_paths() == [str(copy)]

    dialog.delete_checked()

    assert not copy.exists()
    assert emitted == [[str(copy)]]
    # After deletion the re-scan finds nothing, clearing the tree.
    assert dialog.tree.topLevelItemCount() == 0
    assert dialog.status_label.text() == "No duplicates found."


def test_delete_checked_nothing_checked(qtbot, tmp_path):
    files, paths = build_unique_files(tmp_path)
    dialog = DuplicatesDialog(
        files, runner=synchronous_runner, delete_function=unlink_all
    )
    qtbot.addWidget(dialog)
    # No scan has run, so nothing is checked.
    dialog.delete_checked()
    assert dialog.status_label.text() == "Nothing checked."


def test_delete_checked_declined_keeps_files(qtbot, tmp_path, monkeypatch):
    files, (_first, copy, _unique) = build_dupe_files(tmp_path)
    dialog = DuplicatesDialog(
        files, runner=synchronous_runner, delete_function=unlink_all
    )
    qtbot.addWidget(dialog)
    dialog.start_scan()

    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.No),
    )
    dialog.delete_checked()
    assert copy.exists()  # declining the prompt deletes nothing


def test_constructor_accepts_media_file_list(qtbot, tmp_path):
    files, paths = build_dupe_files(tmp_path)
    assert all(isinstance(f, MediaFile) for f in files)
    dialog = DuplicatesDialog(files, runner=synchronous_runner)
    qtbot.addWidget(dialog)
    assert dialog.status_label.text() == "Press Scan to look for duplicates."
