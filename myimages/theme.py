"""Visual theme: colour schemes, Qt palette, stylesheet and the app icon.

The look intentionally mirrors the sibling *myPhotos* project — a flat, dark,
accented interface — while adding a light scheme. Colours live in a single
:class:`ColourScheme` so the palette, the stylesheet and the painted icons all
stay in sync.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPalette,
    QPixmap,
)


@dataclass(frozen=True)
class ColourScheme:
    """Every colour the interface uses, named by role."""

    background: str
    panel: str
    panel_alt: str
    border: str
    text: str
    muted: str
    accent: str
    accent_bright: str
    brand_tint: str


DARK = ColourScheme(
    background="#14161a",
    panel="#1d2026",
    panel_alt="#23262d",
    border="#31353d",
    text="#e8eaed",
    muted="#9aa0a8",
    accent="#4f8cff",
    accent_bright="#6ea3ff",
    brand_tint="#9ec5ff",
)

LIGHT = ColourScheme(
    background="#f4f5f7",
    panel="#ffffff",
    panel_alt="#eceef1",
    border="#d4d7dd",
    text="#1c1f24",
    muted="#5d636d",
    accent="#2f6fe4",
    accent_bright="#4f8cff",
    brand_tint="#3d74d6",
)

SCHEMES: dict[str, ColourScheme] = {"dark": DARK, "light": LIGHT}


def scheme_for(theme: str) -> ColourScheme:
    return SCHEMES.get(theme, DARK)


def make_palette(scheme: ColourScheme) -> QPalette:
    group_enum = QPalette.ColorGroup
    role = QPalette.ColorRole
    palette = QPalette()
    for group in (group_enum.Active, group_enum.Inactive, group_enum.Disabled):
        palette.setColor(group, role.Window, QColor(scheme.background))
        palette.setColor(group, role.Base, QColor(scheme.background))
        palette.setColor(group, role.AlternateBase, QColor(scheme.panel))
        palette.setColor(group, role.WindowText, QColor(scheme.text))
        palette.setColor(group, role.Text, QColor(scheme.text))
        palette.setColor(group, role.Button, QColor(scheme.panel_alt))
        palette.setColor(group, role.ButtonText, QColor(scheme.text))
        palette.setColor(group, role.ToolTipBase, QColor(scheme.panel_alt))
        palette.setColor(group, role.ToolTipText, QColor(scheme.text))
        palette.setColor(group, role.Highlight, QColor(scheme.accent))
        palette.setColor(group, role.HighlightedText, QColor("#ffffff"))
        palette.setColor(group, role.PlaceholderText, QColor(scheme.muted))
    return palette


def stylesheet(scheme: ColourScheme) -> str:
    return f"""
QMainWindow, QDialog {{ background: {scheme.background}; }}
QWidget {{ color: {scheme.text}; font-size: 14px; }}

#topbar {{ background: {scheme.panel}; border-bottom: 1px solid {scheme.border}; }}
/* The wordmark is two spans in one label, so MY and IMAGES sit on the same
   baseline with no gap a layout could stretch. Both colours come from the
   scheme: a flat white would vanish on the light theme. */
#brand {{ font-size: 22px; font-weight: 800; letter-spacing: 1px; }}
#sidebar {{ background: {scheme.panel}; border-left: 1px solid {scheme.border}; }}
QLabel#sectionTitle {{ color: {scheme.muted}; font-size: 12px; font-weight: 600; }}
QLabel#muted {{ color: {scheme.muted}; font-size: 12px; }}

QLineEdit {{
  background: {scheme.background}; border: 1px solid {scheme.border};
  border-radius: 8px; padding: 7px 12px;
  selection-background-color: {scheme.accent};
}}
QLineEdit:focus {{ border: 1px solid {scheme.accent}; }}
/* The typed-shape box sits in the row of aspect buttons and is sized to match
   one, so it needs their padding too -- the default eats 24px of a 52px chip
   and elides the placeholder to an ellipsis. */
QLineEdit#aspectField {{ padding: 6px; }}

QPushButton {{
  background: {scheme.panel_alt}; border: 1px solid {scheme.border};
  border-radius: 8px; padding: 7px 16px;
}}
QPushButton:hover {{ border: 1px solid {scheme.accent}; }}
QPushButton#primary {{
  background: {scheme.accent}; color: #ffffff; font-weight: 600; border: none;
}}
QPushButton#primary:hover {{ background: {scheme.accent_bright}; }}
/* Derived from the scheme rather than hard-coded: the dark greys spelled out
   here before painted a near-black chip on a pale dialog in the light theme. */
QPushButton#primary:disabled {{
  background: {scheme.panel_alt}; color: {scheme.muted};
}}

