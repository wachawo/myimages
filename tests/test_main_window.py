"""Tests for the top-level window (myimages.gui.main_window).

The window wires the source bar, the split preview/list view and every tool
action together. These tests construct a ``MainWindow`` with the synchronous
runner so tool operations complete inline and their effects (files written,
list rebuilt, settings changed) are observable at once. Blocking UI — message
boxes and the tool dialogs' ``exec()`` — is never opened for real: message
boxes are silenced by the ``silence_dialogs`` fixture and each dialog's
``exec`` is monkeypatched to return the wanted truthiness (occasionally after
setting the attribute the handler reads or emitting a signal it listens to).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox, QWidget

from myimages import theme
from myimages.core import thumbnails
from myimages.core.media import MediaFile, MediaKind, build_media_file
from myimages.core.plugins import PluginRegistry
from myimages.core.watcher import FolderChanges
from myimages.gui.main_window import MainWindow
from myimages.gui.task_runner import synchronous_runner


def make_window(qtbot, settings, registry=None) -> MainWindow:
    """Construct a MainWindow driven by the synchronous runner."""
    win = MainWindow(settings, registry or PluginRegistry(), runner=synchronous_runner)
    qtbot.addWidget(win)
    return win


def load_gallery(win: MainWindow, image_dir) -> list[MediaFile]:
    """Scan ``image_dir`` into the window and return the loaded media files."""
    win.set_media_files(win.scan_folder(image_dir))
    return win.media_files


def video_media(path) -> MediaFile:
    """Create a zero-byte file with a video suffix and build its MediaFile."""
    path.touch()
    return build_media_file(path)


# -- source handling -------------------------------------------------------


def test_set_media_files_navigate_and_preview(qtbot, gui_settings, image_dir):
    win = make_window(qtbot, gui_settings)
    load_gallery(win, image_dir)

    assert len(win.media_files) == 3
    # Selecting row 0 flows through to the current file and the preview.
    assert win.current is not None
    assert win.preview.current_media is win.current
    first = win.current

    win.navigate(1)
    assert win.current is not None
    assert win.current.path != first.path
    assert win.preview.current_media is win.current

    win.navigate(-1)
    assert win.current is not None
    assert win.current.path == first.path


def test_folder_controls_are_always_available(qtbot, gui_settings):
    win = make_window(qtbot, gui_settings)
    # A folder is the only source, so its controls are never hidden.
    assert win.folder_input.isVisibleTo(win)
    assert win.browse_button.isVisibleTo(win)
    assert win.recursive_button.isVisibleTo(win)
    assert win.media_files == []  # no folder set yet -> nothing scanned


def test_toggle_recursive_changes_what_is_found(qtbot, gui_settings, tmp_path):
    root = tmp_path / "tree"
    (root / "nested").mkdir(parents=True)
    Image.new("RGB", (10, 10), (0, 0, 0)).save(root / "top.png")
    Image.new("RGB", (10, 10), (0, 0, 0)).save(root / "nested" / "deep.png")
    gui_settings.last_folder = str(root)
    win = make_window(qtbot, gui_settings)
    assert [f.name for f in win.media_files] == ["top.png"]

    win.toggle_recursive(True)  # re-scans, so the sub-folder shows up
    assert gui_settings.recursive_scan is True
    assert sorted(f.name for f in win.media_files) == ["deep.png", "top.png"]

    win.toggle_recursive(False)
    assert gui_settings.recursive_scan is False
    assert [f.name for f in win.media_files] == ["top.png"]


def test_browse_folder_scans(qtbot, gui_settings, image_dir, monkeypatch):
    win = make_window(qtbot, gui_settings)
    monkeypatch.setattr(
        QFileDialog,
        "getExistingDirectory",
        staticmethod(lambda *a, **k: str(image_dir)),
    )
    win.browse_folder()
    assert win.folder_input.text() == str(image_dir)
    assert len(win.media_files) == 3


def test_browse_folder_cancel_keeps_folder(qtbot, gui_settings, monkeypatch):
    win = make_window(qtbot, gui_settings)
    before = win.folder_input.text()
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: "")
    )
    win.browse_folder()
    assert win.folder_input.text() == before


def test_scan_folder(qtbot, gui_settings, image_dir, tmp_path):
    win = make_window(qtbot, gui_settings)
    assert len(win.scan_folder(image_dir)) == 3
    # A path that is not a directory yields no files.
    assert win.scan_folder(tmp_path / "does_not_exist") == []


# -- action states / selection --------------------------------------------


def test_action_states_for_image(qtbot, gui_settings, image_dir):
    win = make_window(qtbot, gui_settings)
    load_gallery(win, image_dir)
    win.file_list.select_all()
    win.update_action_states()

    assert win.current is not None and win.current.kind is MediaKind.IMAGE
    assert win.action_edit.isEnabled()
    assert win.action_convert.isEnabled()
    assert win.action_pdf.isEnabled()
    assert win.action_gif.isEnabled()  # three images selected
    assert not win.action_video.isEnabled()
    assert win.action_delete.isEnabled()


def test_action_states_for_video(qtbot, gui_settings, tmp_path):
    win = make_window(qtbot, gui_settings)
    win.set_media_files([video_media(tmp_path / "clip.mp4")])

    assert win.current is not None and win.current.kind is MediaKind.VIDEO
    assert not win.action_edit.isEnabled()
    assert not win.action_gif.isEnabled()
    assert win.action_video.isEnabled()
    assert win.action_delete.isEnabled()


def test_selected_images_falls_back_to_current(qtbot, gui_settings, image_dir):
    win = make_window(qtbot, gui_settings)
    load_gallery(win, image_dir)
    win.file_list.clear_selection()
    assert win.selected_images() == [win.current]


def test_selected_images_empty_for_video(qtbot, gui_settings, tmp_path):
    win = make_window(qtbot, gui_settings)
    win.set_media_files([video_media(tmp_path / "clip.mp4")])
    win.file_list.clear_selection()
    assert win.selected_images() == []


# -- favourites & deletion ------------------------------------------------


def test_toggle_favorite_current_shows_star(qtbot, gui_settings, image_dir):
    gui_settings.list_view_mode = "table"  # star visible as a table cell
    win = make_window(qtbot, gui_settings)
    load_gallery(win, image_dir)
    current = win.current
    assert current is not None

    win.toggle_favorite_current()
    assert gui_settings.is_favorite(current.path)
    row = win.file_list.table.currentRow()
    star = win.file_list.table.item(row, 0)
    assert star is not None and star.text() == "★"

    win.toggle_favorite_current()
    assert not gui_settings.is_favorite(current.path)


def test_side_button_click_moves_panel(qtbot, gui_settings):
    win = make_window(qtbot, gui_settings)
    assert win.splitter.indexOf(win.sidebar) == 1
    win.side_button.click()  # signal -> toggle_panel_side
    assert win.settings.file_list_on_left is True
    assert win.splitter.indexOf(win.sidebar) == 0


def test_toggle_favorite_no_current(qtbot, gui_settings):
    win = make_window(qtbot, gui_settings)
    assert win.current is None
    win.toggle_favorite_current()  # no-op, must not raise


def test_preview_star_toggles_favorite(qtbot, gui_settings, image_dir):
    win = make_window(qtbot, gui_settings)
    load_gallery(win, image_dir)
    assert win.current is not None
    assert win.preview.favorite_state is False

    win.preview.favorite_button.click()  # favorite_toggled -> toggle_favorite_current
    assert gui_settings.is_favorite(win.current.path)
    assert win.preview.favorite_state is True

    win.preview.favorite_button.click()
    assert not gui_settings.is_favorite(win.current.path)
    assert win.preview.favorite_state is False


def test_current_reflects_favorite_on_preview_star(qtbot, gui_settings, image_dir):
    win = make_window(qtbot, gui_settings)
    files = win.scan_folder(image_dir)
    gui_settings.toggle_favorite(str(files[0].path))  # pre-mark one favourite
    win.set_media_files(files)
    win.file_list.select_path(str(files[0].path))
    assert win.current is not None and win.current.path == files[0].path
    assert win.preview.favorite_state is True


def test_favorite_toggle_keeps_selection_in_selection_mode(
    qtbot, gui_settings, image_dir
):
    gui_settings.selection_mode = True
    win = make_window(qtbot, gui_settings)
    load_gallery(win, image_dir)
    win.file_list.select_all()
    before = {str(f.path) for f in win.file_list.selected_files()}
    assert len(before) == 3

    win.toggle_favorite_current()  # star / F must not clear the selection
    after = {str(f.path) for f in win.file_list.selected_files()}
    assert after == before


def test_delete_selected_removes_files(qtbot, gui_settings, tmp_path, silence_dialogs):
    paths = []
    for index in range(2):
        target = tmp_path / f"del{index}.png"
        Image.new("RGB", (10, 10), (index * 10, 0, 0)).save(target)
        paths.append(str(target))
    gui_settings.last_folder = str(tmp_path)
    win = make_window(qtbot, gui_settings)
    assert len(win.media_files) == 2

    win.file_list.select_all()
    win.delete_selected()

    assert win.media_files == []
    assert not (tmp_path / "del0.png").exists()


def test_delete_selected_falls_back_to_current(
    qtbot, gui_settings, make_image, silence_dialogs
):
    image = make_image("only.png")
    gui_settings.last_folder = str(image.parent)
    win = make_window(qtbot, gui_settings)
    win.file_list.clear_selection()
    assert win.file_list.selected_files() == []
    assert win.current is not None

    win.delete_selected()  # no selection -> deletes the current file
    assert win.media_files == []
    assert not image.exists()


def test_delete_selected_cancelled(qtbot, gui_settings, make_image, monkeypatch):
    image = make_image("keep.png")
    gui_settings.last_folder = str(image.parent)
    win = make_window(qtbot, gui_settings)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.No),
    )
    win.delete_selected()
    assert len(win.media_files) == 1
    assert image.exists()


def test_delete_selected_no_targets(qtbot, gui_settings, silence_dialogs):
    win = make_window(qtbot, gui_settings)
    win.delete_selected()  # nothing selected or current, returns early


# -- plugins info ----------------------------------------------------------


def test_open_plugins_info(qtbot, gui_settings, silence_dialogs):
    win = make_window(qtbot, gui_settings)
    win.open_plugins_info()  # empty registry -> "(none)"


def test_open_plugins_info_with_plugin(qtbot, gui_settings, silence_dialogs):
    registry = PluginRegistry()
    registry.register_viewer("Demo", [".xyz"], lambda path: QWidget())
    win = make_window(qtbot, gui_settings, registry)
    win.open_plugins_info()


# -- tool handlers ---------------------------------------------------------


def test_open_edit_enters_inline_editor(qtbot, gui_settings, make_image):
    image = make_image("edit.png", (40, 30), (10, 20, 30))
    gui_settings.last_folder = str(image.parent)
    win = make_window(qtbot, gui_settings)

    win.open_edit()
    assert win.preview_area.currentWidget() is win.editor
    assert win.editor.working_image is not None


def test_editor_save_reloads_and_returns_to_preview(qtbot, gui_settings, make_image):
    image = make_image("edit.png", (40, 30), (10, 20, 30))
    gui_settings.last_folder = str(image.parent)
    win = make_window(qtbot, gui_settings)
    win.open_edit()
    assert win.preview_area.currentWidget() is win.editor  # really editing

    win.editor.save_over()  # emits closed(True)
    assert win.preview_area.currentWidget() is win.preview
    assert image.exists()


def test_editor_cancel_returns_without_saving(qtbot, gui_settings, make_image):
    image = make_image("edit2.png")
    gui_settings.last_folder = str(image.parent)
    win = make_window(qtbot, gui_settings)
    win.open_edit()
    assert win.preview_area.currentWidget() is win.editor  # really editing

    win.cancel_edit()  # Escape / Cancel path
    assert win.preview_area.currentWidget() is win.preview


def test_cancel_edit_noop_when_not_editing(qtbot, gui_settings, make_image):
    gui_settings.last_folder = str(make_image("x.png").parent)
    win = make_window(qtbot, gui_settings)
    win.cancel_edit()  # not editing -> no-op
    assert win.preview_area.currentWidget() is win.preview


def test_open_edit_ignores_non_image(qtbot, gui_settings, tmp_path):
    win = make_window(qtbot, gui_settings)
    win.set_media_files([video_media(tmp_path / "clip.mp4")])
    win.open_edit()  # current is a video -> early return
    assert win.preview_area.currentWidget() is win.preview


def test_open_convert_writes_files(
    qtbot, gui_settings, make_image, monkeypatch, silence_dialogs, tmp_path
):
    image = make_image("conv.jpg")
    gui_settings.last_folder = str(image.parent)
    win = make_window(qtbot, gui_settings)
    from myimages.gui.convert_dialog import ConvertDialog

    monkeypatch.setattr(ConvertDialog, "exec", lambda self: True)
    win.open_convert()
    # Default format is PNG, written next to the source.
    assert (tmp_path / "conv.png").exists()


def test_open_convert_cancelled(qtbot, gui_settings, make_image, monkeypatch):
    image = make_image("conv2.png")
    gui_settings.last_folder = str(image.parent)
    win = make_window(qtbot, gui_settings)
    from myimages.gui.convert_dialog import ConvertDialog

    monkeypatch.setattr(ConvertDialog, "exec", lambda self: False)
    win.open_convert()  # returns after a cancelled dialog


def test_open_convert_no_images(qtbot, gui_settings, tmp_path):
    win = make_window(qtbot, gui_settings)
    win.set_media_files([video_media(tmp_path / "clip.mp4")])
    win.file_list.clear_selection()
    win.open_convert()  # no images selected -> early return


def test_open_convert_failure_warns(
    qtbot, gui_settings, make_image, monkeypatch, silence_dialogs
):
    image = make_image("bad.png")
    gui_settings.last_folder = str(image.parent)
    win = make_window(qtbot, gui_settings)
    from myimages.gui.convert_dialog import ConvertDialog
    from myimages.imaging import convert

    monkeypatch.setattr(ConvertDialog, "exec", lambda self: True)

    def boom(*a, **k):
        raise RuntimeError("conversion exploded")

    monkeypatch.setattr(convert, "convert_image", boom)
    win.open_convert()  # failure path routes through run_with_progress -> warning


def test_open_convert_save_replaces_original(
    qtbot, gui_settings, make_image, monkeypatch, silence_dialogs, tmp_path
):
    image = make_image("orig.png")
    gui_settings.last_folder = str(image.parent)
    win = make_window(qtbot, gui_settings)
    from myimages.gui.convert_dialog import ConvertDialog

    def fake_exec(self):
        self.format_combo.setCurrentIndex(1)  # JPEG
        self.accept_replacing()
        return True

    monkeypatch.setattr(ConvertDialog, "exec", fake_exec)
    win.open_convert()
    assert (tmp_path / "orig.jpg").exists()
    assert not (tmp_path / "orig.png").exists()  # Save removed the original


def test_open_convert_copy_never_clobbers_original(
    qtbot, gui_settings, make_image, monkeypatch, silence_dialogs, tmp_path
):
    image = make_image("same.png")
    gui_settings.last_folder = str(image.parent)
    win = make_window(qtbot, gui_settings)
    from myimages.gui.convert_dialog import ConvertDialog

    def fake_exec(self):
        self.format_combo.setCurrentIndex(0)  # PNG: same ext, same folder
        self.accept_copying()
        return True

    monkeypatch.setattr(ConvertDialog, "exec", fake_exec)
    win.open_convert()
    assert (tmp_path / "same.png").exists()  # original untouched
    assert (tmp_path / "same_copy.png").exists()  # copy written beside it


def test_open_pdf_writes_file(
    qtbot, gui_settings, make_image, monkeypatch, silence_dialogs
):
    image = make_image("doc.png")
    gui_settings.last_folder = str(image.parent)
    win = make_window(qtbot, gui_settings)
    from myimages.gui.pdf_dialog import PdfDialog

    monkeypatch.setattr(PdfDialog, "exec", lambda self: True)
    win.open_pdf()
    assert image.with_suffix(".pdf").exists()


def test_open_pdf_cancelled(qtbot, gui_settings, make_image, monkeypatch):
    image = make_image("doc2.png")
    gui_settings.last_folder = str(image.parent)
    win = make_window(qtbot, gui_settings)
    from myimages.gui.pdf_dialog import PdfDialog

    monkeypatch.setattr(PdfDialog, "exec", lambda self: False)
    win.open_pdf()


def test_open_pdf_no_images(qtbot, gui_settings, tmp_path):
    win = make_window(qtbot, gui_settings)
    win.set_media_files([video_media(tmp_path / "clip.mp4")])
    win.file_list.clear_selection()
    win.open_pdf()  # no images -> early return


def test_open_gif_writes_file(
    qtbot, gui_settings, tmp_path, monkeypatch, silence_dialogs
):
    for index in range(2):
        Image.new("RGB", (20, 20), (index * 40, 0, 0)).save(tmp_path / f"g{index}.png")
    gui_settings.last_folder = str(tmp_path)
    win = make_window(qtbot, gui_settings)
    win.file_list.select_all()
    from myimages.gui.gif_dialog import GifFromFramesDialog

    monkeypatch.setattr(GifFromFramesDialog, "exec", lambda self: True)
    win.open_gif()
    assert (tmp_path / "g0.gif").exists() or (tmp_path / "g1.gif").exists()


def test_open_gif_needs_two_images(qtbot, gui_settings, make_image, silence_dialogs):
    image = make_image("solo.png")
    gui_settings.last_folder = str(image.parent)
    win = make_window(qtbot, gui_settings)
    win.open_gif()  # only one image -> information box, no build


def test_open_gif_cancelled(qtbot, gui_settings, tmp_path, monkeypatch):
    for index in range(2):
        Image.new("RGB", (20, 20), (0, index * 40, 0)).save(tmp_path / f"h{index}.png")
    gui_settings.last_folder = str(tmp_path)
    win = make_window(qtbot, gui_settings)
    win.file_list.select_all()
    from myimages.gui.gif_dialog import GifFromFramesDialog

    monkeypatch.setattr(GifFromFramesDialog, "exec", lambda self: False)
    win.open_gif()  # cancelled -> returns


def test_open_video_tools_non_video(qtbot, gui_settings, image_dir):
    win = make_window(qtbot, gui_settings)
    load_gallery(win, image_dir)
    win.open_video_tools()  # current is an image -> early return


def test_open_video_tools_missing_ffmpeg(
    qtbot, gui_settings, tmp_path, monkeypatch, silence_dialogs
):
    win = make_window(qtbot, gui_settings)
    win.set_media_files([video_media(tmp_path / "clip.mp4")])
    from myimages.video import ffmpeg

    monkeypatch.setattr(ffmpeg, "is_available", lambda: False)
    win.open_video_tools()  # information box explaining ffmpeg is needed


def test_open_video_tools_available(
    qtbot, gui_settings, tmp_path, monkeypatch, silence_dialogs
):
    win = make_window(qtbot, gui_settings)
    win.set_media_files([video_media(tmp_path / "clip.mp4")])
    from myimages.video import ffmpeg

    monkeypatch.setattr(ffmpeg, "is_available", lambda: True)
    from myimages.gui.video_tool_dialog import VideoToolDialog

    monkeypatch.setattr(VideoToolDialog, "exec", lambda self: True)
    win.open_video_tools()  # builds the dialog, exec, then reload


def test_open_duplicates(qtbot, gui_settings, image_dir, monkeypatch):
    win = make_window(qtbot, gui_settings)
    load_gallery(win, image_dir)
    from myimages.gui.duplicates_dialog import DuplicatesDialog

    def dup_exec(self):
        # Exercise the files_deleted -> reload connection made by the handler.
        self.files_deleted.emit([])
        return 0

    monkeypatch.setattr(DuplicatesDialog, "exec", dup_exec)
    win.open_duplicates()


def test_open_duplicates_empty(qtbot, gui_settings):
    win = make_window(qtbot, gui_settings)
    win.open_duplicates()  # no media files -> early return


def test_open_rename(qtbot, gui_settings, tmp_path, monkeypatch):
    Image.new("RGB", (10, 10), (0, 0, 0)).save(tmp_path / "pic.png")
    gui_settings.last_folder = str(tmp_path)
    win = make_window(qtbot, gui_settings)
    from myimages.gui.rename_dialog import RenameDialog

    monkeypatch.setattr(RenameDialog, "exec", lambda self: True)
    win.open_rename()
    assert (tmp_path / "pic_001.png").exists()


def test_open_rename_error_warns(
    qtbot, gui_settings, tmp_path, monkeypatch, silence_dialogs
):
    Image.new("RGB", (10, 10), (0, 0, 0)).save(tmp_path / "pic.png")
    gui_settings.last_folder = str(tmp_path)
    win = make_window(qtbot, gui_settings)
    from myimages.core import rename as rename_mod
    from myimages.gui.rename_dialog import RenameDialog

    def boom(plan):
        raise ValueError("cannot rename")

    monkeypatch.setattr(rename_mod, "apply_rename_plan", boom)
    monkeypatch.setattr(RenameDialog, "exec", lambda self: True)
    win.open_rename()  # error is caught and surfaced as a warning
    assert (tmp_path / "pic.png").exists()


def test_open_rename_cancelled(qtbot, gui_settings, tmp_path, monkeypatch):
    Image.new("RGB", (10, 10), (0, 0, 0)).save(tmp_path / "pic.png")
    gui_settings.last_folder = str(tmp_path)
    win = make_window(qtbot, gui_settings)
    from myimages.gui.rename_dialog import RenameDialog

    monkeypatch.setattr(RenameDialog, "exec", lambda self: False)
    win.open_rename()
    assert (tmp_path / "pic.png").exists()


def test_open_rename_no_targets(qtbot, gui_settings):
    win = make_window(qtbot, gui_settings)
    win.open_rename()  # empty file set -> early return


def test_open_settings_applies_values(qtbot, gui_settings, monkeypatch):
    win = make_window(qtbot, gui_settings)
    from myimages.gui.settings_dialog import SettingsDialog

    monkeypatch.setattr(SettingsDialog, "exec", lambda self: True)
    win.open_settings()
    # The dialog pre-fills from settings, so applying them keeps them valid and
    # syncs the thumbnail loader size.
    assert win.loader.size == gui_settings.thumbnail_size


def test_open_settings_cancelled(qtbot, gui_settings, monkeypatch):
    win = make_window(qtbot, gui_settings)
    from myimages.gui.settings_dialog import SettingsDialog

    monkeypatch.setattr(SettingsDialog, "exec", lambda self: False)
    win.open_settings()  # returns without touching settings


def test_open_dependencies(qtbot, gui_settings, monkeypatch):
    win = make_window(qtbot, gui_settings)
    from myimages.gui.dependencies_dialog import DependenciesDialog

    monkeypatch.setattr(DependenciesDialog, "exec", lambda self: 0)
    win.open_dependencies()


# -- persistence -----------------------------------------------------------


def test_store_layout_and_close_persists(qtbot, gui_settings):
    win = make_window(qtbot, gui_settings)
    win.resize(1000, 700)
    win.store_layout()
    assert gui_settings.window_width == win.width()
    assert gui_settings.window_height == win.height()

    win.close()  # closeEvent stores the layout and writes settings.json
    from myimages.config import settings_path

    assert settings_path().exists()


# -- file-list side ---------------------------------------------------------


def test_toggle_panel_side_moves_list_and_flips_button(qtbot, gui_settings):
    win = make_window(qtbot, gui_settings)
    assert gui_settings.file_list_on_left is False
    assert win.splitter.indexOf(win.sidebar) == 1  # right by default
    tip_before = win.side_button.toolTip()

    win.toggle_panel_side()
    assert gui_settings.file_list_on_left is True
    assert win.splitter.indexOf(win.sidebar) == 0  # moved to the left
    assert win.side_button.toolTip() != tip_before
    assert not win.side_button.icon().isNull()

    win.toggle_panel_side()
    assert gui_settings.file_list_on_left is False
    assert win.splitter.indexOf(win.sidebar) == 1


def test_constructing_with_list_on_left(qtbot, gui_settings):
    gui_settings.file_list_on_left = True
    win = make_window(qtbot, gui_settings)
    assert win.splitter.indexOf(win.sidebar) == 0
    # The tooltip names the move the press makes, not where the list is now.
    assert "right" in win.side_button.toolTip()


def rendered_columns(win) -> int:
    """How many thumbnails actually share the top row of the grid."""
    view = win.file_list.icon_list
    if view.count() < 2:
        return 0
    tops = [view.visualItemRect(view.item(i)).top() for i in range(view.count())]
    return tops.count(min(tops))


def test_the_column_button_sets_the_panel_width(qtbot, gui_settings, image_dir):
    """The user picks a number of thumbnails per row and gets exactly that."""
    win = make_window(qtbot, gui_settings)
    win.show()
    win.resize(win.preview_pane_container.minimumSizeHint().width() + 900, 700)
    load_gallery(win, image_dir)
    QApplication.processEvents()

    for columns in (1, 2, 3):  # the fixture holds three images
        gui_settings.grid_columns = columns
        win.change_columns(columns)
        QApplication.processEvents()
        assert rendered_columns(win) == columns


def test_the_divider_cannot_be_dragged(qtbot, gui_settings):
    """Dragging could only ever land between two column counts."""
    win = make_window(qtbot, gui_settings)
    handles = [win.splitter.handle(i) for i in range(win.splitter.count())]
    assert handles
    assert all(handle is not None and not handle.isEnabled() for handle in handles)


def test_storing_the_layout_records_only_the_window_size(qtbot, gui_settings):
    win = make_window(qtbot, gui_settings)
    gui_settings.grid_columns = 4
    win.resize(1100, 700)

    win.store_layout()

    assert gui_settings.window_width == win.width()
    assert gui_settings.grid_columns == 4  # untouched by the geometry


def test_the_panel_width_survives_a_narrow_window(qtbot, gui_settings):
    """The whole point: squeezing the window must not be a change of mind."""
    from myimages.gui.file_list import panel_width_for

    win = make_window(qtbot, gui_settings)
    win.show()
    sidebar = win.splitter.indexOf(win.sidebar)
    gui_settings.grid_columns = 4
    roomy = win.preview_pane_container.minimumSizeHint().width() + 900

    def settle(width: int) -> None:
        win.resize(width, 700)
        qtbot.waitUntil(lambda: win.splitter.width() > 0, timeout=1000)
        QApplication.processEvents()

    settle(roomy)
    win.apply_panel_width()
    QApplication.processEvents()
    assert win.splitter.sizes()[sidebar] == panel_width_for(4)

    settle(win.minimumSizeHint().width())  # squeezed as far as it goes
    assert gui_settings.grid_columns == 4  # the choice is untouched

    settle(roomy)
    assert win.splitter.sizes()[sidebar] == panel_width_for(4)  # and it comes back


def test_first_launch_seeds_a_folder(qtbot, monkeypatch, tmp_path):
    """With no saved folder the window opens on the user's pictures directory."""
    from myimages.config import Settings
    from myimages.gui import main_window as main_window_module

    pictures = tmp_path / "Pictures"
    pictures.mkdir()
    Image.new("RGB", (10, 10), (0, 0, 0)).save(pictures / "seeded.png")
    monkeypatch.setattr(main_window_module, "default_media_dir", lambda: pictures)

    settings = Settings()  # nothing persisted yet
    win = make_window(qtbot, settings)
    assert settings.last_folder == str(pictures)
    assert win.folder_input.text() == str(pictures)
    assert [f.name for f in win.media_files] == ["seeded.png"]


