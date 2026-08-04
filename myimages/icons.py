"""Crisp vector icons drawn with QPainter, so no image assets are shipped.

Every toolbar control is an icon with a tooltip rather than a labelled button,
keeping the interface compact. Icons are stroked in the current theme's text
colour; call :func:`configure` once after choosing a theme.
"""

from __future__ import annotations

import math
from collections.abc import Callable

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

ICON_COLOUR = "#e8eaed"
ACCENT_COLOUR = "#4f8cff"
CANVAS = 22
MOST_COLUMNS = 4  # the widest the file list offers


def configure(text_colour: str, accent_colour: str) -> None:
    """Set the colours new icons are drawn with (call on theme change)."""
    global ICON_COLOUR, ACCENT_COLOUR
    ICON_COLOUR = text_colour
    ACCENT_COLOUR = accent_colour


def painted(draw: Callable[[QPainter], None], colour: str | None = None) -> QIcon:
    """Build a QIcon by running ``draw`` on a transparent canvas."""
    pixmap = QPixmap(CANVAS, CANVAS)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(colour or ICON_COLOUR), 1.8)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    draw(painter)
    painter.end()
    return QIcon(pixmap)


def star_points(cx: float, cy: float, outer: float, inner: float) -> QPainterPath:
    path = QPainterPath()
    for index in range(10):
        radius = outer if index % 2 == 0 else inner
        angle = math.pi / 2 + index * math.pi / 5
        point = QPointF(cx + radius * math.cos(angle), cy - radius * math.sin(angle))
        if index == 0:
            path.moveTo(point)
        else:
            path.lineTo(point)
    path.closeSubpath()
    return path


def open_folder() -> QIcon:
    """A folder outline: one path, tab above the body on the left.

    Drawn as a single closed path rather than a rectangle with two lines
    attached to it. The rectangle read as a box with a scratch in the corner,
    because the tab has to *break* the top edge to be a tab at all.
    """

    def draw(p: QPainter) -> None:
        path = QPainterPath()
        path.moveTo(3.5, 17.5)  # bottom-left
        path.lineTo(3.5, 5.5)  # up the left edge, past the body
        path.lineTo(9.0, 5.5)  # across the tab
        path.lineTo(11.0, 8.0)  # down-right to where the body starts
        path.lineTo(18.5, 8.0)  # across the top of the body
        path.lineTo(18.5, 17.5)  # down the right edge
        path.closeSubpath()  # back along the bottom
        p.drawPath(path)

    return painted(draw)


def settings() -> QIcon:
    def draw(p: QPainter) -> None:
        p.drawEllipse(QRectF(7.5, 7.5, 7, 7))
        for step in range(8):
            angle = step * math.pi / 4
            dx, dy = math.cos(angle), math.sin(angle)
            p.drawLine(
                QPointF(11 + dx * 5.6, 11 + dy * 5.6),
                QPointF(11 + dx * 7.8, 11 + dy * 7.8),
            )

    return painted(draw)


def previous() -> QIcon:
    def draw(p: QPainter) -> None:
        p.drawLine(13, 4, 7, 11)
        p.drawLine(7, 11, 13, 18)

    return painted(draw)


def next_item() -> QIcon:
    def draw(p: QPainter) -> None:
        p.drawLine(9, 4, 15, 11)
        p.drawLine(15, 11, 9, 18)

    return painted(draw)


def star(filled: bool) -> QIcon:
    def draw(p: QPainter) -> None:
        path = star_points(11, 11.5, 8.5, 3.6)
        if filled:
            p.fillPath(path, QColor(ACCENT_COLOUR))
        p.drawPath(path)

    colour = ACCENT_COLOUR if filled else None
    return painted(draw, colour)


def crop() -> QIcon:
    def draw(p: QPainter) -> None:
        p.drawLine(6, 2, 6, 16)
        p.drawLine(6, 16, 20, 16)
        p.drawLine(2, 6, 16, 6)
        p.drawLine(16, 6, 16, 20)

    return painted(draw)


