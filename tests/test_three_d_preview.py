"""Tests for the bundled 3D-preview example plugin."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QLabel

from myimages.core.plugins import PluginRegistry
from myimages.plugins.three_d_preview import (
    MODEL_EXTENSIONS,
    create_widget,
    register,
    summarise_obj,
)


def test_summarise_obj_counts_vertices_and_faces(tmp_path: Path) -> None:
    obj = tmp_path / "cube.obj"
    obj.write_text(
        "# a tiny mesh\n"
        "v 0 0 0\n"
        "v 1 0 0\n"
        "v 0 1 0\n"
        "vn 0 0 1\n"
        "f 1 2 3\n"
        "f 3 2 1\n",
        encoding="utf-8",
    )
    assert summarise_obj(obj) == (3, 2)


def test_summarise_obj_missing_file_returns_zeros(tmp_path: Path) -> None:
    assert summarise_obj(tmp_path / "absent.obj") == (0, 0)


def test_create_widget_obj_shows_counts(tmp_path: Path, qtbot) -> None:
    obj = tmp_path / "shape.obj"
    obj.write_text("v 0 0 0\nv 1 1 1\nf 1 1 1\n", encoding="utf-8")

    widget = create_widget(obj)
    qtbot.addWidget(widget)

    assert isinstance(widget, QLabel)
    text = widget.text()
    assert "shape.obj" in text
    assert "2 vertices" in text
    assert "1 faces" in text


def test_create_widget_stl_shows_byte_size(tmp_path: Path, qtbot) -> None:
    stl = tmp_path / "part.stl"
    stl.write_bytes(b"solid part\nendsolid part\n")

    widget = create_widget(stl)
    qtbot.addWidget(widget)

    assert isinstance(widget, QLabel)
    text = widget.text()
    assert "part.stl" in text
    assert f"{stl.stat().st_size} bytes" in text


def test_create_widget_missing_stl_reports_zero_bytes(tmp_path: Path, qtbot) -> None:
    widget = create_widget(tmp_path / "gone.ply")
    qtbot.addWidget(widget)

    assert isinstance(widget, QLabel)
    assert "0 bytes" in widget.text()


def test_register_installs_viewer_for_all_model_extensions() -> None:
    registry = PluginRegistry()
    register(registry)

    assert registry.handled_extensions() == frozenset(MODEL_EXTENSIONS)
    for ext in MODEL_EXTENSIONS:
        resolved = registry.viewer_for(f"model{ext}")
        assert resolved is not None
        assert resolved.name == "3D model info"
