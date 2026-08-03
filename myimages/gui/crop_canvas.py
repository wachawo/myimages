"""An interactive crop selector with movable, resizable handles.

Drag on the image to rubber-band a selection (kept to the chosen aspect ratio
when one is locked). Once a selection exists it shows eight square handles: the
four **corner** handles resize it (keeping the locked ratio), the four **edge**
handles — and dragging anywhere inside — **move** it. ``selection_changed``
reports the current rectangle (or ``None``) so the editor can show its pixel
size and enable Crop.

The widget also serves the cut-out tools, under :meth:`CropCanvas.set_interaction`.
It stays ignorant of what those tools mean: ``pick`` reports the point that was
clicked and ``paint`` reports the points a drag passes through, both in image
pixels, and the editor above decides whether that clears a region, erases, or
restores. Keeping the vocabulary out of the widget is what lets the crop
machinery be left entirely alone when the mode is ``crop``.

All the fiddly maths — mapping widget↔image pixels, forcing a rectangle to an
aspect ratio, locating a handle, moving within bounds, sizing the brush ring —
lives in small pure functions so it can be tested without ever synthesising a
mouse event.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QRect, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QWidget

from myimages import icons
from myimages.imaging.transform import CropRect, aspect_crop_rect

CORNER_HANDLES: tuple[str, ...] = ("tl", "tr", "bl", "br")
EDGE_HANDLES: tuple[str, ...] = ("t", "b", "l", "r")
OPPOSITE_CORNER: dict[str, str] = {"tl": "br", "tr": "bl", "bl": "tr", "br": "tl"}
HANDLE_SIZE = 9
HANDLE_TOLERANCE = 8.0

# What the widget does with a press and a drag. ``crop`` is the original
# rubber-band behaviour; the other two feed the cut-out tools.
INTERACTIONS: tuple[str, ...] = ("crop", "pick", "paint")

# The empty space around the image.
BACKDROP_COLOUR = "#101216"

# The checkerboard shown through transparent pixels. Mid greys rather than the
# conventional white and light grey: against this dark surround, white reads as
# part of the picture, which is the one thing the pattern exists to prevent.
CHECKER_LIGHT = "#5a5f66"
CHECKER_DARK = "#464b52"
CHECKER_SQUARE = 8

# The brush ring is stroked twice, dark under light, so it stays legible over a
# blown-out sky and over a black jacket alike.
RING_SHADOW_COLOUR = "#000000"
RING_WIDTH = 1.4


def fit_layout(
    image_width: int, image_height: int, area_width: int, area_height: int
) -> tuple[float, float, float]:
    """Return (scale, offset_x, offset_y) that centres the image in the area."""
    if image_width <= 0 or image_height <= 0:
        return 1.0, 0.0, 0.0
    scale = min(area_width / image_width, area_height / image_height)
    offset_x = (area_width - image_width * scale) / 2
    offset_y = (area_height - image_height * scale) / 2
    return scale, offset_x, offset_y


def constrain_to_aspect(
    anchor: tuple[int, int],
    corner: tuple[int, int],
    aspect: tuple[int, int] | None,
) -> CropRect:
    """Build a rectangle from ``anchor`` toward ``corner``, honouring ``aspect``."""
    anchor_x, anchor_y = anchor
    corner_x, corner_y = corner
    width = abs(corner_x - anchor_x)
    height = abs(corner_y - anchor_y)
    if aspect is not None:
        ratio = aspect[0] / aspect[1]
        if width / max(height, 1) > ratio:
            height = round(width / ratio)
        else:
            width = round(height * ratio)
    width = max(1, width)
    height = max(1, height)
    left = anchor_x if corner_x >= anchor_x else anchor_x - width
    top = anchor_y if corner_y >= anchor_y else anchor_y - height
    return CropRect(left, top, width, height)


def handle_points(rect: CropRect) -> dict[str, tuple[float, float]]:
    """Centre points (image coords) of the eight resize/move handles."""
    left, top = float(rect.left), float(rect.top)
    right, bottom = float(rect.right), float(rect.bottom)
    mid_x, mid_y = left + rect.width / 2, top + rect.height / 2
    return {
        "tl": (left, top),
        "tr": (right, top),
        "bl": (left, bottom),
        "br": (right, bottom),
        "t": (mid_x, top),
        "b": (mid_x, bottom),
        "l": (left, mid_y),
        "r": (right, mid_y),
    }


def opposite_corner(rect: CropRect, handle: str) -> tuple[int, int]:
    """The fixed anchor corner when dragging ``handle`` to resize."""
    point = handle_points(rect)[OPPOSITE_CORNER[handle]]
    return int(round(point[0])), int(round(point[1]))


def move_rect(
    rect: CropRect, dx: int, dy: int, image_width: int, image_height: int
) -> CropRect:
    """Shift ``rect`` by (dx, dy), clamped to stay inside the image."""
    max_left = max(0, image_width - rect.width)
    max_top = max(0, image_height - rect.height)
    left = min(max(rect.left + dx, 0), max_left)
    top = min(max(rect.top + dy, 0), max_top)
    return CropRect(left, top, rect.width, rect.height)


def nearest_handle(
    point: tuple[float, float],
    centers: dict[str, tuple[float, float]],
    tolerance: float,
) -> str | None:
    """Name of the handle whose centre is within ``tolerance`` of ``point``."""
    px, py = point
    for name, (cx, cy) in centers.items():
        if abs(px - cx) <= tolerance and abs(py - cy) <= tolerance:
            return name
    return None


def checker_tile(light: str, dark: str, square: int) -> QPixmap:
    """A two-by-two checker tile, shown through an image's transparent pixels."""
    tile = QPixmap(square * 2, square * 2)
    tile.fill(QColor(light))
    painter = QPainter(tile)
    painter.fillRect(0, 0, square, square, QColor(dark))
    painter.fillRect(square, square, square, square, QColor(dark))
    painter.end()
    return tile


