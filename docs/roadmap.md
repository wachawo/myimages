# Roadmap & plugin API

## Writing a plugin

A plugin is a plain Python file placed in `~/.myimages/plugins/` (or bundled in
`myimages/plugins/`). It must define a module-level `register(registry)`
function. Inside it, claim one or more file extensions and provide a factory
that builds a preview widget:

```python
from pathlib import Path

def create_widget(path: Path):
    from PySide6.QtWidgets import QLabel
    return QLabel(f"Custom preview for {path.name}")

def register(registry) -> None:
    registry.register_viewer(
        name="My format",
        extensions=(".xyz",),
        create_widget=create_widget,
        description="Preview .xyz files",
    )
```

When a file with a registered extension is selected, the preview pane shows the
widget your factory returns instead of the built-in image/video view. Plugins
are loaded at startup; a broken plugin is logged and skipped, never crashing the
app. See `myimages/plugins/three_d_preview.py` for a complete example (OBJ/STL
model info — swap the `QLabel` for an OpenGL view to get real 3D).

The registry (`myimages/core/plugins.py`) is intentionally Qt-agnostic: it only
stores callables, so plugin resolution is unit-testable without a display.

## Planned

- Toolbar plugins (actions), not just viewers.
- EXIF panel and capture-date sort.
- Non-blocking previews for very large images (progressive/threaded decode).
- Poster-frame thumbnails for sub-second clips (current ffmpeg seek can miss
  the last frame of ~1s videos).
- Lossless JPEG rotate; more crop-tool handles (drag existing edges).
- Optional GPU-accelerated video preview.
