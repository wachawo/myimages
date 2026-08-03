"""Shared pytest fixtures.

Tests must never touch a developer's real data or need a display, so the data
directory is redirected to a temporary folder and Qt runs on the offscreen
platform. Small real assets (PNGs and, if ffmpeg is present, a short clip) are
generated on demand for genuine end-to-end coverage.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Keep QtMultimedia's per-player ffmpeg backend threads out of the test process;
# they crash on teardown when many short-lived windows come and go.
os.environ.setdefault("MYIMAGES_NO_VIDEO", "1")


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect all persisted state into a per-test temporary directory."""
    data = tmp_path / "data"
    monkeypatch.setenv("MYIMAGES_DATA_DIR", str(data))
    return data


@pytest.fixture(autouse=True)
def isolated_media_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the first-launch folder default at a temp folder.

    The window seeds an empty ``last_folder`` with the user's pictures
    directory, so without this a test that forgets to name a folder would scan
    (and a delete test could even touch) the developer's real photos.
    """
    from myimages.gui import main_window as main_window_module

    pictures = tmp_path / "pictures"
    pictures.mkdir(exist_ok=True)
    monkeypatch.setattr(main_window_module, "default_media_dir", lambda: pictures)
    return pictures


@pytest.fixture(autouse=True)
def reset_clipboard():
    """Empty the clipboard after each test: the offscreen platform crashes at
    shutdown if it still holds mime data (especially an image)."""
    yield
    from PySide6.QtGui import QGuiApplication

    app = QGuiApplication.instance()
    if app is not None:
        clipboard = app.clipboard()
        if clipboard is not None:
            clipboard.clear()


@pytest.fixture
def make_image(tmp_path: Path) -> Callable[..., Path]:
    """Factory that writes a solid-colour image and returns its path."""
    from PIL import Image

    def factory(
        name: str = "image.png",
        size: tuple[int, int] = (64, 48),
        colour: tuple[int, int, int] = (200, 90, 40),
    ) -> Path:
        path = tmp_path / name
        Image.new("RGB", size, colour).save(path)
        return path

    return factory


@pytest.fixture
def image_dir(tmp_path: Path) -> Path:
    """A directory with a handful of images of varied size and colour."""
    from PIL import Image

    folder = tmp_path / "gallery"
    folder.mkdir()
    specs = [
        ("alpha.png", (40, 40), (255, 0, 0)),
        ("bravo.jpg", (80, 60), (0, 255, 0)),
        ("charlie.png", (20, 20), (0, 0, 255)),
    ]
    for name, size, colour in specs:
        Image.new("RGB", size, colour).save(folder / name)
    return folder


@pytest.fixture
def gui_settings(tmp_path: Path):
    """Settings pointed at an empty temp folder.

    The window seeds an empty ``last_folder`` with the user's real pictures
    directory, so tests must name a folder of their own to stay isolated.
    """
    from myimages.config import Settings

    empty = tmp_path / "empty"
    empty.mkdir(exist_ok=True)
    return Settings(last_folder=str(empty))


@pytest.fixture
def media_file(make_image):
    """A single image turned into a MediaFile with its dimensions filled in."""
    from myimages.core.media import build_media_file
    from myimages.core.scanner import probe_image_dimensions

    path = make_image()
    built = build_media_file(path)
    width, height = probe_image_dimensions(path)
    return built.with_dimensions(width, height)


@pytest.fixture
def silence_dialogs(monkeypatch: pytest.MonkeyPatch):
    """Make blocking message boxes return safe defaults so tests never hang."""
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox,
        "information",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok),
    )
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok),
    )
    monkeypatch.setattr(
        QMessageBox,
        "critical",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok),
    )
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes),
    )


@pytest.fixture
def sample_video(tmp_path: Path) -> Path:
    """A one-second test clip; skips the test if ffmpeg is unavailable."""
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not available")
    out = tmp_path / "clip.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=1:size=128x96:rate=10",
            "-pix_fmt",
            "yuv420p",
            str(out),
        ],
        check=True,
        capture_output=True,
    )
    return out
