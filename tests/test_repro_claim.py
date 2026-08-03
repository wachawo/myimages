"""Repro of the claim: does an external folder change wipe a multi-selection?"""

from __future__ import annotations

from PIL import Image

from myimages.core.plugins import PluginRegistry
from myimages.gui.main_window import MainWindow
from myimages.gui.task_runner import synchronous_runner


def make_window(qtbot, settings):
    win = MainWindow(settings, PluginRegistry(), runner=synchronous_runner)
    qtbot.addWidget(win)
    return win


def test_claim_selection_survives_external_change(qtbot, gui_settings, tmp_path):
    folder = tmp_path / "shots"
    folder.mkdir()
    for i in range(3):
        Image.new("RGB", (32, 32), (10 * i, 40, 90)).save(folder / f"p{i}.png")

    gui_settings.watch_folder = True
    win = make_window(qtbot, gui_settings)
    win.folder_input.setText(str(folder))
    win.load_source()
    assert len(win.media_files) == 3

    win.file_list.select_all()
    assert len(win.file_list.selected_files()) == 3
    before = win.file_list.selected_path_set()

    # An unrelated new file lands in the folder (camera import / sync client).
    Image.new("RGB", (32, 32), (255, 255, 0)).save(folder / "new.png")

    # One watch tick, run inline via the synchronous runner.
    win.monitor.runner = synchronous_runner
    win.monitor.check_now()

    after = win.file_list.selected_files()
    print("BEFORE:", sorted(p.rsplit("/", 1)[-1] for p in before))
    print("AFTER :", sorted(f.name for f in after))
    print("visible count:", win.file_list.active_count())
    print("current row:", win.file_list.active_row())
    assert len(win.media_files) == 4
    assert {str(f.path) for f in after} >= before, "selection was wiped"


def test_claim_selection_survives_external_change_table(qtbot, gui_settings, tmp_path):
    folder = tmp_path / "shots2"
    folder.mkdir()
    for i in range(3):
        Image.new("RGB", (32, 32), (10 * i, 40, 90)).save(folder / f"p{i}.png")

    gui_settings.list_view_mode = "table"
    gui_settings.watch_folder = True
    win = make_window(qtbot, gui_settings)
    win.folder_input.setText(str(folder))
    win.load_source()

    win.file_list.select_all()
    before = win.file_list.selected_path_set()
    assert len(before) == 3

    Image.new("RGB", (32, 32), (255, 255, 0)).save(folder / "new.png")
    win.monitor.runner = synchronous_runner
    win.monitor.check_now()

    after = {str(f.path) for f in win.file_list.selected_files()}
    print("TABLE AFTER:", len(after))
    assert after >= before, "table selection was wiped"


def test_claim_deleted_file_case(qtbot, gui_settings, tmp_path):
    """Selection minus the removed file should survive a deletion elsewhere."""
    folder = tmp_path / "shots3"
    folder.mkdir()
    for i in range(4):
        Image.new("RGB", (32, 32), (10 * i, 40, 90)).save(folder / f"p{i}.png")

    gui_settings.watch_folder = True
    win = make_window(qtbot, gui_settings)
    win.folder_input.setText(str(folder))
    win.load_source()
    win.file_list.select_all()
    assert len(win.file_list.selected_files()) == 4

    (folder / "p2.png").unlink()
    win.monitor.runner = synchronous_runner
    win.monitor.check_now()

    after = sorted(f.name for f in win.file_list.selected_files())
    print("AFTER DELETE:", after)
    assert after == ["p0.png", "p1.png", "p3.png"]


def test_action_states_after_tick(qtbot, gui_settings, tmp_path):
    folder = tmp_path / "shots4"
    folder.mkdir()
    for i in range(3):
        Image.new("RGB", (32, 32), (10 * i, 40, 90)).save(folder / f"p{i}.png")
    gui_settings.watch_folder = True
    win = make_window(qtbot, gui_settings)
    win.folder_input.setText(str(folder))
    win.load_source()
    win.file_list.select_all()
    print("gif enabled before:", win.action_gif.isEnabled())
    Image.new("RGB", (32, 32), (255, 255, 0)).save(folder / "new.png")
    win.monitor.runner = synchronous_runner
    win.monitor.check_now()
    print("selected after:", len(win.file_list.selected_files()))
    print("gif enabled after:", win.action_gif.isEnabled())
    print("selected_images:", len(win.selected_images()))
