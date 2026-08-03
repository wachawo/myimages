"""A zoomable, pannable image viewer built on QGraphicsView.

Fitting is the default: the photo always starts scaled to the viewport, and a
window resize re-fits until the user zooms. The mouse wheel zooms around the
cursor and dragging pans, matching what people expect from every other viewer.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QPainter, QPixmap, QResizeEvent, QWheelEvent
from PySide6.QtWidgets import (
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QWidget,
)

ZOOM_STEP = 1.25
MAX_SCALE = 40.0


class ImageView(QGraphicsView):
    """Displays one pixmap with fit-to-window, wheel navigation and zoom.

    The mouse wheel steps to the previous/next file; **Shift**+wheel zooms. Fit
    is the most zoomed-out state — you can never zoom out past the point where
    the whole image is visible.
    """

    navigate = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.scene_object = QGraphicsScene(self)
        self.setScene(self.scene_object)
        self.pixmap_item = QGraphicsPixmapItem()
        self.scene_object.addItem(self.pixmap_item)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform
        )
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.fitting = True
        self.fit_scale = 1.0

    def set_pixmap(self, pixmap: QPixmap) -> None:
        """Show a new pixmap and fit it to the viewport."""
        self.pixmap_item.setPixmap(pixmap)
        self.scene_object.setSceneRect(QRectF(pixmap.rect()))
        self.fit()

    def clear(self) -> None:
        self.pixmap_item.setPixmap(QPixmap())

    def has_image(self) -> bool:
        return not self.pixmap_item.pixmap().isNull()

    def fit(self) -> None:
        """Scale the image so it fits entirely inside the viewport."""
        if not self.has_image():
            return
        self.fitInView(self.pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)
        self.fitting = True
        self.fit_scale = self.current_scale()

    def current_scale(self) -> float:
        return self.transform().m11()

    def zoom_by(self, factor: float) -> None:
        """Zoom, refusing to go below fit (all visible) or above the max."""
        current = self.current_scale()
        target = current * factor
        if target > MAX_SCALE:
            return
        if target < self.fit_scale:
            # Never zoom out past fit; snap back to exactly fit if beyond it.
            if current > self.fit_scale:
                self.fit()
            return
        self.fitting = False
        self.scale(factor, factor)

    def zoom_in(self) -> None:
        self.zoom_by(ZOOM_STEP)

    def zoom_out(self) -> None:
        self.zoom_by(1 / ZOOM_STEP)

    def wheelEvent(self, event: QWheelEvent) -> None:
        stepping_up = event.angleDelta().y() > 0
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            if self.has_image():
                self.zoom_by(ZOOM_STEP if stepping_up else 1 / ZOOM_STEP)
        else:
            self.navigate.emit(-1 if stepping_up else 1)
        event.accept()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if self.fitting:
            self.fit()