def test_saved_folder_is_not_overridden(qtbot, gui_settings, image_dir):
    gui_settings.last_folder = str(image_dir)
    win = make_window(qtbot, gui_settings)
    assert win.folder_input.text() == str(image_dir)
    assert len(win.media_files) == 3


def test_unreadable_folder_opens_empty_instead_of_crashing(
    qtbot, gui_settings, tmp_path
):
    import os

    locked = tmp_path / "locked"
    locked.mkdir()
    Image.new("RGB", (10, 10), (0, 0, 0)).save(locked / "inside.png")
    os.chmod(locked, 0o000)
    try:
        gui_settings.last_folder = str(locked)
        win = make_window(qtbot, gui_settings)  # must not raise
        assert win.media_files == []
    finally:
        os.chmod(locked, 0o755)


def test_settings_dialog_resyncs_recursive_button(qtbot, gui_settings, monkeypatch):
    win = make_window(qtbot, gui_settings)
    assert win.recursive_button.isChecked() is False
    from myimages.gui.settings_dialog import SettingsDialog

    def fake_exec(self):
        self.recursive_check.setChecked(True)
        return True

    monkeypatch.setattr(SettingsDialog, "exec", fake_exec)
    win.open_settings()
    assert gui_settings.recursive_scan is True
    assert win.recursive_button.isChecked() is True  # top bar follows the dialog


