"""Tests for the inline image editor (myimages.gui.image_editor)."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

from myimages.core.media import build_media_file
from myimages.gui import crop_canvas as cc
from myimages.gui import image_editor as ie
from myimages.gui.image_editor import (
    ImageEditor,
    copy_destination,
    pixmap_from_pil,
)
from myimages.gui.task_runner import synchronous_runner
from myimages.imaging.transform import CropRect


def make_editor(qtbot):
    # The synchronous runner is not a convenience here: every test that reads
    # working_image or status_label straight after an operation would otherwise
    # be racing a worker thread.
    editor = ImageEditor(runner=synchronous_runner)
    qtbot.addWidget(editor)
    return editor


def media_from(make_image, name="photo.png", size=(80, 60)):
    return build_media_file(make_image(name, size, (30, 120, 180)))


def test_pixmap_from_pil_matches_size(qtbot):
    image = Image.new("RGB", (48, 24), (10, 20, 30))
    pixmap = pixmap_from_pil(image)
    assert not pixmap.isNull()
    assert pixmap.size().width() == 48
    assert pixmap.size().height() == 24


def test_copy_destination_avoids_clashes(tmp_path: Path):
    original = tmp_path / "shot.png"
    original.write_bytes(b"x")
    first = copy_destination(original)
    assert first.name == "shot_copy.png"

    first.write_bytes(b"x")
    second = copy_destination(original)
    assert second.name == "shot_copy2.png"


def test_load_sets_working_image_and_canvas(qtbot, make_image):
    editor = make_editor(qtbot)
    editor.load(media_from(make_image, size=(80, 60)))
    assert editor.working_image is not None
    assert editor.working_image.size == (80, 60)
    assert not editor.canvas.pixmap.isNull()


def test_rotate_swaps_dimensions(qtbot, make_image):
    editor = make_editor(qtbot)
    editor.load(media_from(make_image, size=(80, 60)))
    editor.rotate(90)
    assert editor.working_image is not None
    assert editor.working_image.size == (60, 80)


def test_rotate_before_load_is_a_noop(qtbot):
    editor = make_editor(qtbot)
    editor.rotate(90)  # working_image is None -> returns without raising
    assert editor.working_image is None


def test_apply_crop_crops_working_image(qtbot, make_image):
    editor = make_editor(qtbot)
    editor.load(media_from(make_image, size=(80, 60)))
    editor.canvas.selection = CropRect(10, 5, 40, 30)
    editor.apply_crop()
    assert editor.working_image is not None
    assert editor.working_image.size == (40, 30)


def test_apply_crop_without_selection_is_a_noop(qtbot, make_image):
    editor = make_editor(qtbot)
    editor.load(media_from(make_image, size=(80, 60)))
    editor.apply_crop()  # no selection -> unchanged
    assert editor.working_image is not None
    assert editor.working_image.size == (80, 60)


def test_aspect_buttons_lock_the_canvas(qtbot, make_image):
    editor = make_editor(qtbot)
    editor.load(media_from(make_image, size=(80, 60)))
    # The second aspect button is 1:1.
    square_button = editor.aspect_group.buttons()[1]
    square_button.click()
    assert editor.canvas.aspect == (1, 1)


def test_save_over_writes_and_emits_closed_true(qtbot, make_image):
    editor = make_editor(qtbot)
    media = media_from(make_image, size=(80, 60))
    editor.load(media)
    editor.canvas.selection = CropRect(0, 0, 40, 40)
    editor.apply_crop()

    with qtbot.waitSignal(editor.closed, timeout=1000) as blocker:
        editor.save_over()
    assert blocker.args == [True]
    assert Image.open(media.path).size == (40, 40)


def test_save_copy_writes_new_file(qtbot, make_image):
    editor = make_editor(qtbot)
    media = media_from(make_image, name="orig.png", size=(80, 60))
    editor.load(media)

    with qtbot.waitSignal(editor.closed, timeout=1000) as blocker:
        editor.save_copy()
    assert blocker.args == [True]
    assert (media.path.parent / "orig_copy.png").exists()


def test_cancel_emits_closed_false(qtbot, make_image):
    editor = make_editor(qtbot)
    editor.load(media_from(make_image))
    with qtbot.waitSignal(editor.closed, timeout=1000) as blocker:
        editor.cancel()
    assert blocker.args == [False]


def test_save_without_load_just_closes(qtbot):
    editor = make_editor(qtbot)
    with qtbot.waitSignal(editor.closed, timeout=1000) as blocker:
        editor.save_over()  # media_file is None -> nothing written, still closes
    assert blocker.args == [True]


def test_crop_disabled_until_selection(qtbot, make_image):
    editor = make_editor(qtbot)
    editor.load(media_from(make_image, size=(80, 60)))
    assert not editor.crop_button.isEnabled()
    assert not editor.clear_button.isEnabled()
    assert editor.size_label.text() == "No selection"


def test_selection_shows_pixel_size_and_enables_crop(qtbot, make_image):
    editor = make_editor(qtbot)
    editor.load(media_from(make_image, size=(80, 60)))
    editor.set_aspect((1, 1))
    rect = editor.canvas.selection_rect()
    assert rect is not None
    assert editor.size_label.text() == f"{rect.width} × {rect.height} px"
    assert editor.crop_button.isEnabled()
    assert editor.clear_button.isEnabled()


def test_clear_button_removes_selection(qtbot, make_image):
    editor = make_editor(qtbot)
    editor.load(media_from(make_image, size=(80, 60)))
    editor.set_aspect((1, 1))
    editor.clear_button.click()
    assert editor.canvas.selection_rect() is None
    assert editor.size_label.text() == "No selection"
    assert not editor.crop_button.isEnabled()


# -- mirroring and watermark removal ---------------------------------------


def test_flip_mirrors_the_working_image(qtbot, tmp_path):
    path = tmp_path / "asymmetric.png"
    picture = Image.new("RGB", (80, 60), (30, 120, 180))
    ImageDraw.Draw(picture).rectangle((0, 0, 20, 20), fill=(240, 40, 40))
    picture.save(path)

    editor = make_editor(qtbot)
    editor.load(build_media_file(path))
    original = editor.working_image.tobytes()

    editor.flip(True)
    assert editor.working_image.tobytes() != original
    editor.flip(True)  # mirroring back restores it exactly
    assert editor.working_image.tobytes() == original


def test_flip_before_load_is_a_noop(qtbot):
    editor = make_editor(qtbot)
    editor.flip(True)
    assert editor.working_image is None


def test_remove_watermark_clears_a_corner_emblem(qtbot, tmp_path):
    from PIL import Image, ImageDraw, ImageStat

    from myimages.core.media import build_media_file

    path = tmp_path / "marked.png"
    # Sized like a real photo: a small badge inside a roomy corner, which is
    # what the automatic search is tuned for.
    picture = Image.new("RGB", (800, 600), (46, 40, 36))
    ImageDraw.Draw(picture).ellipse((700, 520, 740, 552), fill=(215, 215, 215))
    picture.save(path)

    editor = make_editor(qtbot)
    editor.load(build_media_file(path))
    corner = (695, 515, 745, 557)
    assert ImageStat.Stat(editor.working_image.crop(corner)).mean[0] > 70

    editor.remove_watermark()

    assert editor.status_label.text() == "Watermark removed"
    assert ImageStat.Stat(editor.working_image.crop(corner)).mean[0] < 70
    assert editor.media_file is not None
    # Nothing is written until Save/Copy, so the file on disk is still marked.
    assert ImageStat.Stat(Image.open(path).crop(corner)).mean[0] > 70


def test_remove_watermark_reports_when_it_finds_nothing(qtbot, make_image):
    editor = make_editor(qtbot)
    editor.load(media_from(make_image, size=(120, 90)))  # a flat colour
    editor.remove_watermark()
    assert editor.status_label.text() == "No watermark found there"


def test_remove_watermark_uses_the_selection_when_one_is_drawn(qtbot, tmp_path):
    from PIL import Image, ImageDraw, ImageStat

    from myimages.core.media import build_media_file

    path = tmp_path / "middle.png"
    picture = Image.new("RGB", (300, 200), (46, 40, 36))
    ImageDraw.Draw(picture).ellipse((40, 40, 80, 80), fill=(215, 215, 215))
    picture.save(path)

    editor = make_editor(qtbot)
    editor.load(build_media_file(path))
    editor.canvas.selection = CropRect(20, 20, 100, 100)  # around the blob
    editor.remove_watermark()

    assert editor.status_label.text() == "Watermark removed"
    assert ImageStat.Stat(editor.working_image.crop((45, 45, 75, 75))).mean[0] < 100


def test_remove_watermark_before_load_is_a_noop(qtbot):
    editor = make_editor(qtbot)
    editor.remove_watermark()
    assert editor.working_image is None
    assert editor.status_label.text() == ""


def test_loading_a_file_clears_the_status(qtbot, make_image):
    editor = make_editor(qtbot)
    editor.load(media_from(make_image))
    editor.status_label.setText("Watermark removed")
    editor.load(media_from(make_image, name="other.png"))
    assert editor.status_label.text() == ""


def test_the_editor_buttons_say_what_they_write(qtbot):
    """ "Save" next to "Copy" gave no hint that one overwrites the original."""
    editor = make_editor(qtbot)
    assert editor.copy_button.text() == "Save as Copy"
    assert "Keep the original" in editor.copy_button.toolTip()
    assert "Overwrite" in editor.save_button.toolTip()


def test_the_tool_row_is_not_clipped_by_its_own_scrollbar(qtbot):
    """The horizontal scrollbar is drawn inside the fixed height."""
    editor = make_editor(qtbot)
    editor.resize(900, 700)
    area = editor.toolbar_area
    assert area.viewport().height() >= area.widget().sizeHint().height()


def test_reopening_the_editor_starts_at_the_left_of_the_tool_row(
    qtbot, make_image, tmp_path
):
    editor = make_editor(qtbot)
    editor.resize(500, 400)
    editor.load(media_from(make_image))
    bar = editor.toolbar_area.horizontalScrollBar()
    bar.setValue(bar.maximum())

    editor.load(media_from(make_image, "second.png"))

    assert bar.value() == 0


def test_the_readout_stays_on_screen_when_the_tools_scroll(qtbot, make_image):
    """Scrolling right to reach a button used to carry its own reply off-screen."""
    editor = make_editor(qtbot)
    editor.resize(600, 450)
    editor.show()
    editor.load(media_from(make_image))
    bar = editor.toolbar_area.horizontalScrollBar()
    bar.setValue(bar.maximum())

    editor.remove_watermark()

    assert editor.status_label.text()
    assert not editor.toolbar_area.isAncestorOf(editor.status_label)
    assert not editor.toolbar_area.isAncestorOf(editor.size_label)
    assert editor.status_label.visibleRegion().boundingRect().width() > 0


def test_load_reports_an_unreadable_file_and_keeps_nothing(
    qtbot, tmp_path: Path, silence_dialogs, monkeypatch
):
    """A file the decoder rejects must not leave half a state behind."""
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"not an image at all")
    media = build_media_file(broken)

    warned: list[str] = []
    monkeypatch.setattr(
        "myimages.gui.image_editor.QMessageBox.warning",
        staticmethod(lambda *a, **k: warned.append(a[1])),
    )
    editor = make_editor(qtbot)
    assert editor.load(media) is False
    assert editor.working_image is None
    assert editor.media_file is None
    assert warned == ["Cannot open image"]


def test_load_returns_true_for_a_readable_file(qtbot, make_image):
    editor = make_editor(qtbot)
    assert editor.load(media_from(make_image)) is True


def test_save_plan_keeps_the_format_for_an_opaque_edit(qtbot, make_image):
    editor = make_editor(qtbot)
    media = media_from(make_image, name="shot.jpg")
    editor.load(media)
    plan = editor.save_plan(copy=False)
    assert plan is not None
    assert plan.destination == Path(media.path)
    assert not plan.retargeted


def test_save_plan_diverts_a_transparent_result_to_a_sibling_png(qtbot, make_image):
    """The editor cannot produce alpha yet; the policy it delegates to can."""
    editor = make_editor(qtbot)
    media = media_from(make_image, name="shot.jpg")
    editor.load(media)
    editor.working_image = Image.new("RGBA", (8, 8), (1, 2, 3, 0))

    plan = editor.save_plan(copy=False)
    assert plan is not None
    assert plan.destination == Path(media.path).with_suffix(".png")
    assert plan.retargeted
    assert Path(media.path).exists()


def test_save_plan_is_none_with_nothing_open(qtbot):
    editor = make_editor(qtbot)
    assert editor.save_plan(copy=False) is None


def test_a_failed_save_is_reported_and_the_editor_stays_open(
    qtbot, make_image, monkeypatch
):
    """A write error must reach the user, not vanish into the event loop."""
    editor = make_editor(qtbot)
    editor.load(media_from(make_image))

    def explode(*args, **kwargs):
        raise OSError("disk is full")

    warned: list[str] = []
    monkeypatch.setattr("myimages.imaging.transform.save_image", explode)
    monkeypatch.setattr(
        "myimages.gui.image_editor.QMessageBox.warning",
        staticmethod(lambda *a, **k: warned.append(a[2])),
    )
    closed: list[bool] = []
    editor.closed.connect(closed.append)

    editor.save_over()
    assert closed == []
    assert warned == ["OSError: disk is full"]


def watermarked(make_image, name="mark.png"):
    """An image carrying a bright badge in its bottom-right corner."""
    path = make_image(name, (120, 90), (40, 60, 90))
    image = Image.open(path)
    draw = ImageDraw.Draw(image)
    draw.rectangle([92, 70, 116, 84], fill=(250, 250, 250))
    image.save(path)
    return build_media_file(path)


def test_the_editor_locks_its_controls_while_work_is_in_flight(qtbot, make_image):
    """A second press mid-operation would race the first on working_image."""
    editor = make_editor(qtbot)
    editor.load(watermarked(make_image))
    editor.canvas.selection_changed.emit(CropRect(0, 0, 20, 20))

    seen: list[bool] = []

    def capture_then_run(function, on_finished, on_failed=None):
        seen.append(editor.save_button.isEnabled())
        seen.append(editor.watermark_button.isEnabled())
        synchronous_runner(function, on_finished, on_failed)

    editor.runner = capture_then_run
    editor.remove_watermark()

    assert seen == [False, False]
    assert not editor.busy
    assert editor.save_button.isEnabled()
    assert editor.watermark_button.isEnabled()


def test_the_editor_unlocks_after_a_failed_operation(qtbot, make_image, monkeypatch):
    """The failure path has to release the controls too, or the editor is dead."""
    editor = make_editor(qtbot)
    editor.load(watermarked(make_image))
    monkeypatch.setattr(
        "myimages.gui.image_editor.QMessageBox.warning",
        staticmethod(lambda *a, **k: None),
    )
    monkeypatch.setattr(
        "myimages.imaging.watermark.remove_watermark",
        lambda *a, **k: (_ for _ in ()).throw(ValueError("inpaint exploded")),
    )
    editor.remove_watermark()

    assert not editor.busy
    assert editor.save_button.isEnabled()
    assert editor.watermark_button.isEnabled()


def test_remove_watermark_ignores_a_second_press_while_busy(qtbot, make_image):
    """Re-entrancy guard: the in-flight operation owns working_image."""
    editor = make_editor(qtbot)
    editor.load(watermarked(make_image))
    editor.busy = True
    calls: list[object] = []
    editor.runner = lambda *a, **k: calls.append(a)

    editor.remove_watermark()
    assert calls == []


# -- cut-out mode ----------------------------------------------------------


def test_entering_cutout_mode_swaps_which_controls_are_shown(qtbot, make_image):
    """The row already only fits by scrolling, so the modes must not stack."""
    editor = make_editor(qtbot)
    editor.load(media_from(make_image))
    editor.show()

    assert editor.crop_button.isVisible()
    assert not editor.wand_button.isVisible()

    editor.set_mode("cutout")
    assert not editor.crop_button.isVisible()
    assert editor.wand_button.isVisible()
    assert editor.cutout_mode_button.isChecked()

    editor.set_mode("crop")
    assert editor.crop_button.isVisible()
    assert not editor.wand_button.isVisible()


def test_load_resets_the_mode_between_files(qtbot, make_image):
    """Opening a second file in cut-out mode would inherit the first's tools."""
    editor = make_editor(qtbot)
    editor.load(media_from(make_image, name="one.png"))
    editor.set_mode("cutout")
    editor.arm_tool("wand")

    editor.load(media_from(make_image, name="two.png"))
    assert editor.mode == "crop"
    assert editor.active_tool is None
    assert editor.edits == []