def edit_image() -> QIcon:
    """A pencil over a picture, for the editor that changes the photo itself.

    Deliberately not the bare pencil of :func:`rename`: that one edits the file's
    name and this one edits its pixels, and two identical pencils in the same
    window would be a coin toss. The pencil is knocked out of the frame beneath
    it so the two shapes stay readable where they cross at 22 pixels.
    """

    def draw(p: QPainter) -> None:
        p.drawRoundedRect(QRectF(2.2, 6.4, 12.4, 11.4), 2, 2)
        p.drawPolyline(
            [QPointF(4.4, 15.0), QPointF(7.2, 11.6), QPointF(9.6, 14.2)]
        )  # a hill, so the frame reads as a photo rather than a window
        p.drawEllipse(QPointF(11.2, 9.8), 1.1, 1.1)

        pencil = pencil_path(QPointF(10.2, 20.2), QPointF(19.6, 10.8), 1.75)
        knockout = QPen(QColor("#000000"), 3.4)
        knockout.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.save()
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        p.setPen(knockout)
        p.drawPath(pencil)
        p.restore()
        p.drawPath(pencil)

    return painted(draw)


def pencil_path(tip: QPointF, butt: QPointF, half_width: float) -> QPainterPath:
    """Outline a pencil lying along ``tip``→``butt``, point first.

    Built from the axis rather than hard-coded corners so the same pencil can be
    re-aimed without recomputing eight coordinates by hand.
    """
    span = QPointF(butt.x() - tip.x(), butt.y() - tip.y())
    length = math.hypot(span.x(), span.y())
    along = QPointF(span.x() / length, span.y() / length)
    across = QPointF(-along.y() * half_width, along.x() * half_width)

    def at(distance: float, side: int) -> QPointF:
        return QPointF(
            tip.x() + along.x() * distance + across.x() * side,
            tip.y() + along.y() * distance + across.y() * side,
        )

    shoulder = min(3.4, length / 3)
    path = QPainterPath(tip)
    path.lineTo(at(shoulder, 1))
    path.lineTo(at(length, 1))
    path.lineTo(at(length, -1))
    path.lineTo(at(shoulder, -1))
    path.closeSubpath()
    path.moveTo(at(shoulder, 1))  # the collar where the wood meets the paint
    path.lineTo(at(shoulder, -1))
    return path


def resize() -> QIcon:
    def draw(p: QPainter) -> None:
        p.drawRoundedRect(QRectF(3, 3, 16, 16), 2, 2)
        p.drawLine(8, 14, 14, 8)
        p.drawLine(14, 8, 11, 8)
        p.drawLine(14, 8, 14, 11)

    return painted(draw)


def rotate_glyph(clockwise: bool) -> Callable[[QPainter], None]:
    """A circular arrow with a tangent-aligned arrowhead at its open end."""

    def draw(p: QPainter) -> None:
        cx, cy, radius = 10.5, 11.5, 6.6
        rect = QRectF(cx - radius, cy - radius, 2 * radius, 2 * radius)
        start, span = (60.0, -250.0) if clockwise else (120.0, 250.0)
        p.drawArc(rect, round(start * 16), round(span * 16))
        end = math.radians(start + span)
        tip = QPointF(cx + radius * math.cos(end), cy - radius * math.sin(end))
        tangent_x, tangent_y = -math.sin(end), -math.cos(end)
        if clockwise:
            tangent_x, tangent_y = -tangent_x, -tangent_y
        length = math.hypot(tangent_x, tangent_y) or 1.0
        tangent_x, tangent_y = tangent_x / length, tangent_y / length
        perp_x, perp_y = -tangent_y, tangent_x
        head = 5.0
        wing = 3.1
        left = QPointF(
            tip.x() - tangent_x * head + perp_x * wing,
            tip.y() - tangent_y * head + perp_y * wing,
        )
        right = QPointF(
            tip.x() - tangent_x * head - perp_x * wing,
            tip.y() - tangent_y * head - perp_y * wing,
        )
        arrowhead = QPainterPath()
        arrowhead.moveTo(tip)
        arrowhead.lineTo(left)
        arrowhead.lineTo(right)
        arrowhead.closeSubpath()
        p.fillPath(arrowhead, QColor(ICON_COLOUR))

    return draw


