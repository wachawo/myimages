"""Tests for the minimal plugin system in ``myimages.core.plugins``."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from myimages.core.plugins import (
    PluginRegistry,
    ViewerPlugin,
    load_plugin_file,
    load_plugins_from_dir,
)


def dummy_widget(path: Path) -> str:
    """A stand-in factory; the registry never calls it in these tests."""
    return f"widget:{path}"


def test_register_viewer_normalises_extensions_and_returns_plugin() -> None:
    registry = PluginRegistry()
    plugin = registry.register_viewer(
        "Upper", [".FOO", ".Bar"], dummy_widget, description="d"
    )
    assert isinstance(plugin, ViewerPlugin)
    assert plugin.name == "Upper"
    assert plugin.description == "d"
    assert plugin.extensions == frozenset({".foo", ".bar"})
    assert registry.viewers == [plugin]


def test_viewer_for_last_registered_wins() -> None:
    registry = PluginRegistry()
    first = registry.register_viewer("first", [".obj"], dummy_widget)
    second = registry.register_viewer("second", [".obj"], dummy_widget)

    resolved = registry.viewer_for("model.obj")
    assert resolved is second
    assert resolved is not first


def test_viewer_for_is_case_insensitive_on_suffix() -> None:
    registry = PluginRegistry()
    plugin = registry.register_viewer("caps", [".png"], dummy_widget)

    assert registry.viewer_for("PHOTO.PNG") is plugin
    assert registry.viewer_for(Path("dir/PHOTO.Png")) is plugin


def test_viewer_for_returns_none_when_unhandled() -> None:
    registry = PluginRegistry()
    registry.register_viewer("png", [".png"], dummy_widget)
    assert registry.viewer_for("clip.mp4") is None


def test_handled_extensions_is_union() -> None:
    registry = PluginRegistry()
    registry.register_viewer("a", [".png", ".jpg"], dummy_widget)
    registry.register_viewer("b", [".jpg", ".gif"], dummy_widget)

    assert registry.handled_extensions() == frozenset({".png", ".jpg", ".gif"})


def test_load_plugin_file_success_adds_viewer(tmp_path: Path) -> None:
    plugin_path = tmp_path / "good_plugin.py"
    plugin_path.write_text(
        "def register(registry):\n"
        "    registry.register_viewer('demo', ['.xyz'], lambda path: path)\n",
        encoding="utf-8",
    )

    registry = PluginRegistry()
    assert load_plugin_file(plugin_path, registry) is True
    assert len(registry.viewers) == 1
    resolved = registry.viewer_for("thing.xyz")
    assert resolved is not None
    assert resolved.name == "demo"


def test_load_plugin_file_without_register_returns_false(tmp_path: Path) -> None:
    plugin_path = tmp_path / "no_register.py"
    plugin_path.write_text("value = 42\n", encoding="utf-8")

    registry = PluginRegistry()
    assert load_plugin_file(plugin_path, registry) is False
    assert registry.viewers == []


def test_load_plugin_file_non_callable_register_returns_false(tmp_path: Path) -> None:
    plugin_path = tmp_path / "bad_register.py"
    plugin_path.write_text("register = 123\n", encoding="utf-8")

    registry = PluginRegistry()
    assert load_plugin_file(plugin_path, registry) is False


def test_load_plugin_file_register_raises_is_swallowed(tmp_path: Path) -> None:
    plugin_path = tmp_path / "raising_register.py"
    plugin_path.write_text(
        "def register(registry):\n    raise RuntimeError('boom')\n",
        encoding="utf-8",
    )

    registry = PluginRegistry()
    assert load_plugin_file(plugin_path, registry) is False
    assert registry.viewers == []


def test_load_plugin_file_none_spec_returns_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin_path = tmp_path / "unspecced.py"
    plugin_path.write_text("value = 1\n", encoding="utf-8")

    monkeypatch.setattr(importlib.util, "spec_from_file_location", lambda *a, **k: None)
    registry = PluginRegistry()
    assert load_plugin_file(plugin_path, registry) is False


def test_load_plugin_file_import_error_is_swallowed(tmp_path: Path) -> None:
    plugin_path = tmp_path / "broken_import.py"
    plugin_path.write_text("raise RuntimeError('kaboom')\n", encoding="utf-8")

    registry = PluginRegistry()
    assert load_plugin_file(plugin_path, registry) is False


def test_load_plugins_from_dir_counts_and_skips(tmp_path: Path) -> None:
    directory = tmp_path / "plugins"
    directory.mkdir()

    good = (
        "def register(registry):\n"
        "    registry.register_viewer('{name}', ['{ext}'], lambda path: path)\n"
    )
    (directory / "alpha.py").write_text(
        good.format(name="alpha", ext=".a"), encoding="utf-8"
    )
    (directory / "bravo.py").write_text(
        good.format(name="bravo", ext=".b"), encoding="utf-8"
    )
    # Skipped: leading underscore and leading dot.
    (directory / "_private.py").write_text(
        good.format(name="private", ext=".p"), encoding="utf-8"
    )
    (directory / ".hidden.py").write_text(
        good.format(name="hidden", ext=".h"), encoding="utf-8"
    )
    # A file that fails to register does not count.
    (directory / "charlie.py").write_text("value = 1\n", encoding="utf-8")

    registry = PluginRegistry()
    loaded = load_plugins_from_dir(directory, registry)

    assert loaded == 2
    names = {plugin.name for plugin in registry.viewers}
    assert names == {"alpha", "bravo"}


def test_load_plugins_from_dir_missing_directory_returns_zero(tmp_path: Path) -> None:
    registry = PluginRegistry()
    assert load_plugins_from_dir(tmp_path / "nope", registry) == 0
    assert registry.viewers == []


def test_bundled_plugins_are_registered_by_import(caplog):
    """A packaged build has no .py files on disk for a scanner to find."""
    from myimages.core.plugins import PluginRegistry, load_bundled_plugins

    registry = PluginRegistry()
    assert load_bundled_plugins(registry) == 1
    assert registry.handled_extensions()


def test_a_bundled_plugin_that_will_not_import_is_logged_and_skipped(monkeypatch):
    from myimages.core import plugins

    monkeypatch.setattr(plugins, "BUNDLED_PLUGINS", ("no_such_module",))
    registry = plugins.PluginRegistry()
    assert plugins.load_bundled_plugins(registry) == 0


def test_a_bundled_plugin_without_register_is_skipped(monkeypatch):
    from myimages.core import plugins

    # A real, importable module of ours that has no register() function.
    monkeypatch.setattr(plugins, "BUNDLED_PLUGINS", ("__init__",))
    registry = plugins.PluginRegistry()
    assert plugins.load_bundled_plugins(registry) == 0
