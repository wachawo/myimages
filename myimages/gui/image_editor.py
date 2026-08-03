"""Inline image editor shown under the main preview (no separate window).

The flow the toolbar supports, left to right: rotate left/right, pick an aspect
ratio (which locks the crop box's proportions so you can only move and resize
it), press **Crop** to apply the current selection to the working image, then
**Save** (overwrite) or **Save as Copy** (write a new file) — both close it —
or **Cancel**. Cropping is iterative: each Crop applies to the running result.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PIL import Image
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from myimages import icons
from myimages.core.media import MediaFile
from myimages.gui.crop_canvas import CropCanvas
from myimages.gui.task_runner import Runner, threaded_runner
from myimages.imaging import save_policy, transform, watermark
from myimages.imaging.transform import CropRect

ASPECTS: tuple[tuple[str, tuple[int, int] | None], ...] = (
    ("Free", None),
    ("1:1", (1, 1)),
    ("3:2", (3, 2)),
    ("2:3", (2, 3)),
    ("4:3", (4, 3)),
    ("3:4", (3, 4)),
    ("16:9", (16, 9)),
    ("9:16", (9, 16)),
)


def pixmap_from_pil(image: Image.Image) -> QPixmap:
    """Convert a Pillow image to a QPixmap (detached from the source buffer)."""
    rgba = image.convert("RGBA")
    qimage = QImage(
        rgba.tobytes("raw", "RGBA"),
        rgba.width,
        rgba.height,
        QImage.Format.Format_RGBA8888,
    )
    return QPixmap.fromImage(qimage.copy())


def copy_destination(path: Path) -> Path:
    """A non-clashing ``name_copy.ext`` path next to ``path``."""
    return save_policy.copy_plan(path, transparent=False).destination


class ImageEditor(QWidget):
    """Crop / rotate an image in place; emits ``closed(changed)`` when done."""

    closed = Signal(bool)

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        runner: Runner = threaded_runner,
    ) -> None:
        super().__init__(parent)
        self.media_file: MediaFile | None = None
        self.working_image: Image.Image | None = None
        self.themed_buttons: list[tuple[QToolButton, Callable[[], QIcon]]] = []
        self.runner = runner
        self.busy = False
        self.build_ui()

    def build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.canvas = CropCanvas()
        self.canvas.selection_changed.connect(self.on_selection_changed)
        layout.addWidget(self.canvas, 1)

        toolbar = QFrame()
        toolbar.setObjectName("banner")
        row = QHBoxLayout(toolbar)
        row.setContentsMargins(8, 6, 8, 6)
        row.setSpacing(6)

        self.rotate_left_button = self.tool_button(
            icons.rotate_left, "Rotate left", lambda: self.rotate(-90)
        )
        self.rotate_right_button = self.tool_button(
            icons.rotate_right, "Rotate right", lambda: self.rotate(90)
        )
        self.flip_horizontal_button = self.tool_button(
            icons.flip_horizontal, "Mirror left to right", lambda: self.flip(True)
        )
        self.flip_vertical_button = self.tool_button(
            icons.flip_vertical, "Mirror top to bottom", lambda: self.flip(False)
        )
        row.addWidget(self.rotate_left_button)
        row.addWidget(self.rotate_right_button)
        row.addWidget(self.flip_horizontal_button)
        row.addWidget(self.flip_vertical_button)
        row.addSpacing(8)

        self.aspect_group = QButtonGroup(self)
        self.aspect_group.setExclusive(True)
        for label, ratio in ASPECTS:
            button = QToolButton()
            button.setText(label)
            button.setCheckable(True)
            button.setToolTip(f"Lock crop to {label}")
            button.clicked.connect(lambda checked, r=ratio: self.set_aspect(r))
            self.aspect_group.addButton(button)
            row.addWidget(button)
        first = self.aspect_group.buttons()[0]
        first.setChecked(True)
        row.addSpacing(8)

        self.crop_button = self.tool_button(icons.crop, "Apply crop", self.apply_crop)
        row.addWidget(self.crop_button)
        self.clear_button = QToolButton()
        self.clear_button.setText("Clear")
        self.clear_button.setToolTip("Clear the selection to draw a new one")
        self.clear_button.clicked.connect(self.canvas.clear_selection)
        row.addWidget(self.clear_button)
        self.watermark_button = self.tool_button(
            icons.watermark,
            "Remove a watermark: inside the selection, or the bottom-right corner",
            self.remove_watermark,
        )
        row.addWidget(self.watermark_button)
        row.addStretch(1)

        self.save_button = QPushButton("Save")
        self.save_button.setObjectName("primary")
        self.save_button.setToolTip("Overwrite the original file with these edits")
        self.save_button.clicked.connect(self.save_over)
        self.copy_button = QPushButton("Save as Copy")
        self.copy_button.setToolTip("Keep the original and write a new file beside it")
        self.copy_button.clicked.connect(self.save_copy)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.cancel)
        row.addWidget(self.save_button)
        row.addWidget(self.copy_button)
        row.addWidget(self.cancel_button)
        layout.addWidget(self.scrolling_toolbar(toolbar))
        layout.addWidget(self.build_readout())
        self.on_selection_changed(None)

    def build_readout(self) -> QWidget:
        """The selection size and the last action's result, always on screen.

        Kept out of the scrolling tool row on purpose: in a narrow window the
        user has to scroll right to reach Remove Watermark, which would carry
        the very message that reports what it did off the other edge -- so the
        button looked like it had done nothing at all.
        """
        strip = QWidget()
        line = QHBoxLayout(strip)
        line.setContentsMargins(8, 0, 8, 0)
        line.setSpacing(12)
        self.size_label = QLabel("No selection")
        self.size_label.setObjectName("muted")
        self.status_label = QLabel("")
        self.status_label.setObjectName("muted")
        line.addWidget(self.size_label)
        line.addWidget(self.status_label)
        line.addStretch(1)
        return strip

    def scrolling_toolbar(self, toolbar: QFrame) -> QScrollArea:
        """Let the tool row scroll sideways instead of setting a width floor.

        Fifteen controls in one non-wrapping row demand about 1100 pixels, and
        because the editor shares a stack with the preview that floor applied
        even while the editor was hidden -- it was the reason a narrow window
        stole space from the file list until only two thumbnails fit per row.
        Scrolling keeps every button reachable; clipping them would not.
        """
        area = QScrollArea()
        area.setWidget(toolbar)
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # The horizontal scrollbar is drawn inside this height, so the row has
        # to be told to make space for it -- otherwise it eats the bottom of
        # every button, including the accent border on the selected aspect.
        area.setFixedHeight(
            toolbar.sizeHint().height() + area.horizontalScrollBar().sizeHint().height()
        )
        self.toolbar_area = area
        return area

    def tool_button(
        self,
        icon_factory: Callable[[], QIcon],
        tooltip: str,
        handler: Callable[..., object],
    ) -> QToolButton:
        button = QToolButton()
        button.setIcon(icon_factory())
        button.setToolTip(tooltip)
        button.clicked.connect(handler)
        self.themed_buttons.append((button, icon_factory))
        return button

    def refresh_icons(self) -> None:
        """Redraw the editor's icons in the current theme's colour."""
        for button, icon_factory in self.themed_buttons:
            button.setIcon(icon_factory())

    # -- editing -----------------------------------------------------------

    def report_failure(self, title: str, error: Exception) -> None:
        """Show a file operation's failure instead of letting it escape a slot.

        An exception raised inside a Qt slot unwinds into the event loop, where
        it is printed to the console and otherwise discarded: the button appears
        to do nothing at all. Every path in and out of the filesystem therefore
        ends here.
        """
        QMessageBox.warning(self, title, f"{type(error).__name__}: {error}")

    def load(self, media_file: MediaFile) -> bool:
        """Open ``media_file`` for editing, resetting any previous state.

        Returns whether the file could be read. A missing codec (``.heic``
        without the optional extra) or an unreadable file is reported and the
        editor is left holding nothing rather than half a state.
        """
        try:
            opened = transform.load_image(media_file.path).convert("RGB")
        except (OSError, ValueError) as error:
            self.media_file = None
            self.working_image = None
            self.report_failure("Cannot open image", error)
            return False
        self.media_file = media_file
        self.working_image = opened
        self.canvas.set_pixmap(pixmap_from_pil(self.working_image))
        self.aspect_group.buttons()[0].setChecked(True)
        self.canvas.set_aspect(None)
        self.status_label.setText("")
        # Reopening the editor should start at the left of the tool row, not
        # wherever it was scrolled to when it was last closed.
        self.toolbar_area.horizontalScrollBar().setValue(0)
        return True

    def on_selection_changed(self, rect: CropRect | None) -> None:
        if rect is not None:
            self.size_label.setText(f"{rect.width} × {rect.height} px")
        else:
            self.size_label.setText("No selection")
        self.crop_button.setEnabled(rect is not None)
        self.clear_button.setEnabled(rect is not None)

    def set_aspect(self, ratio: tuple[int, int] | None) -> None:
        self.canvas.set_aspect(ratio)

    def rotate(self, degrees: int) -> None:
        if self.working_image is None:
            return
        self.working_image = transform.rotate_image(self.working_image, degrees)
        self.canvas.set_pixmap(pixmap_from_pil(self.working_image))
        self.canvas.set_aspect(self.canvas.aspect)

    def flip(self, horizontal: bool) -> None:
        """Mirror the working image, keeping any aspect lock intact."""
        if self.working_image is None:
            return
        self.working_image = transform.flip_image(self.working_image, horizontal)
        self.canvas.set_pixmap(pixmap_from_pil(self.working_image))
        self.canvas.set_aspect(self.canvas.aspect)

    def set_busy(self, busy: bool) -> None:
        """Lock the controls that would race a running operation.

        The tools all read and replace ``working_image``, and Save writes it to
        disk, so a second press while the first is still on a worker thread
        either loses an edit or writes a half-finished one. Rotate and flip stay
        live: they are instant and were never a race.
        """
        self.busy = busy
        for button in (
            self.watermark_button,
            self.crop_button,
            self.save_button,
            self.copy_button,
        ):
            button.setEnabled(not busy)
        if not busy:
            # Crop is only meaningful with a selection; hand that decision back.
            self.on_selection_changed(self.canvas.selection_rect())

    def run_operation(
        self,
        function: Callable[[], object],
        title: str,
        on_finished: Callable[[object], None],
    ) -> None:
        """Run slow work off the UI thread, locking the editor while it runs."""
        progress = QProgressDialog(title, "", 0, 0, self)
        progress.setCancelButton(None)
        progress.setWindowTitle("Please wait")
        progress.show()
        self.set_busy(True)

        def finished(result: object) -> None:
            progress.close()
            self.set_busy(False)
            on_finished(result)

        def failed(message: str) -> None:
            progress.close()
            self.set_busy(False)
            QMessageBox.warning(self, title, message)

        self.runner(function, finished, failed)

    def remove_watermark(self) -> None:
        """Paint out a watermark, in the selection when one is drawn.

        Nothing is written to disk here: the result replaces the working image so
        it can be inspected (and undone with Cancel) before Save or Copy.
        """
        image = self.working_image
        if image is None or self.busy:
            return
        rect = self.canvas.selection_rect()
        box = None if rect is None else (rect.left, rect.top, rect.right, rect.bottom)
        self.run_operation(
            lambda: watermark.remove_watermark(image, box),
            "Removing watermark…",
            self.on_watermark_removed,
        )

    def on_watermark_removed(self, result: object) -> None:
        """Adopt the inpainted image, or say that nothing was found there."""
        if not isinstance(result, watermark.WatermarkResult) or not result.found:
            self.status_label.setText("No watermark found there")
            return
        self.working_image = result.image
        self.canvas.set_pixmap(pixmap_from_pil(self.working_image))
        self.status_label.setText("Watermark removed")

    def apply_crop(self) -> None:
        rect = self.canvas.selection_rect()
        if rect is None or self.working_image is None:
            return
        self.working_image = transform.crop_image(self.working_image, rect)
        self.canvas.set_pixmap(pixmap_from_pil(self.working_image))

    def write_image(self, image: Image.Image, destination: Path) -> bool:
        """Write ``image`` to disk, reporting a failure rather than raising."""
        try:
            transform.save_image(image, destination, quality=95)
        except (OSError, ValueError) as error:
            self.report_failure("Cannot save image", error)
            return False
        return True

    def save_plan(self, copy: bool) -> save_policy.SavePlan | None:
        """Where the working image would be written, or None with nothing open.

        Transparency decides the destination: a cut-out cannot be written back
        over a JPEG, so it goes to a sibling PNG and the original is left where
        it is. An opaque result always keeps the source's format.
        """
        if self.media_file is None or self.working_image is None:
            return None
        transparent = save_policy.has_transparency(self.working_image)
        path = Path(self.media_file.path)
        if copy:
            return save_policy.copy_plan(path, transparent)
        return save_policy.overwrite_plan(path, transparent)

    def commit(self, copy: bool) -> None:
        """Write the result and close, staying open if the write failed."""
        image = self.working_image
        plan = self.save_plan(copy)
        if (
            image is not None
            and plan is not None
            and not self.write_image(image, plan.destination)
        ):
            return
        self.closed.emit(True)

    def save_over(self) -> None:
        self.commit(copy=False)

    def save_copy(self) -> None:
        self.commit(copy=True)

    def cancel(self) -> None:
        self.closed.emit(False)
