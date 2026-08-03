"""Example plugin: a lightweight information preview for 3D model files.

It demonstrates the whole extension contract without pulling in a heavy 3D
engine: it claims the ``.obj``/``.stl``/``.ply`` extensions and, when one is
selected, shows a small summary (vertex/face counts). A real 3D plugin would
return an OpenGL widget from ``create_widget`` instead — the host does not care
what widget it gets. Copy this file into the user plugins folder as a starting
point.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget

    from myimages.core.plugins import PluginRegistry

MODEL_EXTENSIONS = (".obj", ".stl", ".ply")


def summarise_obj(path: Path) -> tuple[int, int]:
    """Count vertices and faces in an ASCII OBJ file (best effort)."""
    vertices = 0
    faces = 0
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                if line.startswith("v "):
                    vertices += 1
                elif line.startswith("f "):
                    faces += 1
    except OSError:
        pass
    return vertices, faces


def create_widget(path: Path) -> QWidget:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QLabel

    label = QLabel()
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setObjectName("muted")
    if path.suffix.lower() == ".obj":
        vertices, faces = summarise_obj(path)
        label.setText(
            f"3D model: {path.name}\n\n{vertices} vertices · {faces} faces\n\n"
            "(example plugin — swap in an OpenGL view for real 3D)"
        )
    else:
        size = path.stat().st_size if path.exists() else 0
        label.setText(f"3D model: {path.name}\n\n{size} bytes\n\n(example plugin)")
    return label


def register(registry: PluginRegistry) -> None:
    """Entry point the host calls to install this plugin's viewer."""
    registry.register_viewer(
        name="3D model info",
        extensions=MODEL_EXTENSIONS,
        create_widget=create_widget,
        description="Shows basic info for OBJ/STL/PLY files.",
    )
