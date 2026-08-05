"""Tests for the preview pane (myimages.gui.preview_pane).

Covers pixmap loading, the image/video/other/plugin display branches and the
playback helpers. Video-backend-dependent behaviour is asserted in a way that
holds whether or not Qt Multimedia is present, by checking that
``update_controls`` ran (play-button visibility must match
``VIDEO_BACKEND_AVAILABLE``).
"""

from __future__ import annotations

from typing import Any, cast

from PySide6.QtCore import QPoint, QPointF, QSize, Qt
from PySide6.QtGui import QIcon, QWheelEvent
from PySide6.QtWidgets import QLabel, QToolButton, QWidget

from myimages import icons
from myimages.core.media import MediaFile, MediaKind, build_media_file
from myimages.core.plugins import PluginRegistry
from myimages.gui.preview_pane import (
    VIDEO_BACKEND_AVAILABLE,
    PreviewPane,
    load_pixmap,
)


class FakePlayer:
    """Stand-in for QMediaPlayer to exercise the playback branches directly."""

    def __init__(self) -> None:
        self.playing = False
        self.played = False
        self.paused = False
        self.stopped = False
        self.source = None

    def isPlaying(self) -> bool:
        return self.playing

    def setSource(self, url) -> None:
        self.source = url

    def play(self) -> None:
        self.played = True

    def pause(self) -> None:
        self.paused = True

    def stop(self) -> None:
        self.stopped = True


def make_pane(qtbot) -> PreviewPane:
    pane = PreviewPane()
    qtbot.addWidget(pane)
    return pane


def fake_video_pane(qtbot) -> tuple[PreviewPane, FakePlayer]:
    """A pane with a FakePlayer and a stand-in video widget in its stack.

    The suite runs with MYIMAGES_NO_VIDEO set, so the real player is never
    built; this puts the video branch back within reach without QtMultimedia.
    """
    pane = make_pane(qtbot)
    fake = FakePlayer()
    pane.media_player = cast(Any, fake)
    pane.video_widget = QWidget()
    pane.stack.addWidget(pane.video_widget)
    return pane, fake


def icon_bytes(icon: QIcon) -> bytes:
    """Rasterise an icon, so two of them can be compared for real.

    QIcon has no useful equality, and both glyphs are drawn by the same
    factory; only the pixels tell them apart.
    """
    return icon.pixmap(QSize(16, 16)).toImage().constBits().tobytes()


def video_media(tmp_path) -> MediaFile:
    """A .mp4 stub turned into a VIDEO MediaFile (classified by extension)."""
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"")
    media = build_media_file(path)
    assert media.kind is MediaKind.VIDEO
    return media


def wheel_event(delta_y, modifiers=Qt.KeyboardModifier.NoModifier) -> QWheelEvent:
    return QWheelEvent(
        QPointF(5, 5),
        QPointF(5, 5),
        QPoint(0, 0),
        QPoint(0, delta_y),
        Qt.MouseButton.NoButton,
        modifiers,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )


def test_image_view_navigation_is_re_emitted(qtbot):
    pane = make_pane(qtbot)
    directions: list[int] = []
    pane.navigate.connect(directions.append)
    pane.image_view.navigate.emit(1)
    assert directions == [1]


def test_wheel_over_pane_navigates(qtbot):
    pane = make_pane(qtbot)
    directions: list[int] = []
    pane.navigate.connect(directions.append)
    pane.wheelEvent(wheel_event(120))  # up -> previous
    pane.wheelEvent(wheel_event(-120))  # down -> next
    assert directions == [-1, 1]


def test_ctrl_wheel_over_pane_does_not_navigate(qtbot):
    pane = make_pane(qtbot)
    directions: list[int] = []
    pane.navigate.connect(directions.append)
    pane.wheelEvent(wheel_event(120, Qt.KeyboardModifier.ControlModifier))
    assert directions == []


def test_load_pixmap_real_image_is_not_null(qtbot, make_image):
    pixmap = load_pixmap(make_image())
    assert not pixmap.isNull()