def test_rename_fallback_ignores_filtered_out_files(
    qtbot, gui_settings, tmp_path, monkeypatch
):
    """With nothing selected, rename must only target what the list shows."""
    for name in ("cat.png", "dog.png"):
        Image.new("RGB", (10, 10), (0, 0, 0)).save(tmp_path / name)
    gui_settings.last_folder = str(tmp_path)
    win = make_window(qtbot, gui_settings)
    win.file_list.search_edit.setText("cat")  # dog.png is filtered out
    win.file_list.clear_selection()

    seen: list[int] = []
    from myimages.gui.rename_dialog import RenameDialog

    original_init = RenameDialog.__init__

    def spy_init(self, files, parent=None):
        seen.append(len(files))
        original_init(self, files, parent)

    monkeypatch.setattr(RenameDialog, "__init__", spy_init)
    monkeypatch.setattr(RenameDialog, "exec", lambda self: False)
    win.open_rename()
    assert seen == [1]  # only the visible cat.png, never the hidden dog.png


def dominant_icon_colour(button) -> str:
    """The most common opaque colour in a button's icon."""
    image = button.icon().pixmap(22, 22).toImage()
    counts: dict[str, int] = {}
    for y in range(image.height()):
        for x in range(image.width()):
            colour = image.pixelColor(x, y)
            if colour.alpha() > 200:
                counts[colour.name()] = counts.get(colour.name(), 0) + 1
    return max(counts, key=lambda name: counts[name]) if counts else "none"


