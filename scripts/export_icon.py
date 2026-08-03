#!/usr/bin/env python3
"""Render the application icon to a PNG for packaging (.desktop / AppImage).

Usage: ``python scripts/export_icon.py assets/myimages.png [size]``
"""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    destination = Path(sys.argv[1] if len(sys.argv) > 1 else "assets/myimages.png")
    size = int(sys.argv[2]) if len(sys.argv) > 2 else 256
    destination.parent.mkdir(parents=True, exist_ok=True)

    import os

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from myimages.theme import app_icon

    QApplication(sys.argv[:1])
    pixmap = app_icon().pixmap(size, size)
    pixmap.save(str(destination), "PNG")
    print(f"wrote {destination} ({size}x{size})")


if __name__ == "__main__":
    main()
