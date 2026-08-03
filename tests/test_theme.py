"""Tests for :mod:`myimages.theme`.

These exercise the colour-scheme lookup, the Qt palette and stylesheet builders
and the painted application icon. A ``QApplication`` must exist for any painting,
so every test requests the ``qtbot`` fixture from pytest-qt.
"""

from __future__ import annotations

from PySide6.QtGui import QIcon, QPalette

from myimages import theme


def test_scheme_for_known_and_unknown(qtbot):
    assert theme.scheme_for("dark") is theme.DARK
    assert theme.scheme_for("light") is theme.LIGHT
    assert theme.scheme_for("nonsense") is theme.DARK


def test_make_palette_returns_palette(qtbot):
    palette = theme.make_palette(theme.DARK)
    assert isinstance(palette, QPalette)
    role = QPalette.ColorRole
    window = palette.color(QPalette.ColorGroup.Active, role.Window)
    assert window.name() == theme.DARK.background


def test_stylesheet_contains_accent(qtbot):
    css = theme.stylesheet(theme.LIGHT)
    assert isinstance(css, str)
    assert theme.LIGHT.accent in css
    assert theme.LIGHT.background in css


def test_app_icon_is_non_null(qtbot):
    icon = theme.app_icon()
    assert isinstance(icon, QIcon)
    assert not icon.isNull()
    assert icon.availableSizes()
