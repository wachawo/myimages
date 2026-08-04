"""Put myImages in the application menu and offer it as a file handler.

Running from a checkout leaves the app invisible to the desktop: it has no menu
entry and double-clicking a photo never reaches it. Both are fixed by writing a
single ``.desktop`` file into the user's own data directory -- no root, no
package manager, and removable again from the same dialog.

Two things follow from installing into ``~/.local/share`` rather than system
directories: nothing outside the user's account is touched, and the entry keeps
working for a checkout that later moves, because the launch command is recorded
absolutely at install time.

The module shells out to the standard ``xdg`` tools only to *refresh caches* and
to set defaults, and treats every one of them as optional: a desktop that lacks
them still gets a valid entry, it just may need a re-login to notice it. All
subprocess calls go through an injectable runner so the behaviour can be tested
without touching the developer's real desktop.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from myimages import APP_NAME, DESKTOP_ID
from myimages.paths import is_frozen
from myimages.system import quiet_subprocess_flags

CommandRunner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]

ENTRY_NAME = f"{DESKTOP_ID}.desktop"
ICON_NAME = DESKTOP_ID

# The types the app can genuinely open. Offered as defaults only when the user
# asks for it, because silently stealing every photo association from whatever
# they already use would be rude.
IMAGE_MIME_TYPES: tuple[str, ...] = (
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/bmp",
    "image/tiff",
    "image/gif",
)
VIDEO_MIME_TYPES: tuple[str, ...] = (
    "video/mp4",
    "video/quicktime",
    "video/x-matroska",
    "video/webm",
)
SUPPORTED_MIME_TYPES: tuple[str, ...] = IMAGE_MIME_TYPES + VIDEO_MIME_TYPES


@dataclass(frozen=True)
class IntegrationResult:
    """What an install or removal actually managed to do."""

    succeeded: bool
    message: str


def data_home() -> Path:
    """The user's data directory, honouring ``XDG_DATA_HOME`` when it is set."""
    override = os.environ.get("XDG_DATA_HOME")
    return Path(override) if override else Path.home() / ".local" / "share"


def applications_dir() -> Path:
    return data_home() / "applications"


def entry_path() -> Path:
    return applications_dir() / ENTRY_NAME


def icon_path() -> Path:
    return data_home() / "icons" / "hicolor" / "256x256" / "apps" / f"{ICON_NAME}.png"


def is_installed() -> bool:
    return entry_path().is_file()


def launch_command() -> str:
    """The command line that starts this very installation.

    A checkout is launched through its own interpreter and ``main.py`` so the
    entry keeps working without the package being installed; an installed
    console script is preferred when one is on the path, because it survives the
    virtual environment being rebuilt.
    """
    if is_frozen():
        # A packaged build IS the executable, and the source tree the branch
        # below reaches for does not exist inside it.
        return f"{Path(sys.executable).resolve()} %F"
    installed = shutil.which("myimages")
    if installed:
        return f"{installed} %F"
    entry_point = Path(__file__).resolve().parent.parent.parent / "main.py"
    if not entry_point.is_file():
        # A wheel install without its console script on the path: main.py is not
        # shipped, so run the module instead of naming a file that is not there.
        return f"{sys.executable} -m myimages.app %F"
    return f"{sys.executable} {entry_point} %F"


def build_entry(command: str, mime_types: Iterable[str] = ()) -> str:
    """Render the ``.desktop`` file contents."""
    types = ";".join(mime_types)
    lines = [
        "[Desktop Entry]",
        "Type=Application",
        "Name=myImages",
        "GenericName=Photo and video viewer",
        "Comment=Lightweight photo and video viewer, editor and converter",
        f"Exec={command}",
        f"Icon={ICON_NAME}",
        "Terminal=false",
        "Categories=Graphics;Viewer;Photography;",
        "Keywords=photo;image;video;viewer;convert;crop;pdf;gif;",
        # The second field of the window's WM_CLASS, which Qt takes from the
        # application name. A panel matches the running window to this entry on
        # it; without it the window and its launcher stay strangers.
        f"StartupWMClass={APP_NAME}",
    ]
    if types:
        lines.append(f"MimeType={types};")
    return "\n".join(lines) + "\n"