def test_theme_switch_recolours_every_icon(qtbot, gui_settings, monkeypatch):
    """Icons bake in the theme colour, so a theme switch must redraw them."""
    from myimages.app import apply_theme_to_app

    apply_theme_to_app("dark")
    win = make_window(qtbot, gui_settings)
    dark = {
        "toolbar": dominant_icon_colour(win.browse_button),
        "editor": dominant_icon_colour(win.editor.rotate_left_button),
        "preview": dominant_icon_colour(win.preview.fit_button),
        "list": dominant_icon_colour(win.file_list.view_button),
    }

    from myimages.gui.settings_dialog import SettingsDialog

    def fake_exec(self):
        self.theme_combo.setCurrentIndex(1)  # light
        return True

    monkeypatch.setattr(SettingsDialog, "exec", fake_exec)
    win.open_settings()

    assert gui_settings.theme == "light"
    light = {
        "toolbar": dominant_icon_colour(win.browse_button),
        "editor": dominant_icon_colour(win.editor.rotate_left_button),
        "preview": dominant_icon_colour(win.preview.fit_button),
        "list": dominant_icon_colour(win.file_list.view_button),
    }
    for area, colour in dark.items():
        assert light[area] != colour, f"{area} icon kept the dark theme's colour"

    apply_theme_to_app("dark")  # leave the app as the other tests expect it


# -- following a folder that changes underneath the window ------------------


def gallery_window(qtbot, settings, folder) -> MainWindow:
    """A window already showing ``folder``, with its monitor running."""
    settings.last_folder = str(folder)
    return make_window(qtbot, settings)


def warm_thumbnails(win: MainWindow) -> dict[str, tuple[MediaFile, Path]]:
    """Render every visible thumbnail; returns each file with its cached PNG.

    The grid asks for its own thumbnails on a worker pool the moment files are
    set, and those workers write the very cache files these tests then read, so
    draining the pool first is what keeps the reads deterministic.
    """
    assert win.loader.pool.waitForDone(10000)
    warmed: dict[str, tuple[MediaFile, Path]] = {}
    for media_file in win.media_files:
        assert win.loader.load_now(media_file) is not None
        cached = thumbnails.cache_path_for(media_file, win.loader.size)
        assert cached.exists()
        warmed[media_file.name] = (media_file, cached)
    return warmed


def listed_names(win: MainWindow) -> set[str]:
    return {f.name for f in win.media_files}


def test_sync_monitor_watches_the_folder_on_screen(qtbot, gui_settings, image_dir):
    win = gallery_window(qtbot, gui_settings, image_dir)

    assert win.monitor.folder == image_dir
    assert win.monitor.timer.isActive()
    assert win.monitor.watcher.directories() == [str(image_dir)]
    assert win.monitor.interval_seconds == gui_settings.watch_interval_seconds
    # Seeded from the scan the window just did, so nothing is announced as new.
    assert set(win.monitor.stamps) == {str(f.path) for f in win.media_files}


