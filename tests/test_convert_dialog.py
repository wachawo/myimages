"""Tests for the image-conversion options dialog (myimages.gui.convert_dialog).

The dialog only collects choices, so the tests construct it, drive its widgets,
and read back the resulting ``ConvertParameters``. The folder picker is exercised
by monkeypatching ``QFileDialog.getExistingDirectory`` (never opened for real).
"""

from __future__ import annotations

from PySide6.QtWidgets import QFileDialog, QPushButton

from myimages.gui.convert_dialog import ConvertDialog, ConvertParameters


def make_dialog(qtbot, tmp_path, file_count=3) -> ConvertDialog:
    """A ConvertDialog wired into qtbot with the temp dir as its default output."""
    dialog = ConvertDialog(file_count, tmp_path)
    qtbot.addWidget(dialog)
    return dialog


def test_defaults_and_png_disables_quality(qtbot, tmp_path):
    dialog = make_dialog(qtbot, tmp_path)
    # PNG is the first (lossless) entry, so quality is meaningless and disabled.
    assert dialog.format_combo.currentData() == ".png"
    assert not dialog.quality_spin.isEnabled()
    assert dialog.quality_spin.value() == 90


def test_jpg_and_webp_enable_quality(qtbot, tmp_path):
    dialog = make_dialog(qtbot, tmp_path)
    dialog.format_combo.setCurrentIndex(dialog.format_combo.findData(".jpg"))
    assert dialog.quality_spin.isEnabled()
    dialog.format_combo.setCurrentIndex(dialog.format_combo.findData(".webp"))
    assert dialog.quality_spin.isEnabled()


def test_lossless_format_disables_quality(qtbot, tmp_path):
    dialog = make_dialog(qtbot, tmp_path)
    dialog.format_combo.setCurrentIndex(dialog.format_combo.findData(".jpg"))
    assert dialog.quality_spin.isEnabled()
    # Switching back to a lossless format disables the spin again.
    dialog.format_combo.setCurrentIndex(dialog.format_combo.findData(".bmp"))
    assert not dialog.quality_spin.isEnabled()


def test_parameters_reflect_widgets(qtbot, tmp_path):
    dialog = make_dialog(qtbot, tmp_path)
    out = tmp_path / "converted"
    dialog.format_combo.setCurrentIndex(dialog.format_combo.findData(".webp"))
    dialog.quality_spin.setValue(72)
    dialog.grayscale_check.setChecked(True)
    dialog.output_edit.setText(str(out))

    assert dialog.parameters() == ConvertParameters(
        target_extension=".webp",
        quality=72,
        grayscale=True,
        output_dir=out,
    )


def test_browse_output_sets_directory(qtbot, tmp_path, monkeypatch):
    dialog = make_dialog(qtbot, tmp_path)
    chosen = tmp_path / "picked"
    monkeypatch.setattr(
        QFileDialog,
        "getExistingDirectory",
        staticmethod(lambda *a, **k: str(chosen)),
    )
    dialog.browse_output()
    assert dialog.output_edit.text() == str(chosen)


def test_browse_output_cancel_keeps_text(qtbot, tmp_path, monkeypatch):
    dialog = make_dialog(qtbot, tmp_path)
    before = dialog.output_edit.text()
    monkeypatch.setattr(
        QFileDialog,
        "getExistingDirectory",
        staticmethod(lambda *a, **k: ""),
    )
    dialog.browse_output()
    assert dialog.output_edit.text() == before


def test_save_and_copy_buttons_set_replace_flag(qtbot, tmp_path):
    from pathlib import Path

    from myimages.gui.convert_dialog import ConvertDialog

    dialog = ConvertDialog(1, Path(tmp_path))
    qtbot.addWidget(dialog)
    assert dialog.parameters().replace_originals is False  # default: Copy

    dialog.accept_replacing()
    assert dialog.replace_originals is True
    assert dialog.parameters().replace_originals is True
    assert dialog.result() == 1  # dialog accepted

    dialog.accept_copying()
    assert dialog.parameters().replace_originals is False


def test_the_buttons_name_what_happens_to_the_originals(qtbot, tmp_path):
    """One of these deletes the originals; the label has to say so."""
    dialog = make_dialog(qtbot, tmp_path)
    labels = {
        button.text(): button.toolTip()
        for button in dialog.findChildren(QPushButton)
        if button.text() in {"Save", "Save as Copy", "Cancel"}
    }
    assert set(labels) == {"Save", "Save as Copy", "Cancel"}
    assert "delete" in labels["Save"]
    assert "keep originals" in labels["Save as Copy"]


def test_the_accept_button_is_styled_as_the_primary_one(qtbot, tmp_path):
    """Naming a widget after it exists does not re-match the stylesheet."""
    from PySide6.QtWidgets import QDialogButtonBox

    from myimages.app import apply_theme_to_app
    from myimages.gui.dialog_buttons import accept_cancel

    apply_theme_to_app("dark")
    box = accept_cancel("Save Settings")
    qtbot.addWidget(box)
    accept = box.button(QDialogButtonBox.StandardButton.Ok)
    cancel = box.button(QDialogButtonBox.StandardButton.Cancel)

    assert accept.objectName() == "primary"
    assert accept.palette().button().color() != cancel.palette().button().color()
