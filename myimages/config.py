"""Application settings, stored as a single human-readable JSON file.

A plain dataclass keeps the settings self-documenting and lets every module
depend on typed attributes instead of stringly-typed lookups. Persistence is
deliberately independent of Qt so the settings can be created and asserted on
in tests without a running ``QApplication``.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

from myimages.paths import data_dir

SortKey = str  # one of SORT_KEYS

SORT_KEYS: tuple[str, ...] = ("name", "size", "resolution", "modified")
THEMES: tuple[str, ...] = ("dark", "light")


@dataclass
class Settings:
    """Everything the user can configure, with safe defaults."""

    # Where files come from: one folder, optionally scanned recursively.
    last_folder: str = ""
    recursive_scan: bool = False

    # Noticing changes made to that folder by other programs.
    watch_folder: bool = True
    watch_interval_seconds: int = 10
    verify_checksums: bool = False

    # File list presentation.
    sort_key: SortKey = "name"
    sort_descending: bool = False
    show_images: bool = True
    show_videos: bool = True
    favorites_only: bool = False
    favorites: list[str] = field(default_factory=list)
    list_view_mode: str = "grid"  # one of VIEW_MODES: grid | list | table
    selection_mode: bool = False  # tap-to-select with a visible check circle

    # Whether the desktop entry has ever been offered. Set once, whether the
    # write worked or not: a user who deleted the entry deliberately should not
    # find it back the next morning.
    desktop_entry_attempted: bool = False

    # Layout.
    file_list_on_left: bool = False
    # How many thumbnails fit across the file list. The panel's width follows
    # from this, which is why the divider is not draggable: a width that is not
    # a whole number of thumbnails just leaves a ragged gap.
    grid_columns: int = 2
    thumbnail_size: int = 128
    window_width: int = 1280
    window_height: int = 820
    theme: str = "dark"

    # PDF export.
    pdf_quality: int = 85
    pdf_grayscale: bool = False
    pdf_max_edge_px: int = 2200
    pdf_target_mib: float = 0.0  # 0 disables the size budget

    # GIF export.
    gif_fps: int = 12
    gif_width: int = 480

    def is_favorite(self, path: str | Path) -> bool:
        return str(path) in set(self.favorites)

    def toggle_favorite(self, path: str | Path) -> bool:
        """Add or remove a favorite; returns the new favorite state."""
        text = str(path)
        current = list(self.favorites)
        if text in current:
            current.remove(text)
            self.favorites = current
            return False
        current.append(text)
        self.favorites = current
        return True


def settings_path() -> Path:
    return data_dir() / "settings.json"


def load_settings() -> Settings:
    """Read settings from disk, ignoring unknown or malformed keys."""
    path = settings_path()
    if not path.exists():
        return Settings()
    try:
        raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return Settings()
    known = {item.name for item in fields(Settings)}
    return Settings(**{key: value for key, value in raw.items() if key in known})


def save_settings(settings: Settings) -> None:
    """Write settings to disk as pretty-printed JSON."""
    settings_path().write_text(
        json.dumps(asdict(settings), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
