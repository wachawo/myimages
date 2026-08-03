"""Tests for :mod:`myimages.paths`.

The autouse ``isolated_data_dir`` fixture points ``MYIMAGES_DATA_DIR`` at a
temporary folder, so the directory-creating helpers can be exercised for real
without touching a developer's home directory. Branches that depend on
``Path.home`` are covered by monkeypatching it at a throwaway location.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from myimages import paths


def test_is_frozen_false_by_default() -> None:
    assert paths.is_frozen() is False


def test_data_dir_honours_env(isolated_data_dir: Path) -> None:
    result = paths.data_dir()
    assert result == isolated_data_dir
    assert result.is_dir()


def test_data_dir_without_env_uses_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(paths.DATA_DIR_ENV, raising=False)
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))

    result = paths.data_dir()
    assert result == fake_home / ".myimages"
    assert result.is_dir()


def test_cache_dir_created_under_data_dir(isolated_data_dir: Path) -> None:
    result = paths.cache_dir()
    assert result == isolated_data_dir / "thumbnails"
    assert result.is_dir()


def test_plugins_dir_created_under_data_dir(isolated_data_dir: Path) -> None:
    result = paths.plugins_dir()
    assert result == isolated_data_dir / "plugins"
    assert result.is_dir()


def test_log_file_path_under_data_dir(isolated_data_dir: Path) -> None:
    result = paths.log_file()
    assert result == isolated_data_dir / "myimages.log"
    assert result.parent == paths.data_dir()


def test_default_media_dir_returns_existing_directory() -> None:
    result = paths.default_media_dir()
    assert result.is_dir()


def test_default_media_dir_prefers_pictures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_home = tmp_path / "home"
    pictures = fake_home / "Pictures"
    pictures.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))

    assert paths.default_media_dir() == pictures


def test_default_media_dir_falls_back_to_later_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_home = tmp_path / "home"
    photos = fake_home / "Photos"
    photos.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))

    assert paths.default_media_dir() == photos


def test_default_media_dir_falls_back_to_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))

    assert paths.default_media_dir() == fake_home
