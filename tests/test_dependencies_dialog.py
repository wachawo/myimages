"""Tests for the optional-features dialog: row status and install flow."""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QMessageBox

from myimages.core import dependencies
from myimages.core.dependencies import InstallResult
from myimages.gui.dependencies_dialog import DependenciesDialog
from myimages.gui.task_runner import synchronous_runner


def succeed(dep):
    return InstallResult(dependency=dep, succeeded=True, output="ok")


def test_rows_reflect_unavailable(qtbot, silence_dialogs, monkeypatch):
    monkeypatch.setattr(dependencies, "is_available", lambda dep: False)

    dialog = DependenciesDialog(runner=synchronous_runner, install_function=succeed)
    qtbot.addWidget(dialog)

    ffmpeg_button = dialog.action_buttons["ffmpeg"]
    assert dialog.status_labels["ffmpeg"].text() == "Not installed"
    assert ffmpeg_button.text() == "System tool"
    assert ffmpeg_button.isEnabled() is False

    trash_button = dialog.action_buttons["trash"]
    assert dialog.status_labels["trash"].text() == "Not installed"
    assert trash_button.text() == "Install"
    assert trash_button.isEnabled() is True


def test_rows_reflect_available(qtbot, silence_dialogs, monkeypatch):
    monkeypatch.setattr(dependencies, "is_available", lambda dep: True)

    dialog = DependenciesDialog(runner=synchronous_runner, install_function=succeed)
    qtbot.addWidget(dialog)

    button = dialog.action_buttons["ffmpeg"]
    assert dialog.status_labels["ffmpeg"].text() == "Installed"
    assert button.text() == "Installed"
    assert button.isEnabled() is False


def test_start_install_success_shows_info(qtbot, silence_dialogs, monkeypatch):
    monkeypatch.setattr(dependencies, "is_available", lambda dep: False)
    infos: list[Any] = []
    monkeypatch.setattr(
        QMessageBox, "information", staticmethod(lambda *a, **k: infos.append(a))
    )
    trash = dependencies.find_dependency("trash")
    assert trash is not None

    def fake(dep):
        return InstallResult(dependency=dep, succeeded=True, output="done")

    dialog = DependenciesDialog(runner=synchronous_runner, install_function=fake)
    qtbot.addWidget(dialog)

    dialog.start_install(trash)

    assert len(infos) == 1
    button = dialog.action_buttons["trash"]
    assert button.text() == "Install"
    assert button.isEnabled() is True


def test_start_install_failure_shows_warning(qtbot, silence_dialogs, monkeypatch):
    monkeypatch.setattr(dependencies, "is_available", lambda dep: False)
    warnings: list[Any] = []
    monkeypatch.setattr(
        QMessageBox, "warning", staticmethod(lambda *a, **k: warnings.append(a))
    )
    heif = dependencies.find_dependency("heif")
    assert heif is not None

    def fake(dep):
        return InstallResult(dependency=dep, succeeded=False, output="pip failed")

    dialog = DependenciesDialog(runner=synchronous_runner, install_function=fake)
    qtbot.addWidget(dialog)

    dialog.start_install(heif)

    assert len(warnings) == 1
    assert "pip failed" in warnings[0][2]


def test_on_install_failed_shows_warning(qtbot, silence_dialogs, monkeypatch):
    warnings: list[Any] = []
    monkeypatch.setattr(
        QMessageBox, "warning", staticmethod(lambda *a, **k: warnings.append(a))
    )

    dialog = DependenciesDialog(runner=synchronous_runner, install_function=succeed)
    qtbot.addWidget(dialog)

    dialog.on_install_failed("network error")

    assert len(warnings) == 1
    assert "network error" in warnings[0][2]