def rotate_left() -> QIcon:
    return painted(rotate_glyph(clockwise=False))


def rotate_right() -> QIcon:
    return painted(rotate_glyph(clockwise=True))


def flip_horizontal() -> QIcon:
    def draw(p: QPainter) -> None:
        for y in (3, 8, 13, 18):
            p.drawLine(QPointF(11, y), QPointF(11, y + 2.5))
        left = QPainterPath()
        left.moveTo(8, 5)
        left.lineTo(8, 17)
        left.lineTo(2, 11)
        left.closeSubpath()
        p.fillPath(left, QColor(ICON_COLOUR))
        p.drawPolygon([QPointF(14, 5), QPointF(14, 17), QPointF(20, 11)])

    return painted(draw)


def flip_vertical() -> QIcon:
    def draw(p: QPainter) -> None:
        for x in (3, 8, 13, 18):
            p.drawLine(QPointF(x, 11), QPointF(x + 2.5, 11))
        top = QPainterPath()
        top.moveTo(5, 8)
        top.lineTo(17, 8)
        top.lineTo(11, 2)
        top.closeSubpath()
        p.fillPath(top, QColor(ICON_COLOUR))
        p.drawPolygon([QPointF(5, 14), QPointF(17, 14), QPointF(11, 20)])

    return painted(draw)


def watermark() -> QIcon:
    """A sparkle with a stroke through it: the mark this tool takes away."""

    def draw(p: QPainter) -> None:
        sparkle = QPainterPath()
        sparkle.moveTo(11, 3)
        sparkle.quadTo(12, 10, 19, 11)
        sparkle.quadTo(12, 12, 11, 19)
        sparkle.quadTo(10, 12, 3, 11)
        sparkle.quadTo(10, 10, 11, 3)
        p.drawPath(sparkle)
        p.drawLine(4, 18, 18, 4)

    return painted(draw)


def convert() -> QIcon:
    def draw(p: QPainter) -> None:
        p.drawLine(4, 8, 16, 8)
        p.drawLine(16, 8, 13, 5)
        p.drawLine(16, 8, 13, 11)
        p.drawLine(18, 14, 6, 14)
        p.drawLine(6, 14, 9, 11)
        p.drawLine(6, 14, 9, 17)

    return painted(draw)


def grayscale() -> QIcon:
    def draw(p: QPainter) -> None:
        p.drawEllipse(QRectF(3, 3, 16, 16))
        path = QPainterPath()
        path.moveTo(11, 3)
        path.arcTo(QRectF(3, 3, 16, 16), 90, -180)
        path.closeSubpath()
        p.fillPath(path, QColor(ICON_COLOUR))

    return painted(draw)


def pdf() -> QIcon:
    def draw(p: QPainter) -> None:
        p.drawRoundedRect(QRectF(4, 2, 14, 18), 2, 2)
        p.drawLine(7, 8, 15, 8)
        p.drawLine(7, 11, 15, 11)
        p.drawLine(7, 14, 12, 14)

    return painted(draw)


def gif() -> QIcon:
    def draw(p: QPainter) -> None:
        p.drawRoundedRect(QRectF(2, 5, 18, 12), 2, 2)
        p.drawArc(QRectF(5, 8, 5, 6), 40 * 16, 260 * 16)
        p.drawLine(15, 8, 15, 14)

    return painted(draw)


def trim() -> QIcon:
    def draw(p: QPainter) -> None:
        p.drawRoundedRect(QRectF(2, 6, 18, 10), 1.5, 1.5)
        for x in (5, 8, 14, 17):
            p.drawLine(x, 6, x, 16)

    return painted(draw)


def scissors() -> QIcon:
    def draw(p: QPainter) -> None:
        p.drawEllipse(QRectF(3, 12, 5, 5))
        p.drawEllipse(QRectF(3, 5, 5, 5))
        p.drawLine(8, 7, 18, 15)
        p.drawLine(8, 15, 18, 7)

    return painted(draw)


