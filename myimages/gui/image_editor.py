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
from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from myimages import icons
from myimages.core.media import MediaFile
from myimages.gui.crop_canvas import BACKDROPS, CropCanvas
from myimages.gui.dependencies_dialog import DependenciesDialog
from myimages.gui.dialog_buttons import accept_cancel
from myimages.gui.task_runner import Runner, threaded_runner
from myimages.imaging import cutout, save_policy, segment, transform, watermark
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

# The download progress dialog counts in steps rather than bytes: a QProgressDialog
# maximum of 179 million is fine for Qt and useless to read.
MODEL_STEPS = 100

# One soften step, as a fraction of the image width, so a softened edge looks
# the same on the preview and in the file that gets written.
SOFTEN_PER_STEP = 0.0016

# The three panes. Splitting them is what makes each row fit: one row carrying
# every tool wanted 1191 pixels against the 1006 the window gives it.
MODES: tuple[str, ...] = ("edit", "crop", "background")
MODE_LABELS: dict[str, str] = {
    "edit": "Edit",
    "crop": "Crop",
    "background": "Background",
}

# What a press on the canvas means in each pane with no cut-out tool armed.
# Edit has nothing to draw, and leaving it on "crop" gave the user a rubber band
# that did nothing while enabling a Crop button that lives in another pane.
IDLE_INTERACTION: dict[str, str] = {
    "edit": "crop",
    "crop": "crop",
    "background": "crop",
}

# Which interaction each armed cut-out tool wants.
TOOL_INTERACTION: dict[str, str] = {
    "wand": "pick",
    "erase": "paint",
    "restore": "paint",
}

# Enough for a typed shape like 0.7667 without crowding the buttons beside it.
ASPECT_FIELD_WIDTH = 64

# A ceiling on a typed size. Past this the resize is a mistake rather than an
# intention, and Pillow would spend a long time proving it.
MAXIMUM_EDGE = 30000

# How much bigger a resize has to get before the interface points out that
# enlarging invents pixels. Under this it is a rounding change nobody needs
# warning about; over it the softness is visible.
UPSCALE_NOTICE = 1.5