def test_arming_the_same_tool_twice_disarms_it(qtbot, make_image):
    editor = make_editor(qtbot)
    editor.load(media_from(make_image))
    editor.set_mode("cutout")

    editor.arm_tool("erase")
    assert editor.active_tool == "erase"
    assert editor.canvas.interaction == "paint"

    editor.arm_tool("erase")
    assert editor.active_tool is None
    assert not editor.eraser_button.isChecked()


def test_the_wand_needs_arming_before_a_click_counts(qtbot, make_image):
    editor = make_editor(qtbot)
    editor.load(media_from(make_image))
    editor.set_mode("cutout")

    editor.on_point_picked(0.5, 0.5)
    assert editor.edits == []

    editor.arm_tool("wand")
    editor.on_point_picked(0.5, 0.5)
    assert len(editor.edits) == 1


def test_a_drag_becomes_one_stroke_holding_every_dab(qtbot, make_image):
    """Undo steps back a gesture, so the dabs of one drag are a single entry."""
    editor = make_editor(qtbot)
    editor.load(media_from(make_image))
    editor.set_mode("cutout")
    editor.arm_tool("erase")

    editor.on_stroke(0.2, 0.5, True)
    editor.on_stroke(0.3, 0.5, False)
    editor.on_stroke(0.4, 0.5, False)

    assert len(editor.edits) == 1
    # More than the three events: the gaps between them are filled in, or the
    # stroke would be three separate circles.
    assert len(editor.edits[0].dabs) >= 3

    editor.on_stroke(0.8, 0.5, True)
    assert len(editor.edits) == 2


