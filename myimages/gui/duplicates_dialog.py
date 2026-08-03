"""Find duplicate and near-duplicate files, then bulk-delete the extras.

Exact duplicates are grouped by content hash; visually similar photos are
grouped by a perceptual hash within an adjustable distance. Each group keeps its
first file unchecked (the one to keep) and pre-checks the rest, so one click
clears the redundant copies. The detection lives in
:mod:`myimages.core.duplicates`.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from myimages.core import deletion, duplicates
from myimages.core.duplicates import DuplicateGroup
from myimages.core.media import MediaFile
from myimages.format_utils import human_readable_size
from myimages.gui.task_runner import Runner, threaded_runner

PATH_ROLE = int(Qt.ItemDataRole.UserRole)


class DuplicatesDialog(QDialog):
    """Scans a file set for duplicates and deletes the checked ones."""

    files_deleted = Signal(list)

    def __init__(
        self,
        files: list[MediaFile],
        parent: QWidget | None = None,
        runner: Runner = threaded_runner,
        delete_function: Callable[[list[str]], list[Path]] = deletion.delete_files,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Find duplicates")
        self.setMinimumSize(620, 480)
        self.files = files
        self.runner = runner
        self.delete_function = delete_function

        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("Similarity distance"))
        self.distance_spin = QSpinBox()
        self.distance_spin.setRange(0, 20)
        self.distance_spin.setValue(5)
        self.distance_spin.setToolTip("0 = identical look; higher = looser match")
        top.addWidget(self.distance_spin)
        self.scan_button = QPushButton("Scan")
        self.scan_button.clicked.connect(self.start_scan)
        top.addWidget(self.scan_button)
        top.addStretch(1)
        layout.addLayout(top)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["File", "Size"])
        self.tree.setColumnWidth(0, 420)
        layout.addWidget(self.tree, 1)

        self.status_label = QLabel("Press Scan to look for duplicates.")
        self.status_label.setObjectName("muted")
        layout.addWidget(self.status_label)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.delete_button = QPushButton("Delete checked")
        self.delete_button.setObjectName("primary")
        self.delete_button.clicked.connect(self.delete_checked)
        buttons.addButton(self.delete_button, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def scan_now(self) -> list[DuplicateGroup]:
        """Compute duplicate groups synchronously (used by tests and the runner)."""
        exact = duplicates.find_exact_duplicates(self.files)
        similar = duplicates.find_similar_images(
            self.files, max_distance=self.distance_spin.value()
        )
        return exact + similar

    def start_scan(self) -> None:
        self.scan_button.setEnabled(False)
        self.status_label.setText("Scanning…")
        self.runner(self.scan_now, self.populate, self.on_scan_failed)

    def on_scan_failed(self, message: str) -> None:
        self.scan_button.setEnabled(True)
        self.status_label.setText(f"Scan failed: {message}")

    def populate(self, groups: list[DuplicateGroup]) -> None:
        self.scan_button.setEnabled(True)
        self.tree.clear()
        total_extras = 0
        for group in groups:
            parent = QTreeWidgetItem(
                self.tree, [f"{group.reason} ({len(group.paths)})"]
            )
            parent.setFirstColumnSpanned(True)
            for position, path in enumerate(group.paths):
                size = (
                    human_readable_size(path.stat().st_size) if path.exists() else "—"
                )
                child = QTreeWidgetItem(parent, [str(path), size])
                child.setData(0, PATH_ROLE, str(path))
                keep_first = position == 0
                child.setCheckState(
                    0,
                    Qt.CheckState.Unchecked if keep_first else Qt.CheckState.Checked,
                )
                if not keep_first:
                    total_extras += 1
            parent.setExpanded(True)
        if groups:
            self.status_label.setText(
                f"{len(groups)} group(s); {total_extras} extra file(s) pre-selected."
            )
        else:
            self.status_label.setText("No duplicates found.")

    def checked_paths(self) -> list[str]:
        result: list[str] = []
        for index in range(self.tree.topLevelItemCount()):
            parent = self.tree.topLevelItem(index)
            if parent is None:
                continue
            for child_index in range(parent.childCount()):
                child = parent.child(child_index)
                if child is not None and child.checkState(0) == Qt.CheckState.Checked:
                    result.append(str(child.data(0, PATH_ROLE)))
        return result

    def delete_checked(self) -> None:
        paths = self.checked_paths()
        if not paths:
            self.status_label.setText("Nothing checked.")
            return
        answer = QMessageBox.question(
            self, "Delete duplicates", f"Delete {len(paths)} file(s)?"
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        removed = self.delete_function(list(paths))
        self.files_deleted.emit([str(path) for path in removed])
        self.status_label.setText(f"Deleted {len(removed)} file(s).")
        self.files = [f for f in self.files if str(f.path) not in set(paths)]
        self.populate(self.scan_now())
