"""Tests for :mod:`myimages.config`.

Persistence is exercised against real JSON files written under the isolated
temporary data directory (see ``isolated_data_dir`` in ``conftest.py``), so the
same ``load``/``save`` code paths production uses are covered without any mocks.
"""

from __future__ import annotations

import json
from pathlib import Path

from myimages.config import (
    Settings,
    load_settings,
    save_settings,
    settings_path,
)


def test_defaults_are_safe() -> None:
    settings = Settings()
    assert settings.last_folder == ""
    assert settings.recursive_scan is False
    assert settings.sort_key == "name"
    assert settings.sort_descending is False
    assert settings.show_images is True
    assert settings.show_videos is True
    assert settings.favorites_only is False
    assert settings.favorites == []
    assert settings.theme == "dark"
    assert settings.pdf_target_mib == 0.0


def test_favorites_are_per_instance_lists() -> None:
    one = Settings()
    two = Settings()
    one.favorites.append("a.png")
    assert two.favorites == []


def test_settings_path_lives_under_data_dir(isolated_data_dir: Path) -> None:
    path = settings_path()
    assert path == isolated_data_dir / "settings.json"


def test_missing_file_returns_defaults() -> None:
    assert not settings_path().exists()
    assert load_settings() == Settings()


def test_save_load_round_trip() -> None:
    original = Settings(
        last_folder="/photos",
        recursive_scan=True,
        sort_key="size",
        sort_descending=True,
        show_videos=False,
        favorites=["/photos/a.png"],
        grid_columns=3,
        thumbnail_size=96,
        theme="light",
        pdf_quality=70,
        pdf_grayscale=True,
        pdf_target_mib=3.5,
        gif_fps=24,
    )
    save_settings(original)
    assert settings_path().exists()
    assert load_settings() == original


def test_saved_file_is_pretty_printed_json() -> None:
    save_settings(Settings(theme="light"))
    text = settings_path().read_text(encoding="utf-8")
    data = json.loads(text)
    assert data["theme"] == "light"
    assert "\n" in text  # indent=2 produces multi-line output


def test_unknown_keys_are_ignored() -> None:
    settings_path().write_text(
        json.dumps({"theme": "light", "bogus_key": 123, "another": [1, 2]}),
        encoding="utf-8",
    )
    loaded = load_settings()
    assert loaded == Settings(theme="light")
    assert not hasattr(loaded, "bogus_key")


def test_malformed_json_returns_defaults() -> None:
    settings_path().write_text("{ this is not valid json ", encoding="utf-8")
    assert load_settings() == Settings()


def test_empty_file_returns_defaults() -> None:
    settings_path().write_text("", encoding="utf-8")
    assert load_settings() == Settings()


def test_is_favorite_reflects_membership() -> None:
    settings = Settings(favorites=["/a.png"])
    assert settings.is_favorite("/a.png") is True
    assert settings.is_favorite("/b.png") is False


def test_is_favorite_accepts_path_objects() -> None:
    settings = Settings(favorites=["/a.png"])
    assert settings.is_favorite(Path("/a.png")) is True


def test_toggle_favorite_adds_then_removes() -> None:
    settings = Settings()
    assert settings.toggle_favorite("/a.png") is True
    assert settings.favorites == ["/a.png"]
    assert settings.is_favorite("/a.png") is True

    assert settings.toggle_favorite("/a.png") is False
    assert settings.favorites == []
    assert settings.is_favorite("/a.png") is False


def test_toggle_favorite_accepts_path_objects() -> None:
    settings = Settings()
    assert settings.toggle_favorite(Path("/a.png")) is True
    assert settings.favorites == ["/a.png"]
    assert settings.toggle_favorite(Path("/a.png")) is False
    assert settings.favorites == []


# -- watching the folder for outside changes -------------------------------


def test_watching_is_on_by_default_and_cheap() -> None:
    """A gallery showing deleted files is worse than a periodic directory read.

    So watching is on out of the box, on a slow interval, and the expensive
    part (hashing file contents) stays off until the user asks for it.
    """
    settings = Settings()
    assert settings.watch_folder is True
    assert settings.watch_interval_seconds == 10
    assert settings.verify_checksums is False


def test_watch_defaults_survive_a_round_trip() -> None:
    save_settings(Settings())

    loaded = load_settings()

    assert loaded.watch_folder is True
    assert loaded.watch_interval_seconds == 10
    assert loaded.verify_checksums is False
    assert loaded == Settings()


def test_edited_watch_settings_survive_a_round_trip() -> None:
    original = Settings(
        watch_folder=False,
        watch_interval_seconds=45,
        verify_checksums=True,
    )

    save_settings(original)
    loaded = load_settings()

    assert loaded == original
    assert loaded.watch_folder is False
    assert loaded.watch_interval_seconds == 45
    assert loaded.verify_checksums is True


def test_watch_settings_are_written_to_the_json_file() -> None:
    save_settings(Settings(watch_interval_seconds=90, verify_checksums=True))

    data = json.loads(settings_path().read_text(encoding="utf-8"))

    assert data["watch_folder"] is True
    assert data["watch_interval_seconds"] == 90
    assert data["verify_checksums"] is True


def test_a_settings_file_written_before_watching_existed_gains_the_defaults() -> None:
    """Upgrading must not leave the watch settings undefined."""
    settings_path().write_text(
        json.dumps({"theme": "light", "thumbnail_size": 96}), encoding="utf-8"
    )

    loaded = load_settings()

    assert loaded.watch_folder is True
    assert loaded.watch_interval_seconds == 10
    assert loaded.verify_checksums is False
