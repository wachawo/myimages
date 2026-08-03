"""Two interchangeable ways to run an operation, chosen by the caller.

The GUI runs exports and ffmpeg jobs through a *runner* so the main window can
use a threaded runner in production (keeping the UI responsive) while tests swap
in a synchronous one and observe results immediately. Both share the same tiny
signature: ``runner(function, on_finished, on_failed)``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from myimages.gui.tasks import run_in_background

FinishedHandler = Callable[[Any], None]
FailedHandler = Callable[[str], None]
Runner = Callable[..., None]


def synchronous_runner(
    function: Callable[[], Any],
    on_finished: FinishedHandler,
    on_failed: FailedHandler | None = None,
) -> None:
    """Run ``function`` inline and dispatch the result at once."""
    try:
        result = function()
    except Exception as error:  # noqa: BLE001 - reported to the caller as text
        if on_failed is not None:
            on_failed(str(error))
    else:
        on_finished(result)


def threaded_runner(
    function: Callable[[], Any],
    on_finished: FinishedHandler,
    on_failed: FailedHandler | None = None,
) -> None:
    """Run ``function`` on a worker thread; callbacks fire on the UI thread."""
    run_in_background(function, on_finished, on_failed)
