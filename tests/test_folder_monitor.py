"""Behavioural tests for :mod:`myimages.gui.folder_monitor`.

The monitor's whole job is to notice that a folder stopped matching what the
gallery is showing, so the tests do to the folder exactly what another program
would: delete a photo, drop a new one in, re-save one, or rewrite one so
carefully that ``stat`` cannot tell. Every check then runs through
``synchronous_runner``, which makes ``check_now()`` finish inline so the
resulting ``changed`` emission is observable on the spot instead of after a
thread hop.

``qtbot`` is requested everywhere because the monitor owns a ``QTimer`` and a
``QFileSystemWatcher`` and therefore needs a ``QApplication``. The one test that
exercises the debounce lets a real event loop run, since collapsing a burst of
directory events into a single check is a timing behaviour that cannot be
observed inline.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PIL import Image

from myimages.core import scanner
from myimages.core.watcher import FolderChanges
from myimages.gui.folder_monitor import (
    DEBOUNCE_MS,
    MAX_WATCHED_DIRECTORIES,
    FolderMonitor,
)
from myimages.gui.task_runner import Runner, synchronous_runner


def start_monitor(
    folder: Path,
    runner: Runner = synchronous_runner,
    **options: Any,
) -> tuple[FolderMonitor, list[FolderChanges]]:
    """Watch ``folder`` seeded from its current contents, recording announcements.

    Seeding from a real scan is what the window does, so the baseline the tests
    start from is the same one production code starts from.
    """
    monitor = FolderMonitor(runner=runner)
    seen: list[FolderChanges] = []
    monitor.changed.connect(seen.append)
    recursive = bool(options.get("recursive", False))
    files = scanner.scan_directory(folder, recursive=recursive)
    monitor.start(folder, files, **options)
    return monitor, seen


def write_image(path: Path, size: tuple[int, int] = (30, 20)) -> Path:
    """Write a real image at ``path`` (a genuine file for the scanner to find)."""
    Image.new("RGB", size, (120, 30, 200)).save(path)
    return path


def rewrite_in_place(path: Path) -> None:
    """Replace a file's bytes while preserving its size and modified time.

    This is the one kind of edit ``stat`` is blind to, so the helper asserts
    that the metadata really did stay put -- otherwise a verification test could
    pass for the wrong reason.
    """
    before = os.stat(path)
    path.write_bytes(path.read_bytes()[::-1])
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    after = os.stat(path)
    assert after.st_size == before.st_size
    assert after.st_mtime == before.st_mtime


# --------------------------------------------------------------------------
# starting up
# --------------------------------------------------------------------------


def test_start_seeds_from_the_given_files_and_reports_no_change(
    qtbot, image_dir: Path
) -> None:
    monitor, seen = start_monitor(image_dir)

    monitor.check_now()

    assert seen == []
    assert monitor.timer.isActive()
    assert monitor.watcher.directories() == [str(image_dir)]


def test_start_on_something_that_is_not_a_folder_does_not_watch(
    qtbot, make_image: Callable[..., Path]
) -> None:
    photo = make_image("lonely.png")
    monitor = FolderMonitor(runner=synchronous_runner)
    seen: list[FolderChanges] = []
    monitor.changed.connect(seen.append)

    monitor.start(photo, [])

    assert not monitor.timer.isActive()
    assert monitor.watcher.directories() == []
    monitor.check_now()
    assert seen == []


# --------------------------------------------------------------------------
# what a check reports
# --------------------------------------------------------------------------


def test_a_deleted_file_is_reported_as_removed(qtbot, image_dir: Path) -> None:
    monitor, seen = start_monitor(image_dir)
    gone = image_dir / "bravo.jpg"
    gone.unlink()

    monitor.check_now()

    assert len(seen) == 1
    assert seen[0].removed == (str(gone),)
    assert seen[0].added == ()
    assert seen[0].modified == ()

    # The snapshot moved on, so the same deletion is not announced twice.
    monitor.check_now()
    assert len(seen) == 1


def test_a_new_file_is_reported_as_added(qtbot, image_dir: Path) -> None:
    monitor, seen = start_monitor(image_dir)
    fresh = write_image(image_dir / "delta.png")

    monitor.check_now()

    assert len(seen) == 1
    assert seen[0].added == (str(fresh),)
    assert seen[0].removed == ()
    assert seen[0].modified == ()


def test_a_rewritten_file_is_reported_as_modified(qtbot, image_dir: Path) -> None:
    monitor, seen = start_monitor(image_dir)
    target = image_dir / "alpha.png"
    before = target.stat().st_size

    write_image(target, size=(240, 180))
    assert target.stat().st_size != before

    monitor.check_now()

    assert len(seen) == 1
    assert seen[0].modified == (str(target),)
    assert seen[0].stale_paths == (str(target),)


def test_a_file_with_only_a_new_modified_time_is_reported_as_modified(
    qtbot, image_dir: Path
) -> None:
    monitor, seen = start_monitor(image_dir)
    target = image_dir / "charlie.png"
    later = target.stat().st_mtime + 120
    os.utime(target, (later, later))

    monitor.check_now()

    assert len(seen) == 1
    assert seen[0].modified == (str(target),)


# --------------------------------------------------------------------------
# stopping, re-seeding and overlapping work
# --------------------------------------------------------------------------


def test_stop_halts_the_timers_and_makes_checks_do_nothing(
    qtbot, image_dir: Path
) -> None:
    monitor, seen = start_monitor(image_dir)
    monitor.schedule_check(str(image_dir))
    assert monitor.debounce.isActive()

    monitor.stop()

    assert not monitor.timer.isActive()
    assert not monitor.debounce.isActive()
    assert monitor.watcher.directories() == []

    (image_dir / "alpha.png").unlink()
    monitor.check_now()

    assert seen == []


def test_adopt_reseeds_the_baseline_so_a_known_change_is_not_reported(
    qtbot, image_dir: Path
) -> None:
    monitor, seen = start_monitor(image_dir)
    (image_dir / "alpha.png").unlink()

    monitor.adopt(scanner.scan_directory(image_dir))
    monitor.check_now()

    assert seen == []

    # Re-seeding must not switch detection off: the next change still lands.
    later = image_dir / "bravo.jpg"
    later.unlink()
    monitor.check_now()

    assert len(seen) == 1
    assert seen[0].removed == (str(later),)


def test_a_second_check_is_refused_while_one_is_still_running(
    qtbot, image_dir: Path
) -> None:
    parked: list[Callable[[], Any]] = []

    def parked_runner(
        function: Callable[[], Any],
        on_finished: Callable[[Any], None],
        on_failed: Callable[[str], None] | None = None,
    ) -> None:
        parked.append(function)  # never completes: the check stays in flight

    monitor, seen = start_monitor(image_dir, runner=parked_runner)
    (image_dir / "alpha.png").unlink()

    monitor.check_now()
    monitor.check_now()

    assert len(parked) == 1
    assert seen == []


def test_a_result_arriving_after_stop_is_discarded(qtbot, image_dir: Path) -> None:
    parked: list[tuple[Callable[[], Any], Callable[[Any], None]]] = []

    def parked_runner(
        function: Callable[[], Any],
        on_finished: Callable[[Any], None],
        on_failed: Callable[[str], None] | None = None,
    ) -> None:
        parked.append((function, on_finished))

    monitor, seen = start_monitor(image_dir, runner=parked_runner)
    (image_dir / "alpha.png").unlink()
    monitor.check_now()

    work, deliver = parked[0]
    result = work()  # the check finishes...
    monitor.stop()  # ...but the window closed the folder meanwhile
    deliver(result)

    assert seen == []
    assert monitor.busy is False


def test_a_failed_check_does_not_wedge_the_monitor(qtbot, image_dir: Path) -> None:
    attempts: list[Callable[[], Any]] = []

    def flaky_runner(
        function: Callable[[], Any],
        on_finished: Callable[[Any], None],
        on_failed: Callable[[str], None] | None = None,
    ) -> None:
        attempts.append(function)
        if len(attempts) == 1 and on_failed is not None:
            on_failed("the share went away")
        else:
            synchronous_runner(function, on_finished, on_failed)

    monitor, seen = start_monitor(image_dir, runner=flaky_runner)
    gone = image_dir / "alpha.png"
    gone.unlink()

    monitor.check_now()

    assert seen == []  # a failed check is not worth interrupting anyone for
    assert monitor.busy is False

    monitor.check_now()

    assert len(seen) == 1
    assert seen[0].removed == (str(gone),)


# --------------------------------------------------------------------------
# filesystem events and the debounce
# --------------------------------------------------------------------------


def test_schedule_check_arms_the_debounce_only_while_watching(
    qtbot, image_dir: Path
) -> None:
    monitor = FolderMonitor(runner=synchronous_runner)

    monitor.schedule_check(str(image_dir))

    assert not monitor.debounce.isActive()

    monitor.start(image_dir, scanner.scan_directory(image_dir))
    monitor.schedule_check(str(image_dir))

    assert monitor.debounce.isActive()


def test_a_burst_of_directory_events_collapses_into_one_check(
    qtbot, image_dir: Path
) -> None:
    monitor, seen = start_monitor(image_dir)
    gone = image_dir / "alpha.png"
    gone.unlink()

    with qtbot.waitSignal(monitor.changed, timeout=DEBOUNCE_MS * 10):
        monitor.schedule_check(str(image_dir))
        monitor.schedule_check(str(image_dir))
        monitor.schedule_check(str(image_dir))

    assert len(seen) == 1
    assert seen[0].removed == (str(gone),)


# --------------------------------------------------------------------------
# which directories are watched
# --------------------------------------------------------------------------


def test_watched_directories_is_empty_when_nothing_is_watched(qtbot) -> None:
    monitor = FolderMonitor(runner=synchronous_runner)

    assert monitor.watched_directories() == []


def test_watched_directories_is_just_the_folder_when_not_recursive(
    qtbot, image_dir: Path
) -> None:
    (image_dir / "holiday").mkdir()
    monitor = FolderMonitor(runner=synchronous_runner)

    monitor.start(image_dir, scanner.scan_directory(image_dir))

    assert monitor.watched_directories() == [image_dir]


def test_watched_directories_includes_sub_folders_when_recursive(
    qtbot, image_dir: Path
) -> None:
    nested = image_dir / "holiday" / "day two"
    nested.mkdir(parents=True)
    monitor = FolderMonitor(runner=synchronous_runner)

    monitor.start(
        image_dir,
        scanner.scan_directory(image_dir, recursive=True),
        recursive=True,
    )

    assert set(monitor.watched_directories()) == {
        image_dir,
        image_dir / "holiday",
        nested,
    }


def test_watched_directories_stops_at_the_handle_budget(qtbot, tmp_path: Path) -> None:
    folder = tmp_path / "deep"
    folder.mkdir()
    for number in range(MAX_WATCHED_DIRECTORIES + 10):
        (folder / f"sub{number:03d}").mkdir()
    monitor = FolderMonitor(runner=synchronous_runner)

    monitor.start(folder, [], recursive=True)

    assert len(monitor.watched_directories()) == MAX_WATCHED_DIRECTORIES


def test_an_unreadable_entry_does_not_break_the_watch_list(
    qtbot, image_dir: Path
) -> None:
    """A folder we may not enter must not stop the others being watched."""
    import os

    readable = image_dir / "holiday"
    readable.mkdir()
    forbidden = image_dir / "forbidden"
    forbidden.mkdir()
    (forbidden / "deeper").mkdir()
    os.chmod(forbidden, 0o000)
    monitor = FolderMonitor(runner=synchronous_runner)
    try:
        monitor.start(image_dir, [], recursive=True)
        watched = set(monitor.watched_directories())
        # The readable folders are all present; whatever hides inside the
        # unreadable one simply cannot be reached, and that is not an error.
        assert {image_dir, readable} <= watched
        assert forbidden / "deeper" not in watched
    finally:
        os.chmod(forbidden, 0o755)


# --------------------------------------------------------------------------
# checksum verification
# --------------------------------------------------------------------------


def test_verification_notices_a_rewrite_that_stat_cannot_see(
    qtbot, image_dir: Path
) -> None:
    monitor, seen = start_monitor(image_dir, verify=True)

    monitor.check_now()  # first pass only records checksums

    assert seen == []

    target = image_dir / "alpha.png"
    rewrite_in_place(target)

    monitor.check_now()

    assert len(seen) == 1
    assert seen[0].modified == (str(target),)
    assert seen[0].added == ()
    assert seen[0].removed == ()


def test_without_verification_an_in_place_rewrite_goes_unnoticed(
    qtbot, image_dir: Path
) -> None:
    monitor, seen = start_monitor(image_dir)

    monitor.check_now()
    rewrite_in_place(image_dir / "alpha.png")
    monitor.check_now()

    assert seen == []


# -- hardening against races and unreadable folders -------------------------


def test_a_check_finishing_after_a_re_point_is_discarded(qtbot, tmp_path, make_image):
    """Its answer describes the folder we just stopped looking at."""
    from myimages.core.media import build_media_file
    from myimages.gui.folder_monitor import FolderMonitor
    from myimages.gui.task_runner import synchronous_runner

    folder = tmp_path / "watched"
    folder.mkdir()
    known = [build_media_file(make_image("kept.png"))]
    monitor = FolderMonitor(runner=synchronous_runner)
    monitor.start(folder, known)
    seen: list[object] = []
    monitor.changed.connect(seen.append)

    monitor.busy = True
    monitor.checking_generation = monitor.generation
    monitor.generation += 1  # as if start() had been called for another folder
    monitor.apply_snapshot(({}, []))

    assert seen == []  # nothing announced from the stale check
    assert len(monitor.stamps) == 1  # and the baseline is untouched


def test_a_folder_that_cannot_be_listed_is_not_read_as_emptied(
    qtbot, tmp_path, make_image
):
    import os

    from myimages.core.media import build_media_file
    from myimages.gui.folder_monitor import FolderMonitor
    from myimages.gui.task_runner import synchronous_runner

    folder = tmp_path / "locked"
    folder.mkdir()
    from PIL import Image

    Image.new("RGB", (10, 10), (0, 0, 0)).save(folder / "inside.png")
    known = [build_media_file(folder / "inside.png")]
    monitor = FolderMonitor(runner=synchronous_runner)
    monitor.start(folder, known)
    seen: list[object] = []
    monitor.changed.connect(seen.append)

    os.chmod(folder, 0o000)
    try:
        monitor.check_now()
        assert seen == []  # no "everything was deleted" announcement
        assert len(monitor.stamps) == 1
    finally:
        os.chmod(folder, 0o755)


def test_adopt_keeps_checksums_already_computed(qtbot, tmp_path, make_image):
    """Re-seeding must not throw away the verification md5 exists to provide."""
    from dataclasses import replace

    from myimages.core.media import build_media_file
    from myimages.gui.folder_monitor import FolderMonitor
    from myimages.gui.task_runner import synchronous_runner

    media = build_media_file(make_image("photo.png"))
    monitor = FolderMonitor(runner=synchronous_runner)
    monitor.start(media.path.parent, [media])
    key = str(media.path)
    monitor.stamps[key] = replace(monitor.stamps[key], checksum="deadbeef")

    monitor.adopt([media])

    assert monitor.stamps[key].checksum == "deadbeef"


def test_a_change_arriving_during_a_check_is_not_lost(qtbot, tmp_path, make_image):
    """Refusing an overlapping check must not swallow the event behind it."""
    from myimages.core.media import build_media_file
    from myimages.gui.folder_monitor import FolderMonitor

    folder = tmp_path / "busy"
    folder.mkdir()
    monitor = FolderMonitor(runner=lambda work, ok, fail=None: None)  # never finishes
    monitor.start(folder, [build_media_file(make_image("a.png"))])

    monitor.check_now()  # takes the slot and stays in flight
    assert monitor.busy is True
    assert monitor.pending is False

    monitor.check_now()  # a second event lands while the first is running
    assert monitor.pending is True

    monitor.busy = False
    monitor.checking_generation = monitor.generation
    monitor.apply_snapshot((dict(monitor.stamps), []))

    assert monitor.pending is False
    assert monitor.debounce.isActive()  # the missed check was re-armed


def test_a_failed_check_also_re_arms_a_pending_one(qtbot, tmp_path):
    from myimages.gui.folder_monitor import FolderMonitor

    folder = tmp_path / "failing"
    folder.mkdir()
    monitor = FolderMonitor(runner=lambda work, ok, fail=None: None)
    monitor.start(folder, [])
    monitor.busy = True
    monitor.pending = True

    monitor.handle_failure("disk went away")

    assert monitor.busy is False
    assert monitor.pending is False
    assert monitor.debounce.isActive()


def test_watching_a_big_tree_stops_at_the_cap(qtbot, tmp_path):
    """A file-heavy tree must not be walked to the end to find its folders."""
    from myimages.gui.folder_monitor import MAX_WATCHED_DIRECTORIES, FolderMonitor

    root = tmp_path / "tree"
    root.mkdir()
    for index in range(MAX_WATCHED_DIRECTORIES + 20):
        (root / f"d{index:04}").mkdir()

    monitor = FolderMonitor(runner=lambda *args, **kwargs: None)
    monitor.folder = root
    monitor.recursive = True

    assert len(monitor.watched_directories()) == MAX_WATCHED_DIRECTORIES
