"""Tests for :mod:`myimages.gui.file_list`.

``FileListPanel`` presents the media as a grid of thumbnails, a plain name list
or a sortable table (with a favourite star column and a ★ header). Every test
requests ``qtbot`` for a live ``QApplication`` and ``gui_settings`` for fresh
``Settings``. Real PNGs become image ``MediaFile`` snapshots; a
``.mp4`` stub classifies as a video by extension.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QPixmap

from myimages.config import Settings
from myimages.core.media import MediaFile, build_media_file
from myimages.gui.file_list import (
    FAVOURITE_COLUMN,
    LIST_STAR,
    NAME_COLUMN,
    RESOLUTION_COLUMN,
    SIZE_COLUMN,
    FileListPanel,
)
from myimages.gui.thumbnail_loader import ThumbnailLoader


def build_image(
    make_image, name: str, size=(40, 30), colour=(200, 90, 40)
) -> MediaFile:
    path = make_image(name, size, colour)
    return build_media_file(path).with_dimensions(size[0], size[1])


def build_video(tmp_path: Path, name: str = "clip.mp4") -> MediaFile:
    path = tmp_path / name
    path.write_bytes(b"\x00" * 32)
    return build_media_file(path)


def build_panel(qtbot, settings: Settings, files: list[MediaFile]) -> FileListPanel:
    panel = FileListPanel(settings, ThumbnailLoader(size=64))
    qtbot.addWidget(panel)
    panel.set_files(files)
    return panel


def make_gallery(make_image, tmp_path: Path) -> list[MediaFile]:
    """Three images and one video, deliberately out of name order."""
    return [
        build_image(make_image, "charlie.png", colour=(0, 0, 255)),
        build_image(make_image, "alpha.png", colour=(255, 0, 0)),
        build_image(make_image, "bravo.png", colour=(0, 255, 0)),
        build_video(tmp_path),
    ]


def names(files: list[MediaFile]) -> list[str]:
    return [f.name for f in files]


def current_name(panel: FileListPanel) -> str:
    current = panel.current_file()
    assert current is not None
    return current.name


# -- filtering & sorting ---------------------------------------------------


def test_visible_files_sorted_by_name(qtbot, gui_settings, make_image, tmp_path):
    panel = build_panel(qtbot, gui_settings, make_gallery(make_image, tmp_path))
    assert names(panel.visible_files()) == [
        "alpha.png",
        "bravo.png",
        "charlie.png",
        "clip.mp4",
    ]


def test_visible_files_honours_sort_order(qtbot, gui_settings, make_image, tmp_path):
    gui_settings.sort_descending = True
    panel = build_panel(qtbot, gui_settings, make_gallery(make_image, tmp_path))
    assert names(panel.visible_files())[0] == "clip.mp4"


def test_passes_filters_for_image_video_favourites_and_search(
    qtbot, gui_settings, make_image, tmp_path
):
    image = build_image(make_image, "alpha.png")
    video = build_video(tmp_path)
    panel = build_panel(qtbot, gui_settings, [image, video])

    assert panel.passes_filters(image) is True
    assert panel.passes_filters(video) is True

    gui_settings.show_images = False
    assert panel.passes_filters(image) is False
    gui_settings.show_images = True

    gui_settings.show_videos = False
    assert panel.passes_filters(video) is False
    gui_settings.show_videos = True

    gui_settings.favorites_only = True
    gui_settings.toggle_favorite(str(image.path))
    assert panel.passes_filters(image) is True
    assert panel.passes_filters(video) is False
    gui_settings.favorites_only = False

    panel.search_text = "alph"
    assert panel.passes_filters(image) is True
    assert panel.passes_filters(video) is False


def test_search_box_filters_by_name(qtbot, gui_settings, make_image, tmp_path):
    files = [
        build_image(make_image, "cat.png"),
        build_image(make_image, "dog.png"),
        build_image(make_image, "catnip.png"),
    ]
    panel = build_panel(qtbot, gui_settings, files)
    with qtbot.waitSignal(panel.visible_changed, timeout=1000):
        panel.search_edit.setText("cat")
    assert set(names(panel.visible_files())) == {"cat.png", "catnip.png"}


# -- view modes ------------------------------------------------------------


def test_cycle_view_mode_grid_list_table(qtbot, gui_settings, make_image, tmp_path):
    panel = build_panel(qtbot, gui_settings, make_gallery(make_image, tmp_path))
    assert gui_settings.list_view_mode == "grid"
    assert not panel.view_button.icon().isNull()

    panel.cycle_view_mode()
    assert gui_settings.list_view_mode == "list"
    panel.cycle_view_mode()
    assert gui_settings.list_view_mode == "table"
    assert panel.stack.currentWidget() is panel.table
    panel.cycle_view_mode()
    assert gui_settings.list_view_mode == "grid"
    assert panel.stack.currentWidget() is panel.icon_list


def test_invalid_saved_mode_resets_to_grid(qtbot):
    settings = Settings()
    settings.list_view_mode = "nonsense"
    panel = FileListPanel(settings, ThumbnailLoader(size=64))
    qtbot.addWidget(panel)
    assert settings.list_view_mode == "grid"


def test_table_mode_has_star_header(qtbot, gui_settings, make_image, tmp_path):
    gui_settings.list_view_mode = "table"
    panel = build_panel(qtbot, gui_settings, make_gallery(make_image, tmp_path))
    assert panel.table.horizontalHeaderItem(FAVOURITE_COLUMN).text() == "★"


def test_list_mode_shows_names(qtbot, gui_settings, make_image, tmp_path):
    gui_settings.list_view_mode = "list"
    panel = build_panel(qtbot, gui_settings, make_gallery(make_image, tmp_path))
    row = panel.index_by_path[str(panel.visible_files()[0].path)]
    assert panel.icon_list.item(row).text() == "alpha.png"


# -- header sorting --------------------------------------------------------


def test_header_click_sets_key_and_toggles_direction(
    qtbot, gui_settings, make_image, tmp_path
):
    gui_settings.list_view_mode = "table"
    panel = build_panel(qtbot, gui_settings, make_gallery(make_image, tmp_path))

    panel.handle_header_clicked(SIZE_COLUMN)
    assert gui_settings.sort_key == "size"
    assert gui_settings.sort_descending is False
    panel.handle_header_clicked(SIZE_COLUMN)
    assert gui_settings.sort_descending is True
    panel.handle_header_clicked(RESOLUTION_COLUMN)
    assert (gui_settings.sort_key, gui_settings.sort_descending) == (
        "resolution",
        False,
    )


def test_header_click_on_star_column_is_ignored(
    qtbot, gui_settings, make_image, tmp_path
):
    gui_settings.list_view_mode = "table"
    panel = build_panel(qtbot, gui_settings, make_gallery(make_image, tmp_path))
    before = gui_settings.sort_key
    panel.handle_header_clicked(FAVOURITE_COLUMN)
    assert gui_settings.sort_key == before


def test_sort_indicator_falls_back_for_non_column_key(
    qtbot, gui_settings, make_image, tmp_path
):
    gui_settings.list_view_mode = "table"
    gui_settings.sort_key = "modified"
    panel = build_panel(qtbot, gui_settings, make_gallery(make_image, tmp_path))
    assert panel.table.horizontalHeader().sortIndicatorSection() == NAME_COLUMN


# -- controls --------------------------------------------------------------


def test_favorites_button_toggles_setting(qtbot, gui_settings, make_image, tmp_path):
    panel = build_panel(qtbot, gui_settings, make_gallery(make_image, tmp_path))
    panel.favorites_button.setChecked(True)
    assert gui_settings.favorites_only is True
    panel.favorites_button.setChecked(False)
    assert gui_settings.favorites_only is False


def test_the_columns_button_cycles_and_announces_the_count(
    qtbot, gui_settings, make_image, tmp_path
):
    """The panel width is chosen in whole thumbnails, not dragged in pixels."""
    panel = build_panel(qtbot, gui_settings, make_gallery(make_image, tmp_path))
    gui_settings.grid_columns = 2

    with qtbot.waitSignal(panel.columns_changed, timeout=1000) as caught:
        panel.columns_button.click()

    assert gui_settings.grid_columns == 3
    assert caught.args == [3]
    assert panel.columns_button.toolTip() == "3 per row"
    assert not panel.columns_button.icon().isNull()


def test_the_column_count_wraps_round(qtbot, gui_settings):
    from myimages.gui.file_list import next_column_count

    assert [next_column_count(n) for n in (1, 2, 3, 4)] == [2, 3, 4, 1]
    assert next_column_count(99) == 1  # a hand-edited settings file cannot wedge it


def test_the_panel_width_follows_the_column_count(qtbot, gui_settings):
    from myimages.gui.file_list import panel_width_for

    widths = [panel_width_for(n) for n in (1, 2, 3, 4)]
    assert widths == sorted(widths)
    steps = {b - a for a, b in zip(widths, widths[1:], strict=False)}
    assert len(steps) == 1  # each extra column costs exactly one thumbnail


# -- thumbnails & favourite badge ------------------------------------------


def test_apply_thumbnail_badges_favourite_in_grid(qtbot, gui_settings, make_image):
    image = build_image(make_image, "alpha.png")
    gui_settings.toggle_favorite(str(image.path))
    panel = build_panel(qtbot, gui_settings, [image])
    pixmap = QPixmap(str(image.path))
    assert not pixmap.isNull()
    panel.apply_thumbnail(str(image.path), pixmap)
    row = panel.index_by_path[str(image.path)]
    assert not panel.icon_list.item(row).icon().isNull()


def test_apply_thumbnail_plain_when_not_favourite(qtbot, gui_settings, make_image):
    image = build_image(make_image, "alpha.png")
    panel = build_panel(qtbot, gui_settings, [image])
    panel.apply_thumbnail(str(image.path), QPixmap(str(image.path)))
    row = panel.index_by_path[str(image.path)]
    assert not panel.icon_list.item(row).icon().isNull()
    panel.apply_thumbnail("unknown", QPixmap(str(image.path)))  # unknown: no-op


def test_apply_thumbnail_ignored_outside_grid(qtbot, gui_settings, make_image):
    gui_settings.list_view_mode = "list"
    image = build_image(make_image, "alpha.png")
    panel = build_panel(qtbot, gui_settings, [image])
    before = panel.icon_list.item(panel.index_by_path[str(image.path)]).icon()

    panel.apply_thumbnail(str(image.path), QPixmap(str(image.path)))

    row = panel.index_by_path[str(image.path)]
    after = panel.icon_list.item(row).icon()
    # List rows carry only the favourite marker, never a thumbnail.
    assert after.cacheKey() == before.cacheKey()


def test_badge_favorite_returns_same_size(qtbot, gui_settings, make_image):
    panel = build_panel(qtbot, gui_settings, [])
    pixmap = QPixmap(str(make_image(size=(80, 80))))
    badged = panel.badge_favorite(pixmap)
    assert badged.size() == pixmap.size()


# -- selection & navigation across modes -----------------------------------


def test_current_and_selected_and_select_path_in_grid(
    qtbot, gui_settings, make_image, tmp_path
):
    files = make_gallery(make_image, tmp_path)
    panel = build_panel(qtbot, gui_settings, files)
    assert current_name(panel) == "alpha.png"

    with qtbot.waitSignal(panel.current_changed, timeout=1000):
        panel.select_path(str(files[0].path))  # charlie.png
    assert current_name(panel) == "charlie.png"

    panel.select_path("missing")  # unknown path leaves selection untouched
    assert current_name(panel) == "charlie.png"

    with qtbot.waitSignal(panel.selection_changed, timeout=1000):
        panel.icon_list.selectAll()
    assert set(names(panel.selected_files())) == {
        "alpha.png",
        "bravo.png",
        "charlie.png",
        "clip.mp4",
    }


def test_selection_in_table_mode(qtbot, gui_settings, make_image, tmp_path):
    gui_settings.list_view_mode = "table"
    panel = build_panel(qtbot, gui_settings, make_gallery(make_image, tmp_path))
    panel.table.selectAll()
    assert len(panel.selected_files()) == 4


def test_empty_panel_has_no_current_or_selection(qtbot, gui_settings):
    panel = build_panel(qtbot, gui_settings, [])
    assert panel.current_file() is None
    assert panel.selected_files() == []
    assert panel.path_for_row(-1) is None


def test_step_moves_and_clamps_in_grid(qtbot, gui_settings, make_image, tmp_path):
    panel = build_panel(qtbot, gui_settings, make_gallery(make_image, tmp_path))
    assert panel.active_row() == 0
    panel.step(-1)
    assert panel.active_row() == 0
    panel.step(1)
    assert panel.active_row() == 1
    panel.step(50)
    assert panel.active_row() == panel.active_count() - 1


def test_step_in_table_mode(qtbot, gui_settings, make_image, tmp_path):
    gui_settings.list_view_mode = "table"
    panel = build_panel(qtbot, gui_settings, make_gallery(make_image, tmp_path))
    panel.step(2)
    assert panel.active_row() == 2


def test_step_on_empty_is_a_noop(qtbot, gui_settings):
    panel = build_panel(qtbot, gui_settings, [])
    panel.step(1)
    assert panel.active_row() == -1


# -- favourites ------------------------------------------------------------


def test_table_star_cell_click_toggles_favourite(qtbot, gui_settings, make_image):
    gui_settings.list_view_mode = "table"
    image = build_image(make_image, "alpha.png")
    panel = build_panel(qtbot, gui_settings, [image])
    row = panel.index_by_path[str(image.path)]

    panel.handle_cell_clicked(row, FAVOURITE_COLUMN)
    assert gui_settings.is_favorite(image.path)
    assert panel.table.item(row, FAVOURITE_COLUMN).text() == "★"

    panel.handle_cell_clicked(row, FAVOURITE_COLUMN)
    assert not gui_settings.is_favorite(image.path)

    panel.handle_cell_clicked(row, NAME_COLUMN)  # non-star column: no-op
    assert not gui_settings.is_favorite(image.path)


def test_refresh_current_label_rerenders(qtbot, gui_settings, make_image):
    gui_settings.list_view_mode = "table"
    image = build_image(make_image, "alpha.png")
    panel = build_panel(qtbot, gui_settings, [image])
    gui_settings.toggle_favorite(str(image.path))
    panel.refresh_current_label()
    row = panel.index_by_path[str(image.path)]
    assert panel.table.item(row, FAVOURITE_COLUMN).text() == "★"


# -- refresh behaviour -----------------------------------------------------


def test_visible_changed_emitted_on_refresh(qtbot, gui_settings, make_image, tmp_path):
    panel = build_panel(qtbot, gui_settings, make_gallery(make_image, tmp_path))
    with qtbot.waitSignal(panel.visible_changed, timeout=1000) as blocker:
        panel.refresh()
    assert names(blocker.args[0])[0] == "alpha.png"


def test_refresh_keeps_current_selection(qtbot, gui_settings, make_image, tmp_path):
    files = make_gallery(make_image, tmp_path)
    panel = build_panel(qtbot, gui_settings, files)
    panel.select_path(str(files[2].path))  # bravo.png
    assert current_name(panel) == "bravo.png"
    panel.refresh()
    assert current_name(panel) == "bravo.png"


def test_rows_carry_name_size_resolution_in_table(
    qtbot, gui_settings, make_image, tmp_path
):
    gui_settings.list_view_mode = "table"
    image = build_image(make_image, "alpha.png", size=(40, 30))
    panel = build_panel(qtbot, gui_settings, [image])
    row = panel.index_by_path[str(image.path)]
    assert panel.table.item(row, NAME_COLUMN).text() == "alpha.png"
    assert panel.table.item(row, RESOLUTION_COLUMN).text() == "40×30"
    assert panel.table.item(row, SIZE_COLUMN).text() != ""


# -- selection mode --------------------------------------------------------


def test_selection_mode_button_switches_to_multi_select(
    qtbot, gui_settings, make_image, tmp_path
):
    from PySide6.QtWidgets import QAbstractItemView

    panel = build_panel(qtbot, gui_settings, make_gallery(make_image, tmp_path))
    assert (
        panel.icon_list.selectionMode()
        == QAbstractItemView.SelectionMode.ExtendedSelection
    )
    panel.select_button.click()
    assert gui_settings.selection_mode is True
    assert (
        panel.icon_list.selectionMode()
        == QAbstractItemView.SelectionMode.MultiSelection
    )
    assert panel.table.selectionMode() == QAbstractItemView.SelectionMode.MultiSelection


def test_badge_selection_returns_same_size(qtbot, gui_settings, make_image):
    panel = build_panel(qtbot, gui_settings, [])
    pixmap = QPixmap(str(make_image(size=(72, 72))))
    assert panel.badge_selection(pixmap, True).size() == pixmap.size()
    assert panel.badge_selection(pixmap, False).size() == pixmap.size()


def test_square_crop_makes_a_square_tile():
    from myimages.gui.file_list import GRID_ICON, square_crop

    landscape = QPixmap(120, 80)
    portrait = QPixmap(80, 120)
    assert square_crop(landscape, GRID_ICON).size() == QSize(GRID_ICON, GRID_ICON)
    assert square_crop(portrait, GRID_ICON).size() == QSize(GRID_ICON, GRID_ICON)
    empty = QPixmap()
    assert square_crop(empty, GRID_ICON).isNull()  # zero side -> returned as-is


def test_grid_icon_composes_selection_and_favourite(qtbot, gui_settings, make_image):
    gui_settings.selection_mode = True
    image = build_image(make_image, "alpha.png", size=(120, 80))
    gui_settings.toggle_favorite(str(image.path))
    panel = build_panel(qtbot, gui_settings, [image])
    base = QPixmap(str(image.path))
    icon = panel.grid_icon(str(image.path), base, {str(image.path)})
    assert not icon.isNull()
    # A square tile, centre-cropped to whatever the panel is showing right now.
    live = panel.icon_list.iconSize().width()
    assert icon.size() == QSize(live, live)


def test_the_tiles_grow_to_fill_the_panel(qtbot, gui_settings, make_image, tmp_path):
    """A fixed tile size left a ragged strip of empty panel on the right."""
    from myimages.gui.file_list import GRID_PADDING

    panel = build_panel(qtbot, gui_settings, make_gallery(make_image, tmp_path))
    panel.show()
    for columns in (1, 2, 3, 4):
        gui_settings.grid_columns = columns
        panel.resize(panel_pixels(columns), 500)
        panel.apply_grid_metrics()
        viewport = panel.icon_list.viewport().width()
        cell = panel.icon_list.iconSize().width() + GRID_PADDING
        assert (viewport - 1) // cell == columns  # exactly the asked-for columns
        assert viewport - columns * cell < cell  # and no room for another


def panel_pixels(columns: int) -> int:
    from myimages.gui.file_list import panel_width_for

    return panel_width_for(columns)


def test_selected_path_set_and_badge_refresh(qtbot, gui_settings, make_image):
    gui_settings.selection_mode = True
    files = [build_image(make_image, f"p{i}.png", size=(64, 64)) for i in range(3)]
    loader = ThumbnailLoader(size=64)
    for media_file in files:
        loader.load_now(media_file)  # seed the base pixmaps
    panel = FileListPanel(gui_settings, loader)
    qtbot.addWidget(panel)
    panel.set_files(files)

    panel.icon_list.item(0).setSelected(True)
    panel.icon_list.item(2).setSelected(True)
    assert panel.selected_path_set() == {str(files[0].path), str(files[2].path)}

    panel.refresh_grid_badges()
    assert not panel.icon_list.item(0).icon().isNull()


def test_refresh_grid_badges_ignores_non_grid(qtbot, gui_settings, make_image):
    gui_settings.list_view_mode = "table"
    panel = build_panel(qtbot, gui_settings, [build_image(make_image, "a.png")])
    panel.refresh_grid_badges()  # non-grid -> returns immediately, no error


def test_favourite_toggle_keeps_multi_selection(qtbot, gui_settings, make_image):
    gui_settings.selection_mode = True
    files = [build_image(make_image, f"p{i}.png", size=(64, 64)) for i in range(3)]
    loader = ThumbnailLoader(size=64)
    for media_file in files:
        loader.load_now(media_file)
    panel = FileListPanel(gui_settings, loader)
    qtbot.addWidget(panel)
    panel.set_files(files)
    panel.icon_list.selectAll()
    before = panel.selected_path_set()
    assert len(before) == 3

    # Favouriting a file must NOT clear the current selection.
    gui_settings.toggle_favorite(str(files[0].path))
    panel.apply_favorite_change(str(files[0].path))
    assert panel.selected_path_set() == before


def test_favourite_toggle_refilters_in_favourites_only(qtbot, gui_settings, make_image):
    gui_settings.list_view_mode = "table"
    image = build_image(make_image, "a.png")
    gui_settings.toggle_favorite(str(image.path))
    gui_settings.favorites_only = True
    panel = build_panel(qtbot, gui_settings, [image])
    assert panel.table.rowCount() == 1

    gui_settings.toggle_favorite(str(image.path))  # un-favourite
    panel.apply_favorite_change(str(image.path))
    assert panel.table.rowCount() == 0  # drops out of the favourites-only view


# -- copy to clipboard -----------------------------------------------------


def test_copy_selected_files_to_clipboard(qtbot, gui_settings, make_image):
    from PySide6.QtGui import QGuiApplication

    files = [build_image(make_image, f"c{i}.png") for i in range(2)]
    panel = build_panel(qtbot, gui_settings, files)
    panel.icon_list.selectAll()
    panel.copy_selected_to_clipboard()

    mime = QGuiApplication.clipboard().mimeData()
    assert {u.toLocalFile() for u in mime.urls()} == {str(f.path) for f in files}
    assert mime.hasText()
    gnome = bytes(mime.data("x-special/gnome-copied-files")).decode()
    assert gnome.startswith("copy\n")


def test_copy_single_image_carries_pixels(qtbot, gui_settings, make_image):
    from PySide6.QtGui import QGuiApplication

    panel = build_panel(qtbot, gui_settings, [build_image(make_image, "one.png")])
    panel.icon_list.selectAll()
    panel.copy_selected_to_clipboard()
    assert QGuiApplication.clipboard().mimeData().hasImage()


def test_selected_or_current_falls_back(qtbot, gui_settings, make_image, tmp_path):
    panel = build_panel(qtbot, gui_settings, make_gallery(make_image, tmp_path))
    panel.icon_list.clearSelection()
    assert len(panel.selected_or_current()) == 1  # the current row


def test_copy_with_nothing_selected_is_a_noop(qtbot, gui_settings):
    panel = build_panel(qtbot, gui_settings, [])
    panel.copy_selected_to_clipboard()  # no files -> returns without raising


# -- right-click on a thumbnail --------------------------------------------


def test_right_click_announces_a_screen_position(qtbot, gui_settings, make_image):
    from PySide6.QtCore import QPoint

    files = [build_image(make_image, f"r{i}.png") for i in range(3)]
    panel = build_panel(qtbot, gui_settings, files)
    seen: list[QPoint] = []
    panel.context_menu_requested.connect(seen.append)

    panel.relay_context_menu(QPoint(5, 5))

    assert len(seen) == 1  # the window is told where to open the menu


def test_right_clicking_an_unselected_thumbnail_makes_it_current(
    qtbot, gui_settings, make_image
):
    files = [build_image(make_image, f"p{i}.png") for i in range(3)]
    panel = build_panel(qtbot, gui_settings, files)
    panel.clear_selection()
    third = panel.icon_list.visualItemRect(panel.icon_list.item(2)).center()

    panel.relay_context_menu(third)

    current = panel.current_file()
    assert current is not None and current.name == "p2.png"


def test_right_clicking_inside_a_selection_keeps_it(qtbot, gui_settings, make_image):
    """Acting on ten files must not silently reduce them to the one clicked."""
    files = [build_image(make_image, f"q{i}.png") for i in range(3)]
    panel = build_panel(qtbot, gui_settings, files)
    panel.select_all()
    assert len(panel.selected_files()) == 3

    first = panel.icon_list.visualItemRect(panel.icon_list.item(0)).center()
    panel.relay_context_menu(first)

    assert len(panel.selected_files()) == 3


def test_right_click_on_empty_space_still_offers_the_menu(qtbot, gui_settings):
    from PySide6.QtCore import QPoint

    panel = build_panel(qtbot, gui_settings, [])
    seen: list[QPoint] = []
    panel.context_menu_requested.connect(seen.append)

    panel.relay_context_menu(QPoint(10, 10))  # no item under the cursor

    assert len(seen) == 1


def test_double_click_asks_for_the_editor(qtbot, gui_settings, make_image, tmp_path):
    """Single click previews; double click is the shortcut into Edit Image."""
    panel = build_panel(qtbot, gui_settings, make_gallery(make_image, tmp_path))
    with qtbot.waitSignal(panel.edit_requested, timeout=1000):
        panel.handle_double_click(panel.icon_list.item(0))


def test_double_click_in_the_table_asks_too(qtbot, gui_settings, make_image, tmp_path):
    gui_settings.list_view_mode = "table"
    panel = build_panel(qtbot, gui_settings, make_gallery(make_image, tmp_path))
    with qtbot.waitSignal(panel.edit_requested, timeout=1000):
        panel.handle_double_click(0, 1)  # the table hands over row and column


def test_list_rows_are_left_aligned_with_room_for_a_star(
    qtbot, gui_settings, make_image, tmp_path
):
    """Centred names wandered as the panel resized; a star must not shift them."""
    from PySide6.QtCore import Qt

    gui_settings.list_view_mode = "list"
    files = make_gallery(make_image, tmp_path)
    gui_settings.toggle_favorite(str(files[0].path))
    panel = build_panel(qtbot, gui_settings, files)

    first = panel.icon_list.item(0)
    second = panel.icon_list.item(1)
    assert first.textAlignment() & Qt.AlignmentFlag.AlignLeft
    # Both rows carry an icon, so the favourite one does not indent its name.
    assert not first.icon().isNull()
    assert not second.icon().isNull()
    assert panel.icon_list.iconSize().width() == LIST_STAR


def test_the_list_star_appears_when_a_file_is_favourited(
    qtbot, gui_settings, make_image, tmp_path
):
    gui_settings.list_view_mode = "list"
    files = make_gallery(make_image, tmp_path)
    panel = build_panel(qtbot, gui_settings, files)
    path = str(files[0].path)
    row = panel.index_by_path[path]  # sorting decides the row, not the input order
    blank = panel.icon_list.item(row).icon().cacheKey()

    gui_settings.toggle_favorite(path)
    panel.apply_favorite_change(path)

    assert panel.icon_list.item(row).icon().cacheKey() != blank


def test_the_grid_reflows_when_the_list_is_given_its_real_width(
    qtbot, gui_settings, make_image, tmp_path
):
    """The panel is resized before its children, so the list must be watched.

    Laying the tiles out from the panel's own resize measured the *previous*
    width, which is how a four-column panel came up showing one giant column.
    """
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QResizeEvent

    gui_settings.grid_columns = 4
    panel = build_panel(qtbot, gui_settings, make_gallery(make_image, tmp_path))
    panel.show()
    panel.resize(400, 500)
    panel.icon_list.resize(380, 440)
    panel.icon_list.event(QResizeEvent(QSize(380, 440), QSize(100, 440)))

    assert panel.grid_flowed_for == (panel.grid_area_width(), 4)
    cell = panel.icon_list.gridSize().width()
    assert (panel.grid_area_width() - 1) // cell == 4


def test_reflowing_is_skipped_when_nothing_moved(
    qtbot, gui_settings, make_image, tmp_path
):
    """The tile size stops changing at the cache limit, so width drives this."""
    panel = build_panel(qtbot, gui_settings, make_gallery(make_image, tmp_path))
    panel.show()
    panel.icon_list.resize(300, 400)
    panel.apply_grid_metrics()
    flowed = panel.grid_flowed_for
    before = panel.icon_list.gridSize()

    panel.apply_grid_metrics()

    assert panel.grid_flowed_for == flowed
    assert panel.icon_list.gridSize() == before


@pytest.mark.parametrize("mode", ["grid", "list", "table"])
def test_a_refresh_tells_everyone_the_picks_came_back(
    qtbot, gui_settings, make_image, tmp_path, mode
):
    """restore_selection moves the picks with signals blocked, so nothing heard.

    The visible cost was the GIF/PDF buttons greying out, and the grid's tick
    badges going blank, while the files sat there selected.
    """
    gui_settings.list_view_mode = mode
    panel = build_panel(qtbot, gui_settings, make_gallery(make_image, tmp_path))
    panel.select_all()
    picked = len(panel.selected_files())
    assert picked > 1
    heard: list[int] = []
    panel.selection_changed.connect(lambda files: heard.append(len(files)))

    panel.refresh()

    assert len(panel.selected_files()) == picked
    assert heard and heard[-1] == picked


@pytest.mark.parametrize("mode", ["grid", "list", "table"])
def test_losing_every_pick_still_leaves_a_file_highlighted(
    qtbot, gui_settings, make_image, tmp_path, mode
):
    """An empty selection is what widens Rename and Convert to the whole folder."""
    gui_settings.list_view_mode = mode
    files = make_gallery(make_image, tmp_path)
    panel = build_panel(qtbot, gui_settings, files)
    doomed = str(files[0].path)
    panel.clear_selection()
    panel.select_path(doomed)
    assert [str(f.path) for f in panel.selected_files()] == [doomed]

    panel.set_files([f for f in files if str(f.path) != doomed])

    assert len(panel.selected_files()) == 1
    assert panel.selected_files()[0].path == panel.current_file().path


def test_grid_badges_are_repainted_after_a_refresh(
    qtbot, gui_settings, make_image, tmp_path
):
    gui_settings.selection_mode = True
    files = make_gallery(make_image, tmp_path)
    loader = ThumbnailLoader(size=64)
    for media_file in files:
        loader.load_now(media_file)
    panel = FileListPanel(gui_settings, loader)
    qtbot.addWidget(panel)
    panel.set_files(files)
    panel.select_all()
    picked = panel.icon_list.item(0).icon().cacheKey()

    panel.clear_selection()
    panel.refresh()

    assert panel.icon_list.item(0).icon().cacheKey() != picked