def test_switching_folders_moves_the_watch(qtbot, gui_settings, image_dir, tmp_path):
    other = tmp_path / "elsewhere"
    other.mkdir()
    Image.new("RGB", (10, 10), (4, 4, 4)).save(other / "solo.png")
    win = gallery_window(qtbot, gui_settings, image_dir)

    win.folder_input.setText(str(other))
    win.load_source()

    assert win.monitor.folder == other
    assert win.monitor.watcher.directories() == [str(other)]
    assert set(win.monitor.stamps) == {str(other / "solo.png")}

    # The folder no longer on screen is no longer followed.
    (image_dir / "alpha.png").unlink()
    win.monitor.check_now()
    assert listed_names(win) == {"solo.png"}


def test_watching_turned_off_never_starts_the_monitor(qtbot, gui_settings, image_dir):
    gui_settings.watch_folder = False
    win = gallery_window(qtbot, gui_settings, image_dir)

    assert win.monitor.folder is None
    assert not win.monitor.timer.isActive()
    assert win.monitor.watcher.directories() == []

    (image_dir / "alpha.png").unlink()
    win.monitor.check_now()

    assert len(win.media_files) == 3  # the user opted out, so nothing refreshes


def test_turning_watching_off_stops_a_running_monitor(qtbot, gui_settings, image_dir):
    win = gallery_window(qtbot, gui_settings, image_dir)
    assert win.monitor.timer.isActive()

    gui_settings.watch_folder = False
    win.load_source()

    assert win.monitor.folder is None
    assert not win.monitor.timer.isActive()
    assert win.monitor.watcher.directories() == []


def test_changing_only_the_interval_repoints_the_monitor(
    qtbot, gui_settings, image_dir
):
    win = gallery_window(qtbot, gui_settings, image_dir)
    assert win.monitor.timer.interval() == gui_settings.watch_interval_seconds * 1000

    gui_settings.watch_interval_seconds = 45
    win.load_source()

    assert win.monitor.interval_seconds == 45
    assert win.monitor.timer.interval() == 45 * 1000
    assert win.monitor.folder == image_dir
    assert win.monitor.watcher.directories() == [str(image_dir)]


def test_turning_verification_on_repoints_the_monitor(qtbot, gui_settings, image_dir):
    win = gallery_window(qtbot, gui_settings, image_dir)
    assert win.monitor.verify is False

    gui_settings.verify_checksums = True
    win.load_source()

    assert win.monitor.verify is True
    assert win.monitor.folder == image_dir


def test_scanning_sub_folders_repoints_the_monitor(qtbot, gui_settings, image_dir):
    nested = image_dir / "holiday"
    nested.mkdir()
    win = gallery_window(qtbot, gui_settings, image_dir)
    assert win.monitor.watcher.directories() == [str(image_dir)]

    win.toggle_recursive(True)

    assert win.monitor.recursive is True
    assert set(win.monitor.watcher.directories()) == {str(image_dir), str(nested)}


def test_reloading_the_same_folder_reseeds_without_repointing(
    qtbot, gui_settings, image_dir, monkeypatch
):
    """Re-pointing tears down the filesystem watches, so a reload must not.

    Every scan the window does for its own reasons goes through here, so
    restarting the watch each time would rebuild the inotify handles on every
    keystroke in the folder box.
    """
    win = gallery_window(qtbot, gui_settings, image_dir)
    watching = win.monitor.folder
    repoints: list[object] = []
    original_start = win.monitor.start

    def spy_start(folder, files, **options):
        repoints.append(folder)
        original_start(folder, files, **options)

    monkeypatch.setattr(win.monitor, "start", spy_start)
    fresh = image_dir / "delta.png"
    Image.new("RGB", (12, 12), (5, 5, 5)).save(fresh)

    win.load_source()

    assert repoints == []
    assert win.monitor.folder is watching
    assert win.monitor.timer.isActive()
    assert str(fresh) in win.monitor.stamps  # the baseline still moved on


def test_a_reload_reseeds_so_a_change_is_not_announced_twice(
    qtbot, gui_settings, image_dir
):
    win = gallery_window(qtbot, gui_settings, image_dir)
    Image.new("RGB", (12, 12), (6, 6, 6)).save(image_dir / "delta.png")

    win.load_source()  # the user's own reload already put it on screen
    announced: list[object] = []
    win.monitor.changed.connect(announced.append)
    win.monitor.check_now()

    assert announced == []
    assert "delta.png" in listed_names(win)


def test_a_file_deleted_outside_the_app_leaves_the_list_and_the_cache(
    qtbot, gui_settings, image_dir
):
    win = gallery_window(qtbot, gui_settings, image_dir)
    warmed = warm_thumbnails(win)
    gone, gone_png = warmed["bravo.jpg"]
    kept, kept_png = warmed["alpha.png"]

    gone.path.unlink()
    win.monitor.check_now()

    assert listed_names(win) == {"alpha.png", "charlie.png"}
    assert str(gone.path) not in win.loader.cache
    assert not gone_png.exists()
    # Rebuild only what moved: the untouched photo keeps its preview.
    assert str(kept.path) in win.loader.cache
    assert kept_png.exists()


def test_a_photo_edited_outside_the_app_loses_only_its_own_preview(
    qtbot, gui_settings, image_dir
):
    win = gallery_window(qtbot, gui_settings, image_dir)
    warmed = warm_thumbnails(win)
    edited, edited_png = warmed["alpha.png"]
    kept, kept_png = warmed["charlie.png"]

    Image.new("RGB", (300, 200), (7, 200, 7)).save(edited.path)
    assert edited.path.stat().st_size != edited.size_bytes
    win.monitor.check_now()

    assert str(edited.path) not in win.loader.cache
    assert not edited_png.exists()
    assert str(kept.path) in win.loader.cache
    assert kept_png.exists()
    assert listed_names(win) == {"alpha.png", "bravo.jpg", "charlie.png"}


def test_a_file_added_outside_the_app_shows_up(qtbot, gui_settings, image_dir):
    win = gallery_window(qtbot, gui_settings, image_dir)
    fresh = image_dir / "delta.png"
    Image.new("RGB", (16, 16), (3, 3, 3)).save(fresh)

    win.monitor.check_now()

    assert "delta.png" in listed_names(win)
    assert str(fresh) in win.monitor.stamps


def test_an_added_only_change_keeps_every_existing_thumbnail(
    qtbot, gui_settings, image_dir
):
    win = gallery_window(qtbot, gui_settings, image_dir)
    warmed = warm_thumbnails(win)
    fresh = image_dir / "delta.png"
    Image.new("RGB", (16, 16), (2, 2, 2)).save(fresh)

    win.on_folder_changed(FolderChanges(added=(str(fresh),)))

    assert "delta.png" in listed_names(win)
    for media_file, cached in warmed.values():
        assert str(media_file.path) in win.loader.cache
        assert cached.exists()


def test_delete_selected_forgets_the_deleted_thumbnail(
    qtbot, gui_settings, tmp_path, silence_dialogs
):
    for name, colour in (("one.png", (30, 0, 0)), ("two.png", (0, 30, 0))):
        Image.new("RGB", (24, 24), colour).save(tmp_path / name)
    win = gallery_window(qtbot, gui_settings, tmp_path)
    warmed = warm_thumbnails(win)
    doomed, doomed_png = warmed["one.png"]
    kept, kept_png = warmed["two.png"]

    win.file_list.clear_selection()
    win.file_list.select_path(str(doomed.path))
    win.delete_selected()

    assert not doomed.path.exists()
    assert str(doomed.path) not in win.loader.cache
    assert not doomed_png.exists()
    assert str(kept.path) in win.loader.cache
    assert kept_png.exists()


def test_closing_the_window_stops_the_monitor(qtbot, gui_settings, image_dir):
    win = gallery_window(qtbot, gui_settings, image_dir)
    assert win.monitor.timer.isActive()

    win.close()

    assert win.monitor.folder is None
    assert not win.monitor.timer.isActive()
    assert win.monitor.watcher.directories() == []

    # A closed window must not keep scanning the folder in the background.
    (image_dir / "alpha.png").unlink()
    win.monitor.check_now()
    assert len(win.media_files) == 3


def test_settings_dialog_retargets_the_monitor(
    qtbot, gui_settings, image_dir, monkeypatch
):
    win = gallery_window(qtbot, gui_settings, image_dir)
    from myimages.gui.settings_dialog import SettingsDialog

    def fake_exec(self):
        self.watch_interval_spin.setValue(30)
        self.verify_check.setChecked(True)
        return True

    monkeypatch.setattr(SettingsDialog, "exec", fake_exec)
    win.open_settings()

    assert gui_settings.watch_interval_seconds == 30
    assert gui_settings.verify_checksums is True
    assert win.monitor.interval_seconds == 30
    assert win.monitor.verify is True