def duplicates() -> QIcon:
    def draw(p: QPainter) -> None:
        p.drawRoundedRect(QRectF(3, 3, 12, 12), 2, 2)
        p.drawRoundedRect(QRectF(8, 8, 11, 11), 2, 2)

    return painted(draw)


def rename() -> QIcon:
    def draw(p: QPainter) -> None:
        p.drawLine(4, 16, 15, 5)
        p.drawLine(15, 5, 18, 8)
        p.drawLine(18, 8, 7, 19)
        p.drawLine(4, 16, 7, 19)

    return painted(draw)


def delete_item() -> QIcon:
    def draw(p: QPainter) -> None:
        p.drawLine(4, 6, 18, 6)
        p.drawLine(9, 6, 9, 4)
        p.drawLine(13, 6, 13, 4)
        p.drawRoundedRect(QRectF(6, 6, 10, 13), 2, 2)
        p.drawLine(9, 9, 9, 16)
        p.drawLine(13, 9, 13, 16)

    return painted(draw)


def zoom_in() -> QIcon:
    def draw(p: QPainter) -> None:
        p.drawEllipse(QRectF(3, 3, 11, 11))
        p.drawLine(13, 13, 19, 19)
        p.drawLine(QPointF(8.5, 5.5), QPointF(8.5, 11.5))
        p.drawLine(QPointF(5.5, 8.5), QPointF(11.5, 8.5))

    return painted(draw)


def zoom_out() -> QIcon:
    def draw(p: QPainter) -> None:
        p.drawEllipse(QRectF(3, 3, 11, 11))
        p.drawLine(13, 13, 19, 19)
        p.drawLine(QPointF(5.5, 8.5), QPointF(11.5, 8.5))

    return painted(draw)


def fit() -> QIcon:
    def draw(p: QPainter) -> None:
        p.drawRoundedRect(QRectF(4, 4, 14, 14), 2, 2)
        p.drawLine(4, 8, 8, 8)
        p.drawLine(4, 8, 4, 4)
        p.drawLine(18, 14, 14, 14)
        p.drawLine(18, 14, 18, 18)

    return painted(draw)


def play() -> QIcon:
    def draw(p: QPainter) -> None:
        path = QPainterPath()
        path.moveTo(7, 5)
        path.lineTo(17, 11)
        path.lineTo(7, 17)
        path.closeSubpath()
        p.fillPath(path, QColor(ICON_COLOUR))

    return painted(draw)


def pause() -> QIcon:
    def draw(p: QPainter) -> None:
        p.fillRect(QRectF(6, 5, 3.5, 12), QColor(ICON_COLOUR))
        p.fillRect(QRectF(12.5, 5, 3.5, 12), QColor(ICON_COLOUR))

    return painted(draw)


def sort_order(descending: bool) -> QIcon:
    def draw(p: QPainter) -> None:
        widths = (12, 9, 6) if not descending else (6, 9, 12)
        for row, width in enumerate(widths):
            y = 6 + row * 5
            p.drawLine(4, y, 4 + width, y)
        arrow_x = 18
        p.drawLine(arrow_x, 5, arrow_x, 17)
        if descending:
            p.drawLine(arrow_x, 17, arrow_x - 2, 14)
            p.drawLine(arrow_x, 17, arrow_x + 2, 14)
        else:
            p.drawLine(arrow_x, 5, arrow_x - 2, 8)
            p.drawLine(arrow_x, 5, arrow_x + 2, 8)

    return painted(draw)


def panel_left() -> QIcon:
    def draw(p: QPainter) -> None:
        p.drawRoundedRect(QRectF(3, 5, 16, 12), 2, 2)
        p.fillRect(QRectF(4, 6, 5, 10), QColor(ICON_COLOUR))
        p.drawLine(10, 5, 10, 17)

    return painted(draw)