def parse_aspect(text: str) -> tuple[int, int] | None:
    """Read a shape written as ``3:2``, ``3/2`` or ``0.7667``.

    Returns a pair the crop lock can take, or None when the text is not a shape.
    A decimal becomes a pair by scaling: the canvas wants integers, and four
    decimal places is finer than a crop box drawn by hand can express.
    """
    cleaned = text.replace("/", ":").strip()
    if ":" in cleaned:
        left, _, right = cleaned.partition(":")
        try:
            width, height = float(left), float(right)
        except ValueError:
            return None
    else:
        try:
            ratio = float(cleaned)
        except ValueError:
            return None
        width, height = ratio, 1.0
    if width <= 0 or height <= 0:
        return None
    scale = 10000
    return (max(1, round(width * scale)), max(1, round(height * scale)))


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
        self.mode = "edit"
        self.active_tool: str | None = None
        self.edits: list[cutout.Edit] = []
        self.dabs: list[tuple[float, float, float]] = []
        self.preview_source: Image.Image | None = None
        self.preview_result: Image.Image | None = None
        self.tolerance = 32
        self.brush_index = 2
        self.soften = 0
        self.backdrop_index = 0
        # Whether the canvas holds the preview-sized copy. Edit and Crop show
        # the same full-size pixmap, so moving between them must not pay for a
        # conversion whose result is already on screen.
        self.showing_preview = False
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
        layout.addWidget(self.build_toolbar())
        layout.addWidget(self.build_readout())
        self.on_selection_changed(None)
        self.show_mode_controls("edit")

    def build_toolbar(self) -> QFrame:
        """Two rows: the panes on top, everything that acts on one underneath.

        Only the middle zone scrolls. Everything used to sit inside one scroll
        area, and at the application's own default window the row wanted 1191
        pixels against 1006 -- so the two controls past the right-hand edge were
        Save as Copy at x=978..1099 and Cancel at x=1105..1183. Measured, not
        guessed: the buttons that commit or abandon the user's work were the
        ones a narrow window hid.

        Pinning them costs a width floor. The editor shares a stack with the
        preview, so its minimum applies even while it is hidden and comes out of
        the file list's share. That is the trade: about 280 pixels of floor for
        three controls that can never again be scrolled out of reach. Giving the
        tabs their own line buys most of it back, since they no longer stand
        between the tools and the width they need.
        """
        frame = QFrame()
        frame.setObjectName("banner")
        column = QVBoxLayout(frame)
        column.setContentsMargins(8, 4, 8, 6)
        column.setSpacing(4)

        # The panes get a line of their own. Sharing one with the tools left the
        # row 39 pixels short in Crop and made the tabs compete for width with
        # the things they switch between.
        column.addWidget(self.build_mode_tabs(), 0, Qt.AlignmentFlag.AlignLeft)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addWidget(self.build_tool_area(), 1)
        row.addWidget(self.build_commit_bar())
        column.addLayout(row)
        return frame

    def build_mode_tabs(self) -> QTabBar:
        """The three panes, named. A tab bar, because that is what this is.

        Text rather than icons, against the rest of the row: these are the only
        labels answering which of three panes the user is in, and the accent
        underline the stylesheet already carries for a tab bar says "you are
        here" far better than a one-pixel border on a chip would.
        """
        tabs = QTabBar()
        tabs.setDrawBase(False)
        for mode in MODES:
            tabs.addTab(MODE_LABELS[mode])
        # Connected after the loop on purpose: adding the first tab emits
        # currentChanged(0), which would run set_mode against half-built state.
        tabs.currentChanged.connect(lambda index: self.set_mode(MODES[index]))
        self.mode_tabs = tabs
        return tabs

    def build_tool_area(self) -> QScrollArea:
        """The per-pane tool strip, in the only zone allowed to scroll.

        Each pane owns a container rather than a list of loose controls, so the
        spacing inside it hides with it. Spacers are layout items and cannot be
        hidden at all, so three panes' worth would otherwise stack up in the row
        whichever pane was showing.
        """
        strip = QWidget()
        line = QHBoxLayout(strip)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(6)
        self.mode_panels: dict[str, QWidget] = {
            "edit": self.build_edit_tools(),
            "crop": self.build_crop_tools(),
            "background": self.build_background_tools(),
        }
        for panel in self.mode_panels.values():
            line.addWidget(panel)
        line.addStretch(1)
        area = QScrollArea()
        area.setWidget(strip)
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Measured while all three panels are still visible, which is why it
        # happens here: show_mode_controls does not run until the end of
        # build_ui. A control hidden before this line is never accounted for and
        # gets its bottom clipped -- that already ate the accent border off the
        # aspect buttons once.
        area.setFixedHeight(
            strip.sizeHint().height() + area.horizontalScrollBar().sizeHint().height()
        )
        self.toolbar_area = area
        return area

    def build_commit_bar(self) -> QWidget:
        """Save, Save as Copy and Cancel, where no window width can hide them."""
        holder = QWidget()
        line = QHBoxLayout(holder)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(6)
        self.save_button = QPushButton("Save")
        self.save_button.setObjectName("primary")
        self.save_button.setToolTip("Overwrite the original file with these edits")
        self.save_button.clicked.connect(self.save_over)
        self.copy_button = QPushButton("Save as Copy")
        self.copy_button.setToolTip("Keep the original and write a new file beside it")
        self.copy_button.clicked.connect(self.save_copy)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.cancel)
        for button in (self.save_button, self.copy_button, self.cancel_button):
            line.addWidget(button)
        return holder

    def tool_panel(self, controls: list[QWidget]) -> QWidget:
        """Wrap one pane's controls so they show and hide as a unit."""
        holder = QWidget()
        line = QHBoxLayout(holder)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(6)
        for control in controls:
            line.addWidget(control)
        return holder

    def build_edit_tools(self) -> QWidget:
        """Turn the picture, mirror it, or set its size."""
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
        self.resize_button = self.tool_button(
            icons.resize, "Resize to given dimensions", self.open_resize
        )
        return self.tool_panel(
            [
                self.rotate_left_button,
                self.rotate_right_button,
                self.flip_horizontal_button,
                self.flip_vertical_button,
                self.resize_button,
            ]
        )

    def build_crop_tools(self) -> QWidget:
        """Choose a shape, draw a box, apply it.

        The shapes are buttons rather than a list: a row of them shows at a
        glance which one is on, where a list shows only the one it is showing.
        Pressing the lit one releases the lock, so there is no "Free" entry to
        mean "none of these" -- the buttons are their own off switch.
        """
        self.aspect_group = QButtonGroup(self)
        # Not exclusive: an exclusive group will not let the checked button be
        # unchecked, and releasing the lock by pressing it again is the point.
        self.aspect_group.setExclusive(False)
        self.aspect_buttons: dict[tuple[int, int], QToolButton] = {}
        chips: list[QWidget] = []
        for label, ratio in ASPECTS:
            if ratio is None:
                continue
            button = QToolButton()
            button.setText(label)
            button.setCheckable(True)
            button.setToolTip(f"Lock the box to {label}; press again to release")
            button.clicked.connect(lambda checked, r=ratio: self.toggle_aspect(r))
            self.aspect_group.addButton(button)
            self.aspect_buttons[ratio] = button
            chips.append(button)

        # Print work needs shapes no row of buttons can hold: a KDP cover is
        # 0.7667, which is nobody's camera preset.
        self.aspect_field = QLineEdit()
        self.aspect_field.setPlaceholderText("3:2")
        self.aspect_field.setFixedWidth(ASPECT_FIELD_WIDTH)
        self.aspect_field.setToolTip("Or type a shape, like 3:2 or 0.7667")
        self.aspect_field.editingFinished.connect(self.on_aspect_typed)

        self.crop_button = self.tool_button(icons.crop, "Apply crop", self.apply_crop)
        self.clear_button = self.tool_button(
            icons.clear_selection,
            "Clear the selection to draw a new one",
            self.canvas.clear_selection,
        )
        return self.tool_panel(
            [*chips, self.aspect_field, self.crop_button, self.clear_button]
        )

    def build_background_tools(self) -> QWidget:
        """Take the background away: by model, by hand, or the watermark alone."""
        self.subject_button = self.tool_button(
            icons.auto_subject,
            "Find the subject with a model and clear everything else",
            self.remove_background_automatically,
        )
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
        self.watermark_button = self.tool_button(
            icons.watermark,
            "Remove a watermark: inside the selection, or the bottom-right corner",
            self.remove_watermark,
        )
        self.settings_button = self.build_settings_button()
        self.undo_button = self.tool_button(
            icons.undo, "Undo the last wand click or brush stroke", self.undo_edit
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
        return self.tool_panel(
            [
                self.subject_button,
                self.wand_button,
                self.eraser_button,
                self.restore_button,
                self.watermark_button,
                self.settings_button,
                self.undo_button,
                self.compare_button,
                self.backdrop_button,
            ]
        )

    def build_settings_button(self) -> QToolButton:
        """The three cut-out numbers, behind one icon.

        Inline they need 453 pixels and put the row 30 over the window it has to
        fit in; behind a menu the button is 33 whether it carries one or not.
        """
        button = QToolButton()
        button.setIcon(icons.settings())
        button.setToolTip("Tolerance, brush size and edge softening")
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(button)
        panel = QWidget()
        form = QFormLayout(panel)
        form.setContentsMargins(10, 8, 10, 8)
        tolerance, self.tolerance_label = self.stepper(
            "How close a colour has to be for the wand to take it",
            self.step_tolerance,
        )
        brush, self.brush_label = self.stepper("Brush size", self.step_brush)
        soften, self.soften_label = self.stepper(
            "Soften the cut edge", self.step_soften
        )
        form.addRow("Tolerance", tolerance)
        form.addRow("Brush", brush)
        form.addRow("Soften", soften)
        holder = QWidgetAction(menu)
        holder.setDefaultWidget(panel)
        menu.addAction(holder)
        button.setMenu(menu)
        self.themed_buttons.append((button, icons.settings))
        return button

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
        self.show_mode_controls("edit")
        self.canvas.set_interaction("crop")
        self.canvas.set_pixmap(pixmap_from_pil(self.working_image))
        self.update_commit_buttons()
        self.set_aspect_lock(None)
        self.canvas.set_aspect(None)
        self.status_label.setText("")
        # Reopening the editor should start at the left of the tool row, not
        # wherever it was scrolled to when it was last closed.
        self.toolbar_area.horizontalScrollBar().setValue(0)
        return True

    # -- panes -------------------------------------------------------------

    def show_mode_controls(self, mode: str) -> None:
        """Swap which pane's tools are on the row, and disarm everything.

        Widget state only, no repaint: :meth:`load` sets the canvas itself right
        afterwards, and converting a 24-megapixel photograph to a pixmap costs
        about two hundred milliseconds, so doing it twice per file opened is a
        visible pause for nothing.
        """
        if mode not in self.mode_panels:
            raise ValueError(f"unknown mode {mode!r}")
        self.mode = mode
        for name, panel in self.mode_panels.items():
            panel.setVisible(name == mode)
        # Blocked because a programmatic index change re-emits currentChanged,
        # which would call straight back into here.
        self.mode_tabs.blockSignals(True)
        self.mode_tabs.setCurrentIndex(MODES.index(mode))
        self.mode_tabs.blockSignals(False)
        self.arm_tool(None)
        # The selection readout belongs to Crop. Left visible elsewhere it sits
        # there reading "No selection" next to a number about something else.
        self.size_label.setVisible(mode == "crop")
        # A cut-out is invisible outside its own pane but is still what Save
        # writes, so say so rather than letting the button and the canvas
        # disagree in silence.
        if mode != "background" and self.edits:
            self.status_label.setText(
                f"{len(self.edits)} background edit(s) pending — in what Save writes"
            )
        self.refresh_labels()

    def set_mode(self, mode: str) -> None:
        """Switch panes. No picture work is lost: only the view changes."""
        self.show_mode_controls(mode)
        self.refresh_canvas()
        self.update_commit_buttons()

    def refresh_canvas(self) -> None:
        """Show what this pane works on, converting only when it differs.

        Background works on a preview-sized copy so re-folding the edit list on
        every click stays immediate; the other two work on the full-size image,
        because a crop rectangle is counted in its pixels. Edit and Crop
        therefore show the same pixmap, and switching between them must not pay
        two hundred milliseconds for a conversion already on screen.
        """
        if self.working_image is None:
            return
        if self.mode == "background":
            self.build_preview_source()
            self.refresh_cutout()
            self.showing_preview = True
            return
        if self.showing_preview:
            self.canvas.set_preview_pixmap(pixmap_from_pil(self.working_image))
            self.showing_preview = False

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
        """Arm one tool, or disarm the lot; pressing the armed one turns it off.

        The selection goes with the change. Only the idle state draws it, so a
        rectangle left standing while a brush is armed is live and invisible --
        and the watermark tool, the one thing that reads it, sits in the pane
        those brushes belong to.
        """
        self.active_tool = None if tool == self.active_tool else tool
        for button, name in (
            (self.wand_button, "wand"),
            (self.eraser_button, "erase"),
            (self.restore_button, "restore"),
        ):
            button.setChecked(self.active_tool == name)
        self.canvas.clear_selection()
        if self.active_tool is None:
            self.canvas.set_interaction(IDLE_INTERACTION[self.mode])
            return
        self.canvas.set_interaction(TOOL_INTERACTION[self.active_tool])
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

    def remove_background_automatically(self) -> None:
        """Let the model find the subject, fetching what it needs on the way.

        Three things can be missing and each says so plainly rather than leaving
        an inert button: the optional package, the weights, and a working run.
        The result is appended to the edit list rather than replacing the image,
        so Undo steps back through it and the hand tools still refine it.
        """
        if self.preview_source is None or self.busy:
            return
        if not segment.is_available():
            self.offer_dependency()
            return
        if not segment.model_present():
            self.fetch_model()
            return
        self.run_segmentation()

    def offer_dependency(self) -> None:
        """Explain what is missing and open the place that installs it."""
        self.status_label.setText(
            "Automatic removal needs the onnxruntime package — installing it now"
        )
        DependenciesDialog(self, runner=self.runner).exec()
        if segment.is_available():
            self.status_label.setText("Installed. Press the button again.")

    def fetch_model(self) -> None:
        """Download the weights once, then segment with them.

        A progress dialog rather than a status line: this is 179 MB, and a
        silent wait of that length reads as a button that did nothing. The
        dialog carries a cancel because the wait is long enough to regret.
        """
        progress = QProgressDialog(
            "Fetching the model…", "Cancel", 0, MODEL_STEPS, self
        )
        progress.setWindowTitle("Please wait")
        progress.setAutoClose(False)
        progress.show()

        def on_progress(received: int, total: int) -> None:
            progress.setLabelText(
                f"Fetching the model… {received // 1_000_000} of "
                f"{total // 1_000_000} MB"
            )
            progress.setValue(min(MODEL_STEPS, received * MODEL_STEPS // max(total, 1)))

        def work() -> object:
            return segment.download_model(on_progress, progress.wasCanceled)

        def finished(result: object) -> None:
            progress.close()
            self.set_busy(False)
            self.status_label.setText("Model ready")
            self.run_segmentation()

        def failed(message: str) -> None:
            progress.close()
            self.set_busy(False)
            self.status_label.setText(message)

        self.set_busy(True)
        self.runner(work, finished, failed)

    def run_segmentation(self) -> None:
        """Run the model over the preview and add its answer to the edit list."""
        source = self.preview_source
        if source is None:
            return
        self.run_operation(
            lambda: segment.subject_mask(source),
            "Finding the subject…",
            self.on_subject_found,
        )

    def on_subject_found(self, result: object) -> None:
        """Append the model's mask, then report how much it took."""
        if not isinstance(result, Image.Image):
            return
        self.edits.append(cutout.SubjectMask(mask=result))
        self.refresh_cutout()
        self.report_subject()

    def report_coverage(self) -> None:
        """Warn when a wand click took nearly the whole picture."""
        if self.preview_result is None:
            return
        taken = cutout.coverage_fraction(self.preview_result)
        if taken > 0.9:
            self.status_label.setText("That took almost everything — lower Tolerance")
        else:
            self.status_label.setText(f"{taken * 100:.0f}% cleared")

    def report_subject(self) -> None:
        """Say how the model did, without the wand's advice.

        Separate from :meth:`report_coverage` because that one tells the user to
        lower Tolerance, which is the wand's setting and has nothing to do with
        the model: taking almost everything means the model found no subject,
        and the answer is the hand tools rather than a slider.
        """
        if self.preview_result is None:
            return
        taken = cutout.coverage_fraction(self.preview_result)
        if taken > 0.9:
            self.status_label.setText(
                "The model found almost no subject here — try the wand instead"
            )
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

    def toggle_aspect(self, ratio: tuple[int, int]) -> None:
        """Lock the box to a shape, or release it if that shape was already on."""
        already = self.canvas.aspect == ratio
        self.set_aspect_lock(None if already else ratio)

    def set_aspect_lock(self, ratio: tuple[int, int] | None) -> None:
        """Apply a shape and show which button, if any, is holding it."""
        self.canvas.set_aspect(ratio)
        for locked, button in self.aspect_buttons.items():
            button.setChecked(locked == ratio)
        if ratio is None or ratio in self.aspect_buttons:
            self.aspect_field.clear()

    def on_aspect_typed(self) -> None:
        """Lock the box to a shape the user typed, or say it was not one.

        Both spellings are accepted because both are how a shape gets written
        down: "3:2" comes off a camera, "0.7667" off a page specification.
        """
        text = self.aspect_field.text().strip()
        if not text:
            return
        ratio = parse_aspect(text)
        if ratio is None:
            self.status_label.setText(f"{text!r} is not a shape — try 3:2 or 0.7667")
            return
        self.canvas.set_aspect(ratio)
        for button in self.aspect_buttons.values():
            button.setChecked(False)
        self.status_label.setText("")

    def open_resize(self) -> None:
        """Set the picture's size in pixels, stretching or shrinking it."""
        image = self.working_image
        if image is None or self.busy:
            return
        dialog = ResizeDialog(image.width, image.height, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        width, height = dialog.chosen_size()
        if (width, height) == (image.width, image.height):
            return
        self.working_image = transform.scale_image(
            image, width=width, height=height, keep_aspect=False
        )
        self.after_geometry_change()
        self.status_label.setText(f"Resized to {width} × {height}")

    def after_geometry_change(self) -> None:
        """Re-show the picture after its pixel grid changed underneath.

        The selection and the preview copy both counted in the old grid, so both
        are dropped rather than reinterpreted: a rectangle rescaled behind the
        user's back is a box somewhere they did not put it.
        """
        self.preview_source = None
        self.preview_result = None
        self.showing_preview = True
        self.refresh_canvas()
        self.canvas.clear_selection()
        self.update_commit_buttons()

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
        """What Save would write: the working copy, or the folded edit list.

        The edit list decides, not the mode. A mode says which controls are on
        screen; the cut-out a user made is their work either way, and gating on
        the mode meant switching away from it silently threw that work out --
        Save then rewrote the original with the untouched picture.
        """
        if self.working_image is None:
            return None
        if not self.edits:
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
        # every stroke without re-folding the original. Keyed on the edit list
        # rather than the mode, so the button keeps telling the truth after the
        # user switches away from the tools that made it.
        candidate = self.preview_result if self.edits else self.working_image
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


class ResizeDialog(QDialog):
    """Ask for a new pixel size, offering to keep the shape."""

    def __init__(self, width: int, height: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Resize")
        self.source = (width, height)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.width_spin = QSpinBox()
        self.width_spin.setRange(1, MAXIMUM_EDGE)
        self.width_spin.setValue(width)
        self.height_spin = QSpinBox()
        self.height_spin.setRange(1, MAXIMUM_EDGE)
        self.height_spin.setValue(height)
        self.keep_ratio = QCheckBox("Keep the shape")
        self.keep_ratio.setChecked(True)
        form.addRow("Width", self.width_spin)
        form.addRow("Height", self.height_spin)
        form.addRow("", self.keep_ratio)
        layout.addLayout(form)
        self.note = QLabel("")
        self.note.setObjectName("muted")
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        buttons = accept_cancel("Resize")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.width_spin.valueChanged.connect(self.on_width_changed)
        self.height_spin.valueChanged.connect(self.on_height_changed)
        self.refresh_note()

    def chosen_size(self) -> tuple[int, int]:
        """The size the user settled on."""
        return self.width_spin.value(), self.height_spin.value()

    def on_width_changed(self, value: int) -> None:
        """Follow the width with the height while the shape is locked."""
        if self.keep_ratio.isChecked():
            source_width, source_height = self.source
            with QSignalBlocker(self.height_spin):
                self.height_spin.setValue(
                    max(1, round(value * source_height / source_width))
                )
        self.refresh_note()

    def on_height_changed(self, value: int) -> None:
        """Follow the height with the width while the shape is locked."""
        if self.keep_ratio.isChecked():
            source_width, source_height = self.source
            with QSignalBlocker(self.width_spin):
                self.width_spin.setValue(
                    max(1, round(value * source_width / source_height))
                )
        self.refresh_note()

    def refresh_note(self) -> None:
        """Say what the change costs, because enlarging invents pixels.

        A resize can only rearrange the detail already there. Growing a picture
        makes a bigger file that is no sharper, and saying so once is kinder
        than letting someone find out after they have printed it.
        """
        width, height = self.chosen_size()
        source_width, source_height = self.source
        factor = (width * height) / (source_width * source_height)
        if factor > UPSCALE_NOTICE:
            self.note.setText(
                f"{factor:.1f}× the pixels of the original. Enlarging cannot add "
                f"detail that is not there — the result will be softer."
            )
        else:
            self.note.setText(f"From {source_width} × {source_height}")
