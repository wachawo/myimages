"""The file-list panel: grid, list or sortable-table views of the media.

Three presentations share one panel and cycle from a single toolbar icon:

* **grid** — just the pictures; the filename shows on hover and a favourite star
  is badged over the top-right corner of the thumbnail;
* **list** — a plain column of filenames;
* **table** — sortable Name / Size / Resolution columns (numeric columns sort by
  value) with a ★ favourite column you can click; the header carries a ★ too.

A search box filters by filename and a star button filters to favourites only. A
second icon flips which side of the window the whole panel sits on. The heavy
sorting/filtering lives in :mod:`myimages.core.scanner`, keeping this thin.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import (
    QEvent,
    QItemSelectionModel,
    QMimeData,
    QObject,
    QPoint,
    QPointF,
    QSize,
    Qt,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QGuiApplication,
    QIcon,
    QImage,
    QKeySequence,
    QPainter,
    QPen,
    QPixmap,
    QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from myimages import icons
from myimages.config import Settings, save_settings
from myimages.core import scanner
from myimages.core.media import MediaFile, MediaKind
from myimages.format_utils import human_readable_size
from myimages.gui.thumbnail_loader import ThumbnailLoader

MEDIA_ROLE = int(Qt.ItemDataRole.UserRole)
FAVOURITE_COLUMN = 0
NAME_COLUMN = 1
SIZE_COLUMN = 2
RESOLUTION_COLUMN = 3
COLUMN_SORT_KEYS: dict[int, str] = {
    NAME_COLUMN: "name",
    SIZE_COLUMN: "size",
    RESOLUTION_COLUMN: "resolution",
}
VIEW_MODES: tuple[str, ...] = ("grid", "list", "table")
NEXT_VIEW_MODE: dict[str, str] = {"grid": "list", "list": "table", "table": "grid"}
GRID_ICON = 76
GRID_MINIMUM_ICON = 48
GRID_CELL = GRID_ICON + 4
GRID_PADDING = GRID_CELL - GRID_ICON
LIST_STAR = 14
COLUMN_CHOICES: tuple[int, ...] = (1, 2, 3, 4)
# What the panel costs before any thumbnail fits: the sidebar's own margins,
# the view's frame, and the vertical scrollbar that a full folder always shows.
PANEL_CHROME = 46


def panel_width_for(columns: int) -> int:
    """How wide the file list must be to fit ``columns`` thumbnails per row.

    The width is derived rather than dragged, so the user picks a number of
    columns and always gets exactly that -- no ragged half-column of empty
    space, and nothing to re-drag every time the window changes size.
    """
    return columns * GRID_CELL + PANEL_CHROME


def next_column_count(columns: int) -> int:
    """The next column count the switcher offers, wrapping back to one."""
    if columns not in COLUMN_CHOICES:
        return COLUMN_CHOICES[0]
    return COLUMN_CHOICES[(COLUMN_CHOICES.index(columns) + 1) % len(COLUMN_CHOICES)]


def square_crop(pixmap: QPixmap, size: int) -> QPixmap:
    """Centre-crop ``pixmap`` to a square and scale it to fill a grid tile."""
    side = min(pixmap.width(), pixmap.height())
    if side <= 0:
        return pixmap
    left = (pixmap.width() - side) // 2
    top = (pixmap.height() - side) // 2
    square = pixmap.copy(left, top, side, side)
    return square.scaled(
        size,
        size,
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


class FileListPanel(QWidget):
    """Shows, sorts and filters the media files and emits selection changes."""

    current_changed = Signal(object)
    selection_changed = Signal(list)
    visible_changed = Signal(list)
    columns_changed = Signal(int)
    edit_requested = Signal()
    context_menu_requested = Signal(QPoint)  # screen coordinates

    def __init__(
        self,
        settings: Settings,
        loader: ThumbnailLoader,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self.loader = loader
        self.all_files: list[MediaFile] = []
        self.index_by_path: dict[str, int] = {}
        self.search_text = ""
        # (area width, columns) the grid was last laid out for.
        self.grid_flowed_for: tuple[int, int] = (0, 0)
        if self.settings.list_view_mode not in VIEW_MODES:
            self.settings.list_view_mode = "grid"
        if self.settings.grid_columns not in COLUMN_CHOICES:
            self.settings.grid_columns = Settings.grid_columns
        self.build_ui()
        self.loader.thumbnail_ready.connect(self.apply_thumbnail)

    # -- construction ------------------------------------------------------

    def build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        controls = QHBoxLayout()
        controls.setSpacing(6)
        self.view_button = QToolButton()
        self.view_button.clicked.connect(self.cycle_view_mode)
        controls.addWidget(self.view_button)
        self.favorites_button = QToolButton()
        self.favorites_button.setCheckable(True)
        self.favorites_button.setChecked(self.settings.favorites_only)
        self.favorites_button.toggled.connect(self.handle_favorites_toggled)
        controls.addWidget(self.favorites_button)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search by name…")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self.handle_search_changed)
        controls.addWidget(self.search_edit, 1)
        self.columns_button = QToolButton()
        self.columns_button.clicked.connect(self.cycle_columns)
        controls.addWidget(self.columns_button)
        self.select_button = QToolButton()
        self.select_button.setCheckable(True)
        self.select_button.setChecked(self.settings.selection_mode)
        self.select_button.toggled.connect(self.handle_selection_mode_toggled)
        controls.addWidget(self.select_button)
        layout.addLayout(controls)
        self.search_edit.setFixedHeight(self.view_button.sizeHint().height())

        self.stack = QStackedWidget()
        self.icon_list = QListWidget()
        self.icon_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        # Always reserve the scrollbar. Letting it come and go changes the
        # viewport width by its own thickness, which changes how many tiles fit,
        # which can bring it back again -- the grid would flicker between two
        # column counts on a folder that sits right on the boundary.
        self.icon_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.icon_list.setMovement(QListWidget.Movement.Static)
        self.icon_list.setUniformItemSizes(False)
        self.icon_list.currentItemChanged.connect(self.handle_current_changed)
        self.icon_list.itemSelectionChanged.connect(self.handle_selection_changed)
        self.icon_list.itemDoubleClicked.connect(self.handle_double_click)
        self.icon_list.installEventFilter(self)
        self.stack.addWidget(self.icon_list)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["★", "Name", "Size", "Resolution"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(NAME_COLUMN, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(
            FAVOURITE_COLUMN, QHeaderView.ResizeMode.ResizeToContents
        )
        header.setSectionsClickable(True)
        header.sectionClicked.connect(self.handle_header_clicked)
        self.table.currentCellChanged.connect(self.handle_current_changed)
        self.table.itemSelectionChanged.connect(self.handle_selection_changed)
        self.table.cellClicked.connect(self.handle_cell_clicked)
        self.table.cellDoubleClicked.connect(self.handle_double_click)
        self.stack.addWidget(self.table)
        layout.addWidget(self.stack, 1)

        # Ctrl+C copies the selected files; scoped to the lists so it never
        # steals the search box's own text copy.
        for list_widget in (self.icon_list, self.table):
            copy_shortcut = QShortcut(QKeySequence.StandardKey.Copy, list_widget)
            copy_shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
            copy_shortcut.activated.connect(self.copy_selected_to_clipboard)

        for view in (self.icon_list, self.table):
            view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            view.customContextMenuRequested.connect(self.relay_context_menu)

        self.apply_selection_mode()
        self.refresh_control_icons()

    def relay_context_menu(self, position: QPoint) -> None:
        """Right-clicking a thumbnail offers the same actions as the preview.

        The clicked file becomes current so the menu acts on what was pointed
        at, but an existing multi-selection is left alone when the click lands
        inside it -- otherwise right-clicking to act on ten files would silently
        reduce them to one.
        """
        view = self.table if self.table_mode() else self.icon_list
        index = view.indexAt(position)
        if index.isValid():
            path = self.path_for_row(index.row())
            if path is not None and path not in self.selected_path_set():
                self.set_active_row(index.row())
            elif path is not None:
                self.set_current_without_selecting(index.row())
        self.context_menu_requested.emit(view.viewport().mapToGlobal(position))

    def focus_active_view(self) -> bool:
        """Put the keyboard on the files, so the arrow keys step through photos.

        Skipped when there is nothing to step through: moving the caret out of
        the folder box and into an empty list would strand a user who had simply
        mistyped the path. Reports whether the keyboard actually moved, so a
        caller with only one chance to hand it over knows to try again later.
        """
        if self.active_count() == 0:
            return False
        (self.table if self.table_mode() else self.icon_list).setFocus()
        return True

    def set_current_without_selecting(self, row: int) -> None:
        """Make ``row`` the current file, keeping the selection as it is."""
        view = self.table if self.table_mode() else self.icon_list
        model = view.selectionModel()
        source = view.model()
        if model is None or source is None:
            return
        column = NAME_COLUMN if self.table_mode() else 0
        model.setCurrentIndex(
            source.index(row, column), QItemSelectionModel.SelectionFlag.NoUpdate
        )

    # -- control state -----------------------------------------------------

    def refresh_control_icons(self) -> None:
        mode = self.settings.list_view_mode
        mode_icon = {
            "grid": icons.grid(),
            "list": icons.rows(),
            "table": icons.table_view(),
        }[mode]
        mode_tip = {
            "grid": "Thumbnails — click for a plain list",
            "list": "Plain list — click for a table",
            "table": "Table — click for thumbnails",
        }[mode]
        self.view_button.setIcon(mode_icon)
        self.view_button.setToolTip(mode_tip)
        self.favorites_button.setIcon(icons.star(self.settings.favorites_only))
        self.favorites_button.setToolTip("Show only favourites")
        columns = self.settings.grid_columns
        self.columns_button.setIcon(icons.columns(columns))
        self.columns_button.setToolTip(
            f"{columns} thumbnail(s) per row — click to widen the panel"
        )
        self.select_button.setIcon(icons.select_mode())
        self.select_button.setToolTip("Selection mode — tap files to select them")

    def apply_selection_mode(self) -> None:
        """Tap-to-toggle (MultiSelection) when on; Ctrl/Shift (Extended) when off."""
        mode = (
            QAbstractItemView.SelectionMode.MultiSelection
            if self.settings.selection_mode
            else QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.icon_list.setSelectionMode(mode)
        self.table.setSelectionMode(mode)

    def handle_selection_mode_toggled(self, checked: bool) -> None:
        self.settings.selection_mode = checked
        self.apply_selection_mode()
        save_settings(self.settings)
        self.refresh()

    def cycle_view_mode(self) -> None:
        # Read what is on screen *before* the mode flips. refresh() would
        # otherwise interrogate the view being switched to, which is still
        # empty, and conclude nothing was open -- so switching to the table
        # jumped the preview back to the first photo in the folder.
        showing = self.current_view_state()
        self.settings.list_view_mode = NEXT_VIEW_MODE[self.settings.list_view_mode]
        self.refresh_control_icons()
        save_settings(self.settings)
        self.refresh(showing)

    def handle_double_click(self, *ignored: object) -> None:
        """Open the editor on the file that was double-clicked.

        The views hand over an item or a cell position; both are already the
        current file by the time this runs, so the arguments are not needed --
        they are swallowed rather than declared, because the two signals pass
        different ones.
        """
        self.edit_requested.emit()

    def cycle_columns(self) -> None:
        """Step to the next number of thumbnails per row and widen to match."""
        self.settings.grid_columns = next_column_count(self.settings.grid_columns)
        self.refresh_control_icons()
        save_settings(self.settings)
        self.columns_changed.emit(self.settings.grid_columns)
        # The panel may already be at its minimum width, in which case no resize
        # follows and the tiles would keep the previous count's size.
        self.apply_grid_metrics()

    def handle_search_changed(self, text: str) -> None:
        self.search_text = text.strip()
        self.refresh()

    def handle_favorites_toggled(self, checked: bool) -> None:
        self.settings.favorites_only = checked
        self.refresh_control_icons()
        self.refresh()

    def handle_header_clicked(self, column: int) -> None:
        key = COLUMN_SORT_KEYS.get(column)
        if key is None:
            return
        if self.settings.sort_key == key:
            self.settings.sort_descending = not self.settings.sort_descending
        else:
            self.settings.sort_key = key
            self.settings.sort_descending = False
        self.refresh()

    # -- data --------------------------------------------------------------

    def set_files(self, files: list[MediaFile]) -> None:
        self.all_files = files
        self.refresh()

    def visible_files(self) -> list[MediaFile]:
        chosen = [item for item in self.all_files if self.passes_filters(item)]
        return scanner.sort_media(
            chosen, self.settings.sort_key, self.settings.sort_descending
        )

    def passes_filters(self, media_file: MediaFile) -> bool:
        if media_file.kind is MediaKind.IMAGE and not self.settings.show_images:
            return False
        if media_file.kind is MediaKind.VIDEO and not self.settings.show_videos:
            return False
        if self.settings.favorites_only and not self.settings.is_favorite(
            media_file.path
        ):
            return False
        if not self.search_text:
            return True
        return self.search_text.lower() in media_file.name.lower()

    def table_mode(self) -> bool:
        return self.settings.list_view_mode == "table"

    def current_view_state(self) -> tuple[MediaFile | None, set[str]]:
        """What is on screen right now: the previewed file and the picked paths."""
        return self.current_file(), self.selected_path_set()

    def refresh(self, showing: tuple[MediaFile | None, set[str]] | None = None) -> None:
        """Rebuild the active view to match the files, filters and sort.

        The current file *and* the whole selection are restored afterwards: a
        refresh triggered by something changing on disk must not silently throw
        away the set of files the user had picked out.

        ``showing`` overrides what is read back afterwards, for the one caller
        that changes the view mode and so cannot let this method ask the widgets
        itself.
        """
        previous, chosen = self.current_view_state() if showing is None else showing
        visible = self.visible_files()
        self.icon_list.blockSignals(True)
        self.table.blockSignals(True)
        self.icon_list.clear()
        self.table.clearContents()
        self.table.setRowCount(0)
        self.index_by_path.clear()
        if self.table_mode():
            self.build_table(visible)
            self.stack.setCurrentWidget(self.table)
        else:
            self.build_icon_list(visible)
            self.stack.setCurrentWidget(self.icon_list)
        self.icon_list.blockSignals(False)
        self.table.blockSignals(False)
        self.update_sort_indicator()
        self.visible_changed.emit(visible)
        # Only picks that still exist count. Judging by the pre-rebuild set
        # instead left nothing selected at all when the picked files had just
        # been deleted or filtered away -- and an empty selection is what makes
        # Rename and Convert quietly widen from one file to the whole folder.
        surviving = {path for path in chosen if path in self.index_by_path}
        self.restore_current(previous, had_picks=bool(surviving))
        self.restore_selection(surviving)
        # restore_selection deliberately moves the selection with the view's
        # signals blocked, so nothing downstream has heard about it yet: the
        # grid's tick badges would stay blank and the GIF/PDF buttons would stay
        # greyed out while the files sat there selected.
        self.handle_selection_changed()

    def build_icon_list(self, visible: list[MediaFile]) -> None:
        grid = self.settings.list_view_mode == "grid"
        if grid:
            self.icon_list.setViewMode(QListWidget.ViewMode.IconMode)
            self.icon_list.setFlow(QListWidget.Flow.LeftToRight)
            self.icon_list.setWrapping(True)
            self.icon_list.setUniformItemSizes(True)
            icon = self.grid_icon_size()
            self.icon_list.setIconSize(QSize(icon, icon))
            self.icon_list.setGridSize(QSize(icon + GRID_PADDING, icon + GRID_PADDING))
            self.icon_list.setSpacing(0)
        else:
            self.icon_list.setViewMode(QListWidget.ViewMode.ListMode)
            self.icon_list.setFlow(QListWidget.Flow.TopToBottom)
            self.icon_list.setWrapping(False)
            self.icon_list.setUniformItemSizes(False)
            self.icon_list.setIconSize(QSize(LIST_STAR, LIST_STAR))
            self.icon_list.setGridSize(QSize())
            self.icon_list.setSpacing(0)
        for row, media_file in enumerate(visible):
            item = QListWidgetItem("" if grid else media_file.name)
            item.setData(MEDIA_ROLE, str(media_file.path))
            item.setToolTip(media_file.name)
            if grid:
                item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
                item.setSizeHint(self.icon_list.gridSize())
            else:
                item.setTextAlignment(
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                )
                item.setIcon(self.list_star(media_file.path))
            self.icon_list.addItem(item)
            self.index_by_path[str(media_file.path)] = row
            if grid:
                self.loader.request(media_file)

    def build_table(self, visible: list[MediaFile]) -> None:
        self.table.setRowCount(len(visible))
        for row, media_file in enumerate(visible):
            favourite = self.settings.is_favorite(media_file.path)
            star = QTableWidgetItem("★" if favourite else "")
            star.setData(MEDIA_ROLE, str(media_file.path))
            star.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            name = QTableWidgetItem(media_file.name)
            size = QTableWidgetItem(human_readable_size(media_file.size_bytes))
            size.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            resolution = QTableWidgetItem(media_file.resolution_label)
            resolution.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            self.table.setItem(row, FAVOURITE_COLUMN, star)
            self.table.setItem(row, NAME_COLUMN, name)
            self.table.setItem(row, SIZE_COLUMN, size)
            self.table.setItem(row, RESOLUTION_COLUMN, resolution)
            self.index_by_path[str(media_file.path)] = row

    def badge_favorite(self, pixmap: QPixmap) -> QPixmap:
        """Draw a small gold star (dark outline, no disc) at the top-right."""
        result = QPixmap(pixmap)
        painter = QPainter(result)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width = result.width()
        size = max(9, round(width * 0.15))
        centre = QPointF(width - size - 3, size + 3)
        star = icons.star_points(centre.x(), centre.y(), size, size * 0.42)
        painter.setPen(QPen(QColor(20, 20, 20, 200), 1.4))
        painter.setBrush(QColor("#ffcf3a"))
        painter.drawPath(star)
        painter.end()
        return result

    def badge_selection(self, pixmap: QPixmap, selected: bool) -> QPixmap:
        """Draw a small check circle at the bottom-left; ticked when selected."""
        result = QPixmap(pixmap)
        painter = QPainter(result)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width, height = result.width(), result.height()
        radius = max(7, round(width * 0.11))
        centre = QPointF(radius + 3, height - radius - 3)
        painter.setPen(QPen(QColor("#ffffff"), 2))
        painter.setBrush(QColor("#4f8cff") if selected else QColor(0, 0, 0, 90))
        painter.drawEllipse(centre, radius, radius)
        if selected:
            painter.drawLine(
                QPointF(centre.x() - radius * 0.45, centre.y()),
                QPointF(centre.x() - radius * 0.1, centre.y() + radius * 0.4),
            )
            painter.drawLine(
                QPointF(centre.x() - radius * 0.1, centre.y() + radius * 0.4),
                QPointF(centre.x() + radius * 0.5, centre.y() - radius * 0.4),
            )
        painter.end()
        return result

    def selected_path_set(self) -> set[str]:
        result: set[str] = set()
        for row in self.selected_rows():
            path = self.path_for_row(row)
            if path is not None:
                result.add(path)
        return result

    def grid_icon(
        self, source: str, base: QPixmap, selected_paths: set[str]
    ) -> QPixmap:
        pixmap = square_crop(base, self.icon_list.iconSize().width() or GRID_ICON)
        if self.settings.selection_mode:
            pixmap = self.badge_selection(pixmap, source in selected_paths)
        if self.settings.is_favorite(source):
            pixmap = self.badge_favorite(pixmap)
        return pixmap

    def apply_thumbnail(self, source: str, pixmap: QPixmap) -> None:
        if self.settings.list_view_mode != "grid":
            return
        row = self.index_by_path.get(source)
        if row is None:
            return
        item = self.icon_list.item(row)
        if item is None:
            return
        item.setIcon(QIcon(self.grid_icon(source, pixmap, self.selected_path_set())))

    def restore_selection(self, paths: set[str]) -> None:
        """Re-select the files that were selected before the view was rebuilt."""
        surviving = [self.index_by_path[p] for p in paths if p in self.index_by_path]
        if not surviving:
            return
        view = self.table if self.table_mode() else self.icon_list
        model = view.selectionModel()
        source = view.model()
        if model is None or source is None:
            return
        flag = QItemSelectionModel.SelectionFlag.Select
        if self.table_mode():
            flag |= QItemSelectionModel.SelectionFlag.Rows
        view.blockSignals(True)
        for row in surviving:
            column = NAME_COLUMN if self.table_mode() else 0
            model.select(source.index(row, column), flag)
        view.blockSignals(False)

    def refresh_grid_badges(self) -> None:
        """Re-draw grid icons so the selection circles track the current picks."""
        if self.settings.list_view_mode != "grid":
            return
        selected = self.selected_path_set()
        for path, row in self.index_by_path.items():
            base = self.loader.cache.get(path)
            item = self.icon_list.item(row)
            if base is not None and item is not None:
                item.setIcon(QIcon(self.grid_icon(path, base, selected)))

    def update_sort_indicator(self) -> None:
        column = next(
            (
                col
                for col, key in COLUMN_SORT_KEYS.items()
                if key == self.settings.sort_key
            ),
            NAME_COLUMN,
        )
        order = (
            Qt.SortOrder.DescendingOrder
            if self.settings.sort_descending
            else Qt.SortOrder.AscendingOrder
        )
        header = self.table.horizontalHeader()
        header.setSortIndicatorShown(True)
        header.setSortIndicator(column, order)

    # -- selection helpers -------------------------------------------------

    def active_row(self) -> int:
        return (
            self.table.currentRow()
            if self.table_mode()
            else self.icon_list.currentRow()
        )

    def active_count(self) -> int:
        return self.table.rowCount() if self.table_mode() else self.icon_list.count()

    def set_active_row(self, row: int) -> None:
        """Go to ``row``: show it, and make it the only picked file.

        This is the "as if the user clicked it" primitive, so it has to replace
        the picks rather than add to them. Left to their defaults the two widgets
        disagree -- ``QListWidget.setCurrentRow`` adds to the selection while
        ``QTableWidget.setCurrentCell`` replaces it -- which is why the flag is
        spelled out here instead. Use :meth:`set_current_without_selecting` when
        the picks must survive.
        """
        view = self.table if self.table_mode() else self.icon_list
        model = view.selectionModel()
        source = view.model()
        if model is None or source is None:
            return
        flag = QItemSelectionModel.SelectionFlag.ClearAndSelect
        if self.table_mode():
            flag |= QItemSelectionModel.SelectionFlag.Rows
        column = NAME_COLUMN if self.table_mode() else 0
        model.setCurrentIndex(source.index(row, column), flag)

    def path_for_row(self, row: int) -> str | None:
        if row < 0:
            return None
        if self.table_mode():
            item: QTableWidgetItem | QListWidgetItem | None = self.table.item(
                row, FAVOURITE_COLUMN
            )
        else:
            item = self.icon_list.item(row)
        return None if item is None else str(item.data(MEDIA_ROLE))

    def media_for_path(self, path: str) -> MediaFile | None:
        return next((f for f in self.all_files if str(f.path) == path), None)

    def current_file(self) -> MediaFile | None:
        path = self.path_for_row(self.active_row())
        return None if path is None else self.media_for_path(path)

    def selected_rows(self) -> list[int]:
        if self.table_mode():
            return [index.row() for index in self.table.selectionModel().selectedRows()]
        return [self.icon_list.row(item) for item in self.icon_list.selectedItems()]

    def select_all(self) -> None:
        (self.table if self.table_mode() else self.icon_list).selectAll()

    def clear_selection(self) -> None:
        (self.table if self.table_mode() else self.icon_list).clearSelection()

    def selected_files(self) -> list[MediaFile]:
        result: list[MediaFile] = []
        for row in self.selected_rows():
            path = self.path_for_row(row)
            media_file = None if path is None else self.media_for_path(path)
            if media_file is not None:
                result.append(media_file)
        return result

    def selected_or_current(self) -> list[MediaFile]:
        """Selected files, or the current one when nothing is multi-selected."""
        files = self.selected_files()
        if files:
            return files
        current = self.current_file()
        return [current] if current is not None else []

    def copy_names_to_clipboard(self) -> None:
        """Copy just the file names as text, one per line.

        Wanted often enough to deserve its own action: naming a photo in a
        message or a spreadsheet otherwise means retyping it by eye from the
        thumbnail caption, which is exactly how a digit gets transposed.
        """
        files = self.selected_or_current()
        if not files:
            return
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText("\n".join(media_file.name for media_file in files))

    def copy_selected_to_clipboard(self) -> None:
        """Copy the selected files to the clipboard as file references (Ctrl+C).

        The URL list lets file managers paste the files, the GNOME format makes
        Nautilus paste them as a copy, and a lone image also carries its pixels
        so it can be pasted straight into image-aware apps.
        """
        files = self.selected_or_current()
        if not files:
            return
        paths = [str(media_file.path) for media_file in files]
        urls = [QUrl.fromLocalFile(path) for path in paths]
        mime = QMimeData()
        mime.setUrls(urls)
        mime.setText("\n".join(paths))
        gnome = "copy\n" + "\n".join(url.toString() for url in urls)
        mime.setData("x-special/gnome-copied-files", gnome.encode("utf-8"))
        if len(files) == 1 and files[0].kind is MediaKind.IMAGE:
            image = QImage(paths[0])
            if not image.isNull():
                mime.setImageData(image)
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setMimeData(mime)

    def toggle_current_selection(self) -> None:
        """Add the current file to the selection, or take it out again."""
        row = self.active_row()
        if row < 0:
            return
        view = self.table if self.table_mode() else self.icon_list
        model = view.selectionModel()
        if model is None:
            return
        index = (
            self.table.model().index(row, NAME_COLUMN)
            if self.table_mode()
            else self.icon_list.model().index(row, 0)
        )
        flag = (
            QItemSelectionModel.SelectionFlag.Deselect
            if model.isSelected(index)
            else QItemSelectionModel.SelectionFlag.Select
        )
        if self.table_mode():
            flag |= QItemSelectionModel.SelectionFlag.Rows
        model.select(index, flag)

    def select_path(self, path: str) -> None:
        row = self.index_by_path.get(path)
        if row is not None:
            self.set_active_row(row)

    def step(self, delta: int) -> None:
        """Move the current selection by ``delta`` rows (for prev/next keys)."""
        count = self.active_count()
        if count == 0:
            return
        self.set_active_row(max(0, min(count - 1, self.active_row() + delta)))

    def restore_current(self, previous: MediaFile | None, had_picks: bool) -> None:
        """Put the previewed file back after the view was rebuilt.

        ``had_picks`` says whether the user had files picked out before the
        rebuild. When they did, their picks are the only thing that may end up
        selected -- quietly adding the previewed file to them is how a Delete
        aimed at one photo used to take two. When they had none, the previewed
        file is selected as well, so a freshly loaded folder shows which photo
        is on screen instead of looking like nothing is chosen at all.
        """
        if self.active_count() == 0:
            self.current_changed.emit(None)
            return
        target_row = 0
        if previous is not None:
            existing = self.index_by_path.get(str(previous.path))
            if existing is not None:
                target_row = existing
        if had_picks:
            self.set_current_without_selecting(target_row)
        else:
            self.set_active_row(target_row)

    def grid_icon_size(self) -> int:
        """Thumbnail size that makes the chosen columns fill the panel exactly.

        A fixed tile size leaves a ragged strip of empty panel to the right of
        the last column -- up to most of a thumbnail's width. Growing the tiles
        to share out that strip keeps the grid flush with both edges.

        The photos are never enlarged past what the loader cached for them,
        because a blurry thumbnail is a worse trade than a small margin.
        """
        columns = max(1, self.settings.grid_columns)
        # Measured: Qt fits (width - 1) // cell tiles per row -- one pixel short
        # of the exact share, because tiles adding up to the full width wrap and
        # cost you the last column. Inverting that gives the cell. Spacing is
        # left at zero so the only gap is the padding inside a cell, which keeps
        # this arithmetic exact.
        cell = (self.grid_area_width() - 1) // columns
        icon = cell - GRID_PADDING
        return max(GRID_MINIMUM_ICON, min(icon, self.settings.thumbnail_size))

    def grid_area_width(self) -> int:
        """Room the tiles have to share out.

        Measured from the view itself rather than its viewport, because the
        margins set below change the viewport and reading it back would chase
        its own tail.
        """
        frame = self.icon_list.frameWidth() * 2
        scrollbar = self.icon_list.verticalScrollBar().sizeHint().width()
        return max(0, self.icon_list.width() - frame - scrollbar)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """Re-flow the grid once the list itself has been given its new width.

        Watching the list rather than overriding this panel's own resizeEvent is
        deliberate: the panel is resized first and its children only afterwards,
        so a re-flow driven from here would measure the previous width and lay
        the thumbnails out for a panel size that no longer exists.
        """
        if (
            watched is self.icon_list
            and event.type() == QEvent.Type.Resize
            and self.settings.list_view_mode == "grid"
        ):
            self.apply_grid_metrics()
        return super().eventFilter(watched, event)

    def apply_grid_metrics(self) -> None:
        """Size the tiles and re-cut the thumbnails to the current tile size."""
        columns = max(1, self.settings.grid_columns)
        area = self.grid_area_width()
        # Skip only when nothing that feeds the layout has moved. Comparing the
        # icon size alone is not enough: it stops changing once it reaches the
        # cached thumbnail size, and the re-flow would then be skipped for good.
        if (area, columns) == self.grid_flowed_for:
            return
        self.grid_flowed_for = (area, columns)
        icon = self.grid_icon_size()
        cell = icon + GRID_PADDING
        # Whatever will not divide evenly is split between the two edges, so a
        # capped tile sits centred instead of leaving all the slack on the right.
        # One pixel is left behind on purpose: the row wraps when the tiles fill
        # the width exactly, and that pixel is what keeps the last column.
        slack = max(0, area - columns * cell - 1)
        self.icon_list.setViewportMargins(slack // 2, 0, slack - slack // 2, 0)
        self.icon_list.setIconSize(QSize(icon, icon))
        self.icon_list.setGridSize(QSize(cell, cell))
        chosen = self.selected_path_set()
        for row in range(self.icon_list.count()):
            item = self.icon_list.item(row)
            if item is None:
                continue
            item.setSizeHint(QSize(cell, cell))
            path = str(item.data(MEDIA_ROLE))
            base = self.loader.cache.get(path)
            if base is not None:
                item.setIcon(QIcon(self.grid_icon(path, base, chosen)))

    def list_star(self, path: Path) -> QIcon:
        """The favourite mark for a list row, or an equally wide gap.

        Every row gets an icon whether or not it is a favourite, so the names
        line up in one column instead of stepping in and out by a star's width.
        """
        if self.settings.is_favorite(path):
            return icons.star(True)
        return icons.blank(LIST_STAR)

    def apply_favorite_change(self, path: str) -> None:
        """Update one file's favourite mark in place, keeping the selection.

        A full rebuild would clear a multi-selection, so only the affected
        item is redrawn — unless the favourites-only filter is active, where the
        file may need to leave the view.
        """
        if self.settings.favorites_only and not self.settings.is_favorite(path):
            self.refresh()
            return
        row = self.index_by_path.get(path)
        if row is None:
            return
        if self.table_mode():
            star = self.table.item(row, FAVOURITE_COLUMN)
            if star is not None:
                star.setText("★" if self.settings.is_favorite(path) else "")
        elif self.settings.list_view_mode == "grid":
            item = self.icon_list.item(row)
            base = self.loader.cache.get(path)
            if item is not None and base is not None:
                item.setIcon(
                    QIcon(self.grid_icon(path, base, self.selected_path_set()))
                )
        else:
            item = self.icon_list.item(row)
            if item is not None:
                item.setIcon(self.list_star(Path(path)))

    def refresh_current_label(self) -> None:
        """Reflect the current file's changed favourite state, keeping selection."""
        media = self.current_file()
        if media is not None:
            self.apply_favorite_change(str(media.path))

    # -- signals -----------------------------------------------------------

    def handle_cell_clicked(self, row: int, column: int) -> None:
        if column != FAVOURITE_COLUMN:
            return
        path = self.path_for_row(row)
        if path is None:
            return
        self.settings.toggle_favorite(path)
        save_settings(self.settings)
        self.apply_favorite_change(path)

    def handle_current_changed(self) -> None:
        self.current_changed.emit(self.current_file())

    def handle_selection_changed(self) -> None:
        if self.settings.selection_mode:
            self.refresh_grid_badges()
        self.selection_changed.emit(self.selected_files())