def panel_right() -> QIcon:
    def draw(p: QPainter) -> None:
        p.drawRoundedRect(QRectF(3, 5, 16, 12), 2, 2)
        p.fillRect(QRectF(13, 6, 5, 10), QColor(ICON_COLOUR))
        p.drawLine(12, 5, 12, 17)

    return painted(draw)


def grid() -> QIcon:
    def draw(p: QPainter) -> None:
        for x in (3, 12):
            for y in (3, 12):
                p.drawRoundedRect(QRectF(x, y, 7, 7), 1.5, 1.5)

    return painted(draw)


def rows() -> QIcon:
    def draw(p: QPainter) -> None:
        for y in (5, 11, 17):
            p.drawRect(QRectF(3, y - 1, 2.4, 2.4))
            p.drawLine(8, y, 19, y)

    return painted(draw)


def blank(size: int) -> QIcon:
    """Nothing at all, drawn at ``size``.

    Used to hold a star's place in a list so that rows with and without one
    still start their text at the same column.
    """
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    return QIcon(pixmap)


def columns(count: int) -> QIcon:
    """``count`` upright bars, so the button shows the width it will give you.

    The count is clamped rather than trusted: it comes from a settings file a
    user can edit by hand, and a zero would divide by zero inside a live
    ``QPainter``, which takes the whole process down before any window appears.
    """
    bars = max(1, min(count, MOST_COLUMNS))

    def draw(p: QPainter) -> None:
        span, gap = 16.0, 2.0
        width = (span - gap * (bars - 1)) / bars
        for index in range(bars):
            left = 3 + index * (width + gap)
            p.drawRoundedRect(QRectF(left, 4, width, 14), 1.2, 1.2)

    return painted(draw)


def select_mode() -> QIcon:
    def draw(p: QPainter) -> None:
        p.drawEllipse(QRectF(3, 3, 16, 16))
        p.drawLine(7, 11, 10, 14)
        p.drawLine(10, 14, 15, 7)

    return painted(draw)


def table_view() -> QIcon:
    def draw(p: QPainter) -> None:
        p.drawRoundedRect(QRectF(3, 4, 16, 14), 2, 2)
        p.drawLine(3, 8, 19, 8)
        p.drawLine(9, 8, 9, 18)
        p.drawLine(14, 8, 14, 18)

    return painted(draw)


def subfolders() -> QIcon:
    def draw(p: QPainter) -> None:
        p.drawRoundedRect(QRectF(2, 5, 10, 8), 1.5, 1.5)
        p.drawLine(2, 5, 6, 5)
        p.drawRoundedRect(QRectF(9, 9, 11, 9), 1.5, 1.5)
        p.drawLine(9, 9, 13, 9)

    return painted(draw)


def plugin() -> QIcon:
    def draw(p: QPainter) -> None:
        p.drawRoundedRect(QRectF(4, 7, 14, 12), 2, 2)
        p.drawArc(QRectF(8, 3, 6, 8), 0, 180 * 16)

    return painted(draw)


def info() -> QIcon:
    def draw(p: QPainter) -> None:
        p.drawEllipse(QRectF(3, 3, 16, 16))
        p.drawPoint(QPointF(11, 7))
        p.drawLine(11, 10, 11, 15)

    return painted(draw)


def wand() -> QIcon:
    """A wand with a spark: click a colour and its region goes away."""

    def draw(p: QPainter) -> None:
        p.drawLine(4, 18, 14, 8)
        p.drawLine(4, 18, 6, 18)
        spark = QPainterPath()
        spark.moveTo(16, 3)
        spark.quadTo(16.6, 6.4, 20, 7)
        spark.quadTo(16.6, 7.6, 16, 11)
        spark.quadTo(15.4, 7.6, 12, 7)
        spark.quadTo(15.4, 6.4, 16, 3)
        p.drawPath(spark)

    return painted(draw)


def eraser() -> QIcon:
    """A tilted eraser above the line it clears."""

    def draw(p: QPainter) -> None:
        block = QPainterPath()
        block.moveTo(8.5, 3.5)
        block.lineTo(18.5, 8.5)
        block.lineTo(12.5, 15)
        block.lineTo(2.5, 10)
        block.closeSubpath()
        p.drawPath(block)
        p.drawLine(QPointF(3, 18.5), QPointF(19, 18.5))

    return painted(draw)


