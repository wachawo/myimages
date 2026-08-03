"""Tests for the interactive crop canvas (myimages.gui.crop_canvas).

The geometry is pure-function tested directly; the widget's mouse behaviour is
driven with real ``QMouseEvent`` objects. The canvas maps a 200×120 image into a
400×300 widget, giving scale 2 and offsets (0, 30), so a widget point (wx, wy)
maps to image ((wx)/2, (wy-30)/2).
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent, QPixmap

from myimages.gui import crop_canvas as cc
from myimages.gui.crop_canvas import CropCanvas
from myimages.imaging.transform import CropRect


def make_canvas(qtbot, image=(200, 120), widget=(400, 300)) -> CropCanvas:
    canvas = CropCanvas()
    qtbot.addWidget(canvas)
    canvas.resize(*widget)
    canvas.set_pixmap(QPixmap(*image))
    return canvas


def to_widget(ix: float, iy: float) -> tuple[float, float]:
    return ix * 2, iy * 2 + 30


def send(canvas: CropCanvas, kind: str, x: float, y: float) -> None:
    types = {
        "press": QEvent.Type.MouseButtonPress,
        "move": QEvent.Type.MouseMove,
        "release": QEvent.Type.MouseButtonRelease,
    }
    event = QMouseEvent(
        types[kind],
        QPointF(x, y),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    handlers = {
        "press": canvas.mousePressEvent,
        "move": canvas.mouseMoveEvent,
        "release": canvas.mouseReleaseEvent,
    }
    handlers[kind](event)


# -- pure geometry ---------------------------------------------------------


def test_fit_layout_centres_and_handles_zero():
    scale, ox, oy = cc.fit_layout(200, 120, 400, 300)
    assert (scale, ox, oy) == (2.0, 0.0, 30.0)
    assert cc.fit_layout(0, 0, 100, 100) == (1.0, 0.0, 0.0)


def test_constrain_to_aspect_free_and_locked():
    free = cc.constrain_to_aspect((0, 0), (30, 10), None)
    assert (free.width, free.height) == (30, 10)
    locked = cc.constrain_to_aspect((0, 0), (30, 10), (1, 1))
    assert locked.width == locked.height


def test_constrain_to_aspect_drag_up_left():
    rect = cc.constrain_to_aspect((50, 50), (10, 30), None)
    assert (rect.left, rect.top) == (10, 30)
    assert (rect.width, rect.height) == (40, 20)


def test_constrain_to_aspect_height_dominant():
    # A tall drag with a square lock grows the width to match the height.
    rect = cc.constrain_to_aspect((0, 0), (10, 30), (1, 1))
    assert rect.width == 30 and rect.height == 30


def test_handle_points_positions():
    points = cc.handle_points(CropRect(10, 20, 100, 60))
    assert points["tl"] == (10.0, 20.0)
    assert points["br"] == (110.0, 80.0)
    assert points["t"] == (60.0, 20.0)
    assert points["r"] == (110.0, 50.0)


def test_opposite_corner():
    rect = CropRect(10, 20, 100, 60)
    assert cc.opposite_corner(rect, "br") == (10, 20)
    assert cc.opposite_corner(rect, "tl") == (110, 80)


def test_move_rect_clamps_within_image():
    rect = CropRect(10, 20, 100, 60)
    assert cc.move_rect(rect, -50, 5, 200, 120) == CropRect(0, 25, 100, 60)
    assert cc.move_rect(rect, 500, 500, 200, 120) == CropRect(100, 60, 100, 60)


def test_nearest_handle():
    centers = {"tl": (0.0, 0.0), "br": (100.0, 100.0)}
    assert cc.nearest_handle((2, 1), centers, 8.0) == "tl"
    assert cc.nearest_handle((50, 50), centers, 8.0) is None


# -- widget state ----------------------------------------------------------


def test_set_pixmap_clears_and_emits_none(qtbot):
    canvas = CropCanvas()
    qtbot.addWidget(canvas)
    emitted: list[object] = []
    canvas.selection_changed.connect(emitted.append)
    canvas.set_pixmap(QPixmap(50, 40))
    assert canvas.selection_rect() is None
    assert emitted == [None]


def test_set_aspect_creates_and_emits(qtbot):
    canvas = make_canvas(qtbot)
    emitted: list[object] = []
    canvas.selection_changed.connect(emitted.append)
    canvas.set_aspect((1, 1))
    rect = canvas.selection_rect()
    assert rect is not None and rect.width == rect.height
    assert emitted and emitted[-1] is not None


def test_set_aspect_none_with_no_pixmap_is_safe(qtbot):
    canvas = CropCanvas()
    qtbot.addWidget(canvas)
    canvas.set_aspect((1, 1))  # no pixmap -> no selection created
    assert canvas.selection_rect() is None


def test_clear_selection(qtbot):
    canvas = make_canvas(qtbot)
    canvas.set_aspect((1, 1))
    assert canvas.selection_rect() is not None
    emitted: list[object] = []
    canvas.selection_changed.connect(emitted.append)
    canvas.clear_selection()
    assert canvas.selection_rect() is None
    assert emitted[-1] is None


def test_widget_to_image_and_scale_guard(qtbot):
    canvas = make_canvas(qtbot)
    assert canvas.widget_to_image(*to_widget(50, 30)) == (50, 30)
    canvas.setMinimumSize(0, 0)
    canvas.resize(0, 100)  # zero width -> scale 0 guard
    assert canvas.widget_to_image(10, 10) == (0, 0)


def test_image_size(qtbot):
    canvas = make_canvas(qtbot)
    assert canvas.image_size() == (200, 120)


def test_selection_rect_is_clamped(qtbot):
    canvas = make_canvas(qtbot)
    canvas.selection = CropRect(150, 100, 200, 200)
    rect = canvas.selection_rect()
    assert rect is not None
    assert rect.right <= 200 and rect.bottom <= 120


# -- mouse interaction -----------------------------------------------------


def test_create_selection_via_drag(qtbot):
    canvas = make_canvas(qtbot)
    send(canvas, "press", *to_widget(0, 0))
    send(canvas, "move", *to_widget(100, 60))
    send(canvas, "release", *to_widget(100, 60))
    assert canvas.selection_rect() == CropRect(0, 0, 100, 60)


def test_move_selection_by_dragging_inside(qtbot):
    canvas = make_canvas(qtbot)
    canvas.selection = CropRect(0, 0, 100, 60)
    send(canvas, "press", *to_widget(50, 30))  # inside
    send(canvas, "move", *to_widget(70, 30))  # drag right 20 image px
    send(canvas, "release", *to_widget(70, 30))
    rect = canvas.selection_rect()
    assert rect is not None and rect.left == 20 and rect.width == 100


def test_resize_via_corner_handle(qtbot):
    canvas = make_canvas(qtbot)
    canvas.selection = CropRect(20, 20, 80, 40)
    send(canvas, "press", *to_widget(100, 60))  # bottom-right corner
    send(canvas, "move", *to_widget(60, 40))
    send(canvas, "release", *to_widget(60, 40))
    rect = canvas.selection_rect()
    assert rect is not None
    assert (rect.left, rect.top) == (20, 20)
    assert (rect.width, rect.height) == (40, 20)


def test_edge_handle_moves_selection(qtbot):
    canvas = make_canvas(qtbot)
    canvas.selection = CropRect(20, 20, 80, 40)
    send(canvas, "press", *to_widget(60, 20))  # top-edge handle centre
    send(canvas, "move", *to_widget(70, 20))  # drag right 10 image px
    send(canvas, "release", *to_widget(70, 20))
    rect = canvas.selection_rect()
    assert rect is not None and rect.left == 30 and rect.width == 80


def test_handle_at_variants(qtbot):
    canvas = make_canvas(qtbot)
    assert canvas.handle_at(10, 10) is None  # no selection yet
    canvas.selection = CropRect(20, 20, 80, 40)
    assert canvas.handle_at(*to_widget(20, 20)) == "tl"
    assert canvas.handle_at(*to_widget(60, 40)) == "move"  # inside
    assert canvas.handle_at(*to_widget(190, 110)) is None  # outside


def test_press_without_pixmap_is_a_noop(qtbot):
    canvas = CropCanvas()
    qtbot.addWidget(canvas)
    send(canvas, "press", 10, 10)  # null pixmap -> returns
    assert canvas.selection_rect() is None


def test_move_without_press_is_a_noop(qtbot):
    canvas = make_canvas(qtbot)
    send(canvas, "move", 100, 100)  # drag_mode is None -> returns
    assert canvas.selection_rect() is None


def test_release_resets_drag_mode(qtbot):
    canvas = make_canvas(qtbot)
    send(canvas, "press", *to_widget(0, 0))
    assert canvas.drag_mode == "create"
    send(canvas, "release", *to_widget(0, 0))
    assert canvas.drag_mode is None


# -- painting --------------------------------------------------------------


def test_paint_event_runs_in_all_states(qtbot):
    empty = CropCanvas()
    qtbot.addWidget(empty)
    empty.grab()  # null pixmap branch

    canvas = make_canvas(qtbot)
    canvas.grab()  # image, no selection
    canvas.selection = CropRect(10, 10, 60, 40)
    canvas.grab()  # selection + handles drawn
