"""A minimal plugin system for extending how files are previewed.

A plugin is a Python module (bundled, or dropped into the user plugins folder)
that defines a module-level ``register(registry)`` function. Inside it the
plugin calls :meth:`PluginRegistry.register_viewer` to claim one or more file
extensions and supply a factory that builds a preview widget for such files.

The registry stores plain callables and knows nothing about Qt, so it can be
exercised in tests without a running application. Only the GUI ever calls the
stored factories.
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

WidgetFactory = Callable[[Path], Any]


# The viewers that ship inside the package. Named rather than discovered so a
# packaged build cannot quietly lose one.
BUNDLED_PLUGINS: tuple[str, ...] = ("three_d_preview",)


@dataclass(frozen=True)
class ViewerPlugin:
    """A preview provider for a set of file extensions."""

    name: str
    extensions: frozenset[str]
    create_widget: WidgetFactory
    description: str = ""


class PluginRegistry:
    """Holds registered viewers and resolves the best one for a file."""

    def __init__(self) -> None:
        self.viewers: list[ViewerPlugin] = []

    def register_viewer(
        self,
        name: str,
        extensions: Iterable[str],
        create_widget: WidgetFactory,
        description: str = "",
    ) -> ViewerPlugin:
        normalised = frozenset(ext.lower() for ext in extensions)
        plugin = ViewerPlugin(name, normalised, create_widget, description)
        self.viewers.append(plugin)
        log.info("registered viewer plugin %r for %s", name, sorted(normalised))
        return plugin

    def viewer_for(self, path: str | Path) -> ViewerPlugin | None:
        """Return the last-registered viewer that handles this extension."""
        suffix = Path(path).suffix.lower()
        for plugin in reversed(self.viewers):
            if suffix in plugin.extensions:
                return plugin
        return None

    def handled_extensions(self) -> frozenset[str]:
        result: set[str] = set()
        for plugin in self.viewers:
            result |= plugin.extensions
        return frozenset(result)


def load_plugin_file(path: Path, registry: PluginRegistry) -> bool:
    """Import a single plugin file and let it register itself.

    Returns True on success. Failures are logged and swallowed so one broken
    plugin cannot stop the app from starting.
    """
    try:
        spec = importlib.util.spec_from_file_location(
            f"myimages_plugin_{path.stem}", path
        )
        if spec is None or spec.loader is None:
            return False
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        register = getattr(module, "register", None)
        if not callable(register):
            log.warning("plugin %s has no register() function", path.name)
            return False
        register(registry)
        return True
    except Exception:  # noqa: BLE001 - a plugin must never crash the host
        log.exception("failed to load plugin %s", path.name)
        return False


def load_bundled_plugins(registry: PluginRegistry) -> int:
    """Register the plugins that ship inside the package, by import.

    Not by scanning a directory: a packaged build has no ``.py`` files on disk
    for the scanner to find, so the bundled viewers silently disappeared from
    every artifact while working perfectly from a source checkout. Importing
    goes through whatever the interpreter is using -- a folder, a zip, a frozen
    archive -- so it is the same code path in both.
    """
    loaded = 0
    for name in BUNDLED_PLUGINS:
        try:
            module = importlib.import_module(f"myimages.plugins.{name}")
        except Exception:
            log.exception("Bundled plugin %s could not be imported", name)
            continue
        register = getattr(module, "register", None)
        if register is None:
            log.warning("Bundled plugin %s has no register()", name)
            continue
        register(registry)
        loaded += 1
    return loaded


def load_plugins_from_dir(directory: Path, registry: PluginRegistry) -> int:
    """Load every ``*.py`` plugin in a directory; return how many succeeded."""
    if not directory.is_dir():
        return 0
    loaded = 0
    for path in sorted(directory.glob("*.py")):
        if path.name.startswith((".", "_")):
            continue
        if load_plugin_file(path, registry):
            loaded += 1
    return loaded
