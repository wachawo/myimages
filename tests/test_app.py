"""Tests for the application bootstrap (myimages.app)."""

from __future__ import annotations

from pathlib import Path

from myimages.app import requested_file


def test_a_file_argument_is_recognised(make_image):
    photo = make_image("opened.png")
    assert requested_file([str(photo)]) == photo.resolve()


def test_the_first_real_file_wins(make_image):
    photo = make_image("second.png")
    assert requested_file(["--flag", "/nowhere/missing.png", str(photo)]) == (
        photo.resolve()
    )


def test_no_file_argument_gives_nothing(tmp_path: Path):
    assert requested_file([]) is None
    assert requested_file(["--verbose"]) is None
    assert requested_file([str(tmp_path)]) is None  # a folder is not a file


# -- Ctrl+C ------------------------------------------------------------------


def test_interrupt_closes_windows_instead_of_reporting_a_crash(qtbot, caplog):
    """Ctrl+C is a request to quit, not something to log as CRITICAL."""
    import logging

    from PySide6.QtWidgets import QWidget

    from myimages import app as app_module

    window = QWidget()
    qtbot.addWidget(window)
    window.show()
    assert window.isVisible()

    with caplog.at_level(logging.INFO):
        app_module.excepthook(KeyboardInterrupt, KeyboardInterrupt(), None)

    assert not window.isVisible()  # closed the normal way
    assert "interrupted" in caplog.text
    assert "CRITICAL" not in caplog.text


def test_a_real_error_is_still_reported(qtbot, monkeypatch, caplog):
    import logging

    from PySide6.QtWidgets import QMessageBox

    from myimages import app as app_module

    shown: list[str] = []
    monkeypatch.setattr(
        QMessageBox, "critical", staticmethod(lambda *args, **kw: shown.append(args[2]))
    )

    with caplog.at_level(logging.CRITICAL):
        app_module.excepthook(ValueError, ValueError("broken"), None)

    assert "Unhandled exception" in caplog.text
    assert shown and "broken" in shown[0]


def test_the_interrupt_handler_installs_a_heartbeat(qtbot, monkeypatch):
    """Qt blocks in C++, so Python needs a scheduled moment to see the signal."""
    import signal

    from myimages import app as app_module

    original = signal.getsignal(signal.SIGINT)
    try:
        timer = app_module.install_interrupt_handler()
        assert timer.isActive()
        assert timer.interval() == app_module.INTERRUPT_POLL_MS
        assert signal.getsignal(signal.SIGINT) is not original
        timer.stop()
    finally:
        signal.signal(signal.SIGINT, original)


def test_quitting_without_an_application_is_harmless(monkeypatch):
    from PySide6.QtWidgets import QApplication

    from myimages import app as app_module

    monkeypatch.setattr(QApplication, "instance", staticmethod(lambda: None))
    app_module.quit_gracefully()  # must not raise


# -- bootstrap pieces --------------------------------------------------------


def test_logging_goes_to_the_console_from_a_checkout(monkeypatch):
    import logging

    from myimages import app as app_module

    monkeypatch.setattr(app_module, "is_frozen", lambda: False)
    app_module.setup_logging()
    handlers = logging.getLogger().handlers
    assert any(isinstance(h, logging.StreamHandler) for h in handlers)


def test_a_packaged_build_also_logs_to_a_file(monkeypatch, tmp_path):
    import logging
    from logging.handlers import RotatingFileHandler

    from myimages import app as app_module

    monkeypatch.setattr(app_module, "is_frozen", lambda: True)
    monkeypatch.setattr(app_module, "log_file", lambda: tmp_path / "myimages.log")
    root = logging.getLogger()
    saved = list(root.handlers)
    root.handlers = []  # basicConfig is a no-op once handlers exist
    try:
        app_module.setup_logging()
        assert any(isinstance(h, RotatingFileHandler) for h in root.handlers)
    finally:
        root.handlers = saved


def test_applying_a_theme_needs_a_running_application(qtbot, monkeypatch):
    from PySide6.QtWidgets import QApplication

    from myimages import app as app_module

    app_module.apply_theme_to_app("light")  # a real application is running
    app_module.apply_theme_to_app("dark")

    monkeypatch.setattr(QApplication, "instance", staticmethod(lambda: None))
    app_module.apply_theme_to_app("dark")  # without one it simply does nothing


def test_the_registry_loads_the_bundled_plugins(qtbot):
    from myimages import app as app_module

    registry = app_module.build_registry()
    assert ".obj" in registry.handled_extensions()  # the 3D example ships with us


def test_version_is_asked_for_by_either_spelling():
    """main() owns the event loop and is pragma-excluded, so the test is here."""
    from myimages.app import version_requested

    assert version_requested(["--version"])
    assert version_requested(["-V"])
    assert not version_requested([])
    assert not version_requested(["/home/someone/photo.png"])
