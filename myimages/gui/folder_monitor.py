"""Keep the gallery honest about a folder that changes while it is open.

Two mechanisms cover each other. ``QFileSystemWatcher`` reports directory
changes the moment they happen, so deleting a photo elsewhere updates the list
immediately and costs nothing while nothing happens -- but it is unreliable on
network shares and can hit per-process watch limits. A slow timer therefore
re-checks anyway, turning the watcher into an optimisation rather than a
dependency.

Every check runs on a worker thread and compares only ``stat`` data, so a large
folder costs a directory listing rather than a read of every photo. Bursts (a
file manager copying in a hundred files) collapse into one check through a short
debounce, and overlapping checks are refused outright, which together bound the
work no matter how noisy the folder gets.
"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QObject, QTimer, Signal

from myimages.core import scanner
from myimages.core.media import MediaFile
from myimages.core.watcher import (
    CHECKSUMS_PER_PASS,
    FileStamp,
    carry_over_checksums,
    checksum_batch,
    diff_stamps,
    stamp_media,
    verify_checksums,
)
from myimages.gui.task_runner import Runner, threaded_runner

# A burst of filesystem events is one user action, so wait for it to settle
# rather than re-scanning per event.
DEBOUNCE_MS = 400

# Watching a deep tree costs one inotify handle per directory; past this many the
# periodic check alone carries the load.
MAX_WATCHED_DIRECTORIES = 256


class FolderMonitor(QObject):
    """Emits :class:`FolderChanges` when the watched folder stops matching."""

    changed = Signal(object)

    def __init__(
        self,
        parent: QObject | None = None,
        runner: Runner = threaded_runner,
    ) -> None:
        super().__init__(parent)
        self.runner = runner
        self.folder: Path | None = None
        self.recursive = False
        self.verify = False
        self.interval_seconds = 0
        self.stamps: dict[str, FileStamp] = {}
        self.cursor = 0
        self.busy = False
        # Something changed while a check was running: re-check once it ends.
        self.pending = False
        # Bumped whenever what we watch changes, so a check that finishes
        # afterwards can tell that its answer is about the wrong folder.
        self.generation = 0
        self.checking_generation = -1

        self.watcher = QFileSystemWatcher(self)
        self.watcher.directoryChanged.connect(self.schedule_check)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.check_now)
        self.debounce = QTimer(self)
        self.debounce.setSingleShot(True)
        self.debounce.setInterval(DEBOUNCE_MS)
        self.debounce.timeout.connect(self.check_now)

    # -- lifecycle ---------------------------------------------------------

    def start(
        self,
        folder: Path,
        files: list[MediaFile],
        *,
        recursive: bool = False,
        verify: bool = False,
        interval_seconds: int = 10,
    ) -> None:
        """Watch ``folder``, treating ``files`` as the state to compare against.

        Seeding from the caller's own scan means starting the monitor costs
        nothing, and guarantees the first check reports real changes instead of
        announcing every existing file as new.
        """
        self.stop()
        self.generation += 1
        self.folder = folder
        self.recursive = recursive
        self.verify = verify
        self.interval_seconds = interval_seconds
        self.stamps = stamp_media(files)
        self.cursor = 0
        if not str(folder).strip() or not folder.is_dir():
            # An empty path resolves to the process working directory, which is
            # never what the user meant to watch.
            self.folder = None
            return
        self.watcher.addPaths([str(path) for path in self.watched_directories()])
        self.timer.start(max(1, interval_seconds) * 1000)

    def stop(self) -> None:
        self.generation += 1
        self.timer.stop()
        self.debounce.stop()
        watched = self.watcher.directories()
        if watched:
            self.watcher.removePaths(watched)
        self.folder = None

    def watched_directories(self) -> list[Path]:
        """The folder itself, plus sub-folders when scanning recursively."""
        if self.folder is None:
            return []
        directories = [self.folder]
        if not self.recursive:
            return directories
        # os.walk hands back sub-directory names directly, so a folder holding
        # a hundred thousand files is never stat-ed one entry at a time just to
        # find the handful of directories inside it.
        for root, subdirectories, _files in os.walk(self.folder):
            for name in subdirectories:
                directories.append(Path(root) / name)
                if len(directories) >= MAX_WATCHED_DIRECTORIES:
                    return directories
        return directories

    # -- checking ----------------------------------------------------------

    def schedule_check(self, path: str = "") -> None:
        """Coalesce a burst of filesystem events into a single check."""
        if self.folder is not None:
            self.debounce.start()

    def check_now(self) -> None:
        """Compare the folder against the last snapshot on a worker thread."""
        folder = self.folder
        if folder is None:
            return
        if self.busy:
            # Refusing an overlapping check is right, but silently dropping the
            # event behind it would hide that change until the next slow tick.
            self.pending = True
            return
        self.busy = True
        self.checking_generation = self.generation
        previous = dict(self.stamps)
        recursive, verify, cursor = self.recursive, self.verify, self.cursor

        def work() -> tuple[dict[str, FileStamp], list[str]]:
            found = scanner.scan_directory(folder, recursive=recursive)
            current = carry_over_checksums(previous, stamp_media(found))
            content_changed: list[str] = []
            if verify:
                batch = checksum_batch(sorted(current), cursor, CHECKSUMS_PER_PASS)
                current, content_changed = verify_checksums(current, batch)
            return current, content_changed

        self.runner(work, self.apply_snapshot, self.handle_failure)

    def apply_snapshot(self, result: object) -> None:
        """Adopt a finished snapshot and announce whatever moved."""
        self.busy = False
        if self.folder is None or self.checking_generation != self.generation:
            return  # stopped or re-pointed while the check was in flight
        if not isinstance(result, tuple):
            return
        current, content_changed = result
        if not current and not self.folder_is_readable():
            # A folder that briefly cannot be listed (unmounted share, revoked
            # permission) is not the same as one whose files were all deleted.
            return
        changes = diff_stamps(self.stamps, current, content_changed)
        self.stamps = current
        self.cursor += CHECKSUMS_PER_PASS
        self.drain_pending()
        if changes.has_changes:
            self.changed.emit(changes)

    def folder_is_readable(self) -> bool:
        """Whether the watched folder can still be listed at all."""
        if self.folder is None:
            return False
        try:
            next(iter(self.folder.iterdir()), None)
        except OSError:
            return False
        return self.folder.is_dir()

    def drain_pending(self) -> None:
        """Run the check that was refused while this one was in flight."""
        if self.pending:
            self.pending = False
            self.schedule_check()

    def handle_failure(self, message: str) -> None:
        # A failed check is not worth interrupting the user for; the next tick
        # simply tries again.
        self.busy = False
        self.drain_pending()

    def adopt(self, files: list[MediaFile]) -> None:
        """Re-seed from a fresh scan the window performed for its own reasons.

        Checksums already computed are carried across, so adopting does not
        throw away verification work and reopen the very gap md5 exists to close.
        """
        self.stamps = carry_over_checksums(self.stamps, stamp_media(files))