def test_load_pixmap_garbage_file_is_null(qtbot, tmp_path):
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"this is not a valid image")
    assert load_pixmap(broken).isNull()


def test_show_media_none_shows_message_and_hides_controls(qtbot):
    pane = make_pane(qtbot)
    pane.show_media(None)
    assert pane.current_media is None
    assert pane.stack.currentWidget() is pane.message_label
    assert pane.message_label.text() == "Select a file to preview"
    assert not pane.zoom_in_button.isVisibleTo(pane.controls_bar)
    assert not pane.zoom_out_button.isVisibleTo(pane.controls_bar)
    assert not pane.fit_button.isVisibleTo(pane.controls_bar)
    assert not pane.play_button.isVisibleTo(pane.controls_bar)


def test_show_media_image_shows_image_view_and_image_controls(qtbot, media_file):
    pane = make_pane(qtbot)
    pane.show_media(media_file)
    assert pane.current_media is media_file
    assert pane.stack.currentWidget() is pane.image_view
    assert pane.image_view.has_image()
    assert pane.zoom_in_button.isVisibleTo(pane.controls_bar)
    assert pane.zoom_out_button.isVisibleTo(pane.controls_bar)
    assert pane.fit_button.isVisibleTo(pane.controls_bar)
    assert not pane.play_button.isVisibleTo(pane.controls_bar)


def test_show_media_unreadable_image_shows_error_message(qtbot, tmp_path):
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"still not an image")
    media = build_media_file(broken)
    assert media.kind is MediaKind.IMAGE
    pane = make_pane(qtbot)
    pane.show_media(media)
    assert pane.stack.currentWidget() is pane.message_label
    assert "Could not open" in pane.message_label.text()
    assert "broken.png" in pane.message_label.text()


def test_show_media_video_runs_update_controls(qtbot, tmp_path):
    pane = make_pane(qtbot)
    pane.show_media(video_media(tmp_path))
    # update_controls(VIDEO) ran: play visible iff the backend is present,
    # and the image-only controls are always hidden for video.
    assert pane.play_button.isVisibleTo(pane.controls_bar) is VIDEO_BACKEND_AVAILABLE
    assert not pane.zoom_in_button.isVisibleTo(pane.controls_bar)
    if VIDEO_BACKEND_AVAILABLE:
        assert pane.stack.currentWidget() is pane.video_widget


def test_show_video_without_backend_shows_hint(qtbot, tmp_path):
    pane = make_pane(qtbot)
    # Simulate the missing-backend configuration on this instance only.
    pane.media_player = None
    pane.video_widget = None
    pane.show_video(video_media(tmp_path))
    assert pane.stack.currentWidget() is pane.message_label
    assert "Qt Multimedia" in pane.message_label.text()
    assert "clip.mp4" in pane.message_label.text()


