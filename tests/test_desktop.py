"""Tests for :mod:`myimages.core.desktop`.

Every test redirects ``XDG_DATA_HOME`` into ``tmp_path`` first, so installing a
menu entry never touches the developer's real desktop. Helper tools are driven
through an injected runner, which keeps the tests honest about *what command*
would be run without actually reconfiguring anything.
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

from myimages.core import desktop


@pytest.fixture(autouse=True)
def isolated_desktop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "share"
    monkeypatch.setenv("XDG_DATA_HOME", str(home))
    return home


def completed(
    returncode: int = 0, stdout: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=["x"], returncode=returncode, stdout=stdout)


def recording_runner(log: list[Sequence[str]], returncode: int = 0, stdout: str = ""):
    def runner(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        log.append(list(command))
        return completed(returncode, stdout)

    return runner


# -- locations -------------------------------------------------------------


def test_paths_follow_xdg_data_home(isolated_desktop: Path):
    assert desktop.data_home() == isolated_desktop
    assert (
        desktop.entry_path() == isolated_desktop / "applications" / "myimages.desktop"
    )
    assert desktop.icon_path().name == "myimages.png"
    assert "hicolor" in str(desktop.icon_path())


def test_data_home_falls_back_to_the_home_directory(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    assert desktop.data_home() == Path.home() / ".local" / "share"


# -- the entry itself ------------------------------------------------------


def test_entry_names_the_app_and_its_command():
    text = desktop.build_entry("/usr/bin/myimages %F", desktop.IMAGE_MIME_TYPES)
    assert text.startswith("[Desktop Entry]")
    assert "Name=myImages" in text
    assert "Exec=/usr/bin/myimages %F" in text
    assert "Icon=myimages" in text
    assert "MimeType=image/jpeg;" in text


def test_entry_omits_mime_types_when_none_are_claimed():
    assert "MimeType" not in desktop.build_entry("cmd %F")


def test_launch_command_passes_the_selected_files():
    assert desktop.launch_command().endswith(" %F")


def test_launch_command_points_at_something_runnable():
    command = desktop.launch_command()
    first = command.split(" ")[0]
    assert Path(first).exists()  # an interpreter or the installed console script


# -- installing and removing -----------------------------------------------


def test_install_writes_a_usable_entry():
    log: list[Sequence[str]] = []
    assert desktop.is_installed() is False

    result = desktop.install(
        mime_types=desktop.SUPPORTED_MIME_TYPES, runner=recording_runner(log)
    )

    assert result.succeeded is True
    assert desktop.is_installed() is True
    text = desktop.entry_path().read_text(encoding="utf-8")
    assert "Exec=" in text and "image/png" in text


def test_install_copies_the_icon(tmp_path: Path):
    from PIL import Image

    source = tmp_path / "icon.png"
    Image.new("RGBA", (256, 256), (10, 20, 30, 255)).save(source)

    desktop.install(icon_source=source, runner=recording_runner([]))

    assert desktop.icon_path().is_file()
    assert desktop.icon_path().stat().st_size > 0


def test_install_survives_a_missing_icon_file(tmp_path: Path):
    desktop.install(icon_source=tmp_path / "absent.png", runner=recording_runner([]))
    assert desktop.is_installed() is True
    assert not desktop.icon_path().exists()


def test_install_reports_a_directory_it_cannot_write(monkeypatch: pytest.MonkeyPatch):
    def refuse(self, *args, **kwargs):
        raise PermissionError("read-only home")

    monkeypatch.setattr(Path, "write_text", refuse)
    result = desktop.install(runner=recording_runner([]))
    assert result.succeeded is False
    assert "Could not write" in result.message


def test_uninstall_removes_the_entry_and_icon(tmp_path: Path):
    from PIL import Image

    source = tmp_path / "icon.png"
    Image.new("RGBA", (32, 32), (1, 2, 3, 255)).save(source)
    desktop.install(icon_source=source, runner=recording_runner([]))

    result = desktop.uninstall(runner=recording_runner([]))

    assert result.succeeded is True
    assert not desktop.entry_path().exists()
    assert not desktop.icon_path().exists()


def test_uninstall_is_calm_about_nothing_being_installed():
    result = desktop.uninstall(runner=recording_runner([]))
    assert result.succeeded is True
    assert "no menu entry" in result.message


# -- file associations -----------------------------------------------------


def test_setting_defaults_installs_the_entry_first(monkeypatch: pytest.MonkeyPatch):
    """Registering a default that points at no entry would be a dead link."""
    monkeypatch.setattr(desktop.shutil, "which", lambda name: f"/usr/bin/{name}")
    log: list[Sequence[str]] = []

    result = desktop.set_as_default(["image/png"], runner=recording_runner(log))

    assert result.succeeded is True
    assert desktop.is_installed() is True
    assert ["xdg-mime", "default", "myimages.desktop", "image/png"] in log


def test_setting_defaults_claims_every_requested_type(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(desktop.shutil, "which", lambda name: f"/usr/bin/{name}")
    log: list[Sequence[str]] = []
    wanted = ["image/png", "image/jpeg", "video/mp4"]

    result = desktop.set_as_default(wanted, runner=recording_runner(log))

    claims = [command for command in log if command[:2] == ["xdg-mime", "default"]]
    assert len(claims) == len(wanted)
    assert "3 file type(s)" in result.message


def test_setting_defaults_needs_at_least_one_type():
    result = desktop.set_as_default([], runner=recording_runner([]))
    assert result.succeeded is False


def test_setting_defaults_explains_a_desktop_without_xdg_mime(
    monkeypatch: pytest.MonkeyPatch,
):
    desktop.install(runner=recording_runner([]))
    monkeypatch.setattr(desktop.shutil, "which", lambda name: None)

    result = desktop.set_as_default(["image/png"], runner=recording_runner([]))

    assert result.succeeded is False
    assert "xdg-mime" in result.message


def test_setting_defaults_reports_a_desktop_that_refuses(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(desktop.shutil, "which", lambda name: f"/usr/bin/{name}")
    result = desktop.set_as_default(
        ["image/png"], runner=recording_runner([], returncode=1)
    )
    assert result.succeeded is False
    assert "refused" in result.message


def test_default_for_reads_the_desktops_answer(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(desktop.shutil, "which", lambda name: f"/usr/bin/{name}")

    ours = recording_runner([], stdout="myimages.desktop\n")
    theirs = recording_runner([], stdout="org.gnome.eog.desktop\n")

    assert desktop.default_for("image/png", ours) is True
    assert desktop.default_for("image/png", theirs) is False


def test_default_for_without_xdg_mime_is_false(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(desktop.shutil, "which", lambda name: None)
    assert desktop.default_for("image/png", recording_runner([])) is False


def test_claimed_types_lists_only_what_we_own(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(desktop.shutil, "which", lambda name: f"/usr/bin/{name}")

    def runner(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        mime = command[-1]
        return completed(0, "myimages.desktop" if mime == "image/png" else "other")

    assert desktop.claimed_types(["image/png", "image/jpeg"], runner) == ["image/png"]


# -- helper tooling --------------------------------------------------------


def test_a_missing_helper_tool_is_reported_not_raised(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(desktop.shutil, "which", lambda name: None)
    assert (
        desktop.run_if_available(["update-desktop-database"], recording_runner([]))
        is False
    )


def test_a_helper_that_cannot_be_executed_is_reported(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(desktop.shutil, "which", lambda name: "/usr/bin/tool")

    def explode(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        raise OSError("no such binary after all")

    assert desktop.run_if_available(["tool"], explode) is False


def test_install_still_succeeds_without_desktop_tooling(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(desktop.shutil, "which", lambda name: None)
    result = desktop.install(runner=recording_runner([]))
    assert result.succeeded is True
    assert "log out" in result.message  # the honest caveat, not a silent lie


def test_default_runner_executes_a_command():
    finished = desktop.default_runner(["python3", "-c", "print('ok')"])
    assert finished.returncode == 0
    assert "ok" in finished.stdout


def test_uninstall_reports_a_file_it_cannot_delete(monkeypatch: pytest.MonkeyPatch):
    desktop.install(runner=recording_runner([]))

    def refuse(self, missing_ok: bool = False) -> None:
        raise PermissionError("read-only home")

    monkeypatch.setattr(Path, "unlink", refuse)
    result = desktop.uninstall(runner=recording_runner([]))
    assert result.succeeded is False
    assert "Could not remove" in result.message


def test_setting_defaults_gives_up_if_the_entry_cannot_be_written(
    monkeypatch: pytest.MonkeyPatch,
):
    """A default pointing at an entry we failed to write would be a dead link."""

    def refuse(self, *args, **kwargs):
        raise PermissionError("read-only home")

    monkeypatch.setattr(Path, "write_text", refuse)
    result = desktop.set_as_default(["image/png"], runner=recording_runner([]))
    assert result.succeeded is False
    assert "Could not write" in result.message


def test_default_for_survives_a_helper_that_cannot_run(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(desktop.shutil, "which", lambda name: f"/usr/bin/{name}")

    def explode(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        raise OSError("exec format error")

    assert desktop.default_for("image/png", explode) is False


def test_a_packaged_build_launches_itself(monkeypatch):
    """Inside a bundle sys.executable IS the app, and main.py does not exist."""
    from myimages.core import desktop

    monkeypatch.setattr(desktop, "is_frozen", lambda: True)
    monkeypatch.setattr(desktop.sys, "executable", "/opt/myimages/myimages")
    assert desktop.launch_command() == "/opt/myimages/myimages %F"


def test_a_wheel_install_runs_the_module_rather_than_a_missing_file(
    monkeypatch, tmp_path
):
    """A wheel ships no main.py, so naming one would write a dead command."""
    from pathlib import Path

    from myimages.core import desktop

    monkeypatch.setattr(desktop, "is_frozen", lambda: False)
    monkeypatch.setattr(desktop.shutil, "which", lambda name: None)
    monkeypatch.setattr(desktop, "__file__", str(tmp_path / "a" / "b" / "desktop.py"))
    assert Path(desktop.__file__).parent.parent.parent / "main.py" != tmp_path
    assert desktop.launch_command().startswith(
        f"{desktop.sys.executable} -m myimages.app"
    )
