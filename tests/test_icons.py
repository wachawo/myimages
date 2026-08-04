"""Tests for :mod:`myimages.icons`.

Every icon factory paints onto a pixmap, so a ``QApplication`` must exist; each
test therefore requests the ``qtbot`` fixture. The factories are called for real
(no mocks) and the resulting :class:`QIcon` objects are asserted to be non-null.
"""

from __future__ import annotations

from PySide6.QtGui import QIcon, QPainterPath

from myimages import icons

SIMPLE_FACTORIES = [
    icons.open_folder,
    icons.settings,
    icons.previous,
    icons.next_item,
    icons.crop,
    icons.edit_image,
    icons.resize,
    icons.rotate_left,
    icons.rotate_right,
    icons.convert,
    icons.grayscale,
    icons.pdf,
    icons.gif,
    icons.trim,
    icons.scissors,
    icons.duplicates,
    icons.rename,
    icons.delete_item,
    icons.zoom_in,
    icons.zoom_out,
    icons.fit,
    icons.play,
    icons.pause,
    icons.subfolders,
    icons.plugin,
    icons.info,
    icons.wand,
    icons.eraser,
    icons.restore_brush,
    icons.compare,
    icons.backdrop,
    icons.auto_subject,
    icons.clear_selection,
    icons.undo,
]


def test_configure_sets_colours(qtbot):
    icons.configure("#123456", "#abcdef")
    assert icons.ICON_COLOUR == "#123456"
    assert icons.ACCENT_COLOUR == "#abcdef"


def test_every_simple_factory_returns_non_null_icon(qtbot):
    for factory in SIMPLE_FACTORIES:
        icon = factory()
        assert isinstance(icon, QIcon), factory.__name__
        assert not icon.isNull(), factory.__name__


def test_star_filled_and_empty(qtbot):
    filled = icons.star(True)
    empty = icons.star(False)
    assert isinstance(filled, QIcon)
    assert isinstance(empty, QIcon)
    assert not filled.isNull()
    assert not empty.isNull()


def test_sort_order_both_directions(qtbot):
    ascending = icons.sort_order(False)
    descending = icons.sort_order(True)
    assert not ascending.isNull()
    assert not descending.isNull()


def test_painted_with_explicit_colour(qtbot):
    icon = icons.painted(lambda p: p.drawLine(2, 2, 20, 20), "#ff0000")
    assert isinstance(icon, QIcon)
    assert not icon.isNull()


def test_star_points_returns_path(qtbot):
    path = icons.star_points(11, 11.5, 8.5, 3.6)
    assert isinstance(path, QPainterPath)
    assert not path.isEmpty()


def test_edit_image_is_not_the_rename_pencil(qtbot):
    """Two identical pencils in one window would be a coin toss for the user."""
    edit = icons.edit_image().pixmap(icons.CANVAS, icons.CANVAS).toImage()
    rename = icons.rename().pixmap(icons.CANVAS, icons.CANVAS).toImage()
    assert edit != rename


def test_the_pencil_points_at_its_tip(qtbot):
    """The narrow end has to be the drawing end, or the pencil reads backwards."""
    from PySide6.QtCore import QPointF

    path = icons.pencil_path(QPointF(4, 18), QPointF(18, 4), 2.0)
    assert path.elementCount() > 4
    start = path.elementAt(0)
    assert (start.x, start.y) == (4, 18)


def test_the_column_icon_survives_a_hand_edited_setting(qtbot):
    """A zero divided by zero inside a live QPainter takes the process down."""
    for count in (0, -3, 99):
        icon = icons.columns(count)
        assert isinstance(icon, QIcon)
        assert not icon.isNull()


def test_the_column_icon_draws_the_count_it_is_given(qtbot):
    drawn = [icons.columns(n).pixmap(22, 22).toImage() for n in (1, 2, 3, 4)]
    for earlier in range(len(drawn)):
        for later in range(earlier + 1, len(drawn)):
            assert drawn[earlier] != drawn[later]  # each count looks different