def test_undo_drops_the_last_edit_and_says_so_when_empty(qtbot, make_image):
    editor = make_editor(qtbot)
    editor.load(media_from(make_image))
    editor.set_mode("cutout")
    editor.arm_tool("wand")
    editor.on_point_picked(0.5, 0.5)

    editor.undo_edit()
    assert editor.edits == []

    editor.undo_edit()
    assert editor.status_label.text() == "Nothing to undo"


def test_save_names_the_png_it_will_write_over_a_jpeg(qtbot, make_image):
    """The button closes the editor, so it has to be honest before the click."""
    editor = make_editor(qtbot)
    media = media_from(make_image, name="shot.jpg")
    editor.load(media)
    assert editor.save_button.text() == "Save"

    editor.set_mode("cutout")
    editor.arm_tool("wand")
    editor.on_point_picked(0.5, 0.5)

    assert editor.save_button.text() == "Save as PNG"
    assert "shot.png" in editor.save_button.toolTip()

    plan = editor.save_plan(copy=False)
    assert plan is not None and plan.destination.name == "shot.png"


def test_save_keeps_its_name_when_the_format_can_hold_alpha(qtbot, make_image):
    editor = make_editor(qtbot)
    editor.load(media_from(make_image, name="shot.png"))
    editor.set_mode("cutout")
    editor.arm_tool("wand")
    editor.on_point_picked(0.5, 0.5)
    assert editor.save_button.text() == "Save"


