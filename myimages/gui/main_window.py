"""The main window: source bar, resizable split view and the tool actions.

Layout mirrors the sibling *myPhotos* app — a preview on the left, a panel on
the right — but the file list's width is set in whole thumbnail columns by
its own button, so the divider never lands mid-column. Files come from one
folder, optionally scanned recursively, so there is a single obvious answer to
"what am I looking at". Every tool is an
icon with a tooltip; the heavy work runs through a swappable task runner so the
UI stays responsive and tests stay synchronous.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtGui import (
    QCloseEvent,
    QGuiApplication,
    QIcon,
    QKeySequence,
    QResizeEvent,
    QShortcut,
    QShowEvent,
)
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QSplitter,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from myimages import __version__, icons, theme
from myimages.config import Settings, save_settings
from myimages.core import deletion, scanner
from myimages.core.media import MediaFile, MediaKind
from myimages.core.plugins import PluginRegistry
from myimages.gui.file_list import FileListPanel, panel_width_for
from myimages.gui.folder_monitor import FolderMonitor
from myimages.gui.image_editor import ImageEditor
from myimages.gui.preview_pane import PreviewPane, load_pixmap
from myimages.gui.task_runner import Runner, threaded_runner
from myimages.gui.thumbnail_loader import ThumbnailLoader
from myimages.paths import default_media_dir
from myimages.theme import app_icon


def copy_files_label(count: int) -> str:
    """Name the file-copying action so it cannot be read as "copy the picture".

    Saying how many files it would take also removes the other doubt a context
    menu raises: whether an action applies to the whole selection or only to the
    one item that was right-clicked.
    """
    if count > 1:
        return f"Copy {count} Files"
    return "Copy File"


def copy_names_label(count: int) -> str:
    """Name the action that puts the file names on the clipboard as text."""
    if count > 1:
        return f"Copy {count} Filenames"
    return "Copy Filename"


class MainWindow(QMainWindow):
    """Top-level window coordinating the panels and the tool dialogs."""

    def __init__(
        self,
        settings: Settings,
        registry: PluginRegistry | None = None,
        runner: Runner = threaded_runner,
    ) -> None:
        super().__init__()
        self.settings = settings
        self.registry = registry or PluginRegistry()
        self.task_runner = runner
        self.media_files: list[MediaFile] = []
        self.keyboard_handed_over = False
        self.current: MediaFile | None = None
        self.themed_buttons: list[tuple[QToolButton, Callable[[], QIcon]]] = []
        self.loader = ThumbnailLoader(size=settings.thumbnail_size, parent=self)
        self.monitor = FolderMonitor(self, runner=runner)
        self.monitor.changed.connect(self.on_folder_changed)

        if not settings.last_folder:
            # Folder is the only source, so an empty path box would be a dead
            # end on first launch; start somewhere the user probably has photos.
            settings.last_folder = str(default_media_dir())

        self.setWindowTitle(f"myImages {__version__}")
        self.resize(settings.window_width, settings.window_height)
        self.build_ui()
        self.build_shortcuts()
        self.load_source()

    # -- construction ------------------------------------------------------

    def build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self.build_top_bar())

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)

        self.preview_pane_container = QWidget()
        preview_layout = QVBoxLayout(self.preview_pane_container)
        preview_layout.setContentsMargins(10, 10, 10, 10)
        preview_layout.setSpacing(8)
        self.preview = PreviewPane()
        self.preview.navigate.connect(self.navigate)
        self.preview.favorite_toggled.connect(self.toggle_favorite_current)
        self.preview.context_menu_requested.connect(self.show_preview_menu)
        self.editor = ImageEditor(runner=self.task_runner)
        self.editor.closed.connect(self.on_editor_closed)
        self.preview_area = QStackedWidget()
        self.preview_area.addWidget(self.preview)
        self.preview_area.addWidget(self.editor)
        preview_layout.addWidget(self.preview_area, 1)

        self.sidebar = QWidget()
        self.sidebar.setObjectName("sidebar")
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(12, 12, 12, 12)
        self.file_list = FileListPanel(self.settings, self.loader)
        self.file_list.current_changed.connect(self.on_current_changed)
        self.file_list.selection_changed.connect(self.on_selection_changed)
        self.file_list.columns_changed.connect(self.change_columns)
        self.file_list.edit_requested.connect(self.open_edit)
        self.file_list.context_menu_requested.connect(self.show_preview_menu)
        sidebar_layout.addWidget(self.file_list)

        self.splitter.addWidget(self.preview_pane_container)
        self.splitter.addWidget(self.sidebar)
        self.apply_panel_side()
        root.addWidget(self.splitter, 1)
        self.setCentralWidget(central)

    def apply_panel_side(self) -> None:
        """Order the splitter so the file list sits on the chosen side."""
        on_left = self.settings.file_list_on_left
        self.splitter.insertWidget(
            0, self.sidebar if on_left else self.preview_pane_container
        )
        self.splitter.insertWidget(
            1, self.preview_pane_container if on_left else self.sidebar
        )
        self.splitter.setStretchFactor(
            self.splitter.indexOf(self.preview_pane_container), 1
        )
        self.splitter.setStretchFactor(self.splitter.indexOf(self.sidebar), 0)
        self.lock_splitter_handle()
        self.apply_panel_width()
        if hasattr(self, "side_button"):
            self.side_button.setIcon(self.side_icon())
            self.side_button.setToolTip(
                "File list on the left — click to move it right"
                if on_left
                else "File list on the right — click to move it left"
            )
        if hasattr(self, "file_list"):
            self.file_list.refresh_control_icons()

    def side_icon(self) -> QIcon:
        """The arrow matching the side the file list is currently on."""
        return (
            icons.panel_left()
            if self.settings.file_list_on_left
            else icons.panel_right()
        )

    def lock_splitter_handle(self) -> None:
        """Stop the divider being dragged; the column button owns the width now.

        A drag could only ever land between two column counts, leaving a strip
        of empty grey beside the thumbnails, so the choice is offered as whole
        columns instead of pixels.
        """
        for index in range(self.splitter.count()):
            handle = self.splitter.handle(index)
            if handle is not None:
                handle.setEnabled(False)
                handle.setCursor(Qt.CursorShape.ArrowCursor)

    def change_columns(self, columns: int) -> None:
        """Re-size the panel after the user picked a different column count.

        The tiles are re-flowed explicitly because the panel may already be at
        its minimum width -- the control row above the thumbnails has one of its
        own -- in which case no resize follows to trigger the re-flow.
        """
        self.apply_panel_width()
        self.file_list.apply_grid_metrics()

    def apply_panel_width(self) -> None:
        """Size the file list to hold exactly the chosen number of thumbnails.

        The width is derived from the column count rather than dragged, so it is
        restated after anything that could disturb it. The preview is asked for
        at least its own minimum, because Qt satisfies that minimum out of the
        file list's share -- requesting less would let the list shrink and never
        grow back when the window widens again.
        """
        if self.splitter.count() != 2:
            return
        # The control row above the thumbnails has its own minimum, and at one
        # column it is the wider of the two; asking for less would be ignored
        # anyway, and would make the arithmetic below wrong.
        wanted = max(
            panel_width_for(self.settings.grid_columns),
            self.sidebar.minimumSizeHint().width(),
        )
        room = max(
            self.splitter.width() - self.splitter.handleWidth() - wanted,
            self.preview_pane_container.minimumSizeHint().width(),
        )
        list_first = self.splitter.indexOf(self.sidebar) == 0
        self.splitter.setSizes([wanted, room] if list_first else [room, wanted])

    def resizeEvent(self, event: QResizeEvent) -> None:
        """Restate the chosen list width: a window resize is not a change of mind."""
        super().resizeEvent(event)
        self.apply_panel_width()

    def toggle_panel_side(self) -> None:
        self.store_layout()
        self.settings.file_list_on_left = not self.settings.file_list_on_left
        self.apply_panel_side()
        save_settings(self.settings)

    def build_top_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("topbar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(8)

        brand_icon = QLabel()
        brand_icon.setPixmap(app_icon().pixmap(24, 24))
        layout.addWidget(brand_icon)
        self.brand = QLabel()
        self.brand.setObjectName("brand")
        self.apply_brand_colours()
        layout.addWidget(self.brand)

        self.folder_input = QLineEdit(self.settings.last_folder)
        self.folder_input.setPlaceholderText("Folder with photos and videos…")
        self.folder_input.returnPressed.connect(self.open_typed_folder)
        layout.addWidget(self.folder_input, 1)

        self.browse_button = self.tool_button(
            icons.open_folder, "Choose folder", self.browse_folder
        )
        self.recursive_button = self.tool_button(
            icons.subfolders,
            "Include sub-folders when scanning",
            self.toggle_recursive,
        )
        self.recursive_button.setCheckable(True)
        self.recursive_button.setChecked(self.settings.recursive_scan)
        self.side_button = self.tool_button(
            self.side_icon, "Move the file list", self.toggle_panel_side
        )
        layout.addWidget(self.browse_button)
        layout.addWidget(self.recursive_button)
        layout.addWidget(self.side_button)

        layout.addSpacing(10)
        layout.addWidget(self.build_action_bar())
        return bar

    def build_action_bar(self) -> QWidget:
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        self.action_edit = self.tool_button(
            icons.edit_image, "Edit Image", self.open_edit
        )
        self.action_cutout = self.tool_button(
            icons.wand, "Remove the background", self.open_cutout_editor
        )
        self.action_convert = self.tool_button(
            icons.convert, "Convert image format", self.open_convert
        )
        self.action_pdf = self.tool_button(
            icons.pdf, "Combine images into a PDF", self.open_pdf
        )
        self.action_gif = self.tool_button(
            icons.gif, "Make a GIF from selected frames", self.open_gif
        )
        self.action_video = self.tool_button(
            icons.trim, "Video tools (trim, crop, scale, GIF)", self.open_video_tools
        )
        self.action_duplicates = self.tool_button(
            icons.duplicates, "Find duplicates", self.open_duplicates
        )
        self.action_rename = self.tool_button(
            icons.rename, "Batch rename", self.open_rename
        )
        self.action_delete = self.tool_button(
            icons.delete_item, "Delete selected", self.delete_selected
        )
        for button in (
            self.action_edit,
            self.action_convert,
            self.action_pdf,
            self.action_gif,
            self.action_video,
            self.action_duplicates,
            self.action_rename,
            self.action_delete,
        ):
            row.addWidget(button)
        row.addSpacing(8)
        row.addWidget(self.tool_button(icons.settings, "Settings", self.open_settings))
        row.addWidget(
            self.tool_button(icons.plugin, "Optional features", self.open_dependencies)
        )
        row.addWidget(self.tool_button(icons.info, "Plugins", self.open_plugins_info))
        return holder

    def tool_button(
        self,
        icon_factory: Callable[[], QIcon],
        tooltip: str,
        handler: Callable[..., object],
    ) -> QToolButton:
        """Build a toolbar button, remembering how to redraw its icon.

        Icons bake the theme's colour into a pixmap, so switching themes has to
        rebuild them; keeping the factory next to the button is what makes that
        possible without hunting down every widget by name.
        """
        button = QToolButton()
        button.setIcon(icon_factory())
        # Shown at the size they were drawn for. Qt's 16px default downscaled
        # every icon, which blurred the fine detail -- the gap that separates
        # the pencil from the photo frame closed up into a smudge.
        button.setIconSize(QSize(icons.CANVAS, icons.CANVAS))
        button.setToolTip(tooltip)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(handler)
        self.themed_buttons.append((button, icon_factory))
        return button

    def refresh_icons(self) -> None:
        """Redraw every icon in the window after a theme change."""
        for button, icon_factory in self.themed_buttons:
            button.setIcon(icon_factory())
        self.file_list.refresh_control_icons()
        self.preview.refresh_icons()
        self.editor.refresh_icons()

    def build_shortcuts(self) -> None:
        bindings = (
            (QKeySequence(Qt.Key.Key_Right), lambda: self.navigate(1)),
            (QKeySequence(Qt.Key.Key_Left), lambda: self.navigate(-1)),
            (QKeySequence(Qt.Key.Key_F), self.toggle_favorite_current),
            (QKeySequence(Qt.Key.Key_Delete), self.delete_selected),
            (QKeySequence.StandardKey.ZoomIn, self.preview.image_view.zoom_in),
            (QKeySequence.StandardKey.ZoomOut, self.preview.image_view.zoom_out),
            (QKeySequence(Qt.Key.Key_0), self.preview.image_view.fit),
            (QKeySequence(Qt.Key.Key_Space), self.preview.toggle_playback),
            (QKeySequence(Qt.Key.Key_Escape), self.cancel_edit),
        )
        for sequence, handler in bindings:
            QShortcut(sequence, self, handler)

    # -- source handling ---------------------------------------------------

    def toggle_recursive(self, checked: bool) -> None:
        self.settings.recursive_scan = checked
        self.load_source()

    def browse_folder(self) -> None:
        start = self.folder_input.text() or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self, "Choose a folder", start)
        if chosen:
            self.folder_input.setText(chosen)
            # Same hand-over as typing the folder and pressing Return, so the
            # arrow keys and Ctrl+C work whichever way the folder was chosen.
            self.open_typed_folder()

    def load_source(self) -> None:
        """Populate the file list from the folder currently in the path box."""
        folder = self.folder_input.text().strip()
        self.settings.last_folder = folder
        self.set_media_files(self.scan_folder(Path(folder)) if folder else [])

    def open_typed_folder(self) -> None:
        """Load the folder the user just typed and hand them the results.

        Pressing Return means "I am done typing", so the keyboard moves on to
        the photos; if the path found nothing, it stays in the box where the
        typo can be corrected.
        """
        self.load_source()
        self.file_list.focus_active_view()

    def scan_folder(self, folder: Path) -> list[MediaFile]:
        """Scan ``folder``, measuring only the photos whose size is not known yet."""
        if not folder.is_dir():
            return []
        found = scanner.scan_directory(folder, recursive=self.settings.recursive_scan)
        carried = scanner.reuse_known_dimensions(found, self.media_files)
        return scanner.fill_image_dimensions(carried)

    def open_file(self, path: Path) -> None:
        """Show one particular file, which is what a double-click hands us.

        The folder around it is loaded too, so arriving from a file manager
        still gives the usual gallery to step through rather than a single
        stranded picture. The keyboard lands on that gallery rather than in the
        folder box, so the arrow keys step through photos straight away instead
        of typing into the path.
        """
        target = Path(path).expanduser()
        if not target.is_file():
            return
        self.folder_input.setText(str(target.parent))
        self.load_source()
        self.file_list.select_path(str(target))
        self.file_list.focus_active_view()

    def rescan_watched_folder(self) -> None:
        """Re-read the folder currently being watched, not the path being typed.

        A background refresh must never adopt a half-typed path out of the
        folder box, which would blank the gallery while the user is still typing.
        """
        folder = self.settings.last_folder
        self.set_media_files(self.scan_folder(Path(folder)) if folder else [])

    def set_media_files(self, files: list[MediaFile]) -> None:
        self.media_files = files
        self.file_list.set_files(files)
        self.sync_monitor(files)

    def sync_monitor(self, files: list[MediaFile]) -> None:
        """Point the folder monitor at what is on screen, or just re-seed it.

        Re-seeding is the common case (every reload) and costs nothing;
        re-pointing tears down and rebuilds the filesystem watches, so it is
        reserved for an actual change of folder or of the watch settings.
        """
        if not self.settings.watch_folder or not self.settings.last_folder.strip():
            self.monitor.stop()
            return
        folder = Path(self.settings.last_folder)
        already_watching = (
            self.monitor.folder == folder
            and self.monitor.recursive == self.settings.recursive_scan
            and self.monitor.verify == self.settings.verify_checksums
            and self.monitor.interval_seconds == self.settings.watch_interval_seconds
        )
        if already_watching:
            self.monitor.adopt(files)
            return
        self.monitor.start(
            folder,
            files,
            recursive=self.settings.recursive_scan,
            verify=self.settings.verify_checksums,
            interval_seconds=self.settings.watch_interval_seconds,
        )

    def on_folder_changed(self, changes: object) -> None:
        """Refresh after the folder changed on disk, rebuilding only what moved.

        Thumbnails are dropped one by one rather than wholesale: the files that
        did not change keep theirs, so a single deleted photo never costs a
        folder-wide re-render.
        """
        stale = set(getattr(changes, "stale_paths", ()))
        for media_file in self.media_files:
            if str(media_file.path) in stale:
                self.loader.forget(media_file)
        self.rescan_watched_folder()

    def reload(self) -> None:
        self.load_source()

    # -- selection / navigation -------------------------------------------

    def on_current_changed(self, media_file: MediaFile | None) -> None:
        self.current = media_file
        self.preview.show_media(media_file, self.registry)
        if media_file is not None:
            self.preview.set_favorite(self.settings.is_favorite(media_file.path))
        self.update_action_states()

    def on_selection_changed(self, files: list[MediaFile]) -> None:
        self.update_action_states()

    def navigate(self, delta: int) -> None:
        self.file_list.step(delta)

    def update_action_states(self) -> None:
        current_is_image = (
            self.current is not None and self.current.kind is MediaKind.IMAGE
        )
        current_is_video = (
            self.current is not None and self.current.kind is MediaKind.VIDEO
        )
        images_selected = [
            f for f in self.file_list.selected_files() if f.kind is MediaKind.IMAGE
        ]
        self.action_edit.setEnabled(current_is_image)
        self.action_cutout.setEnabled(current_is_image)
        self.action_convert.setEnabled(bool(images_selected) or current_is_image)
        self.action_pdf.setEnabled(bool(images_selected) or current_is_image)
        self.action_gif.setEnabled(len(images_selected) >= 2)
        self.action_video.setEnabled(current_is_video)
        self.action_delete.setEnabled(self.current is not None)

    def selected_images(self) -> list[MediaFile]:
        chosen = [
            f for f in self.file_list.selected_files() if f.kind is MediaKind.IMAGE
        ]
        if (
            not chosen
            and self.current is not None
            and self.current.kind is MediaKind.IMAGE
        ):
            return [self.current]
        return chosen

    # -- right-click menu ---------------------------------------------------

    def build_preview_menu(self) -> QMenu:
        """The actions offered for the previewed file.

        Built separately from showing it so the wiring can be exercised without
        opening a modal menu that would block.
        """
        menu = QMenu(self)
        menu.setToolTipsVisible(True)
        is_image = self.current is not None and self.current.kind is MediaKind.IMAGE
        entries = (
            (
                copy_files_label(len(self.file_list.selected_or_current())),
                "Paste into a folder or a file manager",
                self.file_list.copy_selected_to_clipboard,
                self.current is not None,
            ),
            (
                copy_names_label(len(self.file_list.selected_or_current())),
                "Paste the name as plain text, one file per line",
                self.file_list.copy_names_to_clipboard,
                self.current is not None,
            ),
            (
                "Copy Picture",
                "Paste into a chat, a document or an image editor",
                self.copy_image_to_clipboard,
                is_image,
            ),
            ("Delete", "", self.delete_selected, self.current is not None),
            (
                "Rename",
                "Rename this one file",
                self.rename_current_file,
                self.current is not None,
            ),
            ("Select", "", self.toggle_current_selection, self.current is not None),
            ("Edit Image", "", self.open_edit, is_image),
            ("Rotate", "", self.rotate_current_file, is_image),
            ("Convert", "", self.open_convert, is_image),
            ("Remove Watermark", "", self.open_watermark_editor, is_image),
            ("Remove Background", "", self.open_cutout_editor, is_image),
        )
        for label, hint, handler, enabled in entries:
            action = menu.addAction(label)
            action.setToolTip(hint)
            action.setEnabled(enabled)
            action.triggered.connect(handler)
        return menu

    def show_preview_menu(self, screen_position: QPoint) -> None:
        """Open the actions menu where the user right-clicked."""
        self.build_preview_menu().exec(screen_position)

    def copy_image_to_clipboard(self) -> None:
        """Put the picture itself on the clipboard, ready to paste into a chat."""
        if self.current is None or self.current.kind is not MediaKind.IMAGE:
            return
        pixmap = load_pixmap(self.current.path)
        clipboard = QGuiApplication.clipboard()
        if not pixmap.isNull() and clipboard is not None:
            clipboard.setPixmap(pixmap)

    def toggle_current_selection(self) -> None:
        self.file_list.toggle_current_selection()

    def rotate_current_file(self) -> None:
        """Turn the current photo a quarter turn clockwise, in place."""
        media_file = self.current
        if media_file is None or media_file.kind is not MediaKind.IMAGE:
            return
        from myimages.imaging import transform

        def work() -> Path:
            rotated = transform.rotate_image(transform.load_image(media_file.path), 90)
            return transform.save_image(rotated, media_file.path, quality=95)

        def done(result: object) -> None:
            self.loader.forget(media_file)
            self.reload()

        self.run_with_progress(work, "Rotating…", done)

    def open_watermark_editor(self) -> None:
        """Open the editor with the watermark already painted out, to review."""
        if self.current is None or self.current.kind is not MediaKind.IMAGE:
            return
        self.open_edit()
        self.editor.remove_watermark()

    def open_cutout_editor(self) -> None:
        """Open the editor already switched to cutting the background away."""
        if self.current is None or self.current.kind is not MediaKind.IMAGE:
            return
        if self.preview_area.currentWidget() is not self.editor:
            self.open_edit()
        if self.preview_area.currentWidget() is self.editor:
            self.editor.set_mode("background")

    # -- favourites & deletion --------------------------------------------

    def toggle_favorite_current(self) -> None:
        # Held onto because refreshing can clear the current file: un-starring
        # the last favourite while the favourites filter is on empties the view,
        # and reading self.current back afterwards used to crash here -- taking
        # the un-favourite down with it, so it was never even saved.
        if self.current is None:
            return
        path = self.current.path
        self.settings.toggle_favorite(path)
        self.file_list.refresh_current_label()
        self.preview.set_favorite(self.settings.is_favorite(path))
        save_settings(self.settings)

    def delete_selected(self) -> None:
        targets = self.file_list.selected_files()
        if not targets and self.current is not None:
            targets = [self.current]
        if not targets:
            return
        answer = QMessageBox.question(self, "Delete", f"Delete {len(targets)} file(s)?")
        if answer != QMessageBox.StandardButton.Yes:
            return
        removed = deletion.delete_files([f.path for f in targets])
        removed_set = {str(path) for path in removed}
        for media_file in targets:
            if str(media_file.path) in removed_set:
                self.loader.forget(media_file)
        self.set_media_files(
            [f for f in self.media_files if str(f.path) not in removed_set]
        )

    # -- tool dialogs ------------------------------------------------------

    def run_with_progress(
        self,
        function: Callable[[], object],
        title: str,
        on_finished: Callable[[object], None],
    ) -> None:
        progress = QProgressDialog(title, "", 0, 0, self)
        progress.setCancelButton(None)
        progress.setWindowTitle("Please wait")
        progress.show()

        def finished(result: object) -> None:
            progress.close()
            on_finished(result)

        def failed(message: str) -> None:
            progress.close()
            QMessageBox.warning(self, title, message)

        self.task_runner(function, finished, failed)

    def open_edit(self) -> None:
        """Enter the inline crop/rotate editor under the preview."""
        if self.current is None or self.current.kind is not MediaKind.IMAGE:
            return
        if not self.editor.load(self.current):
            return
        self.preview_area.setCurrentWidget(self.editor)

    def on_editor_closed(self, changed: bool) -> None:
        self.preview_area.setCurrentWidget(self.preview)
        if changed:
            self.loader.clear()
            self.reload()

    def cancel_edit(self) -> None:
        if self.preview_area.currentWidget() is self.editor:
            self.editor.cancel()

    def open_convert(self) -> None:
        images = self.selected_images()
        if not images:
            return
        from myimages.gui.convert_dialog import ConvertDialog
        from myimages.imaging import convert

        default_dir = images[0].path.parent
        dialog = ConvertDialog(len(images), default_dir, self)
        if not dialog.exec():
            return
        parameters = dialog.parameters()
        sources = [f.path for f in images]

        def convert_destination(source: Path) -> Path:
            """Where one source lands: beside it (Save) or in the copy folder."""
            name = source.stem + parameters.target_extension
            if parameters.replace_originals:
                return source.parent / name
            dest = parameters.output_dir / name
            if dest == source:
                # Copying into the source folder with the same extension must
                # never clobber the original it promised to keep.
                dest = parameters.output_dir / (
                    source.stem + "_copy" + parameters.target_extension
                )
            return dest

        def work() -> list[Path]:
            outputs: list[Path] = []
            for source in sources:
                dest = convert_destination(source)
                convert.convert_image(
                    source,
                    dest,
                    quality=parameters.quality,
                    grayscale=parameters.grayscale,
                )
                if parameters.replace_originals and dest != source:
                    deletion.delete_files([source])
                outputs.append(dest)
            return outputs

        def done(result: object) -> None:
            count = len(result) if isinstance(result, list) else 0
            verb = "Converted" if parameters.replace_originals else "Copied"
            QMessageBox.information(self, "Convert", f"{verb} {count} file(s).")
            self.loader.clear()  # a rewritten file must not keep its old thumbnail
            self.reload()

        self.run_with_progress(work, "Converting…", done)

    def open_pdf(self) -> None:
        images = self.selected_images()
        if not images:
            return
        from myimages.gui.pdf_dialog import PdfDialog
        from myimages.imaging import pdfbuilder

        default_path = images[0].path.with_suffix(".pdf")
        dialog = PdfDialog(len(images), default_path, self.settings.pdf_quality, self)
        if not dialog.exec():
            return
        parameters = dialog.parameters()
        sources = [f.path for f in images]

        def work() -> pdfbuilder.PdfResult:
            return pdfbuilder.build_pdf(
                sources, parameters.destination, parameters.options
            )

        def done(result: object) -> None:
            assert isinstance(result, pdfbuilder.PdfResult)
            from myimages.format_utils import human_readable_size

            QMessageBox.information(
                self,
                "PDF",
                f"Saved {result.page_count} page(s), "
                f"{human_readable_size(result.size_bytes)} at quality "
                f"{result.quality_used}.\n{result.path}",
            )

        self.run_with_progress(work, "Building PDF…", done)

    def open_gif(self) -> None:
        images = [
            f for f in self.file_list.selected_files() if f.kind is MediaKind.IMAGE
        ]
        if len(images) < 2:
            QMessageBox.information(self, "GIF", "Select at least two images.")
            return
        from myimages.gui.gif_dialog import GifFromFramesDialog
        from myimages.video import gif

        default_path = images[0].path.with_suffix(".gif")
        dialog = GifFromFramesDialog(
            len(images),
            default_path,
            self.settings.gif_fps,
            self.settings.gif_width,
            self,
        )
        if not dialog.exec():
            return
        parameters = dialog.parameters()
        frames = [f.path for f in images]

        def work() -> Path:
            return gif.gif_from_frames(
                frames,
                parameters.destination,
                fps=parameters.fps,
                width=parameters.width,
            )

        def done(result: object) -> None:
            QMessageBox.information(self, "GIF", f"Saved GIF:\n{result}")
            self.reload()

        self.run_with_progress(work, "Building GIF…", done)

    def open_video_tools(self) -> None:
        if self.current is None or self.current.kind is not MediaKind.VIDEO:
            return
        from myimages.video import ffmpeg

        if not ffmpeg.is_available():
            QMessageBox.information(
                self,
                "Video tools",
                "FFmpeg is required. Open Optional features to see how to install it.",
            )
            return
        from myimages.gui.video_tool_dialog import VideoToolDialog

        dialog = VideoToolDialog(self.current, self, runner=self.task_runner)
        dialog.exec()
        self.reload()

    def open_duplicates(self) -> None:
        if not self.media_files:
            return
        from myimages.gui.duplicates_dialog import DuplicatesDialog

        dialog = DuplicatesDialog(list(self.media_files), self, runner=self.task_runner)
        dialog.files_deleted.connect(lambda paths: self.reload())
        dialog.exec()

    def rename_current_file(self) -> None:
        """Rename the one file that was right-clicked.

        Handing someone a find-and-replace pattern builder because they wanted
        to fix one filename is a mismatch; the batch tool stays on the toolbar
        for when a whole selection really does need renaming.
        """
        if self.current is None:
            return
        from myimages.core.rename import RenamePlanItem, apply_rename_plan
        from myimages.gui.single_rename_dialog import SingleRenameDialog

        dialog = SingleRenameDialog(self.current.path, self)
        if not dialog.exec():
            return
        target = dialog.new_path()
        if target == self.current.path:
            return
        try:
            apply_rename_plan([RenamePlanItem(self.current.path, target)])
        except Exception as error:  # noqa: BLE001 - surfaced to the user
            QMessageBox.warning(self, "Rename", str(error))
            return
        self.reload()
        self.file_list.select_path(str(target))

    def open_rename(self) -> None:
        targets = self.file_list.selected_files() or self.file_list.visible_files()
        if not targets:
            return
        from myimages.core.rename import apply_rename_plan
        from myimages.gui.rename_dialog import RenameDialog

        dialog = RenameDialog(list(targets), self)
        if dialog.exec() and dialog.plan():
            try:
                apply_rename_plan(dialog.plan())
            except Exception as error:  # noqa: BLE001 - surfaced to the user
                QMessageBox.warning(self, "Rename", str(error))
                return
            self.reload()

    def open_settings(self) -> None:
        from myimages.gui.settings_dialog import SettingsDialog

        dialog = SettingsDialog(self.settings, self)
        if not dialog.exec():
            return
        for key, value in dialog.values().items():
            setattr(self.settings, key, value)
        self.loader.size = self.settings.thumbnail_size
        self.recursive_button.setChecked(self.settings.recursive_scan)
        save_settings(self.settings)
        self.apply_theme()
        self.load_source()

    def open_dependencies(self) -> None:
        from myimages.gui.dependencies_dialog import DependenciesDialog

        DependenciesDialog(self, runner=self.task_runner).exec()

    def open_plugins_info(self) -> None:
        from myimages.paths import plugins_dir

        names = [plugin.name for plugin in self.registry.viewers] or ["(none)"]
        QMessageBox.information(
            self,
            "Plugins",
            "Loaded viewer plugins:\n- "
            + "\n- ".join(names)
            + f"\n\nDrop *.py plugins into:\n{plugins_dir()}",
        )

    def apply_theme(self) -> None:
        from myimages.app import apply_theme_to_app

        apply_theme_to_app(self.settings.theme)
        self.refresh_icons()
        self.apply_brand_colours()

    def apply_brand_colours(self) -> None:
        """Paint the wordmark: MY in the scheme's tint, IMAGES in its text colour.

        Rich text rather than two labels so the halves sit on one baseline with
        no gap a layout could stretch, and both colours are taken from the
        scheme: a literal white would disappear against the light theme.
        """
        scheme = theme.scheme_for(self.settings.theme)
        self.brand.setText(
            f'<span style="color:{scheme.brand_tint}">MY</span>'
            f'<span style="color:{scheme.text}">IMAGES</span>'
        )

    # -- persistence -------------------------------------------------------

    def store_layout(self) -> None:
        """Remember the window size.

        The file-list width is deliberately not read back from the splitter
        here: it is recorded when the divider is dragged. Reading the geometry
        instead would persist whatever a narrow window had last squeezed the
        list down to, so closing the app while it was small used to throw the
        chosen width away for good.
        """
        self.settings.window_width = self.width()
        self.settings.window_height = self.height()

    def showEvent(self, event: QShowEvent) -> None:
        """Hand the keyboard to the photos as the window appears.

        Qt gives the initial focus to the first widget in the tab order, which
        here is the folder box -- so the app opened with a text cursor blinking
        in the path and the arrow keys typing into it instead of stepping
        through pictures. Only done until it succeeds: a window restored from
        the taskbar must not yank the keyboard out of wherever the user left it.
        """
        super().showEvent(event)
        if not self.keyboard_handed_over:
            self.keyboard_handed_over = self.file_list.focus_active_view()

    def closeEvent(self, event: QCloseEvent) -> None:
        self.monitor.stop()
        self.store_layout()
        save_settings(self.settings)
        super().closeEvent(event)