def test_show_media_other_shows_no_preview(qtbot, tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("hello")
    media = build_media_file(path)
    assert media.kind is MediaKind.OTHER
    pane = make_pane(qtbot)
    pane.show_media(media)
    assert pane.stack.currentWidget() is pane.message_label
    assert "No preview" in pane.message_label.text()
    assert ".txt" in pane.message_label.text()


def test_plugin_widget_is_shown_then_cleared_next_time(qtbot, media_file):
    pane = make_pane(qtbot)
    registry = PluginRegistry()

    def make_widget(path):
        return QLabel(str(path))

    registry.register_viewer("stub", [media_file.suffix], make_widget)
    pane.show_media(media_file, registry)

    label = pane.plugin_widget
    assert isinstance(label, QLabel)
    assert pane.stack.currentWidget() is label
    assert label.text() == str(media_file.path)
    # A plugin view is not an image or video, so all media controls are hidden.
    assert not pane.play_button.isVisibleTo(pane.controls_bar)
    assert not pane.zoom_in_button.isVisibleTo(pane.controls_bar)

    # The next show_media call clears the previous plugin widget.
    pane.show_media(None)
    assert pane.plugin_widget is None
    assert pane.stack.indexOf(label) == -1
    assert pane.stack.currentWidget() is pane.message_label


def test_make_control_returns_tool_button(qtbot):
    pane = make_pane(qtbot)
    button = pane.make_control(QIcon, "Tooltip text", lambda: None)
    assert isinstance(button, QToolButton)
    assert button.objectName() == "flat"
    assert button.toolTip() == "Tooltip text"


def test_playback_helpers_are_safe_when_player_is_none(qtbot):
    pane = make_pane(qtbot)
    pane.media_player = None
    # Neither call should raise with no backend/player present.
    pane.toggle_playback()
    pane.stop_playback()


def test_toggle_playback_plays_then_pauses(qtbot):
    pane = make_pane(qtbot)
    fake = FakePlayer()
    pane.media_player = cast(Any, fake)

    pane.toggle_playback()
    assert fake.played is True
    assert fake.paused is False

    fake.playing = True
    pane.toggle_playback()
    assert fake.paused is True


def test_stop_playback_stops_the_player(qtbot):
    pane = make_pane(qtbot)
    fake = FakePlayer()
    pane.media_player = cast(Any, fake)
    pane.stop_playback()
    assert fake.stopped is True


def test_real_playback_helpers_do_not_raise(qtbot, tmp_path):
    pane = make_pane(qtbot)
    pane.show_media(video_media(tmp_path))
    # Exercise the real helpers with whatever backend is configured.
    pane.toggle_playback()
    pane.stop_playback()


def test_selecting_a_video_starts_it_playing(qtbot, tmp_path):
    """Loading the source is not enough. The backend decodes nothing until
    playback starts, so a video that is only loaded shows an empty pane."""
    pane, fake = fake_video_pane(qtbot)
    pane.show_media(video_media(tmp_path))
    assert pane.stack.currentWidget() is pane.video_widget
    assert fake.source is not None
    assert "clip.mp4" in fake.source.toLocalFile()
    assert fake.played is True


def test_moving_to_another_file_stops_the_video(qtbot, tmp_path, make_image):
    """Nothing is left running behind the user: the clip that autoplayed must
    not still be decoding once its file is off the screen."""
    pane, fake = fake_video_pane(qtbot)
    pane.show_media(video_media(tmp_path))
    fake.stopped = False
    pane.show_media(build_media_file(make_image()))
    assert fake.stopped is True


# -- a video the backend cannot decode -------------------------------------


def test_playback_error_puts_the_reason_on_the_message_label(qtbot, tmp_path):
    """Without this the file is a black rectangle and nothing says why."""
    pane, fake = fake_video_pane(qtbot)
    pane.show_media(video_media(tmp_path))
    pane.report_playback_error(None, "Could not open file")
    assert pane.stack.currentWidget() is pane.message_label
    text = pane.message_label.text()
    assert "clip.mp4" in text
    assert "cannot be played" in text
    assert "Could not open file" in text


def test_playback_error_without_a_reason_still_explains(qtbot, tmp_path):
    """Qt does not always supply a string; an empty one must not read as a
    truncated message."""
    pane, fake = fake_video_pane(qtbot)
    pane.show_media(video_media(tmp_path))
    pane.report_playback_error(None, "")
    assert "could not decode" in pane.message_label.text()


def test_a_failed_video_keeps_no_controls_over_its_message(qtbot, tmp_path):
    """A play button over an error is dead chrome: pressing it does nothing."""
    pane, fake = fake_video_pane(qtbot)
    pane.show_media(video_media(tmp_path))
    pane.report_playback_error(None, "Could not open file")
    assert not pane.play_button.isVisibleTo(pane.controls_bar)
    assert not pane.controls_bar.isVisibleTo(pane)


def test_playback_error_before_any_file_does_not_raise(qtbot):
    """The signal can outlive the selection; it must still say something."""
    pane, fake = fake_video_pane(qtbot)
    pane.report_playback_error(None, "Could not open file")
    assert "Could not open file" in pane.message_label.text()


# -- the play button reflects the player -----------------------------------


def test_the_two_playback_glyphs_are_not_the_same_picture(qtbot):
    """Guards every icon assertion below: if play and pause rendered alike,
    they would all pass while the button never changed."""
    assert icon_bytes(icons.play()) != icon_bytes(icons.pause())


def test_play_button_shows_pause_while_the_video_plays(qtbot):
    pane, fake = fake_video_pane(qtbot)
    fake.playing = True
    pane.update_play_icon(None)
    assert icon_bytes(pane.play_button.icon()) == icon_bytes(icons.pause())


def test_play_button_shows_play_again_once_the_video_stops(qtbot):
    pane, fake = fake_video_pane(qtbot)
    fake.playing = True
    pane.update_play_icon(None)
    fake.playing = False
    pane.update_play_icon(None)
    assert icon_bytes(pane.play_button.icon()) == icon_bytes(icons.play())


def test_play_button_shows_play_when_there_is_no_player(qtbot):
    pane = make_pane(qtbot)
    pane.media_player = None
    assert icon_bytes(pane.playback_icon()) == icon_bytes(icons.play())


def test_a_theme_change_leaves_the_pause_glyph_on_a_playing_video(qtbot):
    """refresh_icons redraws every button from its factory. A fixed play icon
    there would put the play arrow back on a video that is playing."""
    pane, fake = fake_video_pane(qtbot)
    fake.playing = True
    pane.update_play_icon(None)
    pane.refresh_icons()
    assert icon_bytes(pane.play_button.icon()) == icon_bytes(icons.pause())


# -- favourite overlay star ------------------------------------------------


def test_favorite_star_hidden_until_media(qtbot):
    pane = make_pane(qtbot)
    assert pane.favorite_button.isHidden()


def test_favorite_star_shows_for_media_and_hides_for_none(qtbot, make_image):
    pane = make_pane(qtbot)
    pane.resize(300, 200)
    pane.show_media(build_media_file(make_image()))
    assert not pane.favorite_button.isHidden()
    pane.show_media(None)
    assert pane.favorite_button.isHidden()


def test_set_favorite_updates_star_icon(qtbot):
    pane = make_pane(qtbot)
    pane.set_favorite(True)
    assert pane.favorite_state is True
    assert not pane.favorite_button.icon().isNull()
    pane.set_favorite(False)
    assert pane.favorite_state is False


def test_star_click_emits_favorite_toggled(qtbot, make_image):
    pane = make_pane(qtbot)
    pane.show_media(build_media_file(make_image()))
    with qtbot.waitSignal(pane.favorite_toggled, timeout=1000):
        pane.favorite_button.click()


def test_resize_repositions_star(qtbot, make_image):
    pane = make_pane(qtbot)
    pane.show_media(build_media_file(make_image()))
    pane.resize(500, 400)
    # The star sits near the top-right corner.
    assert pane.favorite_button.x() > 400
    assert pane.favorite_button.y() < 60


# -- resolution overlay ----------------------------------------------------


def test_resolution_shown_for_image(qtbot, make_image):
    pane = make_pane(qtbot)
    pane.resize(300, 220)
    path = make_image("r.png", (128, 96), (10, 20, 30))
    pane.show_media(build_media_file(path))
    assert not pane.resolution_label.isHidden()
    assert pane.resolution_label.text() == "128 × 96"


def test_resolution_hidden_for_none_and_other(qtbot, tmp_path):
    pane = make_pane(qtbot)
    pane.show_media(None)
    assert pane.resolution_label.isHidden()

    notes = tmp_path / "notes.txt"
    notes.write_text("x")
    pane.show_media(build_media_file(notes))  # OTHER kind
    assert pane.resolution_label.isHidden()


def test_set_resolution_empty_hides(qtbot):
    pane = make_pane(qtbot)
    pane.set_resolution("640 × 480")
    assert not pane.resolution_label.isHidden()
    pane.set_resolution("")
    assert pane.resolution_label.isHidden()


# -- animated GIF and PDF preview ------------------------------------------


def gif_media(tmp_path, make_image):
    from myimages.video.gif import gif_from_frames

    frames = [make_image(f"g{i}.png", (60, 40), (i * 80, 100, 150)) for i in range(3)]
    dest = tmp_path / "anim.gif"
    gif_from_frames(frames, dest, fps=6)
    return build_media_file(dest)


def pdf_media(tmp_path):
    from PIL import Image

    from myimages.imaging.pdfbuilder import PdfOptions, build_pdf

    images = []
    for i in range(2):
        path = tmp_path / f"i{i}.png"
        Image.new("RGB", (80, 60), (i * 100, 120, 140)).save(path)
        images.append(path)
    dest = tmp_path / "doc.pdf"
    build_pdf(images, dest, PdfOptions())
    return build_media_file(dest)


def test_gif_plays_animated_with_resolution(qtbot, tmp_path, make_image):
    pane = make_pane(qtbot)
    pane.resize(200, 150)
    pane.show_media(gif_media(tmp_path, make_image))
    assert pane.stack.currentWidget() is pane.gif_label
    assert pane.gif_movie is not None
    assert pane.resolution_label.text() == "60 × 40"


def test_switching_away_stops_the_gif(qtbot, tmp_path, make_image):
    pane = make_pane(qtbot)
    pane.show_media(gif_media(tmp_path, make_image))
    assert pane.gif_movie is not None
    pane.show_media(None)
    assert pane.gif_movie is None


def test_scale_gif_is_safe_without_a_movie(qtbot):
    pane = make_pane(qtbot)
    pane.scale_gif()  # no gif loaded -> returns without raising


def test_pdf_document_is_previewed(qtbot, tmp_path):
    from myimages.gui.preview_pane import PDF_BACKEND_AVAILABLE

    media = pdf_media(tmp_path)
    assert media.kind is MediaKind.DOCUMENT
    pane = make_pane(qtbot)
    pane.show_media(media)
    if PDF_BACKEND_AVAILABLE:
        assert pane.stack.currentWidget() is pane.pdf_preview
    else:
        assert pane.stack.currentWidget() is pane.message_label


def test_pdf_message_when_backend_missing(qtbot, tmp_path):
    pane = make_pane(qtbot)
    pane.pdf_preview = None  # simulate the QtPdf module being unavailable
    (tmp_path / "d.pdf").write_bytes(b"%PDF-1.4")
    pane.show_media(build_media_file(tmp_path / "d.pdf"))
    assert pane.stack.currentWidget() is pane.message_label
    assert "QtPdf" in pane.message_label.text()


def test_pdf_preview_renders_reloads_and_resizes(qtbot, tmp_path):
    from myimages.gui.preview_pane import PDF_BACKEND_AVAILABLE, PdfPreview

    if not PDF_BACKEND_AVAILABLE:
        return
    view = PdfPreview()
    qtbot.addWidget(view)
    view.resize(420, 500)
    media = pdf_media(tmp_path)  # a 2-page PDF

    view.load(str(media.path))
    assert view.column.count() == 2  # one label per page

    view.load(str(media.path))  # reload re-runs clear_pages then render_pages
    assert view.column.count() == 2

    view.resize(720, 500)  # a wide-enough change triggers a re-render
    qtbot.wait(10)
    assert view.column.count() == 2


def test_pdf_preview_batches_large_documents(qtbot, tmp_path, make_image):
    from myimages.gui.preview_pane import PDF_BACKEND_AVAILABLE, PDF_PAGE_BATCH
    from myimages.imaging.pdfbuilder import PdfOptions, build_pdf

    if not PDF_BACKEND_AVAILABLE:
        return
    frames = [make_image(f"pg{i}.png", (60, 45), (i * 18, 90, 120)) for i in range(12)]
    dest = tmp_path / "many.pdf"
    build_pdf(frames, dest, PdfOptions(max_edge_px=300))

    pane = make_pane(qtbot)
    pane.resize(400, 500)
    pane.show_media(build_media_file(dest))
    view = pane.pdf_preview
    assert view.document.pageCount() == 12
    assert view.rendered_pages == PDF_PAGE_BATCH
    assert view.more_button is not None
    assert "4 remaining" in view.more_button.text()

    view.show_more()
    assert view.rendered_pages == 12
    assert view.more_button is None


def test_unreadable_pdf_shows_message(qtbot, tmp_path):
    from myimages.gui.preview_pane import PDF_BACKEND_AVAILABLE

    if not PDF_BACKEND_AVAILABLE:
        return
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"this is not a pdf")
    pane = make_pane(qtbot)
    pane.show_media(build_media_file(broken))
    assert pane.stack.currentWidget() is pane.message_label
    assert "Could not open" in pane.message_label.text()


