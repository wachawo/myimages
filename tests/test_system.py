"""Tests for the host-platform helpers (myimages.system).

The point of the module is that the two questions it answers -- what to tell a
user to install, and whether a subprocess needs hiding -- are asked in several
places and must not drift apart.
"""

from __future__ import annotations

import pytest

from myimages import system


@pytest.mark.parametrize(
    ("platform", "expected"),
    [
        ("linux", "sudo apt install ffmpeg"),
        ("darwin", "brew install ffmpeg"),
        ("win32", "winget install Gyan.FFmpeg"),
    ],
)
def test_the_ffmpeg_hint_names_this_platforms_package_manager(
    monkeypatch, platform, expected
):
    """A Windows user told to run apt has been told nothing."""
    monkeypatch.setattr(system.sys, "platform", platform)
    assert system.ffmpeg_hint() == expected


def test_an_unknown_platform_points_at_the_download_page(monkeypatch):
    monkeypatch.setattr(system.sys, "platform", "sunos5")
    assert "ffmpeg.org" in system.ffmpeg_hint()


def test_only_linux_can_mean_anything_by_desktop_integration(monkeypatch):
    monkeypatch.setattr(system.sys, "platform", "linux")
    assert system.is_linux()
    monkeypatch.setattr(system.sys, "platform", "win32")
    assert not system.is_linux()


def test_the_quiet_flag_is_zero_where_the_constant_does_not_exist(monkeypatch):
    """CREATE_NO_WINDOW is Windows-only; zero is the no-op everywhere else."""
    monkeypatch.delattr(system.subprocess, "CREATE_NO_WINDOW", raising=False)
    assert system.quiet_subprocess_flags() == 0
    monkeypatch.setattr(
        system.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False
    )
    assert system.quiet_subprocess_flags() == 0x08000000
