"""Tests for the PDF-export options dialog (myimages.gui.pdf_dialog).

The dialog gathers page quality, a maximum edge, greyscale and an optional size
budget, and returns them as ``PdfExportParameters`` wrapping a ``PdfOptions``.
The save picker is monkeypatched (``getSaveFileName`` returns a (path, filter)
tuple) so no real file dialog ever opens.
"""

from __future__ import annotations

from PySide6.QtWidgets import QFileDialog

from myimages.gui.pdf_dialog import PdfDialog, PdfExportParameters
from myimages.imaging.pdfbuilder import PdfOptions


def make_dialog(qtbot, tmp_path, file_count=2, quality=85) -> PdfDialog:
    """A PdfDialog wired into qtbot with ``out.pdf`` in the temp dir as default."""
    dialog = PdfDialog(file_count, tmp_path / "out.pdf", quality)
    qtbot.addWidget(dialog)
    return dialog


def test_slider_defaults_to_settings_quality(qtbot, tmp_path):
    dialog = make_dialog(qtbot, tmp_path, quality=73)
    assert dialog.quality_slider.value() == 73
    assert dialog.quality_value.text() == "73"


def test_quality_label_tracks_slider(qtbot, tmp_path):
    dialog = make_dialog(qtbot, tmp_path)
    dialog.quality_slider.setValue(42)
    assert dialog.quality_value.text() == "42"


def test_parameters_reflect_widgets(qtbot, tmp_path):
    dialog = make_dialog(qtbot, tmp_path)
    out = tmp_path / "book.pdf"
    dialog.quality_slider.setValue(60)
    dialog.grayscale_check.setChecked(True)
    dialog.max_edge_spin.setValue(1500)
    dialog.target_spin.setValue(4.5)
    dialog.path_edit.setText(str(out))

    assert dialog.parameters() == PdfExportParameters(
        destination=out,
        options=PdfOptions(
            quality=60,
            grayscale=True,
            max_edge_px=1500,
            target_mib=4.5,
        ),
    )


def test_browse_path_sets_destination(qtbot, tmp_path, monkeypatch):
    dialog = make_dialog(qtbot, tmp_path)
    chosen = tmp_path / "picked.pdf"
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *a, **k: (str(chosen), "PDF files (*.pdf)")),
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


def test_page_format_combo_toggles_size_controls(qtbot, tmp_path):
    from pathlib import Path

    from myimages.gui.pdf_dialog import PdfDialog

    dialog = PdfDialog(2, Path(tmp_path) / "out.pdf")
    qtbot.addWidget(dialog)

    # Default: JPEG mode with all size controls live.
    assert dialog.parameters().options.jpeg_pages is True
    assert dialog.quality_slider.isEnabled()
    assert dialog.max_edge_spin.isEnabled()
    assert dialog.target_spin.isEnabled()

    dialog.format_combo.setCurrentIndex(1)  # Original size
    assert dialog.parameters().options.jpeg_pages is False
    assert not dialog.quality_slider.isEnabled()
    assert not dialog.max_edge_spin.isEnabled()
    assert not dialog.target_spin.isEnabled()

    dialog.format_combo.setCurrentIndex(0)
    assert dialog.quality_slider.isEnabled()
