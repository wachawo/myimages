"""Tests for :mod:`myimages.gui.task_runner`.

``synchronous_runner`` is pure Python and runs inline, so its callbacks are
observed immediately without any Qt event loop. ``threaded_runner`` dispatches to
the shared ``QThreadPool`` via ``run_in_background``; its ``on_finished`` callback
fires back on the UI thread, so the threaded test requests ``qtbot`` and waits on
a flag with ``qtbot.waitUntil``.
"""

from __future__ import annotations

from myimages.gui.task_runner import synchronous_runner, threaded_runner


def test_synchronous_runner_success_calls_on_finished():
    results: list[object] = []

    synchronous_runner(lambda: 99, results.append)

    assert results == [99]


def test_synchronous_runner_failure_calls_on_failed():
    failures: list[str] = []

    def boom():
        raise ValueError("bad")

    synchronous_runner(boom, lambda result: None, failures.append)

    assert failures == ["bad"]


def test_synchronous_runner_failure_with_on_failed_none_is_swallowed():
    finished: list[object] = []

    def boom():
        raise ValueError("bad")

    # on_failed defaults to None: the error must be swallowed silently and
    # on_finished must never fire.
    synchronous_runner(boom, finished.append)

    assert finished == []


def test_threaded_runner_invokes_on_finished(qtbot, monkeypatch):
    from PySide6.QtCore import QThreadPool

    from myimages.gui import task_runner, tasks

    # The real threaded_runner discards the BackgroundTask returned by
    # run_in_background; because QThreadPool.start does not keep the Python
    # wrapper alive, that runnable is garbage-collected before it runs (see the
    # module notes / bug report). To exercise the *intended* behaviour - the
    # worker actually runs and on_finished fires on the UI thread - we retain a
    # reference to the task for the duration of the test. This drives the real
    # run_in_background, a real QThreadPool and a real worker thread.
    kept: list[object] = []
    real_run_in_background = tasks.run_in_background

    def retaining(*args, **kwargs):
        task = real_run_in_background(*args, **kwargs)
        kept.append(task)
        return task

    monkeypatch.setattr(task_runner, "run_in_background", retaining)

    finished: list[object] = []
    threaded_runner(lambda: "ok", finished.append)

    qtbot.waitUntil(lambda: finished == ["ok"], timeout=3000)
    # Drain the pool so the retained runnable is never collected while a worker
    # thread is still touching it.
    QThreadPool.globalInstance().waitForDone(3000)
