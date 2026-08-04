"""Tests for optional-dependency discovery and installation."""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from collections.abc import Sequence

import pytest

from myimages.core import dependencies


def completed(
    returncode: int, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["x"], returncode=returncode, stdout=stdout, stderr=stderr
    )


def test_find_dependency() -> None:
    ffmpeg = dependencies.find_dependency("ffmpeg")
    assert ffmpeg is not None
    assert ffmpeg.key == "ffmpeg"
    assert dependencies.find_dependency("does-not-exist") is None


def test_dependency_kind_properties() -> None:
    ffmpeg = dependencies.find_dependency("ffmpeg")
    trash = dependencies.find_dependency("trash")
    heif = dependencies.find_dependency("heif")
    assert ffmpeg is not None and trash is not None and heif is not None

    assert ffmpeg.is_external_tool is True
    assert ffmpeg.is_python_package is False

    assert trash.is_python_package is True
    assert trash.is_external_tool is False

    assert heif.is_python_package is True
    assert heif.is_external_tool is False


def test_is_available_binary_branch() -> None:
    ffmpeg = dependencies.find_dependency("ffmpeg")
    assert ffmpeg is not None
    # ffmpeg is present in this environment (conftest depends on it too).
    assert shutil.which("ffmpeg") is not None
    assert dependencies.is_available(ffmpeg) is True


def test_is_available_import_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    trash = dependencies.find_dependency("trash")
    assert trash is not None

    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    assert dependencies.is_available(trash) is True

    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
    assert dependencies.is_available(trash) is False


def test_is_available_returns_false_when_undetectable() -> None:
    bare = dependencies.OptionalDependency(
        key="bare",
        display_name="Bare",
        purpose="Nothing to detect.",
    )
    assert dependencies.is_available(bare) is False


def test_missing_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dependencies, "is_available", lambda dep: dep.key == "ffmpeg")
    missing = dependencies.missing_dependencies()
    assert [dep.key for dep in missing] == ["trash", "heif", "bgremove"]


def test_install_python_package_success() -> None:
    trash = dependencies.find_dependency("trash")
    assert trash is not None
    captured: list[Sequence[str]] = []

    def runner(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        captured.append(command)
        return completed(0, stdout="out", stderr="err")

    result = dependencies.install(trash, runner=runner)

    assert captured == [[sys.executable, "-m", "pip", "install", "Send2Trash"]]
    assert result.succeeded is True
    assert result.dependency is trash
    assert result.output == "out\nerr"


def test_install_python_package_failure() -> None:
    trash = dependencies.find_dependency("trash")
    assert trash is not None

    def runner(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        return completed(1, stdout="", stderr="boom")

    result = dependencies.install(trash, runner=runner)

    assert result.succeeded is False
    assert result.output == "boom"


def test_install_external_tool_reports_package_manager() -> None:
    ffmpeg = dependencies.find_dependency("ffmpeg")
    assert ffmpeg is not None

    def runner(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        raise AssertionError("runner must not be called for a system tool")

    result = dependencies.install(ffmpeg, runner=runner)

    assert result.succeeded is False
    assert result.dependency is ffmpeg
    assert "package manager" in result.output
    assert "apt install ffmpeg" in result.output


def test_run_pip_install_executes_command() -> None:
    result = dependencies.run_pip_install([sys.executable, "-c", "print('hi')"])
    assert result.returncode == 0
    assert "hi" in result.stdout