def test_saving_a_cutout_writes_a_transparent_file_at_full_size(
    qtbot, make_image, tmp_path
):
    """Only the save touches full resolution; the preview is a smaller copy."""
    editor = make_editor(qtbot)
    media = media_from(make_image, name="shot.png", size=(120, 90))
    editor.load(media)
    editor.set_mode("cutout")
    editor.arm_tool("wand")
    editor.on_point_picked(0.5, 0.5)

    editor.save_over()
    written = Image.open(media.path)
    assert written.size == (120, 90)
    assert written.convert("RGBA").getchannel("A").getextrema()[0] == 0


def test_soften_scales_with_the_image_so_preview_and_export_agree(qtbot, make_image):
    """A fixed pixel radius would export a harder edge than the one approved."""
    editor = make_editor(qtbot)
    editor.load(media_from(make_image))
    editor.soften = 4
    small = Image.new("RGB", (400, 300))
    large = Image.new("RGB", (1600, 1200))
    assert editor.soften_pixels(large) == 4 * editor.soften_pixels(small)


def test_compare_shows_the_untouched_picture_while_held(qtbot, make_image):
    editor = make_editor(qtbot)
    editor.load(media_from(make_image))
    editor.set_mode("cutout")
    editor.arm_tool("wand")
    editor.on_point_picked(0.5, 0.5)
    edited = editor.canvas.pixmap.toImage()

    editor.set_comparing(True)
    assert editor.canvas.pixmap.toImage() != edited

    editor.set_comparing(False)
    assert editor.canvas.pixmap.toImage() == edited


