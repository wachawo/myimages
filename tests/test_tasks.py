"""Tests for :mod:`myimages.gui.tasks`.

Qt's signal machinery needs a ``QApplication``, so every test requests the
``qtbot`` fixture. Calling ``BackgroundTask.run()`` directly emits on the calling
thread, so a plain collector slot observes the result synchronously; the
threaded ``run_in_background`` path is driven with a real ``QThreadPool`` and
``qtbot.waitSignal``. A ``threading.Event`` gate keeps each worker parked until
the spy is connected, removing any race between scheduling and emission.
"""

from __future__ import annotations

import threading

from PySide6.QtCore import QThreadPool

from myimages.gui.tasks import BackgroundTask, run_in_background


def test_run_success_emits_finished_with_return_value(qtbot):
    received: list[object] = []
    task = BackgroundTask(lambda: 21 * 2)
    task.signals.finished.connect(received.append)

    task.run()

    assert received == [42]


def test_run_passes_args_and_kwargs(qtbot):
    received: list[object] = []
    task = BackgroundTask(lambda a, b: a + b, 3, b=4)
    task.signals.finished.connect(received.append)

    task.run()

    assert received == [7]


def test_run_failure_emits_failed_with_message(qtbot):
    received: list[str] = []

    def boom():
        raise ValueError("boom")

    task = BackgroundTask(boom)
    task.signals.failed.connect(received.append)

    task.run()

    assert received == ["boom"]


def test_run_in_background_emits_finished_on_worker_thread(qtbot):
    pool = QThreadPool()
    received: list[object] = []
    gate = threading.Event()

    def work():
        gate.wait(2)
        return "done"

    task = run_in_background(work, received.append, pool=pool)
    with qtbot.waitSignal(task.signals.finished, timeout=3000) as blocker:
        gate.set()

    assert blocker.args == ["done"]
    qtbot.waitUntil(lambda: received == ["done"], timeout=1000)
    pool.waitForDone(3000)


def test_run_in_background_calls_on_failed(qtbot):
    pool = QThreadPool()
    finished: list[object] = []
    failures: list[str] = []
    gate = threading.Event()

    def boom():
        gate.wait(2)
        raise RuntimeError("nope")

    task = run_in_background(boom, finished.append, failures.append, pool=pool)
    with qtbot.waitSignal(task.signals.failed, timeout=3000):
        gate.set()

    qtbot.waitUntil(lambda: failures == ["nope"], timeout=1000)
    assert finished == []
    pool.waitForDone(3000)


def test_run_in_background_on_failed_none_does_not_crash(qtbot):
    pool = QThreadPool()
    finished: list[object] = []
    gate = threading.Event()

    def boom():
        gate.wait(2)
        raise RuntimeError("silent")

    task = run_in_background(boom, finished.append, on_failed=None, pool=pool)
    with qtbot.waitSignal(task.signals.failed, timeout=3000):
        gate.set()

    assert finished == []
    pool.waitForDone(3000)
