"""QApplication bootstrap: logging, theming, plugins and the main window."""

from __future__ import annotations

import logging
import signal
import sys
from collections.abc import Sequence
from logging.handlers import RotatingFileHandler
from pathlib import Path
from types import TracebackType

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from myimages import APP_NAME, ORGANISATION, __version__, icons, theme
from myimages.config import load_settings
from myimages.core.plugins import (
    PluginRegistry,
    load_bundled_plugins,
    load_plugins_from_dir,
)
from myimages.paths import is_frozen, log_file, plugins_dir

log = logging.getLogger(__name__)

# How often Python is given a chance to run while Qt owns the event loop.
# Frequent enough that Ctrl+C feels instant, rare enough to cost nothing.
INTERRUPT_POLL_MS = 200


def setup_logging() -> None:
    """Log to the console always, and to a rotating file for packaged builds."""
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if is_frozen():
        handlers.append(
            RotatingFileHandler(
                log_file(), maxBytes=1_000_000, backupCount=1, encoding="utf-8"
            )
        )
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )


def excepthook(
    exc_type: type[BaseException],
    exc: BaseException,
    tb: TracebackType | None,
) -> None:
    """Log unhandled exceptions and tell the user instead of dying silently.

    ``KeyboardInterrupt`` is deliberately not one of them: Ctrl+C in a terminal
    is a request to quit, and reporting it as a crash (traceback in the log, a
    scary dialog, the window still open) is both wrong and alarming.
    """
    if issubclass(exc_type, KeyboardInterrupt):
        quit_gracefully()
        return
    log.critical("Unhandled exception", exc_info=(exc_type, exc, tb))
    if QApplication.instance() is not None:
        QMessageBox.critical(None, APP_NAME, f"Unexpected error:\n{exc}")


def quit_gracefully() -> None:
    """Close every window the normal way, so settings are still saved."""
    app = QApplication.instance()
    if not isinstance(app, QApplication):
        return
    log.info("interrupted — closing")
    app.closeAllWindows()  # runs closeEvent, which persists the layout
    app.quit()


def install_interrupt_handler() -> QTimer:
    """Make Ctrl+C close the window instead of surfacing as a crash.

    Qt's event loop blocks inside C++, so Python never reaches its signal
    handler while the app merely sits there: the interrupt is only noticed when
    some Python callback happens to run, which is why it used to explode inside
    whichever timer fired first. A timer that does nothing at all gives the
    interpreter that moment on a predictable schedule.

    The returned timer must be kept alive by the caller, or it is collected and
    Ctrl+C goes back to being ignored.
    """
    signal.signal(signal.SIGINT, lambda number, frame: quit_gracefully())
    heartbeat = QTimer()
    heartbeat.timeout.connect(lambda: None)
    heartbeat.start(INTERRUPT_POLL_MS)
    return heartbeat


def apply_theme_to_app(theme_name: str) -> None:
    """Apply a colour scheme to the running application and the icon set."""
    app = QApplication.instance()
    if not isinstance(app, QApplication):
        return
    scheme = theme.scheme_for(theme_name)
    app.setPalette(theme.make_palette(scheme))
    app.setStyleSheet(theme.stylesheet(scheme))
    icons.configure(scheme.text, scheme.accent)


def requested_file(arguments: Sequence[str]) -> Path | None:
    """The first argument that names a real file, if the app was given one.

    The desktop entry passes ``%F``, so opening a photo from a file manager
    arrives here; anything that is not an existing file (a stray flag, a deleted
    path) is ignored rather than treated as an error.
    """
    for argument in arguments:
        candidate = Path(argument).expanduser()
        if candidate.is_file():
            return candidate.resolve()
    return None


def version_requested(arguments: Sequence[str]) -> bool:
    """Whether the command line asked for the version and nothing else."""
    return any(argument in {"--version", "-V"} for argument in arguments)


def build_registry() -> PluginRegistry:
    """Create the plugin registry and load bundled and user plugins.

    The bundled ones are imported and the user's are still scanned off disk:
    only the user folder is a real directory in every deployment, and a packaged
    build has no ``.py`` files of its own for a scanner to find.
    """
    registry = PluginRegistry()
    load_bundled_plugins(registry)
    load_plugins_from_dir(plugins_dir(), registry)
    return registry


def main() -> None:  # pragma: no cover - owns the event loop
    if version_requested(sys.argv[1:]):
        print(f"myImages {__version__}")
        return
    setup_logging()
    sys.excepthook = excepthook
    settings = load_settings()
    log.info("myImages %s starting", __version__)

    app = QApplication(sys.argv)
    app.setOrganizationName(ORGANISATION)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setStyle("Fusion")
    apply_theme_to_app(settings.theme)
    app.setWindowIcon(theme.app_icon())

    registry = build_registry()
    from myimages.gui.main_window import MainWindow

    interrupt_timer = install_interrupt_handler()
    window = MainWindow(settings, registry)
    window.show()
    opened = requested_file(sys.argv[1:])
    if opened is not None:
        window.open_file(opened)
    exit_code = app.exec()
    interrupt_timer.stop()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
