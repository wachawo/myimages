"""Every icon-only button says what it is, in a few words.

An icon with no label and no tooltip is a guess, so the first test walks the
real windows rather than the source: a button added later is caught by
construction, not by anybody remembering to list it here.

The second test is about length. A tooltip appears under the pointer for a
moment and is read at a glance; a sentence there is read as a paragraph and
skipped. The limit is a ceiling on that, not a style preference.

Qt's own widgets are excluded: the clear button inside a QLineEdit is Qt's, not
ours to caption, and every platform draws it the same way.
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QAbstractButton, QLineEdit

from myimages.config import Settings
from myimages.core.media import build_media_file
from myimages.core.plugins import PluginRegistry
from myimages.gui.image_editor import MODES, ImageEditor
from myimages.gui.main_window import MainWindow
from myimages.gui.task_runner import synchronous_runner

# Long enough for "Lock the box to 16:9", short enough to reject a sentence.
MOST_TOOLTIP_WORDS = 5


def icon_buttons(root) -> list[QAbstractButton]:
    """Every button in ``root`` that shows an icon and no text of its own."""
    return [
        button
        for button in root.findChildren(QAbstractButton)
        if not button.icon().isNull()
        and not button.text().strip()
        and not isinstance(button.parent(), QLineEdit)
    ]


@pytest.fixture
def windows(qtbot, make_image):
    """The main window and an editor with every pane's tools built."""
    window = MainWindow(Settings(), PluginRegistry(), runner=synchronous_runner)
    qtbot.addWidget(window)
    editor = ImageEditor(runner=synchronous_runner)
    qtbot.addWidget(editor)
    editor.load(build_media_file(make_image()))
    for mode in MODES:
        editor.show_mode_controls(mode)
    return [window, editor]


def test_every_icon_button_has_a_tooltip(windows):
    missing = [
        f"{type(button).__name__} in {type(button.parent()).__name__}"
        for root in windows
        for button in icon_buttons(root)
        if not button.toolTip().strip()
    ]
    assert not missing, f"icon buttons with nothing to read: {missing}"


def test_no_tooltip_is_a_sentence(windows):
    wordy = [
        (button.toolTip(), len(button.toolTip().split()))
        for root in windows
        for button in icon_buttons(root)
        if len(button.toolTip().split()) > MOST_TOOLTIP_WORDS
    ]
    assert not wordy, f"tooltips over {MOST_TOOLTIP_WORDS} words: {wordy}"
