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
from myimages.gui.crop_canvas import BACKDROPS, CropCanvas
from myimages.gui.task_runner import Runner, threaded_runner
from myimages.imaging import cutout, save_policy, transform, watermark
from myimages.imaging.transform import CropRect

# Interactive edits run against a copy no larger than this. A wand click folds
# the whole edit list into a fresh mask, and doing that at 6000px on every click
# is the difference between a tool that feels immediate and one that stutters.
# Only saving touches the full-resolution image.
PREVIEW_EDGE = 1600

# Tool settings, as [-] value [+] steppers. Ranges are what the tools can
# usefully do rather than what the maths allows: a tolerance above 120 selects
# most photographs in one click.
TOLERANCE_STEP = 8
TOLERANCE_RANGE = (0, 120)
BRUSH_STEPS = (0.005, 0.01, 0.02, 0.04, 0.08, 0.15)
SOFTEN_RANGE = (0, 8)

# One soften step, as a fraction of the image width, so a softened edge looks
# the same on the preview and in the file that gets written.
SOFTEN_PER_STEP = 0.0016

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
        self.mode = "crop"
        self.active_tool: str | None = None
        self.edits: list[cutout.Edit] = []
        self.dabs: list[tuple[float, float, float]] = []
        self.preview_source: Image.Image | None = None
        self.preview_result: Image.Image | None = None
        self.tolerance = 32
        self.brush_index = 2
        self.soften = 0
        self.backdrop_index = 0
        self.build_ui()

    def build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.canvas = CropCanvas()
        self.canvas.selection_changed.connect(self.on_selection_changed)
        self.canvas.point_picked.connect(self.on_point_picked)
        self.canvas.stroke.connect(self.on_stroke)
        layout.addWidget(self.canvas, 1)

        toolbar = QFrame()
        toolbar.setObjectName("banner")
        row = QHBoxLayout(toolbar)
        row.setContentsMargins(8, 6, 8, 6)
        row.setSpacing(6)

        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        self.crop_mode_button = self.mode_chip("Crop", "crop")
        self.cutout_mode_button = self.mode_chip("Cut out", "cutout")
        self.crop_mode_button.setChecked(True)
        row.addWidget(self.crop_mode_button)
        row.addWidget(self.cutout_mode_button)
        row.addSpacing(8)

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

        self.crop_controls: list[QWidget] = [
            self.rotate_left_button,
            self.rotate_right_button,
            self.flip_horizontal_button,
            self.flip_vertical_button,
            *self.aspect_group.buttons(),
            self.crop_button,
            self.clear_button,
            self.watermark_button,
        ]
        self.cutout_controls = self.build_cutout_tools(row)
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
        self.set_mode("crop")

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

    def mode_chip(self, label: str, mode: str) -> QToolButton:
        """A checkable chip that switches the pane between crop and cut out.

        The existing checkable-QToolButton idiom, so the accent border the aspect
        buttons already get applies with no new stylesheet.
        """
        button = QToolButton()
        button.setText(label)
        button.setCheckable(True)
        button.setToolTip(f"Switch to {label.lower()}")
        button.clicked.connect(lambda checked, m=mode: self.set_mode(m))
        self.mode_group.addButton(button)
        return button

    def stepper(
        self, tooltip: str, on_change: Callable[[int], None]
    ) -> tuple[QWidget, QLabel]:
        """A ``[-] value [+]`` group, and the label that shows the value.

        Steppers rather than sliders: the tool row already scrolls sideways, and
        a slider inside a scroll area swallows the wheel that the user meant for
        the row.
        """
        holder = QWidget()
        line = QHBoxLayout(holder)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(2)
        down = QToolButton()
        down.setText("−")
        down.setToolTip(f"{tooltip}: less")
        down.clicked.connect(lambda: on_change(-1))
        value = QLabel()
        value.setObjectName("muted")
        value.setToolTip(tooltip)
        value.setMinimumWidth(46)
        value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        up = QToolButton()
        up.setText("+")
        up.setToolTip(f"{tooltip}: more")
        up.clicked.connect(lambda: on_change(1))
        line.addWidget(down)
        line.addWidget(value)
        line.addWidget(up)
        return holder, value

    def build_cutout_tools(self, row: QHBoxLayout) -> list[QWidget]:
        """The cut-out row: three tools, three settings, undo, compare, backdrop.

        Fewer controls than crop mode, deliberately. The row already only fits by
        scrolling, so a mode that added to it would push Save off the edge.
        """
        self.tool_group = QButtonGroup(self)
        self.tool_group.setExclusive(False)
        self.wand_button = self.tool_chip(
            icons.wand, "Magic wand: click a colour to clear its region", "wand"
        )
        self.eraser_button = self.tool_chip(
            icons.eraser, "Eraser: drag to clear", "erase"
        )
        self.restore_button = self.tool_chip(
            icons.restore_brush,
            "Restore brush: drag to paint the picture back",
            "restore",
        )
        row.addWidget(self.wand_button)
        row.addWidget(self.eraser_button)
        row.addWidget(self.restore_button)

        tolerance, self.tolerance_label = self.stepper(
            "How close a colour has to be for the wand to take it",
            self.step_tolerance,
        )
        brush, self.brush_label = self.stepper("Brush size", self.step_brush)
        soften, self.soften_label = self.stepper(
            "Soften the cut edge", self.step_soften
        )
        row.addWidget(tolerance)
        row.addWidget(brush)
        row.addWidget(soften)

        self.undo_button = self.tool_button(
            icons.rotate_left,
            "Undo the last wand click or brush stroke",
            self.undo_edit,
        )
        self.compare_button = self.tool_button(
            icons.compare, "Hold to see the picture before these edits", lambda: None
        )
        self.compare_button.pressed.connect(lambda: self.set_comparing(True))
        self.compare_button.released.connect(lambda: self.set_comparing(False))
        self.backdrop_button = self.tool_button(
            icons.backdrop,
            "What shows through: checker, white, black, magenta",
            self.cycle_backdrop,
        )
        row.addWidget(self.undo_button)
        row.addWidget(self.compare_button)
        row.addWidget(self.backdrop_button)
        return [
            self.wand_button,
            self.eraser_button,
            self.restore_button,
            tolerance,
            brush,
            soften,
            self.undo_button,
            self.compare_button,
            self.backdrop_button,
        ]

    def tool_chip(
        self, icon_factory: Callable[[], QIcon], tooltip: str, tool: str
    ) -> QToolButton:
        """A checkable cut-out tool; pressing the armed one disarms it."""
        button = QToolButton()
        button.setIcon(icon_factory())
        button.setToolTip(tooltip)
        button.setCheckable(True)
        button.clicked.connect(lambda checked, name=tool: self.arm_tool(name))
        self.tool_group.addButton(button)
        self.themed_buttons.append((button, icon_factory))
        return button

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
        self.edits = []
        self.dabs = []
        self.preview_source = None
        self.preview_result = None
        self.set_mode("crop")
        self.canvas.set_pixmap(pixmap_from_pil(self.working_image))
        self.aspect_group.buttons()[0].setChecked(True)
        self.canvas.set_aspect(None)
        self.status_label.setText("")
        # Reopening the editor should start at the left of the tool row, not
        # wherever it was scrolled to when it was last closed.
        self.toolbar_area.horizontalScrollBar().setValue(0)
        return True

    # -- cut-out mode ------------------------------------------------------

    def set_mode(self, mode: str) -> None:
        """Show one mode's controls and hide the other's, resetting the tools."""
        self.mode = mode
        cutout_mode = mode == "cutout"
        for control in self.crop_controls:
            control.setVisible(not cutout_mode)
        for control in self.cutout_controls:
            control.setVisible(cutout_mode)
        (self.cutout_mode_button if cutout_mode else self.crop_mode_button).setChecked(
            True
        )
        self.arm_tool(None)
        if cutout_mode:
            self.build_preview_source()
            self.refresh_cutout()
        else:
            self.canvas.set_interaction("crop")
            if self.working_image is not None:
                self.canvas.set_preview_pixmap(pixmap_from_pil(self.working_image))
        self.refresh_labels()
        self.update_commit_buttons()

    def build_preview_source(self) -> None:
        """Take the working copy down to preview size, once per entry.

        Every edit re-folds the whole list into a fresh mask, so the cost of that
        fold is paid on every click; at full resolution it is what turns an
        immediate tool into a stuttering one.
        """
        if self.working_image is None:
            return
        preview = self.working_image.copy()
        preview.thumbnail((PREVIEW_EDGE, PREVIEW_EDGE), Image.Resampling.LANCZOS)
        self.preview_source = preview

    def arm_tool(self, tool: str | None) -> None:
        """Arm one tool, or disarm the lot; pressing the armed one turns it off."""
        self.active_tool = None if tool == self.active_tool else tool
        for button, name in (
            (self.wand_button, "wand"),
            (self.eraser_button, "erase"),
            (self.restore_button, "restore"),
        ):
            button.setChecked(self.active_tool == name)
        if self.active_tool is None:
            self.canvas.set_interaction("crop" if self.mode == "crop" else "pick")
            return
        self.canvas.set_interaction("pick" if self.active_tool == "wand" else "paint")
        self.canvas.set_brush_radius(BRUSH_STEPS[self.brush_index])

    def soften_pixels(self, image: Image.Image) -> float:
        """The blur radius for this image, so preview and export agree.

        Stored in steps against the width rather than in pixels: a fixed pixel
        radius that looks right on a 1600px preview is a quarter as soft on a
        6000px original, and the exported edge would come out harder than the one
        that was approved.
        """
        return self.soften * SOFTEN_PER_STEP * image.width

    def refresh_cutout(self) -> None:
        """Re-fold the edit list and show the result."""
        if self.preview_source is None:
            return
        self.preview_result = cutout.apply_edits(
            self.preview_source, self.edits, self.soften_pixels(self.preview_source)
        )
        self.canvas.set_preview_pixmap(pixmap_from_pil(self.preview_result))
        self.update_commit_buttons()

    def on_point_picked(self, x: float, y: float) -> None:
        """A wand click: clear the connected patch of similar colour."""
        if self.active_tool != "wand":
            return
        self.edits.append(cutout.RegionPick(x=x, y=y, tolerance=self.tolerance))
        self.refresh_cutout()
        self.report_coverage()

    def on_stroke(self, x: float, y: float, started: bool) -> None:
        """A brush point; ``started`` opens a new stroke rather than extending.

        The gap since the previous point is filled in rather than dabbed once:
        pointer events on a quick drag arrive dozens of pixels apart, which lays
        a row of separate circles instead of a stroke.
        """
        if self.active_tool not in {"erase", "restore"} or self.preview_source is None:
            return
        restore = self.active_tool == "restore"
        dab = (x, y, BRUSH_STEPS[self.brush_index])
        if started or not self.dabs:
            self.dabs = [dab]
        else:
            aspect = self.preview_source.height / self.preview_source.width
            self.dabs.extend(cutout.bridge_dabs(self.dabs[-1], dab, aspect))
        stroke = cutout.BrushStroke(dabs=tuple(self.dabs), restore=restore)
        if started or len(self.dabs) == 1:
            self.edits.append(stroke)
        else:
            self.edits[-1] = stroke
        self.refresh_cutout()

    def report_coverage(self) -> None:
        """Warn when a wand click took nearly the whole picture."""
        if self.preview_result is None:
            return
        taken = cutout.coverage_fraction(self.preview_result)
        if taken > 0.9:
            self.status_label.setText("That took almost everything — lower Tolerance")
        else:
            self.status_label.setText(f"{taken * 100:.0f}% cleared")

    def undo_edit(self) -> None:
        """Drop the last wand click or brush stroke."""
        if not self.edits:
            self.status_label.setText("Nothing to undo")
            return
        self.edits.pop()
        self.dabs = []
        self.refresh_cutout()
        self.status_label.setText("")

    def set_comparing(self, comparing: bool) -> None:
        """While held, show the picture as it was before any of these edits."""
        if self.preview_source is None:
            return
        shown = self.preview_source if comparing else self.preview_result
        if shown is not None:
            self.canvas.set_preview_pixmap(pixmap_from_pil(shown))

    def cycle_backdrop(self) -> None:
        """Step through what shows behind the parts that were taken away."""
        self.backdrop_index = (self.backdrop_index + 1) % len(BACKDROPS)
        self.canvas.set_backdrop(BACKDROPS[self.backdrop_index])

    def step_tolerance(self, delta: int) -> None:
        low, high = TOLERANCE_RANGE
        self.tolerance = min(high, max(low, self.tolerance + delta * TOLERANCE_STEP))
        self.refresh_labels()

    def step_brush(self, delta: int) -> None:
        self.brush_index = min(len(BRUSH_STEPS) - 1, max(0, self.brush_index + delta))
        self.canvas.set_brush_radius(BRUSH_STEPS[self.brush_index])
        self.refresh_labels()

    def step_soften(self, delta: int) -> None:
        low, high = SOFTEN_RANGE
        self.soften = min(high, max(low, self.soften + delta))
        self.refresh_labels()
        self.refresh_cutout()

    def refresh_labels(self) -> None:
        """Show the three settings' current values."""
        self.tolerance_label.setText(str(self.tolerance))
        self.brush_label.setText(f"{BRUSH_STEPS[self.brush_index] * 100:.1f}%")
        self.soften_label.setText(str(self.soften))

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

    def result_image(self) -> Image.Image | None:
        """What Save would write: the working copy, or the folded edit list."""
        if self.working_image is None:
            return None
        if self.mode != "cutout" or not self.edits:
            return self.working_image
        return cutout.apply_edits(
            self.working_image, self.edits, self.soften_pixels(self.working_image)
        )

    def update_commit_buttons(self) -> None:
        """Stop the commit buttons lying about where they will write.

        A cut-out cannot go back over a JPEG, so Save writes a sibling PNG. The
        button has to say so before it is pressed, not afterwards -- it closes
        the editor, so there is no afterwards the user would see.
        """
        plan = self.save_plan(copy=False)
        if plan is not None and plan.retargeted:
            self.save_button.setText(
                f"Save as {plan.destination.suffix.lstrip('.').upper()}"
            )
            self.save_button.setToolTip(
                f"The original cannot hold transparency, so this writes "
                f"{plan.destination.name} and leaves it untouched"
            )
            return
        self.save_button.setText("Save")
        self.save_button.setToolTip("Overwrite the original file with these edits")

    def save_plan(self, copy: bool) -> save_policy.SavePlan | None:
        """Where the working image would be written, or None with nothing open.

        Transparency decides the destination: a cut-out cannot be written back
        over a JPEG, so it goes to a sibling PNG and the original is left where
        it is. An opaque result always keeps the source's format.
        """
        if self.media_file is None or self.working_image is None:
            return None
        # The preview carries the same transparency as the full-resolution
        # result and is already computed, so the button can be relabelled on
        # every stroke without re-folding the original.
        candidate = self.preview_result if self.mode == "cutout" else self.working_image
        transparent = candidate is not None and save_policy.has_transparency(candidate)
        path = Path(self.media_file.path)
        if copy:
            return save_policy.copy_plan(path, transparent)
        return save_policy.overwrite_plan(path, transparent)

    def commit(self, copy: bool) -> None:
        """Write the result and close, staying open if the write failed."""
        image = self.result_image()
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
