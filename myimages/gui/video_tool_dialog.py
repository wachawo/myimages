"""One place for the video operations: trim, crop, scale and GIF export.

Each action reads its fields, runs the matching ffmpeg-backed helper through the
injected runner (threaded in the app, synchronous in tests) and reports where
the result was written. Outputs are always new files next to the source, so the
original clip is never touched.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from myimages.core.media import MediaFile
from myimages.format_utils import human_readable_duration
from myimages.gui.task_runner import Runner, threaded_runner
from myimages.video import ffmpeg, gif, trim
from myimages.video import transform as video_transform


class VideoToolDialog(QDialog):
    """Trim, crop/scale or GIF-export a single video via ffmpeg."""

    def __init__(
        self,
        media_file: MediaFile,
        parent: QWidget | None = None,
        runner: Runner = threaded_runner,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Video tools — {media_file.name}")
        self.setMinimumWidth(460)
        self.media_file = media_file
        self.runner = runner
        self.last_output: Path | None = None
        self.info = self.probe()

        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                f"{self.info.width}×{self.info.height}, "
                f"{human_readable_duration(self.info.duration)}"
            )
        )
        layout.addWidget(self.build_trim_group())
        layout.addWidget(self.build_crop_scale_group())
        layout.addWidget(self.build_gif_group())

        output_row = QHBoxLayout()
        output_row.addWidget(QLabel("Output folder"))
        self.output_edit = QLineEdit(str(media_file.path.parent))
        output_row.addWidget(self.output_edit, 1)
        layout.addLayout(output_row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def probe(self) -> ffmpeg.VideoInfo:
        try:
            return ffmpeg.probe_video(self.media_file.path)
        except ffmpeg.FfmpegError:
            return ffmpeg.VideoInfo(duration=0.0, width=0, height=0, fps=0.0)

    # -- groups ------------------------------------------------------------

    def build_trim_group(self) -> QGroupBox:
        group = QGroupBox("Trim")
        form = QFormLayout(group)
        self.start_spin = QDoubleSpinBox()
        self.start_spin.setRange(0.0, max(self.info.duration, 0.0))
        self.start_spin.setDecimals(2)
        self.start_spin.setSuffix(" s")
        self.end_spin = QDoubleSpinBox()
        self.end_spin.setRange(0.0, max(self.info.duration, 0.0))
        self.end_spin.setDecimals(2)
        self.end_spin.setSuffix(" s")
        self.end_spin.setValue(self.info.duration)
        form.addRow("Start", self.start_spin)
        form.addRow("End", self.end_spin)
        run = QPushButton("Save trimmed clip")
        run.clicked.connect(self.run_trim)
        form.addRow(run)
        return group

    def build_crop_scale_group(self) -> QGroupBox:
        group = QGroupBox("Crop and scale")
        form = QFormLayout(group)
        self.crop_left = self.make_pixel_spin(self.info.width)
        self.crop_top = self.make_pixel_spin(self.info.height)
        self.crop_width = self.make_pixel_spin(self.info.width, self.info.width)
        self.crop_height = self.make_pixel_spin(self.info.height, self.info.height)
        form.addRow("Crop left", self.crop_left)
        form.addRow("Crop top", self.crop_top)
        form.addRow("Crop width", self.crop_width)
        form.addRow("Crop height", self.crop_height)
        self.scale_width = self.make_pixel_spin(8000, 0)
        self.scale_width.setSpecialValueText("keep")
        form.addRow("Scale width", self.scale_width)
        run = QPushButton("Save cropped / scaled clip")
        run.clicked.connect(self.run_crop_scale)
        form.addRow(run)
        return group

    def build_gif_group(self) -> QGroupBox:
        group = QGroupBox("Export GIF")
        form = QFormLayout(group)
        self.gif_fps = QSpinBox()
        self.gif_fps.setRange(1, 50)
        self.gif_fps.setValue(12)
        self.gif_width = QSpinBox()
        self.gif_width.setRange(48, 1920)
        self.gif_width.setValue(480)
        form.addRow("Frames/second", self.gif_fps)
        form.addRow("Width", self.gif_width)
        run = QPushButton("Save GIF of trim range")
        run.clicked.connect(self.run_gif)
        form.addRow(run)
        return group

    def make_pixel_spin(self, maximum: int, value: int = 0) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(0, max(maximum, 1))
        spin.setValue(value)
        spin.setSuffix(" px")
        return spin

    # -- operations --------------------------------------------------------

    def output_path(self, suffix: str) -> Path:
        folder = Path(self.output_edit.text())
        return folder / f"{self.media_file.path.stem}{suffix}"

    def run_operation(
        self, function: Callable[[], object], success_message: str
    ) -> None:
        progress = QProgressDialog("Working…", "", 0, 0, self)
        progress.setCancelButton(None)
        progress.setWindowTitle("Please wait")
        progress.show()

        def finished(result: object) -> None:
            progress.close()
            self.last_output = Path(str(result))
            QMessageBox.information(self, "Video tools", f"{success_message}\n{result}")

        def failed(message: str) -> None:
            progress.close()
            QMessageBox.warning(self, "Video tools", message)

        self.runner(function, finished, failed)

    def run_trim(self) -> None:
        start = self.start_spin.value()
        end = self.end_spin.value()
        destination = self.output_path(f"_trim{self.media_file.suffix}")
        self.run_operation(
            lambda: trim.trim_video(self.media_file.path, destination, start, end),
            "Saved trimmed clip:",
        )

    def run_crop_scale(self) -> None:
        destination = self.output_path(f"_edit{self.media_file.suffix}")
        crop_left = self.crop_left.value()
        crop_top = self.crop_top.value()
        crop_width = self.crop_width.value()
        crop_height = self.crop_height.value()
        scale_width = self.scale_width.value()
        source = self.media_file.path

        def operation() -> Path:
            intermediate = source
            temp = destination.with_name(f"{destination.stem}_tmp{destination.suffix}")
            if (
                crop_width > 0
                and crop_height > 0
                and (
                    crop_left,
                    crop_top,
                    crop_width,
                    crop_height,
                )
                != (0, 0, self.info.width, self.info.height)
            ):
                video_transform.crop_video(
                    intermediate,
                    temp,
                    left=crop_left,
                    top=crop_top,
                    width=crop_width,
                    height=crop_height,
                )
                intermediate = temp
            if scale_width > 0:
                video_transform.scale_video(
                    intermediate, destination, width=scale_width
                )
            else:
                if intermediate == source:
                    video_transform.scale_video(
                        source, destination, width=self.info.width
                    )
                else:
                    temp.replace(destination)
            if temp.exists() and temp != destination:
                temp.unlink()
            return destination

        self.run_operation(operation, "Saved edited clip:")

    def run_gif(self) -> None:
        start = self.start_spin.value()
        duration = max(self.end_spin.value() - start, 0.1)
        destination = self.output_path(".gif")
        self.run_operation(
            lambda: gif.gif_from_video(
                self.media_file.path,
                destination,
                start=start,
                duration=duration,
                fps=self.gif_fps.value(),
                width=self.gif_width.value(),
            ),
            "Saved GIF:",
        )
