"""Show optional features and let the user install the missing Python ones.

Everything beyond the tiny core (PySide6 + Pillow) is optional. This dialog
lists each capability with its status and, for pip-installable ones, an Install
button that runs ``pip`` off the UI thread. System tools such as ffmpeg cannot
be pip-installed, so their row explains how to add them instead.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from myimages.core import dependencies
from myimages.core.dependencies import InstallResult, OptionalDependency
from myimages.gui.task_runner import Runner, threaded_runner


class DependenciesDialog(QDialog):
    """Lists optional dependencies and installs the missing pip packages."""

    def __init__(
        self,
        parent: QWidget | None = None,
        runner: Runner = threaded_runner,
        install_function: Callable[
            [OptionalDependency], InstallResult
        ] = dependencies.install,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Optional features")
        self.setMinimumWidth(480)
        self.runner = runner
        self.install_function = install_function
        self.status_labels: dict[str, QLabel] = {}
        self.action_buttons: dict[str, QPushButton] = {}

        layout = QVBoxLayout(self)
        intro = QLabel(
            "myImages stays small by making these optional. Install only what "
            "you need."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        for dependency in dependencies.REGISTRY:
            layout.addWidget(self.build_row(dependency))

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

    def build_row(self, dependency: OptionalDependency) -> QFrame:
        frame = QFrame()
        frame.setObjectName("banner")
        row = QHBoxLayout(frame)
        text = QVBoxLayout()
        name = QLabel(f"<b>{dependency.display_name}</b>")
        purpose = QLabel(dependency.purpose)
        purpose.setObjectName("muted")
        purpose.setWordWrap(True)
        text.addWidget(name)
        text.addWidget(purpose)
        row.addLayout(text, 1)

        status = QLabel()
        status.setObjectName("muted")
        self.status_labels[dependency.key] = status
        row.addWidget(status)

        action = QPushButton()
        self.action_buttons[dependency.key] = action
        action.clicked.connect(lambda: self.start_install(dependency))
        row.addWidget(action)

        self.refresh_row(dependency)
        return frame

    def refresh_row(self, dependency: OptionalDependency) -> None:
        available = dependencies.is_available(dependency)
        status = self.status_labels[dependency.key]
        action = self.action_buttons[dependency.key]
        status.setText("Installed" if available else "Not installed")
        if available:
            action.setEnabled(False)
            action.setText("Installed")
        elif dependency.is_python_package:
            action.setEnabled(True)
            action.setText("Install")
        else:
            action.setEnabled(False)
            action.setText("System tool")

    def start_install(self, dependency: OptionalDependency) -> None:
        action = self.action_buttons[dependency.key]
        action.setEnabled(False)
        action.setText("Installing…")
        self.runner(
            lambda: self.install_function(dependency),
            self.on_installed,
            self.on_install_failed,
        )

    def on_installed(self, result: InstallResult) -> None:
        self.refresh_row(result.dependency)
        if result.succeeded:
            QMessageBox.information(
                self,
                "Optional features",
                f"{result.dependency.display_name} installed. "
                "Restart myImages to use it.",
            )
        else:
            QMessageBox.warning(
                self, "Optional features", result.output or "Installation failed."
            )

    def on_install_failed(self, message: str) -> None:
        QMessageBox.warning(self, "Optional features", message)
