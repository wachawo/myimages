"""Tests for the interactive crop canvas (myimages.gui.crop_canvas).

The geometry is pure-function tested directly; the widget's mouse behaviour is
driven with real ``QMouseEvent`` objects. The canvas maps a 200×120 image into a
400×300 widget, giving scale 2 and offsets (0, 30), so a widget point (wx, wy)
maps to image ((wx)/2, (wy-30)/2).
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QImage, QMouseEvent, QPixmap

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


# -- transparency and tool input -------------------------------------------


def transparent_pixmap(width: int = 200, height: int = 120) -> QPixmap:
    """A pixmap that reports an alpha channel, as a cut-out result would."""
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    return QPixmap.fromImage(image)


def test_checker_tile_alternates_its_four_squares(qtbot):
    """Four reads are the whole specification; no widget is involved."""
    tile = cc.checker_tile("#ffffff", "#000000", 4)
    image = tile.toImage()
    assert tile.size().width() == 8 and tile.size().height() == 8
    assert image.pixelColor(1, 1).name() == "#000000"
    assert image.pixelColor(5, 5).name() == "#000000"
    assert image.pixelColor(5, 1).name() == "#ffffff"
    assert image.pixelColor(1, 5).name() == "#ffffff"


def test_ring_radius_scales_with_the_image_and_never_vanishes():
    """Sized against image width, so the ring shows the edit's true size."""
    assert cc.ring_radius_on_screen(0.1, 200, 2.0) == 40.0
    assert cc.ring_radius_on_screen(0.1, 200, 0.5) == 10.0
    # A radius that would round below a pixel still has to be visible.
    assert cc.ring_radius_on_screen(0.0001, 10, 0.1) == 1.0


def test_set_preview_pixmap_keeps_the_selection_that_set_pixmap_clears(qtbot):
    """The two must not converge: a live preview would drop the rectangle."""
    canvas = make_canvas(qtbot)
    canvas.selection = CropRect(10, 10, 40, 30)
    canvas.set_preview_pixmap(QPixmap(200, 120))
    assert canvas.selection_rect() == CropRect(10, 10, 40, 30)

    canvas.set_pixmap(QPixmap(200, 120))
    assert canvas.selection_rect() is None


def test_set_preview_pixmap_stays_quiet(qtbot):
    """It runs on every frame of a preview, so it must not emit each time."""
    canvas = make_canvas(qtbot)
    seen: list[object] = []
    canvas.selection_changed.connect(seen.append)
    canvas.set_preview_pixmap(QPixmap(200, 120))
    assert seen == []


def test_set_interaction_rejects_a_mode_it_does_not_have(qtbot):
    canvas = make_canvas(qtbot)
    with pytest.raises(ValueError):
        canvas.set_interaction("magic")


def test_set_interaction_abandons_a_drag_in_progress(qtbot):
    """A half-drawn crop resumed as a brush stroke is not a survivable state."""
    canvas = make_canvas(qtbot)
    send(canvas, "press", *to_widget(20, 20))
    assert canvas.drag_mode == "create"

    canvas.set_interaction("paint")
    assert canvas.drag_mode is None
    assert not canvas.painting
    assert canvas.hasMouseTracking()

    canvas.set_interaction("crop")
    assert not canvas.hasMouseTracking()


def test_normalised_point_divides_by_the_image_it_came_from():
    """Pure arithmetic, and the reason the wand lands right at any zoom."""
    assert cc.normalised_point(50, 30, 200, 120) == (0.25, 0.25)
    assert cc.normalised_point(0, 0, 200, 120) == (0.0, 0.0)
    # A null pixmap has no size to divide by, and the handlers can still run.
    assert cc.normalised_point(5, 5, 0, 0) == (0.0, 0.0)


