"""The large preview area: photos, videos or a plugin-supplied widget.

Images use the zoomable :class:`ImageView`. Videos use Qt Multimedia when it is
present; if that optional backend is missing the pane still shows a still frame
and points the user at the video tools, so the app degrades gracefully instead
of failing to start. Plugins registered for an extension take priority and get
to render the file themselves.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QPoint, QSize, Qt, QUrl, Signal
from PySide6.QtGui import (
    QIcon,
    QImageReader,
    QMovie,
    QPixmap,
    QResizeEvent,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from myimages import icons
from myimages.core.media import MediaFile, MediaKind
from myimages.core.plugins import PluginRegistry
from myimages.gui.image_view import ImageView

try:
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
    from PySide6.QtMultimediaWidgets import QVideoWidget

    VIDEO_IMPORTED = True
except Exception:  # noqa: BLE001 - optional backend, absence is fine
    VIDEO_IMPORTED = False

# The test suite sets MYIMAGES_NO_VIDEO to keep QtMultimedia (which spins up an
# ffmpeg backend thread per player) out of the process, avoiding native teardown
# crashes when many short-lived windows are created and destroyed.
VIDEO_BACKEND_AVAILABLE = VIDEO_IMPORTED and not bool(
    os.environ.get("MYIMAGES_NO_VIDEO")
)

try:
    from PySide6.QtPdf import QPdfDocument

    PDF_BACKEND_AVAILABLE = True
except Exception:  # noqa: BLE001 - optional module, absence is fine
    PDF_BACKEND_AVAILABLE = False


def load_pixmap(path: str | Path) -> QPixmap:
    """Load an image honouring its EXIF orientation; empty pixmap on failure."""
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    image = reader.read()
    if image.isNull():
        return QPixmap()
    return QPixmap.fromImage(image)


# Pages rendered per batch: enough to fill a few screens, small enough that a
# huge document opens instantly instead of freezing while every page rasterises.
PDF_PAGE_BATCH = 8


class PdfPreview(QScrollArea):
    """Scrollable PDF viewer that renders each page to a pixmap synchronously.

    ``QPdfView`` renders asynchronously and often paints blank; rendering pages
    with ``QPdfDocument.render`` into labels is reliable and needs no event
    loop. Pages rasterise in batches of :data:`PDF_PAGE_BATCH` with a
    "show more" button, so a large document never blocks the UI at open.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.container = QWidget()
        self.column = QVBoxLayout(self.container)
        self.column.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.column.setSpacing(10)
        self.setWidget(self.container)
        self.document = QPdfDocument(self)
        self.rendered_width = 0
        self.rendered_pages = 0
        self.more_button: QPushButton | None = None

    def load(self, path: str) -> None:
        self.document.load(path)
        self.rendered_pages = 0
        self.render_pages()

    def clear_pages(self) -> None:
        self.more_button = None
        while self.column.count():
            item = self.column.takeAt(0)
            if item is None:
                break  # cannot happen while count() is positive; keeps it bounded
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def append_page(self, index: int, width: int) -> None:
        point_size = self.document.pagePointSize(index)
        ratio = 1.414  # an A4-ish fallback when the page reports no size
        if point_size.width() > 0:
            ratio = point_size.height() / point_size.width()
        image = self.document.render(index, QSize(width, round(width * ratio)))
        label = QLabel()
        label.setPixmap(QPixmap.fromImage(image))
        self.column.addWidget(label)

    def render_pages(self) -> None:
        """Re-render from scratch, keeping how many pages were expanded to."""
        target = max(self.rendered_pages, PDF_PAGE_BATCH)
        self.clear_pages()
        width = max(300, self.viewport().width() - 24)
        self.rendered_width = width
        total = self.document.pageCount()
        self.rendered_pages = min(total, target)
        for index in range(self.rendered_pages):
            self.append_page(index, width)
        self.update_more_button()

    def update_more_button(self) -> None:
        remaining = self.document.pageCount() - self.rendered_pages
        if remaining <= 0:
            return
        batch = min(PDF_PAGE_BATCH, remaining)
        self.more_button = QPushButton(
            f"Show {batch} more page(s) — {remaining} remaining"
        )
        self.more_button.clicked.connect(self.show_more)
        self.column.addWidget(self.more_button)

    def show_more(self) -> None:
        if self.more_button is not None:
            self.column.removeWidget(self.more_button)
            self.more_button.deleteLater()
            self.more_button = None
        total = self.document.pageCount()
        target = min(total, self.rendered_pages + PDF_PAGE_BATCH)
        for index in range(self.rendered_pages, target):
            self.append_page(index, self.rendered_width)
        self.rendered_pages = target
        self.update_more_button()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        target = max(300, self.viewport().width() - 24)
        if self.document.pageCount() > 0 and abs(target - self.rendered_width) > 24:
            self.render_pages()