def test_right_click_on_the_image_reports_screen_coordinates(qtbot, media_file):
    from PySide6.QtCore import QPoint

    pane = make_pane(qtbot)
    pane.resize(300, 200)
    pane.show_media(media_file)
    seen: list[QPoint] = []
    pane.context_menu_requested.connect(seen.append)

    pane.image_view.customContextMenuRequested.emit(QPoint(10, 10))

    assert len(seen) == 1
    # Mapped to the screen, so the window can open the menu without knowing
    # which of the stacked views was clicked.
    assert seen[0] == pane.image_view.mapToGlobal(QPoint(10, 10))


def test_every_stacked_view_relays_a_right_click(qtbot):
    from PySide6.QtCore import QPoint
    from PySide6.QtCore import Qt as QtCore

    pane = make_pane(qtbot)
    seen: list[QPoint] = []
    pane.context_menu_requested.connect(seen.append)

    views = [pane, pane.image_view, pane.gif_label]
    if pane.pdf_preview is not None:
        views.append(pane.pdf_preview)
    for view in views:
        assert view.contextMenuPolicy() == QtCore.ContextMenuPolicy.CustomContextMenu
        view.customContextMenuRequested.emit(QPoint(1, 1))

    assert len(seen) == len(views)


def test_the_viewing_controls_are_there_as_soon_as_a_picture_is(qtbot, make_image):
    """They do not wait to be discovered. A control that only appears once the
    pointer happens to cross it is one most people never find."""
    from myimages.core.media import build_media_file

    pane = PreviewPane()
    qtbot.addWidget(pane)
    pane.show_media(build_media_file(make_image()))
    # isVisibleTo rather than isVisible: the pane itself was never shown, and a
    # child of a hidden parent reports invisible whatever it was set to.
    assert pane.controls_bar.isVisibleTo(pane)


