"""The accept/cancel pair every dialog ends with, labelled by what it does.

"OK" tells the user nothing about what is about to happen to their files, and
the four dialogs that used it do four very different things: one renames files
in place, two write a new document, one saves preferences. Naming the action on
the button is the cheapest way to answer the question the user is actually
asking before they press it.
"""

from __future__ import annotations

from PySide6.QtWidgets import QDialogButtonBox


def accept_cancel(action: str) -> QDialogButtonBox:
    """An accept/cancel box whose accept button reads ``action``.

    The standard button is relabelled rather than replaced by a plain
    ``QPushButton``: that keeps it the Return-key default, keeps its platform
    position in the row, and keeps working for callers that look it up by
    ``StandardButton.Ok`` to enable or disable it.
    """
    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    accept = buttons.button(QDialogButtonBox.StandardButton.Ok)
    accept.setText(action)
    accept.setObjectName("primary")  # the stylesheet keys on this name
    # A name given to a widget that already exists is not re-matched against the
    # stylesheet on its own, so without this the accent styling silently does
    # nothing and the accept button looks exactly like Cancel.
    style = accept.style()
    style.unpolish(accept)
    style.polish(accept)
    return buttons
