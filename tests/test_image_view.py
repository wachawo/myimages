"""Tests for the zoomable/pannable image viewer (myimages.gui.image_view)."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, QPointF, QSize, Qt
from PySide6.QtGui import QPixmap, QResizeEvent, QWheelEvent

from myimages.gui.image_view import ZOOM_STEP, ImageView


def load_view(qtbot, make_image, size=(400, 300)) -> ImageView:
    """Build an ImageView of a known size showing a real image."""
    view = ImageView()
    qtbot.addWidget(view)
    view.resize(*size)
    path = make_image()
    view.set_pixmap(QPixmap(str(path)))
    return view


def wheel_event(delta_y, modifiers=Qt.KeyboardModifier.NoModifier) -> QWheelEvent:
    """A QWheelEvent with the given vertical angle delta and modifiers."""
    return QWheelEvent(
        QPointF(5, 5),
        QPointF(5, 5),
        QPoint(0, 0),
        QPoint(0, delta_y),
        Qt.MouseButton.NoButton,
        modifiers,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )


def test_new_view_has_no_image(qtbot):
    view = ImageView()
    qtbot.addWidget(view)
    assert view.has_image() is False


def test_set_pixmap_shows_and_fits(qtbot, make_image):
    view = load_view(qtbot, make_image)
    assert view.has_image() is True
    assert view.current_scale() > 0
    assert view.fitting is True


def test_clear_removes_image(qtbot, make_image):
    view = load_view(qtbot, make_image)
    view.clear()
    assert view.has_image() is False


def test_fit_with_no_image_is_a_noop(qtbot):
    view = ImageView()
    qtbot.addWidget(view)
    view.fit()  # must return early without raising
    assert view.has_image() is False


def test_zoom_in_and_out_scale_by_step(qtbot, make_image):
    view = load_view(qtbot, make_image)
    before = view.current_scale()
    view.zoom_in()
    assert view.current_scale() == pytest.approx(before * ZOOM_STEP)
    assert view.fitting is False
    view.zoom_out()
    assert view.current_scale() == pytest.approx(before)


def test_zoom_by_within_limits_changes_scale(qtbot, make_image):
    view = load_view(qtbot, make_image)
    before = view.current_scale()
    view.zoom_by(2.0)
    assert view.current_scale() == pytest.approx(before * 2.0)


def test_zoom_by_beyond_max_is_a_noop(qtbot, make_image):
    view = load_view(qtbot, make_image)
    before = view.current_scale()
    view.zoom_by(1e9)  # target far above MAX_SCALE
    assert view.current_scale() == pytest.approx(before)


def test_zoom_out_never_goes_below_fit(qtbot, make_image):
    view = load_view(qtbot, make_image)
    fit = view.current_scale()
    for step in range(5):
        view.zoom_out()
    assert view.current_scale() == pytest.approx(fit)


def test_zoom_out_after_zoom_in_snaps_back_to_fit(qtbot, make_image):
    view = load_view(qtbot, make_image)
    fit = view.current_scale()
    view.zoom_by(1.1)  # slightly in
    view.zoom_out()  # step of 1/1.25 overshoots below fit -> snaps to fit
    assert view.current_scale() == pytest.approx(fit)


def test_plain_wheel_navigates_previous_and_next(qtbot, make_image):
    view = load_view(qtbot, make_image)
    directions: list[int] = []
    view.navigate.connect(directions.append)
    view.wheelEvent(wheel_event(120))  # up -> previous
    view.wheelEvent(wheel_event(-120))  # down -> next
    assert directions == [-1, 1]


def test_ctrl_wheel_zooms(qtbot, make_image):
    view = load_view(qtbot, make_image)
    before = view.current_scale()
    view.wheelEvent(wheel_event(120, Qt.KeyboardModifier.ControlModifier))
    assert view.current_scale() > before


def test_ctrl_wheel_with_no_image_is_a_noop(qtbot):
    view = ImageView()
    qtbot.addWidget(view)
    view.wheelEvent(wheel_event(120, Qt.KeyboardModifier.ControlModifier))
    assert view.has_image() is False


def test_resize_event_refits_while_fitting(qtbot, make_image):
    view = load_view(qtbot, make_image)
    assert view.fitting is True
    view.resizeEvent(QResizeEvent(QSize(200, 150), QSize(400, 300)))
    assert view.fitting is True
    assert view.current_scale() > 0


def test_resize_event_preserves_manual_zoom(qtbot, make_image):
    view = load_view(qtbot, make_image)
    view.zoom_in()
    assert view.fitting is False
    scale = view.current_scale()
    view.resizeEvent(QResizeEvent(QSize(500, 400), QSize(400, 300)))
    assert view.current_scale() == pytest.approx(scale)
    assert view.fitting is False


def test_show_then_resize_triggers_fit(qtbot, make_image):
    view = load_view(qtbot, make_image)
    view.show()
    view.resize(320, 240)
    qtbot.wait(20)  # let the real resizeEvent be delivered
    assert view.has_image() is True
    assert view.current_scale() > 0
