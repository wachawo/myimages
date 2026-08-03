"""An interactive crop selector with movable, resizable handles.

Drag on the image to rubber-band a selection (kept to the chosen aspect ratio
when one is locked). Once a selection exists it shows eight square handles: the
four **corner** handles resize it (keeping the locked ratio), the four **edge**
handles — and dragging anywhere inside — **move** it. ``selection_changed``
reports the current rectangle (or ``None``) so the editor can show its pixel
size and enable Crop.

All the fiddly maths — mapping widget↔image pixels, forcing a rectangle to an
aspect ratio, locating a handle, moving within bounds — lives in small pure
functions so it can be tested without ever synthesising a mouse event.
"""

from __future__ import annotations

from PySide6.QtCore import QRect, Signal
from PySide6.QtGui import (
    QColor,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QWidget

from myimages.imaging.transform import CropRect, aspect_crop_rect

CORNER_HANDLES: tuple[str, ...] = ("tl", "tr", "bl", "br")
EDGE_HANDLES: tuple[str, ...] = ("t", "b", "l", "r")
OPPOSITE_CORNER: dict[str, str] = {"tl": "br", "tr": "bl", "bl": "tr", "br": "tl"}
HANDLE_SIZE = 9
HANDLE_TOLERANCE = 8.0


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


class CropCanvas(QWidget):
    """Displays an image and captures a crop rectangle in image coordinates."""

    selection_changed = Signal(object)

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

    # -- state -------------------------------------------------------------

    def set_pixmap(self, pixmap: QPixmap) -> None:
        self.pixmap = pixmap
        self.selection = None
        self.drag_mode = None
        self.emit_selection()
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

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if self.pixmap.isNull():
            return
        pos = event.position()
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
        if self.drag_mode is None:
            return
        pos = event.position()
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

    # -- painting ----------------------------------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#101216"))
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
        painter.drawPixmap(target, self.pixmap)
        rect = self.selection_rect()
        if rect is not None:
            self.paint_selection(painter, target, rect)
        painter.end()

    def paint_selection(self, painter: QPainter, target: QRect, rect: CropRect) -> None:
        widget_rect = self.image_rect_to_widget(rect)
        painter.fillRect(target, QColor(0, 0, 0, 120))
        painter.drawPixmap(
            widget_rect,
            self.pixmap,
            QRect(rect.left, rect.top, rect.width, rect.height),
        )
        painter.setPen(QPen(QColor("#4f8cff"), 2))
        painter.drawRect(widget_rect)
        painter.setPen(QPen(QColor("#4f8cff"), 1.4))
        for cx, cy in self.handle_centers_widget(rect).values():
            square = QRect(
                int(cx - HANDLE_SIZE / 2),
                int(cy - HANDLE_SIZE / 2),
                HANDLE_SIZE,
                HANDLE_SIZE,
            )
            painter.fillRect(square, QColor("#ffffff"))
            painter.drawRect(square)
