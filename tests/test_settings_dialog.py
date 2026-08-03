"""Tests for the preferences dialog: pre-fill and edited value extraction."""

from __future__ import annotations

from dataclasses import fields

from myimages.config import Settings
from myimages.gui.settings_dialog import SettingsDialog


def test_widgets_prefilled_from_settings(qtbot, gui_settings):
    dialog = SettingsDialog(gui_settings)
    qtbot.addWidget(dialog)

    assert dialog.theme_combo.currentData() == "dark"
    assert dialog.thumbnail_spin.value() == gui_settings.thumbnail_size
    assert dialog.recursive_check.isChecked() is gui_settings.recursive_scan
    assert dialog.gif_fps_spin.value() == gui_settings.gif_fps
    assert dialog.gif_width_spin.value() == gui_settings.gif_width
    assert dialog.pdf_quality_spin.value() == gui_settings.pdf_quality
    assert dialog.pdf_grayscale_check.isChecked() is gui_settings.pdf_grayscale


def test_light_theme_selects_light_entry(qtbot, gui_settings):
    gui_settings.theme = "light"
    dialog = SettingsDialog(gui_settings)
    qtbot.addWidget(dialog)

    assert dialog.theme_combo.currentData() == "light"


def test_values_reflect_edits(qtbot, gui_settings):
    dialog = SettingsDialog(gui_settings)
    qtbot.addWidget(dialog)

    dialog.theme_combo.setCurrentIndex(1)
    dialog.thumbnail_spin.setValue(256)
    dialog.recursive_check.setChecked(True)
    dialog.watch_check.setChecked(False)
    dialog.watch_interval_spin.setValue(45)
    dialog.verify_check.setChecked(True)
    dialog.gif_fps_spin.setValue(24)
    dialog.gif_width_spin.setValue(800)
    dialog.pdf_quality_spin.setValue(60)
    dialog.pdf_grayscale_check.setChecked(True)

    assert dialog.values() == {
        "theme": "light",
        "thumbnail_size": 256,
        "recursive_scan": True,
        "watch_folder": False,
        "watch_interval_seconds": 45,
        "verify_checksums": True,
        "gif_fps": 24,
        "gif_width": 800,
        "pdf_quality": 60,
        "pdf_grayscale": True,
    }


# -- watching the folder for outside changes -------------------------------


def test_watch_widgets_show_the_defaults(qtbot, gui_settings):
    dialog = SettingsDialog(gui_settings)
    qtbot.addWidget(dialog)

    assert dialog.watch_check.isChecked() is True
    assert dialog.watch_interval_spin.value() == gui_settings.watch_interval_seconds
    assert dialog.verify_check.isChecked() is False


def test_watch_widgets_prefilled_from_settings(qtbot, gui_settings):
    gui_settings.watch_folder = False
    gui_settings.watch_interval_seconds = 120
    gui_settings.verify_checksums = True

    dialog = SettingsDialog(gui_settings)
    qtbot.addWidget(dialog)

    assert dialog.watch_check.isChecked() is False
    assert dialog.watch_interval_spin.value() == 120
    assert dialog.verify_check.isChecked() is True


def test_values_report_edited_watch_settings(qtbot, gui_settings):
    dialog = SettingsDialog(gui_settings)
    qtbot.addWidget(dialog)

    dialog.watch_check.setChecked(False)
    dialog.watch_interval_spin.setValue(300)
    dialog.verify_check.setChecked(True)

    values = dialog.values()
    assert values["watch_folder"] is False
    assert values["watch_interval_seconds"] == 300
    assert values["verify_checksums"] is True


def test_the_check_interval_can_never_be_zero(qtbot, gui_settings):
    """A zero-second interval would mean re-scanning the folder continuously."""
    dialog = SettingsDialog(gui_settings)
    qtbot.addWidget(dialog)

    dialog.watch_interval_spin.setValue(0)

    assert dialog.values()["watch_interval_seconds"] >= 2


def test_every_reported_key_is_a_real_setting(qtbot, gui_settings):
    """The window setattrs these straight onto Settings.

    A key that is not a real field would be silently dropped on save, so the
    edited preference would appear to work and then vanish on restart.
    """
    dialog = SettingsDialog(gui_settings)
    qtbot.addWidget(dialog)

    known = {item.name for item in fields(Settings)}

    assert set(dialog.values()) <= known


# -- desktop integration ----------------------------------------------------


