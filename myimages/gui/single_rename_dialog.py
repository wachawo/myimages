"""Rename one file, without the pattern language of the batch tool.

Right-clicking a single photo and being handed a find-and-replace pattern
builder is a mismatch: the user already knows the name they want and just wants
to type it. The batch tool is still there for a whole selection; this is the
one-file case, which is the common one.

The extension is kept out of the editable text so a rename cannot silently turn
a JPEG into a file the viewer no longer recognises, and the box refuses names
that are empty, contain a path separator, or already exist.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from myimages.gui.dialog_buttons import accept_cancel

ILLEGAL_IN_A_NAME = ("/", "\\", "\0")


def problem_with(stem: str, original: Path) -> str:
    """Why ``stem`` cannot be used, or an empty string when it is fine."""
    cleaned = stem.strip()
    if not cleaned:
        return "The name cannot be empty."
    if any(character in cleaned for character in ILLEGAL_IN_A_NAME):
        return "A file name cannot contain a slash."
    target = original.with_name(cleaned + original.suffix)
    if target == original:
        return ""
    if target.exists():
        return f"{target.name} already exists in this folder."
    return ""


class SingleRenameDialog(QDialog):
    """Ask for a new name for one file."""

    def __init__(self, path: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.original = path
        self.setWindowTitle("Rename")
        self.setMinimumWidth(360)
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel(f"Rename “{path.name}” to:"))
        self.name_edit = QLineEdit(path.stem)
        self.name_edit.setPlaceholderText("New name")
        self.name_edit.selectAll()
        self.name_edit.textChanged.connect(self.check_name)
        layout.addWidget(self.name_edit)

        self.suffix_label = QLabel(f"Keeps the {path.suffix or 'same'} extension.")
        self.suffix_label.setObjectName("muted")
        layout.addWidget(self.suffix_label)

        self.problem_label = QLabel("")
        self.problem_label.setObjectName("muted")
        layout.addWidget(self.problem_label)

        self.buttons = accept_cancel("Rename")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.check_name()

    def check_name(self) -> None:
        """Show why the name will not do, and refuse to accept until it will."""
        problem = problem_with(self.name_edit.text(), self.original)
        self.problem_label.setText(problem)
        self.set_accept_enabled(not problem)

    def set_accept_enabled(self, enabled: bool) -> None:
        from PySide6.QtWidgets import QDialogButtonBox

        button = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        if button is not None:
            button.setEnabled(enabled)

    def new_path(self) -> Path:
        """Where the file should end up, extension preserved."""
        return self.original.with_name(
            self.name_edit.text().strip() + self.original.suffix
        )