def test_settings_dialog_can_switch_watching_off(
    qtbot, gui_settings, image_dir, monkeypatch
):
    win = gallery_window(qtbot, gui_settings, image_dir)
    assert win.monitor.timer.isActive()
    from myimages.gui.settings_dialog import SettingsDialog

    def fake_exec(self):
        self.watch_check.setChecked(False)
        return True

    monkeypatch.setattr(SettingsDialog, "exec", fake_exec)
    win.open_settings()

    assert gui_settings.watch_folder is False
    assert win.monitor.folder is None
    assert not win.monitor.timer.isActive()


# -- right-click menu -------------------------------------------------------


def menu_labels(win) -> list[str]:
    return [action.text() for action in win.build_preview_menu().actions()]


def enabled_labels(win) -> set[str]:
    return {a.text() for a in win.build_preview_menu().actions() if a.isEnabled()}


def test_preview_menu_offers_every_action_for_an_image(qtbot, gui_settings, image_dir):
    win = make_window(qtbot, gui_settings)
    load_gallery(win, image_dir)
    labels = menu_labels(win)
    assert labels == [
        "Copy File",
        "Copy Filename",
        "Copy Picture",
        "Delete",
        "Rename",
        "Select",
        "Edit Image",
        "Rotate",
        "Convert",
        "Remove Watermark",
        "Remove Background",
    ]
    assert enabled_labels(win) == set(labels)


def test_picture_only_actions_are_disabled_for_a_video(qtbot, gui_settings, tmp_path):
    win = make_window(qtbot, gui_settings)
    win.set_media_files([video_media(tmp_path / "clip.mp4")])
    enabled = enabled_labels(win)
    assert {"Copy File", "Delete", "Rename", "Select"} <= enabled
    assert enabled.isdisjoint(
        {"Copy Picture", "Edit Image", "Rotate", "Convert", "Remove Watermark"}
    )


def test_menu_is_all_disabled_with_nothing_selected(qtbot, gui_settings):
    win = make_window(qtbot, gui_settings)
    assert win.current is None
    assert enabled_labels(win) == set()


def test_copy_image_puts_pixels_on_the_clipboard(qtbot, gui_settings, image_dir):
    from PySide6.QtGui import QGuiApplication

    win = make_window(qtbot, gui_settings)
    load_gallery(win, image_dir)
    win.copy_image_to_clipboard()
    assert QGuiApplication.clipboard().mimeData().hasImage()


def test_copy_image_ignores_a_video(qtbot, gui_settings, tmp_path):
    from PySide6.QtGui import QGuiApplication

    QGuiApplication.clipboard().clear()
    win = make_window(qtbot, gui_settings)
    win.set_media_files([video_media(tmp_path / "clip.mp4")])
    win.copy_image_to_clipboard()
    # An emptied clipboard reports no mime data at all on the offscreen platform.
    mime = QGuiApplication.clipboard().mimeData()
    assert mime is None or not mime.hasImage()


def test_select_action_toggles_the_current_file(qtbot, gui_settings, image_dir):
    win = make_window(qtbot, gui_settings)
    load_gallery(win, image_dir)
    win.file_list.clear_selection()
    assert win.file_list.selected_files() == []

    win.toggle_current_selection()
    assert len(win.file_list.selected_files()) == 1

    win.toggle_current_selection()
    assert win.file_list.selected_files() == []


def test_rotate_action_turns_the_file_on_disk(
    qtbot, gui_settings, make_image, silence_dialogs
):
    image = make_image("turn.png", (40, 20), (10, 90, 140))
    gui_settings.last_folder = str(image.parent)
    win = make_window(qtbot, gui_settings)
    assert Image.open(image).size == (40, 20)

    win.rotate_current_file()

    assert Image.open(image).size == (20, 40)  # a quarter turn swaps the edges
    assert str(image) not in win.loader.cache  # its thumbnail was dropped


def test_rotate_action_ignores_a_video(qtbot, gui_settings, tmp_path):
    win = make_window(qtbot, gui_settings)
    win.set_media_files([video_media(tmp_path / "clip.mp4")])
    win.rotate_current_file()  # early return, must not raise


def test_remove_watermark_action_opens_the_editor_with_the_mark_gone(
    qtbot, gui_settings, tmp_path
):
    from PIL import ImageDraw, ImageStat

    picture = Image.new("RGB", (800, 600), (46, 40, 36))
    ImageDraw.Draw(picture).ellipse((700, 520, 740, 552), fill=(215, 215, 215))
    picture.save(tmp_path / "marked.png")
    gui_settings.last_folder = str(tmp_path)
    win = make_window(qtbot, gui_settings)

    win.open_watermark_editor()

    assert win.preview_area.currentWidget() is win.editor
    assert win.editor.status_label.text() == "Watermark removed"
    corner = (695, 515, 745, 557)
    assert ImageStat.Stat(win.editor.working_image.crop(corner)).mean[0] < 70
    # Still only in the editor: nothing is written until the user saves.
    assert ImageStat.Stat(Image.open(tmp_path / "marked.png").crop(corner)).mean[0] > 70


def test_remove_watermark_action_ignores_a_video(qtbot, gui_settings, tmp_path):
    win = make_window(qtbot, gui_settings)
    win.set_media_files([video_media(tmp_path / "clip.mp4")])
    win.open_watermark_editor()
    assert win.preview_area.currentWidget() is win.preview


def test_an_empty_folder_box_is_never_watched(qtbot, gui_settings):
    """An empty path resolves to the process working directory, never a gallery."""
    win = make_window(qtbot, gui_settings)
    win.folder_input.setText("")
    win.load_source()
    assert win.settings.last_folder == ""
    assert win.monitor.folder is None
    assert not win.monitor.timer.isActive()


def test_a_background_refresh_ignores_a_half_typed_path(qtbot, gui_settings, image_dir):
    """Typing a new folder must not blank the gallery mid-keystroke."""
    gui_settings.last_folder = str(image_dir)
    win = make_window(qtbot, gui_settings)
    assert len(win.media_files) == 3

    win.folder_input.setText("/nowhere/half-typ")  # user is still typing
    win.rescan_watched_folder()  # a watcher tick lands right now

    assert len(win.media_files) == 3  # still showing the watched folder


def test_an_external_change_keeps_the_selection(qtbot, gui_settings, tmp_path):
    for index in range(3):
        Image.new("RGB", (10, 10), (index * 40, 0, 0)).save(tmp_path / f"s{index}.png")
    gui_settings.last_folder = str(tmp_path)
    win = make_window(qtbot, gui_settings)
    win.file_list.select_all()
    assert len(win.file_list.selected_files()) == 3

    (tmp_path / "s2.png").unlink()  # something changes on disk
    win.monitor.check_now()

    assert len(win.media_files) == 2
    # The two survivors are still selected: a refresh must not silently drop
    # the set of files the user had picked out.
    assert len(win.file_list.selected_files()) == 2


def test_open_file_shows_that_file_and_its_folder(qtbot, gui_settings, image_dir):
    """Double-clicking a photo in a file manager arrives here."""
    win = make_window(qtbot, gui_settings)
    target = image_dir / "bravo.jpg"

    win.open_file(target)

    assert win.settings.last_folder == str(image_dir)
    assert len(win.media_files) == 3  # the whole folder, to step through
    assert win.current is not None and win.current.name == "bravo.jpg"


def test_open_file_ignores_a_path_that_is_not_a_file(qtbot, gui_settings, image_dir):
    gui_settings.last_folder = str(image_dir)
    win = make_window(qtbot, gui_settings)
    win.open_file(image_dir / "gone.png")
    assert len(win.media_files) == 3  # unchanged


def test_the_two_copy_actions_say_what_they_copy(qtbot, gui_settings, image_dir):
    """ "Copy" and "Copy Image" side by side read as the same thing."""
    win = make_window(qtbot, gui_settings)
    load_gallery(win, image_dir)
    menu = win.build_preview_menu()
    hints = {action.text(): action.toolTip() for action in menu.actions()}

    assert "folder" in hints["Copy File"]
    assert "chat" in hints["Copy Picture"] or "editor" in hints["Copy Picture"]
    assert menu.toolTipsVisible() is True  # otherwise the hints never show


def test_the_copy_action_counts_the_selected_files(qtbot, gui_settings, image_dir):
    win = make_window(qtbot, gui_settings)
    load_gallery(win, image_dir)
    win.file_list.select_all()
    selected = len(win.file_list.selected_or_current())
    assert selected > 1

    assert f"Copy {selected} Files" in menu_labels(win)