def normalised_point(x: int, y: int, width: int, height: int) -> tuple[float, float]:
    """Turn an image pixel into the fractions the mask engine stores edits in.

    Fractions rather than pixels because that is the unit
    :mod:`myimages.imaging.cutout` takes. Emitting pixels would put a division at
    every call site, and the canvas shows a downscaled preview while the file is
    saved at full resolution -- exactly where two such divisions drift apart.
    """
    return (x / width if width else 0.0, y / height if height else 0.0)


def ring_radius_on_screen(radius: float, image_width: int, scale: float) -> float:
    """Widget-pixel radius of a brush sized as a fraction of the image width.

    Brush sizes are stored against width rather than against the widget so the
    ring shows the size the edit will actually have, at any zoom, and matches
    what :mod:`myimages.imaging.cutout` will paint when the file is saved.
    """
    return max(1.0, radius * image_width * scale)


class CropCanvas(QWidget):
    """Displays an image and captures a crop rectangle in image coordinates."""

    selection_changed = Signal(object)
    point_picked = Signal(float, float)
    stroke = Signal(float, float, bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(320, 240)
        self.pixmap = QPixmap()
        self.aspect: tuple[int, int] | None = None
        self.selection: CropRect | None = None
        self.drag_mode: str | None = None
        self.active_handle: str | None = None
        self.anchor_point: tuple[int, int] = (0, 0)
        self.press_point: tuple[int, int] = (0, 0)
        self.selection_at_press: CropRect | None = None
        self.interaction = "crop"
        self.painting = False
        self.brush_radius = 0.05
        self.hover_point: tuple[float, float] | None = None
        self.checker = checker_tile(CHECKER_LIGHT, CHECKER_DARK, CHECKER_SQUARE)

    # -- state -------------------------------------------------------------

    def set_pixmap(self, pixmap: QPixmap) -> None:
        self.pixmap = pixmap
        self.selection = None
        self.drag_mode = None
        self.emit_selection()
        self.update()

    def set_preview_pixmap(self, pixmap: QPixmap) -> None:
        """Swap the displayed pixels, leaving the selection alone.

        Deliberately not :meth:`set_pixmap`: that clears the selection and emits,
        which is right when a different file is opened and wrong on every frame
        of a live preview, where it would throw away the rectangle the user drew
        each time a brush stroke re-rendered the image.
        """
        self.pixmap = pixmap
        self.update()

    def set_interaction(self, mode: str) -> None:
        """Choose what a press and a drag mean: crop, pick a point, or paint.

        Any drag in progress is abandoned rather than carried across, since a
        half-finished crop resumed as a brush stroke is not a state the handlers
        below are written to survive.
        """
        if mode not in INTERACTIONS:
            raise ValueError(f"unknown interaction {mode!r}")
        self.interaction = mode
        self.drag_mode = None
        self.painting = False
        self.hover_point = None
        # The ring has to follow the cursor with no button held, which costs a
        # move event per pixel; the crop tools never needed that.
        self.setMouseTracking(mode == "paint")
        self.update()

    def set_brush_radius(self, radius: float) -> None:
        """Set the brush size, as a fraction of the image width."""
        self.brush_radius = radius
        self.update()

    def image_size(self) -> tuple[int, int]:
        return self.pixmap.width(), self.pixmap.height()

    def set_aspect(self, aspect: tuple[int, int] | None) -> None:
        """Lock or unlock the aspect ratio; re-centres a locked selection."""
        self.aspect = aspect
        if aspect is not None and not self.pixmap.isNull():
            self.selection = aspect_crop_rect(
                self.pixmap.width(), self.pixmap.height(), aspect[0], aspect[1]
            )
            self.emit_selection()
        self.update()

    def clear_selection(self) -> None:
        self.selection = None
        self.drag_mode = None
        self.emit_selection()
        self.update()

    def selection_rect(self) -> CropRect | None:
        """The current selection, clamped to the image, or None."""
        if self.selection is None or self.pixmap.isNull():
            return None
        return self.selection.clamped(self.pixmap.width(), self.pixmap.height())

    def emit_selection(self) -> None:
        self.selection_changed.emit(self.selection_rect())

    # -- coordinate mapping ------------------------------------------------

    def current_layout(self) -> tuple[float, float, float]:
        return fit_layout(
            self.pixmap.width(), self.pixmap.height(), self.width(), self.height()
        )

    def widget_to_image(self, x: float, y: float) -> tuple[int, int]:
        scale, offset_x, offset_y = self.current_layout()
        if scale <= 0:
            return 0, 0
        image_x = int(round((x - offset_x) / scale))
        image_y = int(round((y - offset_y) / scale))
        image_x = max(0, min(image_x, self.pixmap.width()))
        image_y = max(0, min(image_y, self.pixmap.height()))
        return image_x, image_y

    def image_rect_to_widget(self, rect: CropRect) -> QRect:
        scale, offset_x, offset_y = self.current_layout()
        return QRect(
            int(offset_x + rect.left * scale),
            int(offset_y + rect.top * scale),
            int(rect.width * scale),
            int(rect.height * scale),
        )

    def handle_centers_widget(self, rect: CropRect) -> dict[str, tuple[float, float]]:
        scale, offset_x, offset_y = self.current_layout()
        return {
            name: (offset_x + ix * scale, offset_y + iy * scale)
            for name, (ix, iy) in handle_points(rect).items()
        }

    def handle_at(self, x: float, y: float) -> str | None:
        """Return a handle name, ``"move"`` if inside, else ``None``."""
        rect = self.selection_rect()
        if rect is None:
            return None
        handle = nearest_handle(
            (x, y), self.handle_centers_widget(rect), HANDLE_TOLERANCE
        )
        if handle is not None:
            return handle
        if self.image_rect_to_widget(rect).contains(int(x), int(y)):
            return "move"
        return None

    # -- mouse -------------------------------------------------------------

    def widget_to_normalised(self, x: float, y: float) -> tuple[float, float]:
        """Widget point to the fractions the mask engine's edits are stored in."""
        image_x, image_y = self.widget_to_image(x, y)
        return normalised_point(
            image_x, image_y, self.pixmap.width(), self.pixmap.height()
        )

    def begin_tool(self, x: float, y: float) -> None:
        """Report the wand's point, or open a brush stroke.

        ``selection_changed`` carries image pixels because a crop rectangle is
        naturally measured in them and the editor prints that size. These two
        carry fractions because that is what the mask engine consumes; each
        signal speaks its own consumer's unit rather than forcing one on both.
        """
        point_x, point_y = self.widget_to_normalised(x, y)
        if self.interaction == "pick":
            self.point_picked.emit(point_x, point_y)
            return
        self.painting = True
        self.stroke.emit(point_x, point_y, True)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if self.pixmap.isNull():
            return
        pos = event.position()
        if self.interaction != "crop":
            self.begin_tool(pos.x(), pos.y())
            return
        self.press_point = self.widget_to_image(pos.x(), pos.y())
        handle = self.handle_at(pos.x(), pos.y())
        if handle in CORNER_HANDLES:
            self.drag_mode = "resize"
            self.active_handle = handle
            self.selection_at_press = self.selection_rect()
        elif handle is not None:  # an edge handle or inside the selection
            self.drag_mode = "move"
            self.selection_at_press = self.selection_rect()
        else:
            self.drag_mode = "create"
            self.anchor_point = self.press_point
            self.selection = None
            self.emit_selection()
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pos = event.position()
        if self.interaction != "crop":
            self.hover_point = (pos.x(), pos.y())
            if self.painting:
                point_x, point_y = self.widget_to_normalised(pos.x(), pos.y())
                self.stroke.emit(point_x, point_y, False)
            self.update()
            return
        if self.drag_mode is None:
            return
        point = self.widget_to_image(pos.x(), pos.y())
        if self.drag_mode == "create":
            self.selection = constrain_to_aspect(self.anchor_point, point, self.aspect)
        elif self.drag_mode == "move" and self.selection_at_press is not None:
            self.selection = move_rect(
                self.selection_at_press,
                point[0] - self.press_point[0],
                point[1] - self.press_point[1],
                self.pixmap.width(),
                self.pixmap.height(),
            )
        elif self.drag_mode == "resize" and self.selection_at_press is not None:
            anchor = opposite_corner(self.selection_at_press, str(self.active_handle))
            self.selection = constrain_to_aspect(anchor, point, self.aspect)
        self.emit_selection()
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self.drag_mode = None
        self.active_handle = None
        self.painting = False

    def leaveEvent(self, event: QEvent) -> None:
        """Drop the brush ring once the cursor is no longer over the image."""
        self.hover_point = None
        self.update()

    # -- painting ----------------------------------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(BACKDROP_COLOUR))
        if self.pixmap.isNull():
            painter.end()
            return
        scale, offset_x, offset_y = self.current_layout()
        target = QRect(
            int(offset_x),
            int(offset_y),
            int(self.pixmap.width() * scale),
            int(self.pixmap.height() * scale),
        )
        if self.pixmap.hasAlphaChannel():
            self.paint_checkerboard(painter, target)
        painter.drawPixmap(target, self.pixmap)
        rect = self.selection_rect()
        # The dimming overlay and handles would only confuse a cut-out, and the
        # crop controls are hidden in that mode anyway. The selection itself is
        # kept, so switching back to crop finds the rectangle still there.
        if rect is not None and self.interaction == "crop":
            self.paint_selection(painter, target, rect)
        if self.interaction == "paint" and self.hover_point is not None:
            self.paint_brush_ring(painter, self.hover_point, scale)
        painter.end()

    def paint_checkerboard(self, painter: QPainter, target: QRect) -> None:
        """Tile the checker behind the image so transparency reads as absence.

        The brush origin is pinned to the image rather than left at the widget's
        corner: otherwise the pattern slides underneath the picture as the window
        is resized, which looks like the transparency itself is moving.
        """
        painter.setBrushOrigin(target.topLeft())
        painter.fillRect(target, QBrush(self.checker))
        painter.setBrushOrigin(0, 0)

    def paint_brush_ring(
        self, painter: QPainter, point: tuple[float, float], scale: float
    ) -> None:
        """Outline the brush at its true size, stroked dark under accent.

        Two strokes rather than one: a single-colour ring disappears against a
        blown-out sky or a black jacket, which are exactly the edges a cut-out
        is being fixed on.
        """
        x, y = point
        radius = ring_radius_on_screen(self.brush_radius, self.pixmap.width(), scale)
        circle = QRectF(x - radius, y - radius, radius * 2, radius * 2)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(RING_SHADOW_COLOUR), RING_WIDTH + 1.6))
        painter.drawEllipse(circle)
        painter.setPen(QPen(QColor(icons.ACCENT_COLOUR), RING_WIDTH))
        painter.drawEllipse(circle)

    def paint_selection(self, painter: QPainter, target: QRect, rect: CropRect) -> None:
        widget_rect = self.image_rect_to_widget(rect)
        painter.fillRect(target, QColor(0, 0, 0, 120))
        painter.drawPixmap(
            widget_rect,
            self.pixmap,
            QRect(rect.left, rect.top, rect.width, rect.height),
        )
        painter.setPen(QPen(QColor(icons.ACCENT_COLOUR), 2))
        painter.drawRect(widget_rect)
        painter.setPen(QPen(QColor(icons.ACCENT_COLOUR), 1.4))
        for cx, cy in self.handle_centers_widget(rect).values():
            square = QRect(
                int(cx - HANDLE_SIZE / 2),
                int(cy - HANDLE_SIZE / 2),
                HANDLE_SIZE,
                HANDLE_SIZE,
            )
            painter.fillRect(square, QColor("#ffffff"))
            painter.drawRect(square)
