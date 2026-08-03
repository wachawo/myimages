"""Tests for the file-deletion helpers."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

from myimages.core import deletion


def test_is_trash_available_reflects_find_spec(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    assert deletion.is_trash_available() is True

    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
    assert deletion.is_trash_available() is False


def test_delete_file_unlinks(make_image) -> None:
    path = make_image()
    assert path.exists()

    deletion.delete_file(path, prefer_trash=False)

    assert not path.exists()


def test_delete_file_falls_back_to_unlink_without_trash(
    make_image, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = make_image()
    monkeypatch.setattr(deletion, "is_trash_available", lambda: False)

    deletion.delete_file(path, prefer_trash=True)

    assert not path.exists()


def test_delete_file_uses_trash_branch(
    make_image, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = make_image()
    recorded: list[str] = []

    def fake_send(target: str) -> None:
        recorded.append(target)
        Path(target).unlink()

    fake_module = types.SimpleNamespace(send2trash=fake_send)

    monkeypatch.setattr(deletion, "is_trash_available", lambda: True)
    monkeypatch.setitem(sys.modules, "send2trash", fake_module)

    deletion.delete_file(path)  # prefer_trash defaults to True

    assert recorded == [str(path)]
    assert not path.exists()


def test_delete_files_returns_removed_and_skips_missing(
    make_image, tmp_path: Path
) -> None:
    first = make_image("first.png")
    second = make_image("second.png")
    missing = tmp_path / "nope.png"

    removed = deletion.delete_files([first, missing, second], prefer_trash=False)

    assert removed == [first, second]
    assert not first.exists()
    assert not second.exists()
