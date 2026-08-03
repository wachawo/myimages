"""Run slow work off the UI thread so the interface never freezes.

Long operations (ffmpeg runs, PDF assembly, duplicate scanning) are wrapped in
a :class:`BackgroundTask` and dispatched to a shared ``QThreadPool``. Results
and errors come back as Qt signals, which are delivered on the UI thread, so
callers can update widgets safely.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot


class TaskSignals(QObject):
    """Signals emitted by a :class:`BackgroundTask`."""

    finished = Signal(object)
    failed = Signal(str)


class BackgroundTask(QRunnable):
    """A callable executed on a worker thread, reporting via signals."""

    def __init__(self, function: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self.function = function
        self.args = args
        self.kwargs = kwargs
        self.signals = TaskSignals()
        # Manage the lifetime in Python (see run_in_background); if C++ deleted
        # the runnable after run(), the Python wrapper would dangle.
        self.setAutoDelete(False)

    @Slot()
    def run(self) -> None:
        # ``suppress`` guards the emit: the signals object may already be gone if
        # the app is shutting down while this task finishes on a worker thread.
        try:
            result = self.function(*self.args, **self.kwargs)
        except Exception as error:  # noqa: BLE001 - forwarded to the UI intact
            with contextlib.suppress(RuntimeError):
                self.signals.failed.emit(str(error))
        else:
            with contextlib.suppress(RuntimeError):
                self.signals.finished.emit(result)


# Strong references to in-flight tasks. QThreadPool.start() does NOT keep the
# Python wrapper of a QRunnable alive, so without this the task and its signals
# would be garbage-collected before the worker thread runs and the callbacks
# would silently never fire (and could crash under a nested event loop).
LIVE_TASKS: set[BackgroundTask] = set()


def run_in_background(
    function: Callable[..., Any],
    on_finished: Callable[[Any], None],
    on_failed: Callable[[str], None] | None = None,
    pool: QThreadPool | None = None,
) -> BackgroundTask:
    """Schedule ``function`` on the thread pool and wire up its callbacks."""
    task = BackgroundTask(function)
    LIVE_TASKS.add(task)
    task.signals.finished.connect(on_finished)
    if on_failed is not None:
        task.signals.failed.connect(on_failed)
    task.signals.finished.connect(lambda result: LIVE_TASKS.discard(task))
    task.signals.failed.connect(lambda message: LIVE_TASKS.discard(task))
    (pool or QThreadPool.globalInstance()).start(task)
    return task