def test_pick_mode_reports_the_fraction_of_the_image_that_was_clicked(qtbot):
    """Fractions, not pixels: that is the unit cutout.py's edits are stored in.

    The canvas shows a downscaled preview while the file is saved at full
    resolution, so a pixel emitted here would need dividing by the right size at
    every call site. A fraction means the same thing at either size.
    """
    canvas = make_canvas(qtbot)
    canvas.set_interaction("pick")
    picked: list[tuple[float, float]] = []
    canvas.point_picked.connect(lambda x, y: picked.append((x, y)))

    send(canvas, "press", *to_widget(50, 40))
    assert picked == [(0.25, 1 / 3)]


def test_pick_mode_leaves_the_crop_machinery_alone(qtbot):
    canvas = make_canvas(qtbot)
    canvas.set_interaction("pick")
    send(canvas, "press", *to_widget(20, 20))
    send(canvas, "move", *to_widget(60, 50))
    assert canvas.drag_mode is None
    assert canvas.selection_rect() is None


def test_paint_mode_opens_a_stroke_and_then_continues_it(qtbot):
    """The flag tells the editor where one gesture ends and the next begins."""
    canvas = make_canvas(qtbot)
    canvas.set_interaction("paint")
    points: list[tuple[float, float, bool]] = []
    canvas.stroke.connect(lambda x, y, started: points.append((x, y, started)))

    send(canvas, "press", *to_widget(10, 10))
    send(canvas, "move", *to_widget(30, 20))
    send(canvas, "move", *to_widget(50, 30))
    send(canvas, "release", *to_widget(50, 30))
    send(canvas, "move", *to_widget(70, 40))

    assert [(round(x, 4), round(y, 4), s) for x, y, s in points] == [
        (0.05, 0.0833, True),
        (0.15, 0.1667, False),
        (0.25, 0.25, False),
    ]


def test_paint_mode_tracks_the_cursor_without_a_button_held(qtbot):
    """The ring has to follow the cursor before anything is committed."""
    canvas = make_canvas(qtbot)
    canvas.set_interaction("paint")
    send(canvas, "move", *to_widget(30, 20))
    assert canvas.hover_point == to_widget(30, 20)

    canvas.leaveEvent(QEvent(QEvent.Type.Leave))
    assert canvas.hover_point is None


def test_a_press_on_an_empty_canvas_does_nothing(qtbot):
    canvas = CropCanvas()
    qtbot.addWidget(canvas)
    canvas.set_interaction("pick")
    picked: list[tuple[float, float]] = []
    canvas.point_picked.connect(lambda x, y: picked.append((x, y)))
    send(canvas, "press", 10, 10)
    assert picked == []


def test_the_checkerboard_only_appears_under_a_transparent_image(qtbot):
    """Without it a cut-out is indistinguishable from a very dark subject."""
    canvas = make_canvas(qtbot)
    opaque = canvas.grab().toImage()

    canvas.set_preview_pixmap(transparent_pixmap())
    clear = canvas.grab().toImage()

    assert opaque != clear
    assert clear.pixelColor(4, 34).name() in {cc.CHECKER_LIGHT, cc.CHECKER_DARK}


def test_the_brush_ring_is_drawn_only_while_painting(qtbot):
    canvas = make_canvas(qtbot)
    canvas.set_interaction("paint")
    canvas.set_brush_radius(0.2)
    without_ring = canvas.grab().toImage()

    send(canvas, "move", *to_widget(100, 60))
    with_ring = canvas.grab().toImage()
    assert without_ring != with_ring


def test_the_selection_overlay_is_hidden_outside_crop_mode(qtbot):
    """The rectangle survives the round trip; only its chrome goes away."""
    canvas = make_canvas(qtbot)
    canvas.selection = CropRect(20, 20, 60, 40)
    with_overlay = canvas.grab().toImage()

    canvas.set_interaction("paint")
    without_overlay = canvas.grab().toImage()
    assert with_overlay != without_overlay
    assert canvas.selection_rect() == CropRect(20, 20, 60, 40)

    canvas.set_interaction("crop")
    assert canvas.grab().toImage() == with_overlay