QToolButton {{
  background: {scheme.panel_alt}; border: 1px solid {scheme.border};
  border-radius: 8px; padding: 6px;
}}
QToolButton:hover {{ border: 1px solid {scheme.accent}; }}
QToolButton:checked {{ border: 1px solid {scheme.accent}; background: {scheme.panel}; }}
QToolButton#flat {{ background: transparent; border: none; }}
QToolButton#flat:hover {{ background: {scheme.panel_alt}; }}
QToolButton#overlayStar {{
  background: rgba(0, 0, 0, 0.4); border: none; border-radius: 15px; padding: 0;
}}
QToolButton#overlayStar:hover {{ background: rgba(0, 0, 0, 0.6); }}
/* The viewing controls sit on the photograph, so they carry their own dark
   backing: a button drawn straight onto an image is legible over a dark
   subject and invisible over a bright one. */
QWidget#overlayControls {{
  background: rgba(0, 0, 0, 0.55);
  border-radius: 6px;
}}
/* Same padding and radius as #overlayInfo opposite, so the two float level. */
QWidget#overlayControls QToolButton {{ padding: 2px; border-radius: 4px; }}
QLabel#overlayInfo {{
  background: rgba(0, 0, 0, 0.55); color: #ffffff;
  border-radius: 6px; padding: 2px 8px; font-size: 12px;
}}

QListView, QTreeView, QListWidget {{
  background: {scheme.background}; border: 1px solid {scheme.border};
  border-radius: 8px; outline: none;
}}
QListView::item:selected, QListWidget::item:selected {{
  background: {scheme.accent}; color: #ffffff; border-radius: 6px;
}}

QComboBox, QSpinBox, QDoubleSpinBox {{
  background: {scheme.background}; border: 1px solid {scheme.border};
  border-radius: 6px; padding: 4px 8px; min-width: 80px;
}}
QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
  border: 1px solid {scheme.accent};
}}
QComboBox QAbstractItemView {{
  background: {scheme.panel_alt}; border: 1px solid {scheme.border};
  selection-background-color: {scheme.accent};
}}

QSlider::groove:horizontal {{
  height: 6px; background: {scheme.panel_alt}; border-radius: 3px;
}}
QSlider::handle:horizontal {{
  width: 14px; margin: -5px 0; border-radius: 7px; background: {scheme.accent};
}}
QSlider::sub-page:horizontal {{ background: {scheme.accent}; border-radius: 3px; }}

QProgressBar {{
  background: {scheme.panel_alt}; border: none; border-radius: 4px;
  max-height: 8px; min-height: 8px; text-align: center;
}}
QProgressBar::chunk {{
  border-radius: 4px;
  background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
    stop:0 {scheme.accent}, stop:1 {scheme.accent_bright});
}}

QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{
  background: {scheme.border}; border-radius: 5px; min-height: 30px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
QScrollBar::handle:horizontal {{
  background: {scheme.border}; border-radius: 5px; min-width: 30px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

QTabBar::tab {{
  background: transparent; padding: 8px 14px; color: {scheme.muted};
  border-bottom: 2px solid transparent;
}}
QTabBar::tab:selected {{
  color: {scheme.text}; border-bottom: 2px solid {scheme.accent};
}}
QTabWidget::pane {{ border: none; }}

QToolTip {{
  background: {scheme.panel_alt}; color: {scheme.text};
  border: 1px solid {scheme.border}; padding: 4px 6px;
}}
"""


def paint_app_icon(painter: QPainter) -> None:
    """Draw the camera-on-a-tile app icon onto a 256×256 canvas."""
    tile = QPainterPath()
    tile.addRoundedRect(QRectF(8, 8, 240, 240), 52, 52)
    gradient = QLinearGradient(0, 8, 0, 248)
    gradient.setColorAt(0.0, QColor("#6ea3ff"))
    gradient.setColorAt(1.0, QColor("#3567d6"))
    painter.fillPath(tile, gradient)

    body = QPainterPath()
    body.addRoundedRect(QRectF(40, 92, 176, 116), 22, 22)
    bump = QPainterPath()
    bump.addRoundedRect(QRectF(96, 68, 64, 40), 12, 12)
    painter.fillPath(body.united(bump), QColor("#f4f6f9"))

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#1b2634"))
    painter.drawEllipse(QPointF(128, 150), 42, 42)
    painter.setBrush(QColor("#4f8cff"))
    painter.drawEllipse(QPointF(128, 150), 30, 30)
    painter.setBrush(QColor("#dbe7ff"))
    painter.drawEllipse(QPointF(138, 140), 8, 8)


def write_app_icon(destination: Path, size: int = 256) -> Path | None:
    """Render the application icon to a PNG, or None if it could not be drawn.

    The installer needs a file: an icon theme is a directory of images, and the
    painter that draws every other icon in this application produces a QIcon.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    pixmap = app_icon().pixmap(size, size)
    if pixmap.isNull() or not pixmap.save(str(destination), "PNG"):
        return None
    return destination


def app_icon() -> QIcon:
    icon = QIcon()
    for size in (16, 32, 48, 64, 128, 256):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(size / 256, size / 256)
        paint_app_icon(painter)
        painter.end()
        icon.addPixmap(pixmap)
    return icon