def restore_brush() -> QIcon:
    """The eraser's opposite: a brush laying the picture back down.

    A brush rather than a second eraser with an arrow. The two tools sit side by
    side and have to be told apart at 22 pixels, where an added arrow is noise.
    """

    def draw(p: QPainter) -> None:
        handle = QPainterPath()
        handle.moveTo(18.5, 3.5)
        handle.lineTo(9, 13)
        p.drawPath(handle)
        p.drawRoundedRect(QRectF(5.4, 11.4, 6.2, 4.6), 1.4, 1.4)
        p.drawLine(QPointF(6, 16), QPointF(4, 19.5))
        p.drawLine(QPointF(11, 16), QPointF(13, 19.5))

    return painted(draw)


def compare() -> QIcon:
    """A frame split down the middle: hold to see the picture as it was."""

    def draw(p: QPainter) -> None:
        p.drawRoundedRect(QRectF(3, 4.5, 16, 13), 2, 2)
        p.drawLine(QPointF(11, 4.5), QPointF(11, 17.5))
        left = QPainterPath()
        left.addRoundedRect(QRectF(3, 4.5, 8, 13), 2, 2)
        p.fillPath(left, QColor(ICON_COLOUR))

    return painted(draw)


def backdrop() -> QIcon:
    """A checkerboard: what sits behind the parts that were taken away."""

    def draw(p: QPainter) -> None:
        p.drawRect(QRectF(3, 3, 16, 16))
        for column in range(4):
            for row in range(4):
                if (column + row) % 2:
                    continue
                p.fillRect(
                    QRectF(3 + column * 4, 3 + row * 4, 4, 4), QColor(ICON_COLOUR)
                )

    return painted(draw)


def auto_subject() -> QIcon:
    """A head and shoulders with a spark: let the model find the subject.

    Deliberately not another wand. The wand beside it is the manual tool, and at
    22 pixels two wands would be a coin toss; a figure says what this one looks
    for rather than how it is driven.
    """

    def draw(p: QPainter) -> None:
        p.drawEllipse(QRectF(7.2, 3.4, 6.6, 6.6))
        shoulders = QPainterPath()
        shoulders.moveTo(3.6, 18.6)
        shoulders.quadTo(4.2, 12.4, 10.5, 12.4)
        shoulders.quadTo(16.8, 12.4, 17.4, 18.6)
        p.drawPath(shoulders)
        spark = QPainterPath()
        spark.moveTo(18.6, 2.6)
        spark.quadTo(19.0, 4.6, 21.0, 5.0)
        spark.quadTo(19.0, 5.4, 18.6, 7.4)
        spark.quadTo(18.2, 5.4, 16.2, 5.0)
        spark.quadTo(18.2, 4.6, 18.6, 2.6)
        p.drawPath(spark)

    return painted(draw)


def clear_selection() -> QIcon:
    """A dashed box with a stroke through it: drop the box and draw again."""

    def draw(p: QPainter) -> None:
        pen = p.pen()
        pen.setDashPattern([2.2, 2.2])
        p.setPen(pen)
        p.drawRect(QRectF(3.5, 5.5, 15, 11))
        pen.setStyle(Qt.PenStyle.SolidLine)
        p.setPen(pen)
        p.drawLine(QPointF(5, 18), QPointF(17, 4))

    return painted(draw)


def undo() -> QIcon:
    """An arrow curving back on itself: take the last step off again."""

    def draw(p: QPainter) -> None:
        path = QPainterPath()
        path.moveTo(4.5, 9.5)
        path.quadTo(12, 3.5, 17.5, 9.5)
        path.quadTo(19.5, 13, 15, 17)
        p.drawPath(path)
        p.drawLine(QPointF(4.5, 9.5), QPointF(4.5, 4.5))
        p.drawLine(QPointF(4.5, 9.5), QPointF(9.5, 9.5))

    return painted(draw)