def desktop_isolated(tmp_path, monkeypatch):
    """Point XDG at tmp_path so nothing touches the real desktop."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))


def quiet_runner(command):
    """A helper-tool runner that reports success without running anything."""
    import subprocess

    return subprocess.CompletedProcess(args=list(command), returncode=0, stdout="")


def test_desktop_section_offers_to_add_the_shortcut(
    qtbot, gui_settings, tmp_path, monkeypatch
):
    from myimages.gui.settings_dialog import SettingsDialog

    desktop_isolated(tmp_path, monkeypatch)
    dialog = SettingsDialog(gui_settings)
    qtbot.addWidget(dialog)

    assert dialog.shortcut_button.text() == "Add to application menu"
    assert "not in the application menu" in dialog.desktop_status.text()


def test_adding_and_removing_the_shortcut(qtbot, gui_settings, tmp_path, monkeypatch):
    from myimages.core import desktop
    from myimages.gui.settings_dialog import SettingsDialog

    desktop_isolated(tmp_path, monkeypatch)
    dialog = SettingsDialog(gui_settings)
    qtbot.addWidget(dialog)

    dialog.toggle_shortcut()
    assert desktop.entry_path().is_file()
    assert desktop.icon_path().is_file()  # the icon is rendered and copied
    assert dialog.shortcut_button.text() == "Remove from application menu"
    assert "Added myImages" in dialog.desktop_status.text()

    dialog.toggle_shortcut()
    assert not desktop.entry_path().exists()
    assert dialog.shortcut_button.text() == "Add to application menu"


def test_claiming_file_types_installs_and_registers(
    qtbot, gui_settings, tmp_path, monkeypatch
):
    from myimages.core import desktop
    from myimages.gui.settings_dialog import SettingsDialog

    desktop_isolated(tmp_path, monkeypatch)
    calls: list[list[str]] = []

    def fake_default(mime_types=desktop.SUPPORTED_MIME_TYPES, runner=None):
        calls.append(list(mime_types))
        return desktop.IntegrationResult(True, "myImages now opens 4 file type(s).")

    monkeypatch.setattr(desktop, "set_as_default", fake_default)
    dialog = SettingsDialog(gui_settings)
    qtbot.addWidget(dialog)

    dialog.claim_file_types()

    assert desktop.entry_path().is_file()  # installed on the way
    assert calls  # and the defaults were registered
    assert "now opens" in dialog.desktop_status.text()


def test_the_rendered_icon_is_a_real_image(qtbot, gui_settings, tmp_path, monkeypatch):
    from PIL import Image

    from myimages.gui.settings_dialog import SettingsDialog

    desktop_isolated(tmp_path, monkeypatch)
    dialog = SettingsDialog(gui_settings)
    qtbot.addWidget(dialog)

    written = dialog.write_icon()

    assert written is not None
    assert Image.open(written).size == (256, 256)


def test_status_reports_the_types_already_claimed(
    qtbot, gui_settings, tmp_path, monkeypatch
):
    from myimages.core import desktop
    from myimages.gui.settings_dialog import SettingsDialog

    desktop_isolated(tmp_path, monkeypatch)
    desktop.install(runner=quiet_runner)
    monkeypatch.setattr(desktop, "claimed_types", lambda *a, **k: ["image/png"])

    dialog = SettingsDialog(gui_settings)
    qtbot.addWidget(dialog)

    assert "opens 1 file type(s) by default" in dialog.desktop_status.text()


def test_status_when_installed_but_claiming_nothing(
    qtbot, gui_settings, tmp_path, monkeypatch
):
    from myimages.core import desktop
    from myimages.gui.settings_dialog import SettingsDialog

    desktop_isolated(tmp_path, monkeypatch)
    desktop.install(runner=quiet_runner)
    monkeypatch.setattr(desktop, "claimed_types", lambda *a, **k: [])

    dialog = SettingsDialog(gui_settings)
    qtbot.addWidget(dialog)

    assert dialog.desktop_status.text() == "In the application menu."


def test_an_icon_that_cannot_be_rendered_is_reported_as_missing(
    qtbot, gui_settings, tmp_path, monkeypatch
):
    """Installing must still work when the icon cannot be written."""
    from PySide6.QtGui import QPixmap

    from myimages.gui.settings_dialog import SettingsDialog

    desktop_isolated(tmp_path, monkeypatch)
    dialog = SettingsDialog(gui_settings)
    qtbot.addWidget(dialog)
    monkeypatch.setattr(QPixmap, "save", lambda self, *a, **k: False)

    assert dialog.write_icon() is None