def test_nothing_appears_over_a_file_with_no_controls(qtbot):
    """A strip of dead buttons over an empty pane reads as a fault."""
    pane = PreviewPane()
    qtbot.addWidget(pane)
    pane.show_media(None)
    assert not pane.controls_bar.isVisibleTo(pane)


def test_the_controls_go_away_again_when_the_next_file_has_none(qtbot, make_image):
    """Moving from a photograph to a text file must take the zoom buttons with
    it, or they sit over the message enabled and inert."""
    from myimages.core.media import build_media_file

    pane = PreviewPane()
    qtbot.addWidget(pane)
    pane.show_media(build_media_file(make_image()))
    assert pane.controls_bar.isVisibleTo(pane)

    pane.show_media(None)
    assert not pane.controls_bar.isVisibleTo(pane)


def test_the_controls_and_the_resolution_badge_are_the_same_height(qtbot, make_image):
    """They float on the same edge of the same photograph. Two overlays of
    different heights there read as an accident rather than as a pair."""
    from myimages.core.media import build_media_file

    pane = PreviewPane()
    qtbot.addWidget(pane)
    pane.resize(600, 400)
    pane.show_media(build_media_file(make_image()))
    pane.resolution_label.setText("800 × 600")
    pane.resolution_label.show()
    pane.position_overlays()

    difference = abs(pane.controls_bar.height() - pane.resolution_label.height())
    assert difference <= 2, (
        f"controls {pane.controls_bar.height()}px "
        f"vs badge {pane.resolution_label.height()}px"
    )
