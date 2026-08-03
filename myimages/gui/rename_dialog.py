"""Batch-rename dialog driven by a filename mask with a live preview.

Supported tokens are shown in the hint and implemented in
:mod:`myimages.core.rename`: ``{name}`` ``{ext}`` ``{n}`` (``{n:03}`` pads)
``{index}`` ``{date}`` ``{parent}``. The preview updates on every keystroke and
the OK button stays disabled while the pattern is invalid or would collide.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from myimages.core.media import MediaFile
from myimages.core.rename import (
    RenameError,
    RenamePlanItem,
    build_rename_plan,
    find_collisions,
)
from myimages.gui.dialog_buttons import accept_cancel

TOKENS_HINT = "Tokens: {name} {ext} {n} {n:03} {index} {date} {parent}"


class RenameDialog(QDialog):
    """Previews and confirms a mask-based rename of several files."""

    def __init__(self, files: list[MediaFile], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Batch rename")
        self.setMinimumSize(560, 420)
        self.files = files
        self.current_plan: list[RenamePlanItem] = []

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.pattern_edit = QLineEdit("{name}_{n:03}.{ext}")
        self.pattern_edit.textChanged.connect(self.update_preview)
        form.addRow("Pattern", self.pattern_edit)
        self.start_spin = QSpinBox()
        self.start_spin.setRange(0, 100000)
        self.start_spin.setValue(1)
        self.start_spin.valueChanged.connect(self.update_preview)
        form.addRow("Start at", self.start_spin)
        self.step_spin = QSpinBox()
        self.step_spin.setRange(1, 1000)
        self.step_spin.setValue(1)
        self.step_spin.valueChanged.connect(self.update_preview)
        form.addRow("Step", self.step_spin)
        layout.addLayout(form)

        hint = QLabel(TOKENS_HINT)
        hint.setObjectName("muted")
        layout.addWidget(hint)

        self.preview_table = QTableWidget(0, 2)
        self.preview_table.setHorizontalHeaderLabels(["Current name", "New name"])
        self.preview_table.horizontalHeader().setStretchLastSection(True)
        self.preview_table.verticalHeader().setVisible(False)
        layout.addWidget(self.preview_table, 1)

        self.status_label = QLabel("")
        self.status_label.setObjectName("muted")
        layout.addWidget(self.status_label)

        self.buttons = accept_cancel("Rename Files")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.update_preview()

    def update_preview(self) -> None:
        pattern = self.pattern_edit.text()
        try:
            plan = build_rename_plan(
                self.files,
                pattern,
                start=self.start_spin.value(),
                step=self.step_spin.value(),
            )
        except RenameError as error:
            self.current_plan = []
            self.preview_table.setRowCount(0)
            self.status_label.setText(f"Invalid pattern: {error}")
            self.set_ok_enabled(False)
            return

        self.current_plan = plan
        self.preview_table.setRowCount(len(plan))
        for row, item in enumerate(plan):
            self.preview_table.setItem(row, 0, QTableWidgetItem(item.source.name))
            self.preview_table.setItem(row, 1, QTableWidgetItem(item.target.name))

        collisions = find_collisions(plan)
        if collisions:
            self.status_label.setText(
                f"{len(collisions)} name collision(s) — adjust the pattern."
            )
            self.set_ok_enabled(False)
        else:
            self.status_label.setText(f"{len(plan)} file(s) will be renamed.")
            self.set_ok_enabled(bool(plan))

    def set_ok_enabled(self, enabled: bool) -> None:
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(enabled)

    def plan(self) -> list[RenamePlanItem]:
        return self.current_plan