class PreviewPane(QWidget):
    """Switches between image, video and plugin views for the current file."""

    navigate = Signal(int)
    favorite_toggled = Signal()
    context_menu_requested = Signal(QPoint)  # screen coordinates

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.current_media: MediaFile | None = None
        self.plugin_widget: QWidget | None = None
        self.favorite_state = False
        self.themed_buttons: list[tuple[QToolButton, Callable[[], QIcon]]] = []
        self.build_ui()

    def build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.stack = QStackedWidget()
        self.image_view = ImageView()
        self.image_view.navigate.connect(self.navigate)
        self.message_label = QLabel("Select a file to preview")
        self.message_label.setObjectName("muted")
        self.message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stack.addWidget(self.image_view)  # index 0
        self.stack.addWidget(self.message_label)  # index 1

        self.video_widget: QWidget | None = None
        self.media_player = None
        self.audio_output = None
        if VIDEO_BACKEND_AVAILABLE:
            self.video_widget = QVideoWidget()
            self.media_player = QMediaPlayer(self)
            self.audio_output = QAudioOutput(self)
            self.media_player.setAudioOutput(self.audio_output)
            self.media_player.setVideoOutput(self.video_widget)
            self.stack.addWidget(self.video_widget)

        # Animated GIFs play in a QLabel driven by a QMovie.
        self.gif_movie: QMovie | None = None
        self.gif_native = QSize()
        self.gif_label = QLabel()
        self.gif_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stack.addWidget(self.gif_label)

        # PDFs render page-by-page in a scrollable PdfPreview when QtPdf is present.
        self.pdf_preview: PdfPreview | None = None
        if PDF_BACKEND_AVAILABLE:
            self.pdf_preview = PdfPreview()
            self.stack.addWidget(self.pdf_preview)
        layout.addWidget(self.stack, 1)

        # A favourite star floating over the top-right of the preview.
        self.favorite_button = QToolButton(self)
        self.favorite_button.setObjectName("overlayStar")
        self.favorite_button.setIcon(icons.star(False))
        self.favorite_button.setIconSize(QSize(18, 18))
        self.favorite_button.setFixedSize(30, 30)
        self.favorite_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.favorite_button.setToolTip("Mark as favourite")
        self.favorite_button.clicked.connect(self.favorite_toggled.emit)
        self.favorite_button.hide()

        self.enable_context_menu()

        # The pixel resolution floating over the bottom-right of the preview.
        self.resolution_label = QLabel(self)
        self.resolution_label.setObjectName("overlayInfo")
        self.resolution_label.hide()

        controls = QHBoxLayout()
        controls.setContentsMargins(6, 0, 6, 6)
        controls.setSpacing(6)
        self.zoom_out_button = self.make_control(
            icons.zoom_out, "Zoom out", self.image_view.zoom_out
        )
        self.zoom_in_button = self.make_control(
            icons.zoom_in, "Zoom in", self.image_view.zoom_in
        )
        self.fit_button = self.make_control(
            icons.fit, "Fit to window", self.image_view.fit
        )
        self.play_button = self.make_control(
            icons.play, "Play / pause", self.toggle_playback
        )
        controls.addWidget(self.zoom_out_button)
        controls.addWidget(self.zoom_in_button)
        controls.addWidget(self.fit_button)
        controls.addStretch(1)
        controls.addWidget(self.play_button)
        layout.addLayout(controls)
        self.update_controls(MediaKind.OTHER)

    def enable_context_menu(self) -> None:
        """Route a right-click anywhere in the preview to one signal.

        Each view inside the stack would otherwise swallow the click itself, so
        the policy is set on the children as well as on the pane.
        """
        targets: list[QWidget] = [self, self.image_view, self.gif_label]
        if self.pdf_preview is not None:
            targets.append(self.pdf_preview)
        if self.video_widget is not None:
            targets.append(self.video_widget)
        for widget in targets:
            widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            widget.customContextMenuRequested.connect(self.relay_context_menu)

    def relay_context_menu(self, position: QPoint) -> None:
        """Announce a right-click in screen coordinates.

        The click can come from any of the stacked views, so it is mapped to the
        screen once here instead of leaving every listener to work out which
        widget the position belonged to.
        """
        sender = self.sender()
        source = sender if isinstance(sender, QWidget) else self
        self.context_menu_requested.emit(source.mapToGlobal(position))

    def make_control(
        self,
        icon_factory: Callable[[], QIcon],
        tooltip: str,
        handler: Callable[..., object],
    ) -> QToolButton:
        button = QToolButton()
        button.setObjectName("flat")
        button.setIcon(icon_factory())
        button.setToolTip(tooltip)
        button.clicked.connect(handler)
        self.themed_buttons.append((button, icon_factory))
        return button

    def refresh_icons(self) -> None:
        """Redraw the pane's icons in the current theme's colour."""
        for button, icon_factory in self.themed_buttons:
            button.setIcon(icon_factory())
        self.set_favorite(self.favorite_state)

    def update_controls(self, kind: MediaKind) -> None:
        is_image = kind is MediaKind.IMAGE
        for button in (self.zoom_out_button, self.zoom_in_button, self.fit_button):
            button.setVisible(is_image)
        self.play_button.setVisible(kind is MediaKind.VIDEO and VIDEO_BACKEND_AVAILABLE)

    def set_favorite(self, favorite: bool) -> None:
        """Reflect whether the current file is a favourite on the overlay star."""
        self.favorite_state = favorite
        self.favorite_button.setIcon(icons.star(favorite))

    def set_resolution(self, text: str) -> None:
        """Show a pixel-size badge (e.g. ``1920 × 1080``); empty text hides it."""
        self.resolution_label.setText(text)
        self.resolution_label.setVisible(bool(text))
        self.position_overlays()

    def position_overlays(self) -> None:
        self.favorite_button.move(self.width() - self.favorite_button.width() - 14, 14)
        self.favorite_button.raise_()
        self.resolution_label.adjustSize()
        self.resolution_label.move(
            self.width() - self.resolution_label.width() - 12,
            self.height() - self.resolution_label.height() - 10,
        )
        self.resolution_label.raise_()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self.position_overlays()
        self.scale_gif()

    def clear_plugin_widget(self) -> None:
        if self.plugin_widget is not None:
            self.stack.removeWidget(self.plugin_widget)
            self.plugin_widget.deleteLater()
            self.plugin_widget = None

    def show_media(
        self, media_file: MediaFile | None, registry: PluginRegistry | None = None
    ) -> None:
        """Display ``media_file`` using the most specific viewer available."""
        self.stop_playback()
        self.stop_gif()
        self.clear_plugin_widget()
        self.current_media = media_file
        self.favorite_button.setVisible(media_file is not None)
        self.resolution_label.hide()  # re-shown by show_image/show_video if sized
        self.position_overlays()
        if media_file is None:
            self.message_label.setText("Select a file to preview")
            self.stack.setCurrentWidget(self.message_label)
            self.update_controls(MediaKind.OTHER)
            return

        plugin = registry.viewer_for(media_file.path) if registry else None
        if plugin is not None:
            self.show_plugin(plugin.create_widget(media_file.path))
            self.update_controls(MediaKind.OTHER)
            return

        if media_file.kind is MediaKind.IMAGE and media_file.suffix == ".gif":
            self.show_gif(media_file)
        elif media_file.kind is MediaKind.IMAGE:
            self.show_image(media_file)
        elif media_file.kind is MediaKind.VIDEO:
            self.show_video(media_file)
        elif media_file.kind is MediaKind.DOCUMENT:
            self.show_pdf(media_file)
        else:
            self.message_label.setText(f"No preview for {media_file.suffix} files")
            self.stack.setCurrentWidget(self.message_label)
            self.update_controls(MediaKind.OTHER)

    def show_plugin(self, widget: QWidget) -> None:
        self.plugin_widget = widget
        self.stack.addWidget(widget)
        self.stack.setCurrentWidget(widget)

    def show_image(self, media_file: MediaFile) -> None:
        pixmap = load_pixmap(media_file.path)
        if pixmap.isNull():
            self.message_label.setText(f"Could not open {media_file.name}")
            self.stack.setCurrentWidget(self.message_label)
        else:
            self.image_view.set_pixmap(pixmap)
            self.stack.setCurrentWidget(self.image_view)
            self.set_resolution(f"{pixmap.width()} × {pixmap.height()}")
        self.update_controls(MediaKind.IMAGE)

    def show_video(self, media_file: MediaFile) -> None:
        if self.media_player is not None and self.video_widget is not None:
            self.media_player.setSource(QUrl.fromLocalFile(str(media_file.path)))
            self.stack.setCurrentWidget(self.video_widget)
        else:
            self.message_label.setText(
                f"{media_file.name}\n\nVideo preview needs Qt Multimedia.\n"
                "Use the video tools to trim, scale or export a GIF."
            )
            self.stack.setCurrentWidget(self.message_label)
        self.update_controls(MediaKind.VIDEO)

    def show_gif(self, media_file: MediaFile) -> None:
        """Play an animated GIF, scaled to fit while keeping its aspect ratio."""
        movie = QMovie(str(media_file.path))
        movie.jumpToFrame(0)
        self.gif_native = movie.currentPixmap().size()
        self.gif_movie = movie
        self.gif_label.setMovie(movie)
        self.scale_gif()
        movie.start()
        self.stack.setCurrentWidget(self.gif_label)
        if self.gif_native.width() > 0:
            self.set_resolution(
                f"{self.gif_native.width()} × {self.gif_native.height()}"
            )
        self.update_controls(MediaKind.OTHER)

    def scale_gif(self) -> None:
        if self.gif_movie is None or self.gif_native.width() <= 0:
            return
        area = self.stack.size()
        if area.width() <= 0 or area.height() <= 0:
            return
        scaled = self.gif_native.scaled(area, Qt.AspectRatioMode.KeepAspectRatio)
        if scaled.width() > self.gif_native.width():
            scaled = self.gif_native  # never upscale past the source
        self.gif_movie.setScaledSize(scaled)

    def stop_gif(self) -> None:
        if self.gif_movie is not None:
            self.gif_movie.stop()
            self.gif_label.clear()
            self.gif_movie = None

    def show_pdf(self, media_file: MediaFile) -> None:
        """Render a PDF with QtPdf, or explain if the module is unavailable."""
        if self.pdf_preview is None:
            self.message_label.setText(
                f"{media_file.name}\n\nPDF preview needs the QtPdf module."
            )
            self.stack.setCurrentWidget(self.message_label)
        else:
            self.pdf_preview.load(str(media_file.path))
            if self.pdf_preview.document.pageCount() > 0:
                self.stack.setCurrentWidget(self.pdf_preview)
            else:
                self.message_label.setText(f"Could not open {media_file.name}")
                self.stack.setCurrentWidget(self.message_label)
        self.update_controls(MediaKind.OTHER)

    def toggle_playback(self) -> None:
        if self.media_player is None:
            return
        if self.media_player.isPlaying():
            self.media_player.pause()
        else:
            self.media_player.play()

    def stop_playback(self) -> None:
        if self.media_player is not None:
            self.media_player.stop()

    def wheelEvent(self, event: QWheelEvent) -> None:
        # Reached only when a non-image view is shown (the image view handles
        # its own wheel). Plain wheel steps files; Shift is left for zooming.
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            event.ignore()
            return
        self.navigate.emit(-1 if event.angleDelta().y() > 0 else 1)
        event.accept()
