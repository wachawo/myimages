"""Optional dependencies and the ability to install them from the UI.

The app ships with a tiny required core (PySide6 + Pillow). Everything else is
optional and declared here so the interface can show what is missing and offer
to install it. Python packages are installed with ``pip`` in a subprocess;
external tools such as ffmpeg are only detected, never installed, because that
belongs to the system package manager.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from myimages.paths import is_frozen
from myimages.system import ffmpeg_hint, quiet_subprocess_flags


@dataclass(frozen=True)
class OptionalDependency:
    """One capability the user can enable, and how to provide it."""

    key: str
    display_name: str
    purpose: str
    import_name: str | None = None
    pip_package: str | None = None
    binary_name: str | None = None

    @property
    def is_python_package(self) -> bool:
        return self.pip_package is not None

    @property
    def is_external_tool(self) -> bool:
        return self.binary_name is not None and self.pip_package is None


@dataclass(frozen=True)
class InstallResult:
    """Outcome of an install attempt."""

    dependency: OptionalDependency
    succeeded: bool
    output: str


REGISTRY: tuple[OptionalDependency, ...] = (
    OptionalDependency(
        key="ffmpeg",
        display_name="FFmpeg",
        purpose="Trim, crop and scale videos and build GIFs.",
        binary_name="ffmpeg",
    ),
    OptionalDependency(
        key="trash",
        display_name="Send2Trash",
        purpose="Move deleted files to the system trash instead of erasing them.",
        import_name="send2trash",
        pip_package="Send2Trash",
    ),
    OptionalDependency(
        key="heif",
        display_name="HEIF/HEIC support",
        purpose="Open and convert Apple HEIC photos.",
        import_name="pillow_heif",
        pip_package="pillow-heif",
    ),
    OptionalDependency(
        key="bgremove",
        display_name="Automatic background removal",
        purpose="Find the subject with a model instead of clicking it out by hand.",
        import_name="onnxruntime",
        pip_package="onnxruntime",
    ),
)

CommandRunner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def find_dependency(key: str) -> OptionalDependency | None:
    return next((item for item in REGISTRY if item.key == key), None)


def is_available(dependency: OptionalDependency) -> bool:
    """Whether the capability can be used right now."""
    if dependency.binary_name is not None and dependency.pip_package is None:
        return shutil.which(dependency.binary_name) is not None
    if dependency.import_name is not None:
        return importlib.util.find_spec(dependency.import_name) is not None
    return False


def missing_dependencies() -> list[OptionalDependency]:
    return [item for item in REGISTRY if not is_available(item)]


def run_pip_install(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    """Default command runner: execute ``command`` and capture its output."""
    return subprocess.run(  # noqa: S603 - command is app-controlled
        command,
        capture_output=True,
        text=True,
        check=False,
        creationflags=quiet_subprocess_flags(),
    )


def can_install() -> bool:
    """Whether pip can install into this deployment at all.

    False in a packaged build. There, ``sys.executable`` is the application
    rather than an interpreter, so ``sys.executable -m pip`` launches a second
    copy of the window instead of installing anything, and the prefix is
    read-only or root-owned besides. Those builds ship the optional packages
    already, so the honest answer to the user is that there is nothing to do.
    """
    return not is_frozen()


def install(
    dependency: OptionalDependency,
    runner: CommandRunner = run_pip_install,
) -> InstallResult:
    """Install a Python-package dependency with pip.

    External tools (ffmpeg) cannot be installed this way; the caller is told to
    use the system package manager.
    """
    if not can_install():
        return InstallResult(
            dependency=dependency,
            succeeded=False,
            output=(
                f"{dependency.display_name} cannot be installed into this build. "
                "Packaged builds ship what they support already."
            ),
        )
    if not dependency.is_python_package:
        return InstallResult(
            dependency=dependency,
            succeeded=False,
            output=(
                f"{dependency.display_name} is a system tool. Install it with "
                f"your package manager: {ffmpeg_hint()}"
            ),
        )
    command = [sys.executable, "-m", "pip", "install", dependency.pip_package or ""]
    completed = runner(command)
    combined = f"{completed.stdout}\n{completed.stderr}".strip()
    return InstallResult(
        dependency=dependency,
        succeeded=completed.returncode == 0,
        output=combined,
    )