def test_the_backdrop_button_cycles_through_every_backdrop(qtbot, make_image):
    editor = make_editor(qtbot)
    editor.load(media_from(make_image))
    seen = []
    for _ in range(len(cc.BACKDROPS) + 1):
        seen.append(editor.canvas.backdrop)
        editor.cycle_backdrop()
    assert seen[: len(cc.BACKDROPS)] == list(cc.BACKDROPS)
    assert seen[-1] == seen[0]


def test_the_steppers_stay_inside_their_ranges(qtbot, make_image):
    editor = make_editor(qtbot)
    editor.load(media_from(make_image))
    editor.set_mode("cutout")

    for _ in range(40):
        editor.step_tolerance(-1)
    assert editor.tolerance == 0
    for _ in range(40):
        editor.step_tolerance(1)
    assert editor.tolerance == 120

    for _ in range(20):
        editor.step_brush(-1)
    assert editor.brush_index == 0
    for _ in range(20):
        editor.step_brush(1)
    assert editor.brush_index == len(ie.BRUSH_STEPS) - 1

    for _ in range(20):
        editor.step_soften(1)
    assert editor.soften == 8
    assert editor.soften_label.text() == "8"


def test_a_wand_click_that_takes_everything_says_so(qtbot, make_image):
    """A tolerance too high for the picture is the common first mistake."""
    editor = make_editor(qtbot)
    editor.load(media_from(make_image))
    editor.set_mode("cutout")
    editor.arm_tool("wand")
    editor.tolerance = 120
    editor.on_point_picked(0.5, 0.5)
    assert "lower Tolerance" in editor.status_label.text()