def default_runner(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - command is app-controlled
        list(command),
        capture_output=True,
        text=True,
        check=False,
        creationflags=quiet_subprocess_flags(),
    )


def run_if_available(
    command: Sequence[str], runner: CommandRunner = default_runner
) -> bool:
    """Run a helper tool, reporting whether it existed and succeeded.

    Missing desktop tooling is a normal state on minimal systems, so it is
    reported rather than raised: the entry itself is already on disk and works.
    """
    if shutil.which(command[0]) is None:
        return False
    try:
        return runner(command).returncode == 0
    except OSError:
        return False


def install(
    icon_source: Path | None = None,
    mime_types: Iterable[str] = (),
    runner: CommandRunner = default_runner,
) -> IntegrationResult:
    """Write the menu entry (and icon), claiming ``mime_types`` if given."""
    entry = entry_path()
    try:
        entry.parent.mkdir(parents=True, exist_ok=True)
        entry.write_text(build_entry(launch_command(), mime_types), encoding="utf-8")
        entry.chmod(0o755)
        if icon_source is not None and icon_source.is_file():
            icon_path().parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(icon_source, icon_path())
    except OSError as error:
        return IntegrationResult(False, f"Could not write the menu entry: {error}")

    refreshed = run_if_available(
        ["update-desktop-database", str(applications_dir())], runner
    )
    note = "" if refreshed else " You may need to log out and back in to see it."
    return IntegrationResult(True, f"Added myImages to the application menu.{note}")


def uninstall(runner: CommandRunner = default_runner) -> IntegrationResult:
    """Remove the menu entry and its icon again."""
    removed = False
    try:
        for path in (entry_path(), icon_path()):
            if path.exists():
                path.unlink()
                removed = True
    except OSError as error:
        return IntegrationResult(False, f"Could not remove the menu entry: {error}")
    run_if_available(["update-desktop-database", str(applications_dir())], runner)
    if not removed:
        return IntegrationResult(True, "There was no menu entry to remove.")
    return IntegrationResult(True, "Removed myImages from the application menu.")


def set_as_default(
    mime_types: Iterable[str] = SUPPORTED_MIME_TYPES,
    runner: CommandRunner = default_runner,
) -> IntegrationResult:
    """Make myImages the default application for ``mime_types``.

    The entry has to exist first, so this installs one when it is missing rather
    than registering a default that points at nothing.
    """
    wanted = tuple(mime_types)
    if not wanted:
        return IntegrationResult(False, "No file types were selected.")
    if not is_installed():
        outcome = install(mime_types=wanted, runner=runner)
        if not outcome.succeeded:
            return outcome

    if shutil.which("xdg-mime") is None:
        return IntegrationResult(
            False, "xdg-mime is not installed, so defaults cannot be set here."
        )
    claimed = [
        mime
        for mime in wanted
        if run_if_available(["xdg-mime", "default", ENTRY_NAME, mime], runner)
    ]
    if not claimed:
        return IntegrationResult(False, "The desktop refused to change defaults.")
    return IntegrationResult(
        True, f"myImages now opens {len(claimed)} file type(s) by default."
    )


def default_for(mime_type: str, runner: CommandRunner = default_runner) -> bool:
    """Whether myImages is already the default handler for one type."""
    if shutil.which("xdg-mime") is None:
        return False
    try:
        completed = runner(["xdg-mime", "query", "default", mime_type])
    except OSError:
        return False
    return completed.returncode == 0 and ENTRY_NAME in completed.stdout


def claimed_types(
    mime_types: Iterable[str] = SUPPORTED_MIME_TYPES,
    runner: CommandRunner = default_runner,
) -> list[str]:
    """The subset of ``mime_types`` myImages currently opens by default."""
    return [mime for mime in mime_types if default_for(mime, runner)]
