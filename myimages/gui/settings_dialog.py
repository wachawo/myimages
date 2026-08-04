"""Preferences dialog for the options users most often want to change.

It reads the current :class:`~myimages.config.Settings` to pre-fill each control
and returns the edited values as a plain dict, which the main window writes back
and persists. Layout sizes (pane width, window size) are captured live from the
widgets, so they are not duplicated here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from myimages.config import Settings
from myimages.core import desktop
from myimages.gui.dialog_buttons import accept_cancel
from myimages.system import is_linux

THEME_LABELS: tuple[tuple[str, str], ...] = (("dark", "Dark"), ("light", "Light"))


class SettingsDialog(QDialog):
    """Edits the persisted, user-facing preferences."""

    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(400)
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.theme_combo = QComboBox()
        for key, label in THEME_LABELS:
            self.theme_combo.addItem(label, key)
        self.theme_combo.setCurrentIndex(0 if settings.theme != "light" else 1)
        form.addRow("Theme", self.theme_combo)

        self.thumbnail_spin = QSpinBox()
        self.thumbnail_spin.setRange(64, 320)
        self.thumbnail_spin.setSingleStep(16)
        self.thumbnail_spin.setValue(settings.thumbnail_size)
        form.addRow("Thumbnail size", self.thumbnail_spin)

        self.recursive_check = QCheckBox("Scan sub-folders")
        self.recursive_check.setChecked(settings.recursive_scan)
        form.addRow("", self.recursive_check)

        self.watch_check = QCheckBox("Follow changes made outside the app")
        self.watch_check.setChecked(settings.watch_folder)
        self.watch_check.setToolTip(
            "Refresh the list when files are added, deleted or edited elsewhere."
        )
        form.addRow("", self.watch_check)

        self.watch_interval_spin = QSpinBox()
        self.watch_interval_spin.setRange(2, 600)
        self.watch_interval_spin.setValue(settings.watch_interval_seconds)
        self.watch_interval_spin.setSuffix(" s")
        self.watch_interval_spin.setToolTip(
            "How often to re-check the folder. Each check only reads the file "
            "list, never the pictures themselves."
        )
        form.addRow("Check every", self.watch_interval_spin)

        self.verify_check = QCheckBox("Also verify file checksums")
        self.verify_check.setChecked(settings.verify_checksums)
        self.verify_check.setToolTip(
            "Catches files rewritten without changing their size or date. A few "
            "files are hashed per check, so the cost stays spread out."
        )
        form.addRow("", self.verify_check)

        self.gif_fps_spin = QSpinBox()
        self.gif_fps_spin.setRange(1, 60)
        self.gif_fps_spin.setValue(settings.gif_fps)
        form.addRow("GIF frames/second", self.gif_fps_spin)

        self.gif_width_spin = QSpinBox()
        self.gif_width_spin.setRange(80, 1920)
        self.gif_width_spin.setSingleStep(20)
        self.gif_width_spin.setValue(settings.gif_width)
        form.addRow("GIF width", self.gif_width_spin)

        self.pdf_quality_spin = QSpinBox()
        self.pdf_quality_spin.setRange(20, 100)
        self.pdf_quality_spin.setValue(settings.pdf_quality)
        form.addRow("Default PDF quality", self.pdf_quality_spin)

        self.pdf_grayscale_check = QCheckBox("PDF pages black and white by default")
        self.pdf_grayscale_check.setChecked(settings.pdf_grayscale)
        form.addRow("", self.pdf_grayscale_check)

        layout.addLayout(form)
        # Only on Linux. Everywhere else this wrote a .desktop file that could
        # never take effect and then reported success, which is worse than not
        # offering it at all.
        if is_linux():
            layout.addWidget(self.build_desktop_section())
        buttons = accept_cancel("Save Settings")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def build_desktop_section(self) -> QWidget:
        """Buttons that put myImages in the menu and offer it as a file handler.

        These act at once rather than through :meth:`values`, because they change
        the desktop rather than a preference, and the user should see whether it
        worked while the dialog is still open.
        """
        holder = QWidget()
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 8, 0, 0)
        title = QLabel("DESKTOP")
        title.setObjectName("sectionTitle")
        column.addWidget(title)

        row = QHBoxLayout()
        self.shortcut_button = QPushButton()
        self.shortcut_button.clicked.connect(self.toggle_shortcut)
        self.associate_button = QPushButton("Open photos and videos with myImages")
        self.associate_button.setToolTip(
            "Make myImages the default application for the file types it can open."
        )
        self.associate_button.clicked.connect(self.claim_file_types)
        row.addWidget(self.shortcut_button)
        row.addWidget(self.associate_button)
        column.addLayout(row)

        self.desktop_status = QLabel("")
        self.desktop_status.setObjectName("muted")
        self.desktop_status.setWordWrap(True)
        column.addWidget(self.desktop_status)
        self.refresh_desktop_section()
        return holder

    def refresh_desktop_section(self) -> None:
        installed = desktop.is_installed()
        self.shortcut_button.setText(
            "Remove from application menu" if installed else "Add to application menu"
        )
        self.associate_button.setEnabled(True)
        if not installed:
            self.desktop_status.setText("myImages is not in the application menu.")
            return
        claimed = desktop.claimed_types()
        if claimed:
            self.desktop_status.setText(
                f"In the application menu; opens {len(claimed)} file type(s) "
                "by default."
            )
        else:
            self.desktop_status.setText("In the application menu.")

    def toggle_shortcut(self) -> None:
        if desktop.is_installed():
            result = desktop.uninstall()
        else:
            result = desktop.install(
                icon_source=self.write_icon(), mime_types=desktop.SUPPORTED_MIME_TYPES
            )
        self.desktop_status.setText(result.message)
        self.shortcut_button.setText(
            "Remove from application menu"
            if desktop.is_installed()
            else "Add to application menu"
        )

    def claim_file_types(self) -> None:
        if not desktop.is_installed():
            desktop.install(
                icon_source=self.write_icon(), mime_types=desktop.SUPPORTED_MIME_TYPES
            )
        result = desktop.set_as_default()
        self.desktop_status.setText(result.message)
        self.shortcut_button.setText("Remove from application menu")

    def write_icon(self) -> Path | None:
        """Render the app icon to a file the installer can copy."""
        from myimages.paths import data_dir
        from myimages.theme import app_icon

        destination = data_dir() / "myimages-icon.png"
        pixmap = app_icon().pixmap(256, 256)
        if pixmap.isNull() or not pixmap.save(str(destination), "PNG"):
            return None
        return destination

    def values(self) -> dict[str, Any]:
        return {
            "theme": str(self.theme_combo.currentData()),
            "thumbnail_size": self.thumbnail_spin.value(),
            "recursive_scan": self.recursive_check.isChecked(),
            "watch_folder": self.watch_check.isChecked(),
            "watch_interval_seconds": self.watch_interval_spin.value(),
            "verify_checksums": self.verify_check.isChecked(),
            "gif_fps": self.gif_fps_spin.value(),
            "gif_width": self.gif_width_spin.value(),
            "pdf_quality": self.pdf_quality_spin.value(),
            "pdf_grayscale": self.pdf_grayscale_check.isChecked(),
        }