def test_cutout_handlers_do_nothing_before_a_file_is_open(qtbot):
    """Every one of them is reachable from a stale click after Cancel."""
    editor = make_editor(qtbot)
    editor.build_preview_source()
    editor.refresh_cutout()
    editor.set_comparing(True)
    editor.report_coverage()
    assert editor.preview_source is None
    assert editor.edits == []
    assert editor.result_image() is None


def test_a_modest_wand_click_reports_what_it_cleared(qtbot, tmp_path: Path):
    """The fixture image is one flat colour, so a wand there always takes all."""
    path = tmp_path / "halves.png"
    picture = Image.new("RGB", (120, 90), (200, 30, 30))
    picture.paste((30, 30, 200), (60, 0, 120, 90))
    picture.save(path)

    editor = make_editor(qtbot)
    editor.load(build_media_file(path))
    editor.set_mode("cutout")
    editor.arm_tool("wand")
    editor.tolerance = 8
    editor.on_point_picked(0.25, 0.5)
    assert editor.status_label.text().endswith("% cleared")


def test_a_stroke_is_ignored_when_no_brush_is_armed(qtbot, make_image):
    editor = make_editor(qtbot)
    editor.load(media_from(make_image))
    editor.set_mode("cutout")
    editor.arm_tool("wand")
    editor.on_stroke(0.5, 0.5, True)
    assert editor.edits == []


def test_a_quick_drag_is_filled_in_rather_than_left_dotted(qtbot, make_image):
    """Three sparse pointer events must become a stroke, not three circles."""
    editor = make_editor(qtbot)
    editor.load(media_from(make_image, size=(400, 300)))
    editor.set_mode("cutout")
    editor.arm_tool("erase")

    editor.on_stroke(0.1, 0.5, True)
    editor.on_stroke(0.5, 0.5, False)
    editor.on_stroke(0.9, 0.5, False)

    assert len(editor.edits) == 1
    assert len(editor.edits[0].dabs) > 3