def test_the_copy_label_is_singular_for_one_file(qtbot, gui_settings):
    from myimages.gui.main_window import copy_files_label

    assert copy_files_label(0) == "Copy File"
    assert copy_files_label(1) == "Copy File"
    assert copy_files_label(4) == "Copy 4 Files"


def test_copy_filename_puts_plain_text_on_the_clipboard(qtbot, gui_settings, image_dir):
    from PySide6.QtGui import QGuiApplication

    win = make_window(qtbot, gui_settings)
    load_gallery(win, image_dir)
    win.file_list.select_all()
    names = [media_file.name for media_file in win.file_list.selected_or_current()]
    assert len(names) > 1

    win.file_list.copy_names_to_clipboard()

    clipboard = QGuiApplication.clipboard()
    assert clipboard.text() == "\n".join(names)


def test_copy_filename_falls_back_to_the_previewed_file(qtbot, gui_settings, image_dir):
    from PySide6.QtGui import QGuiApplication

    win = make_window(qtbot, gui_settings)
    load_gallery(win, image_dir)
    win.file_list.clear_selection()

    win.file_list.copy_names_to_clipboard()

    assert QGuiApplication.clipboard().text() == win.current.name


def test_copy_filename_does_nothing_with_an_empty_gallery(qtbot, gui_settings):
    from PySide6.QtGui import QGuiApplication

    win = make_window(qtbot, gui_settings)
    win.set_media_files([])
    QGuiApplication.clipboard().setText("untouched")

    win.file_list.copy_names_to_clipboard()

    assert QGuiApplication.clipboard().text() == "untouched"


def test_the_filename_label_counts_the_selection(qtbot):
    from myimages.gui.main_window import copy_names_label

    assert copy_names_label(0) == "Copy Filename"
    assert copy_names_label(1) == "Copy Filename"
    assert copy_names_label(3) == "Copy 3 Filenames"


# -- what is selected, and what has the keyboard ----------------------------


@pytest.mark.parametrize("mode", ["grid", "list", "table"])
def test_opening_a_file_selects_only_that_file(qtbot, gui_settings, image_dir, mode):
    """Arriving from a file manager must not drag the folder's first photo along."""
    gui_settings.list_view_mode = mode
    win = make_window(qtbot, gui_settings)
    target = image_dir / "charlie.png"  # not the first file the folder loads

    win.open_file(target)

    assert win.current.name == target.name
    assert [f.name for f in win.file_list.selected_files()] == [target.name]


@pytest.mark.parametrize("mode", ["grid", "list", "table"])
def test_stepping_through_photos_does_not_hoard_them(
    qtbot, gui_settings, image_dir, mode
):
    """Pressing Right ten times used to leave eleven files ready to be deleted."""
    gui_settings.list_view_mode = mode
    win = make_window(qtbot, gui_settings)
    load_gallery(win, image_dir)

    for step in range(2):
        win.file_list.step(1)

    assert len(win.file_list.selected_files()) == 1
    assert win.file_list.selected_files()[0].name == win.current.name


@pytest.mark.parametrize("mode", ["grid", "list", "table"])
def test_a_refresh_never_adds_the_previewed_file_to_the_picks(
    qtbot, gui_settings, image_dir, mode
):
    """The picks are the user's; a rebuild may restore them but not extend them."""
    gui_settings.list_view_mode = mode
    win = make_window(qtbot, gui_settings)
    load_gallery(win, image_dir)
    everything = win.file_list.visible_files()
    picked = everything[0]
    win.file_list.clear_selection()
    win.file_list.select_path(str(picked.path))
    win.file_list.set_current_without_selecting(2)  # preview a file that is not picked

    win.file_list.refresh()

    assert [f.name for f in win.file_list.selected_files()] == [picked.name]


@pytest.mark.parametrize("mode", ["grid", "list", "table"])
def test_a_fresh_folder_shows_which_photo_is_open(qtbot, gui_settings, image_dir, mode):
    """With no picks to protect, the previewed file is selected so it looks open."""
    gui_settings.list_view_mode = mode
    win = make_window(qtbot, gui_settings)
    load_gallery(win, image_dir)

    assert len(win.file_list.selected_files()) == 1
    assert win.file_list.selected_files()[0].name == win.current.name


def test_switching_view_mode_keeps_the_photo_that_is_open(
    qtbot, gui_settings, image_dir
):
    """Flipping to the table used to jump the preview back to the first photo."""
    win = make_window(qtbot, gui_settings)
    load_gallery(win, image_dir)
    win.file_list.step(2)
    opened = win.current.name

    for step in range(3):  # grid -> list -> table -> grid
        win.file_list.cycle_view_mode()
        assert win.current.name == opened


def test_opening_a_file_puts_the_keyboard_on_the_photos(qtbot, gui_settings, image_dir):
    """Otherwise the arrow keys type into the folder box instead of navigating."""
    win = make_window(qtbot, gui_settings)
    with qtbot.waitExposed(win):
        win.show()
    win.folder_input.setFocus()

    win.open_file(image_dir / "bravo.jpg")

    view = (
        win.file_list.table if win.file_list.table_mode() else win.file_list.icon_list
    )
    assert view.hasFocus()
    assert not win.folder_input.hasFocus()


def test_a_mistyped_folder_leaves_the_caret_where_it_can_be_fixed(
    qtbot, gui_settings, tmp_path
):
    win = make_window(qtbot, gui_settings)
    with qtbot.waitExposed(win):
        win.show()
    win.folder_input.setText(str(tmp_path / "no-such-folder"))
    win.folder_input.setFocus()

    win.open_typed_folder()

    assert win.folder_input.hasFocus()


def test_return_in_the_folder_box_hands_over_the_results(
    qtbot, gui_settings, image_dir
):
    win = make_window(qtbot, gui_settings)
    with qtbot.waitExposed(win):
        win.show()
    win.folder_input.setText(str(image_dir))
    win.folder_input.setFocus()

    win.open_typed_folder()

    view = (
        win.file_list.table if win.file_list.table_mode() else win.file_list.icon_list
    )
    assert view.hasFocus()


def test_renaming_from_the_menu_touches_only_that_file(qtbot, gui_settings, image_dir):
    """The context menu renames one file; the batch tool stays on the toolbar."""
    from myimages.gui import main_window as module

    win = make_window(qtbot, gui_settings)
    win.folder_input.setText(str(image_dir))  # rename reloads from the folder box
    win.load_source()
    win.file_list.select_path(str(image_dir / "bravo.jpg"))
    before = {path.name for path in image_dir.iterdir()}

    class Renamer:
        def __init__(self, path, parent=None):
            self.path = path

        def exec(self):
            return 1

        def new_path(self):
            return self.path.with_name("seaside.jpg")

    monkey = pytest.MonkeyPatch()
    monkey.setattr(
        "myimages.gui.single_rename_dialog.SingleRenameDialog", Renamer, raising=True
    )
    try:
        win.rename_current_file()
    finally:
        monkey.undo()

    after = {path.name for path in image_dir.iterdir()}
    assert after == (before - {"bravo.jpg"}) | {"seaside.jpg"}
    assert win.current.name == "seaside.jpg"
    assert module.MainWindow.rename_current_file is not None


def test_renaming_to_the_same_name_does_nothing(qtbot, gui_settings, image_dir):
    win = make_window(qtbot, gui_settings)
    win.folder_input.setText(str(image_dir))
    win.load_source()
    win.file_list.select_path(str(image_dir / "bravo.jpg"))
    before = sorted(path.name for path in image_dir.iterdir())

    class SameName:
        def __init__(self, path, parent=None):
            self.path = path

        def exec(self):
            return 1

        def new_path(self):
            return self.path

    monkey = pytest.MonkeyPatch()
    monkey.setattr(
        "myimages.gui.single_rename_dialog.SingleRenameDialog", SameName, raising=True
    )
    try:
        win.rename_current_file()
    finally:
        monkey.undo()

    assert sorted(path.name for path in image_dir.iterdir()) == before


def test_renaming_with_nothing_open_is_harmless(qtbot, gui_settings):
    win = make_window(qtbot, gui_settings)
    win.set_media_files([])
    win.rename_current_file()  # must not raise


def test_the_side_button_lives_in_the_top_bar(qtbot, gui_settings):
    """Moved out of the file list so all the window's tools sit together."""
    win = make_window(qtbot, gui_settings)
    assert win.side_button.isVisibleTo(win)
    assert not hasattr(win.file_list, "side_button")
    assert "left" in win.side_button.toolTip()

    win.toggle_panel_side()

    assert "right" in win.side_button.toolTip()
    assert not win.side_button.icon().isNull()


