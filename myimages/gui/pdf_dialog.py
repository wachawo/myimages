"""Dialog to combine the selected images into a single PDF.

Exposes the levers that decide the final file size — page quality, a maximum
edge in pixels, greyscale, and an optional hard size budget in mebibytes — and
returns them alongside the destination path. :mod:`myimages.imaging.pdfbuilder`
does the work and honours the budget by lowering quality until it fits.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSlider,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from myimages.gui.dialog_buttons import accept_cancel
from myimages.imaging.pdfbuilder import PdfOptions


@dataclass(frozen=True)
class PdfExportParameters:
    """Everything needed to build the PDF."""

    destination: Path
    options: PdfOptions


class PdfDialog(QDialog):
    """Collects PDF export options for a batch of images."""

    def __init__(
        self,
        file_count: int,
        default_path: Path,
        settings_quality: int = 85,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Export to PDF")
        self.setMinimumWidth(440)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Combine {file_count} image(s) into a PDF."))
        form = QFormLayout()

        self.format_combo = QComboBox()
        self.format_combo.addItem("JPEG — recompressed, size control", "jpeg")
        self.format_combo.addItem("Original size — no resize, top quality", "original")
        self.format_combo.setToolTip(
            "JPEG pages honour the quality/size settings below;\n"
            "Original size keeps full resolution at top quality (bigger file)."
        )
        self.format_combo.currentIndexChanged.connect(self.sync_mode_controls)
        form.addRow("Pages", self.format_combo)

        quality_row = QHBoxLayout()
        self.quality_slider = QSlider(Qt.Orientation.Horizontal)
        self.quality_slider.setRange(20, 100)
        self.quality_slider.setValue(settings_quality)
        self.quality_value = QLabel(str(settings_quality))
        self.quality_slider.valueChanged.connect(
            lambda value: self.quality_value.setText(str(value))
        )
        quality_row.addWidget(self.quality_slider, 1)
        quality_row.addWidget(self.quality_value)
        form.addRow("Page quality", quality_row)

        self.max_edge_spin = QSpinBox()
        self.max_edge_spin.setRange(300, 8000)
        self.max_edge_spin.setSingleStep(100)
        self.max_edge_spin.setValue(2200)
        self.max_edge_spin.setSuffix(" px")
        form.addRow("Max page edge", self.max_edge_spin)

        self.target_spin = QDoubleSpinBox()
        self.target_spin.setRange(0.0, 500.0)
        self.target_spin.setDecimals(1)
        self.target_spin.setSingleStep(0.5)
        self.target_spin.setSuffix(" MiB (0 = no limit)")
        form.addRow("Target size", self.target_spin)

        self.grayscale_check = QCheckBox("Black and white pages")
        form.addRow("", self.grayscale_check)

        path_row = QHBoxLayout()
        self.path_edit = QLineEdit(str(default_path))
        browse = QToolButton()
        browse.setText("…")
        browse.setToolTip("Choose PDF file")
        browse.clicked.connect(self.browse_path)
        path_row.addWidget(self.path_edit, 1)
        path_row.addWidget(browse)
        form.addRow("Save as", path_row)
        layout.addLayout(form)

        buttons = accept_cancel("Export PDF")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.sync_mode_controls()

    def jpeg_mode(self) -> bool:
        return str(self.format_combo.currentData()) == "jpeg"

    def sync_mode_controls(self) -> None:
        """Size controls only make sense when pages are recompressed."""
        jpeg = self.jpeg_mode()
        self.quality_slider.setEnabled(jpeg)
        self.max_edge_spin.setEnabled(jpeg)
        self.target_spin.setEnabled(jpeg)

    def browse_path(self) -> None:
        chosen, chosen_filter = QFileDialog.getSaveFileName(
            self, "Save PDF", self.path_edit.text(), "PDF files (*.pdf)"
        )
        if chosen:
            self.path_edit.setText(chosen)

    def parameters(self) -> PdfExportParameters:
        return PdfExportParameters(
            destination=Path(self.path_edit.text()),
            options=PdfOptions(
                quality=self.quality_slider.value(),
                grayscale=self.grayscale_check.isChecked(),
                max_edge_px=self.max_edge_spin.value(),
                target_mib=self.target_spin.value(),
                jpeg_pages=self.jpeg_mode(),
            ),
        )
