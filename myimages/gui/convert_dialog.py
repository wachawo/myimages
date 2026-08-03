"""Dialog to convert the selected images to another format.

It only collects choices — target format, JPEG/WebP quality, greyscale and the
output folder — and hands them back as :class:`ConvertParameters`. The actual
conversion is done by :mod:`myimages.imaging.convert`, which is already tested.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

TARGET_EXTENSIONS: tuple[tuple[str, str], ...] = (
    (".png", "PNG (lossless)"),
    (".jpg", "JPEG"),
    (".webp", "WebP"),
    (".bmp", "BMP"),
    (".tiff", "TIFF"),
    (".gif", "GIF"),
)
LOSSY_EXTENSIONS: frozenset[str] = frozenset({".jpg", ".jpeg", ".webp"})


@dataclass(frozen=True)
class ConvertParameters:
    """The user's conversion choices.

    ``replace_originals`` mirrors the button that closed the dialog: **Save**
    converts each file next to its original and removes the original, while
    **Copy** writes converted copies into ``output_dir`` and keeps everything.
    """

    target_extension: str
    quality: int
    grayscale: bool
    output_dir: Path
    replace_originals: bool = False


class ConvertDialog(QDialog):
    """Collects conversion options for a batch of images."""

    def __init__(
        self, file_count: int, default_dir: Path, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Convert images")
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel(f"Convert {file_count} file(s) to:"))
        form = QFormLayout()

        self.format_combo = QComboBox()
        for extension, label in TARGET_EXTENSIONS:
            self.format_combo.addItem(label, extension)
        self.format_combo.currentIndexChanged.connect(self.sync_quality_enabled)
        form.addRow("Format", self.format_combo)

        self.quality_spin = QSpinBox()
        self.quality_spin.setRange(1, 100)
        self.quality_spin.setValue(90)
        form.addRow("Quality", self.quality_spin)

        self.grayscale_check = QCheckBox("Convert to black and white")
        form.addRow("", self.grayscale_check)

        output_row = QHBoxLayout()
        self.output_edit = QLineEdit(str(default_dir))
        browse = QToolButton()
        browse.setText("…")
        browse.setToolTip("Choose output folder")
        browse.clicked.connect(self.browse_output)
        output_row.addWidget(self.output_edit, 1)
        output_row.addWidget(browse)
        form.addRow("Copy to", output_row)
        layout.addLayout(form)

        self.replace_originals = False
        layout.addWidget(self.build_buttons())
        self.sync_quality_enabled()

    def build_buttons(self) -> QWidget:
        """Save / Save as Copy / Cancel, in that order.

        Laid out by hand rather than with a ``QDialogButtonBox``: the box sorts
        buttons by role, which put the destructive one last and left the three
        in a different order here than in the image editor. Two dialogs that do
        the same thing should not need reading twice.
        """
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addStretch(1)
        self.save_button = QPushButton("Save")
        self.save_button.setObjectName("primary")
        self.save_button.setToolTip(
            "Convert next to each original, then delete the original"
        )
        self.save_button.clicked.connect(self.accept_replacing)
        self.copy_button = QPushButton("Save as Copy")
        self.copy_button.setToolTip(
            "Write converted copies to the folder above; keep originals"
        )
        self.copy_button.clicked.connect(self.accept_copying)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)
        for button in (self.save_button, self.copy_button, self.cancel_button):
            row.addWidget(button)
        holder = QWidget()
        holder.setLayout(row)
        return holder

    def accept_replacing(self) -> None:
        self.replace_originals = True
        self.accept()

    def accept_copying(self) -> None:
        self.replace_originals = False
        self.accept()

    def sync_quality_enabled(self) -> None:
        extension = str(self.format_combo.currentData())
        self.quality_spin.setEnabled(extension in LOSSY_EXTENSIONS)

    def browse_output(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, "Output folder", self.output_edit.text()
        )
        if chosen:
            self.output_edit.setText(chosen)

    def parameters(self) -> ConvertParameters:
        return ConvertParameters(
            target_extension=str(self.format_combo.currentData()),
            quality=self.quality_spin.value(),
            grayscale=self.grayscale_check.isChecked(),
            output_dir=Path(self.output_edit.text()),
            replace_originals=self.replace_originals,
        )