def test_double_clicking_a_thumbnail_opens_the_editor(qtbot, gui_settings, image_dir):
    win = make_window(qtbot, gui_settings)
    load_gallery(win, image_dir)

    win.file_list.edit_requested.emit()

    assert win.preview_area.currentWidget() is win.editor


def test_unfavouriting_the_last_favourite_does_not_crash(
    qtbot, gui_settings, image_dir
):
    """The refresh empties the view, so the current file is gone by then."""
    win = make_window(qtbot, gui_settings)
    load_gallery(win, image_dir)
    win.file_list.select_path(str(image_dir / "bravo.jpg"))
    win.toggle_favorite_current()
    win.file_list.favorites_button.setChecked(True)  # show only favourites
    assert len(win.file_list.visible_files()) == 1

    win.toggle_favorite_current()  # un-star the only one left

    assert gui_settings.favorites == []  # and the change was actually saved
    assert win.file_list.visible_files() == []


def test_toolbar_icons_are_shown_at_the_size_they_are_drawn(qtbot, gui_settings):
    """Qt's 16px default downscaled them and smudged the fine detail."""
    from myimages import icons

    win = make_window(qtbot, gui_settings)
    assert win.action_edit.iconSize().width() == icons.CANVAS


# -- keyboard focus at startup ------------------------------------------------
#
# These assert on window.focusWidget() rather than widget.hasFocus(): hasFocus()
# is only true once the window is also ACTIVE, and the offscreen platform used by
# the suite never activates anything. focusWidget() is the widget the keystrokes
# will reach the moment the window does become active, which is the real claim.


def test_opening_the_app_puts_the_keyboard_on_the_photos(
    qtbot, gui_settings, image_dir
):
    """The app used to open with the cursor blinking in the folder path."""
    gui_settings.last_folder = str(image_dir)
    win = make_window(qtbot, gui_settings)

    win.show()
    qtbot.waitExposed(win)

    assert win.focusWidget() is win.file_list.icon_list
    assert win.focusWidget() is not win.folder_input


def test_a_folder_with_nothing_in_it_leaves_the_path_editable(qtbot, gui_settings):
    """Moving off a mistyped path into an empty list would strand the user."""
    win = make_window(qtbot, gui_settings)  # gui_settings points at an empty folder

    win.show()
    qtbot.waitExposed(win)

    assert win.file_list.active_count() == 0
    # Qt only picks its own default focus widget once the window is ACTIVATED,
    # which the offscreen platform never does, so focusWidget() is None here.
    # What this test can honestly pin down is that we left the keyboard alone;
    # that it then rests in the path box was verified against a real display.
    assert win.focusWidget() is not win.file_list.icon_list
    assert win.focusWidget() is not win.file_list.table
    # still owed a hand-over, so loading a real folder later still moves on
    assert win.keyboard_handed_over is False


def test_showing_the_window_again_does_not_steal_the_keyboard(
    qtbot, gui_settings, image_dir
):
    """Restoring from the taskbar must not yank focus out of the search box."""
    gui_settings.last_folder = str(image_dir)
    win = make_window(qtbot, gui_settings)
    win.show()
    qtbot.waitExposed(win)
    win.file_list.search_edit.setFocus()

    win.hide()
    win.show()
    qtbot.waitExposed(win)

    assert win.focusWidget() is win.file_list.search_edit


def test_remove_background_opens_the_editor_already_in_cutout_mode(
    qtbot, gui_settings, image_dir
):
    """The menu row is the whole point of the entry: one step, not two."""
    win = make_window(qtbot, gui_settings)
    load_gallery(win, image_dir)
    win.open_cutout_editor()
    assert win.preview_area.currentWidget() is win.editor
    assert win.editor.mode == "background"


def test_remove_background_is_offered_only_for_an_image(qtbot, gui_settings, image_dir):
    win = make_window(qtbot, gui_settings)
    load_gallery(win, image_dir)
    assert "Remove Background" in enabled_labels(win)
    assert win.action_cutout.isEnabled()

    win.current = None
    win.update_action_states()
    assert not win.action_cutout.isEnabled()


def test_remove_background_does_nothing_without_a_current_image(qtbot, gui_settings):
    win = make_window(qtbot, gui_settings)
    win.open_cutout_editor()
    assert win.preview_area.currentWidget() is not win.editor


def test_the_wordmark_reads_myimages_in_two_colours(qtbot, gui_settings):
    """MY takes the scheme's tint, IMAGES its text colour."""
    win = make_window(qtbot, gui_settings)
    markup = win.brand.text()
    assert ">MY<" in markup and ">IMAGES<" in markup

    dark = theme.scheme_for("dark")
    assert dark.brand_tint in markup
    assert dark.text in markup


def test_the_wordmark_follows_a_theme_change(qtbot, gui_settings):
    """A literal white would vanish against the light scheme."""
    win = make_window(qtbot, gui_settings)
    win.settings.theme = "light"
    win.apply_theme()
    light = theme.scheme_for("light")
    assert light.brand_tint in win.brand.text()
    assert light.text in win.brand.text()


def make_folder(tmp_path, name, count) -> Path:
    """A folder of ``count`` small distinct pictures, named p0..pN."""
    folder = tmp_path / name
    folder.mkdir()
    for index in range(count):
        Image.new("RGB", (32, 32), (10 * index, 40, 90)).save(folder / f"p{index}.png")
    return folder


def tick_watch(win) -> None:
    """Run one folder-watch pass inline instead of waiting for the timer."""
    win.monitor.runner = synchronous_runner
    win.monitor.check_now()


def test_a_file_arriving_in_the_folder_keeps_the_selection(
    qtbot, gui_settings, tmp_path
):
    """A camera import or a sync client dropping a file in mid-session must not
    take the user's multi-selection with it: the next tool press would then act
    on nothing, or on the wrong file."""
    folder = make_folder(tmp_path, "shots", 3)
    gui_settings.watch_folder = True
    win = make_window(qtbot, gui_settings)
    win.folder_input.setText(str(folder))
    win.load_source()
    win.file_list.select_all()
    before = win.file_list.selected_path_set()
    assert len(before) == 3

    Image.new("RGB", (32, 32), (255, 255, 0)).save(folder / "new.png")
    tick_watch(win)

    assert len(win.media_files) == 4
    assert {str(f.path) for f in win.file_list.selected_files()} >= before


def test_the_table_view_keeps_its_selection_too(qtbot, gui_settings, tmp_path):
    """The three views hold their selection in different widgets, so the grid
    surviving says nothing about the table."""
    gui_settings.list_view_mode = "table"
    gui_settings.watch_folder = True
    folder = make_folder(tmp_path, "shots-table", 3)
    win = make_window(qtbot, gui_settings)
    win.folder_input.setText(str(folder))
    win.load_source()
    win.file_list.select_all()
    before = win.file_list.selected_path_set()
    assert len(before) == 3

    Image.new("RGB", (32, 32), (255, 255, 0)).save(folder / "new.png")
    tick_watch(win)

    assert {str(f.path) for f in win.file_list.selected_files()} >= before


def test_a_file_deleted_elsewhere_leaves_the_rest_selected(
    qtbot, gui_settings, tmp_path
):
    """The removed file drops out of the selection and nothing else does."""
    folder = make_folder(tmp_path, "shots-deleted", 4)
    gui_settings.watch_folder = True
    win = make_window(qtbot, gui_settings)
    win.folder_input.setText(str(folder))
    win.load_source()
    win.file_list.select_all()
    assert len(win.file_list.selected_files()) == 4

    (folder / "p2.png").unlink()
    tick_watch(win)

    surviving = sorted(f.name for f in win.file_list.selected_files())
    assert surviving == ["p0.png", "p1.png", "p3.png"]


def test_the_tools_stay_enabled_across_a_watch_tick(qtbot, gui_settings, tmp_path):
    """The selection surviving is only half of it: the actions are enabled from
    the selection, and a tick that leaves them disabled is the same failure one
    step later."""
    folder = make_folder(tmp_path, "shots-actions", 3)
    gui_settings.watch_folder = True
    win = make_window(qtbot, gui_settings)
    win.folder_input.setText(str(folder))
    win.load_source()
    win.file_list.select_all()
    assert win.action_gif.isEnabled()

    Image.new("RGB", (32, 32), (255, 255, 0)).save(folder / "new.png")
    tick_watch(win)

    assert len(win.selected_images()) == 3
    assert win.action_gif.isEnabled()
