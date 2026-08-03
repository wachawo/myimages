"""Delete files, preferring the system trash when Send2Trash is installed.

Moving to trash is recoverable, so it is the default; if the optional package
is absent the caller can still permanently remove files. Keeping this in one
place means both the Delete key and the duplicate finder behave identically.
"""

from __future__ import annotations

import importlib.util
from collections.abc import Iterable
from pathlib import Path


def is_trash_available() -> bool:
    return importlib.util.find_spec("send2trash") is not None


def delete_file(path: str | Path, prefer_trash: bool = True) -> None:
    """Delete one file, to the trash when possible and requested."""
    target = Path(path)
    if prefer_trash and is_trash_available():
        import send2trash

        send2trash.send2trash(str(target))
        return
    target.unlink()


def delete_files(paths: Iterable[str | Path], prefer_trash: bool = True) -> list[Path]:
    """Delete several files; returns the ones that were removed."""
    removed: list[Path] = []
    for path in paths:
        target = Path(path)
        try:
            delete_file(target, prefer_trash=prefer_trash)
        except OSError:
            continue
        removed.append(target)
    return removed
