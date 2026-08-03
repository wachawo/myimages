"""Dialog to assemble the selected images into an animated GIF.

Collects frame rate, width and destination; the frames themselves come from the
current selection. :func:`myimages.video.gif.gif_from_frames` builds the GIF and
needs no ffmpeg, so this works out of the box.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from myimages.gui.dialog_buttons import accept_cancel


@dataclass(frozen=True)
class GifParameters:
    """Choices for a frames-to-GIF export."""

    destination: Path
    fps: int
    width: int


class GifFromFramesDialog(QDialog):
    """Collects GIF options for a set of image frames."""

    def __init__(
        self,
        frame_count: int,
        default_path: Path,
        default_fps: int = 12,
        default_width: int = 480,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Create GIF from frames")
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Build a GIF from {frame_count} frame(s)."))
        form = QFormLayout()

        self.fps_spin = QSpinBox()
        self.fps_spin.setRange(1, 60)
        self.fps_spin.setValue(default_fps)
        form.addRow("Frames/second", self.fps_spin)

        self.width_spin = QSpinBox()
        self.width_spin.setRange(48, 1920)
        self.width_spin.setSingleStep(20)
        self.width_spin.setValue(default_width)
        self.width_spin.setSuffix(" px")
        form.addRow("Width", self.width_spin)

        path_row = QHBoxLayout()
        self.path_edit = QLineEdit(str(default_path))
        browse = QToolButton()
        browse.setText("…")
        browse.clicked.connect(self.browse_path)
        path_row.addWidget(self.path_edit, 1)
        path_row.addWidget(browse)
        form.addRow("Save as", path_row)
        layout.addLayout(form)

        buttons = accept_cancel("Create GIF")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def browse_path(self) -> None:
        chosen, _filter = QFileDialog.getSaveFileName(
            self, "Save GIF", self.path_edit.text(), "GIF files (*.gif)"
        )
        if chosen:
            self.path_edit.setText(chosen)

    def parameters(self) -> GifParameters:
        return GifParameters(
            destination=Path(self.path_edit.text()),
            fps=self.fps_spin.value(),
            width=self.width_spin.value(),
        )
