"""Tests for the hand cut-out engine (myimages.imaging.cutout).

No Qt, no numpy, no assets, no network: this module is pure Pillow, and its
whole reason for existing is that the preview and the exported file are produced
by the same call.
"""

from __future__ import annotations

from PIL import Image

from myimages.imaging import cutout


def two_tone(width: int, height: int) -> Image.Image:
    """Left half red, right half blue, with a hard edge between them."""
    image = Image.new("RGB", (width, height), (200, 30, 30))
    image.paste((30, 30, 200), (width // 2, 0, width, height))
    return image


def clear_fraction(image: Image.Image) -> float:
    """The share of pixels that ended up fully transparent."""
    histogram = image.getchannel("A").histogram()
    return histogram[0] / sum(histogram)


def opaque_count(image: Image.Image) -> int:
    """How many pixels are still fully opaque."""
    return image.getchannel("A").histogram()[255]


def test_the_same_edits_produce_the_same_result_at_any_size():
    """The failure that yields a perfect preview and a wrong exported file.

    Edits are stored normalised precisely so a mask computed against a
    screen-sized preview reproduces at full resolution. Radii normalise to
    width; against the diagonal instead, this fails on a non-square image.
    """
    edits: list[cutout.Edit] = [
        cutout.RegionPick(x=0.25, y=0.5, tolerance=20),
        cutout.BrushStroke(dabs=((0.75, 0.5, 0.1),), restore=False),
    ]
    small = cutout.apply_edits(two_tone(400, 300), edits)
    large = cutout.apply_edits(two_tone(1600, 1200), edits)

    assert abs(clear_fraction(small) - clear_fraction(large)) < 0.01


def test_a_wand_click_clears_the_half_it_landed_on():
    """The basic case: a flat background against a flat subject."""
    result = cutout.apply_edits(
        two_tone(80, 60), [cutout.RegionPick(x=0.25, y=0.5, tolerance=20)]
    )
    assert result.getpixel((10, 30))[3] == 0
    assert result.getpixel((70, 30))[3] == 255
    assert abs(clear_fraction(result) - 0.5) < 0.02


def test_a_region_already_the_sentinel_colour_is_still_found():
    """The only justification for filling twice; simplify it away and this fails.

    A single flood fill reports a region by what it changed, so a region that is
    already exactly the fill colour changes nothing and comes back empty.
    """
    image = Image.new("RGB", (40, 20), (30, 30, 200))
    image.paste(cutout.FIRST_SENTINEL, (0, 0, 20, 20))

    mask = cutout.region_mask(image, cutout.RegionPick(x=0.1, y=0.5, tolerance=10))
    assert mask.getpixel((5, 10)) == 255
    assert mask.getpixel((35, 10)) == 0


def test_an_empty_edit_list_leaves_the_image_fully_opaque():
    result = cutout.apply_edits(two_tone(40, 30), [])
    assert opaque_count(result) == 40 * 30
    assert cutout.coverage_fraction(result) == 0.0


def test_a_restore_stroke_brings_back_what_an_erase_stroke_took():
    """Order matters where edits overlap; that is why the list is kept."""
    erase = cutout.BrushStroke(dabs=((0.5, 0.5, 0.2),), restore=False)
    restore = cutout.BrushStroke(dabs=((0.5, 0.5, 0.2),), restore=True)

    erased = cutout.apply_edits(two_tone(80, 60), [erase])
    restored = cutout.apply_edits(two_tone(80, 60), [erase, restore])

    assert erased.getpixel((40, 30))[3] == 0
    assert restored.getpixel((40, 30))[3] == 255
    assert opaque_count(restored) == 80 * 60


def test_softening_takes_pixels_off_the_fully_opaque_count():
    """A softened edge is partial alpha, which is neither clear nor opaque."""
    edits: list[cutout.Edit] = [
        cutout.BrushStroke(dabs=((0.5, 0.5, 0.2),), restore=False)
    ]
    hard = cutout.apply_edits(two_tone(80, 60), edits)
    soft = cutout.apply_edits(two_tone(80, 60), edits, soften=3.0)

    assert opaque_count(soft) < opaque_count(hard)
    assert 0 < clear_fraction(soft) < clear_fraction(hard)


def test_existing_transparency_survives_a_second_pass():
    """Re-editing a cut-out must not resurrect pixels an earlier pass removed."""
    already = cutout.apply_edits(
        two_tone(80, 60), [cutout.RegionPick(x=0.25, y=0.5, tolerance=20)]
    )
    again = cutout.apply_edits(
        already, [cutout.BrushStroke(dabs=((0.75, 0.5, 0.05),), restore=False)]
    )
    assert again.getpixel((10, 30))[3] == 0
    assert again.getpixel((60, 30))[3] == 0


def test_a_restore_stroke_cannot_invent_alpha_the_source_never_had():
    """Restoring over an already-transparent source leaves it transparent."""
    source = Image.new("RGBA", (40, 30), (10, 20, 30, 0))
    result = cutout.apply_edits(
        source, [cutout.BrushStroke(dabs=((0.5, 0.5, 0.5),), restore=True)]
    )
    assert result.getpixel((20, 15))[3] == 0


def test_a_dab_never_shrinks_to_nothing_on_a_small_preview():
    """A radius that rounds below a pixel would make the brush do nothing."""
    result = cutout.apply_edits(
        two_tone(40, 30),
        [cutout.BrushStroke(dabs=((0.5, 0.5, 0.0001),), restore=False)],
    )
    assert clear_fraction(result) > 0


def test_a_stroke_records_every_dab_of_one_gesture():
    """Undo steps back a gesture, so a drag is one entry holding many dabs."""
    drag = cutout.BrushStroke(
        dabs=tuple((0.2 + i * 0.1, 0.5, 0.05) for i in range(6)), restore=False
    )
    result = cutout.apply_edits(two_tone(120, 60), [drag])
    assert result.getpixel((24, 30))[3] == 0
    assert result.getpixel((84, 30))[3] == 0


def test_pixel_position_stays_inside_the_image():
    """Normalised coordinates arrive from a widget and can sit on the edge."""
    assert cutout.pixel_position(0.0, 0.0, (40, 30)) == (0, 0)
    assert cutout.pixel_position(1.0, 1.0, (40, 30)) == (39, 29)
    assert cutout.pixel_position(-0.5, 2.0, (40, 30)) == (0, 29)


def test_coverage_fraction_reports_how_much_was_taken():
    result = cutout.apply_edits(
        two_tone(80, 60), [cutout.RegionPick(x=0.25, y=0.5, tolerance=20)]
    )
    assert abs(cutout.coverage_fraction(result) - 0.5) < 0.02


def test_coverage_fraction_of_an_image_without_alpha_is_zero():
    assert cutout.coverage_fraction(Image.new("RGB", (10, 10))) == 0.0


def test_a_sparse_drag_comes_out_solid_rather_than_dotted():
    """Without bridging, the brush lays separate circles and looks broken.

    Pointer events on a quick drag arrive dozens of pixels apart. Measured on an
    800px image with the default radius, three raw events produced three
    separate blobs; bridging them has to leave exactly one.
    """
    image = Image.new("RGB", (800, 200), (200, 30, 30))
    radius = 0.02
    raw = [(0.1, 0.5, radius), (0.35, 0.5, radius), (0.6, 0.5, radius)]

    dabs = [raw[0]]
    for point in raw[1:]:
        dabs.extend(cutout.bridge_dabs(dabs[-1], point, 200 / 800))

    result = cutout.apply_edits(
        image, [cutout.BrushStroke(dabs=tuple(dabs), restore=False)]
    )
    row = [result.getpixel((x, 100))[3] for x in range(800)]
    blobs = sum(
        1 for x, alpha in enumerate(row) if alpha == 0 and (x == 0 or row[x - 1] != 0)
    )
    assert blobs == 1


def test_bridge_dabs_leaves_a_short_step_alone():
    """A slow drag already arrives dense; bridging must not multiply it."""
    assert cutout.bridge_dabs((0.5, 0.5, 0.1), (0.51, 0.5, 0.1), 1.0) == (
        (0.51, 0.5, 0.1),
    )


def test_bridge_dabs_ends_exactly_on_the_point_it_was_given():
    """The last dab must be the pointer's real position, not an interpolation."""
    bridged = cutout.bridge_dabs((0.0, 0.0, 0.02), (0.9, 0.0, 0.02), 1.0)
    assert bridged[-1] == (0.9, 0.0, 0.02)
    assert len(bridged) > 1


def test_bridge_dabs_measures_the_gap_in_the_image_it_is_drawn_on():
    """Off-square, a vertical step covers fewer pixels than a horizontal one.

    Ignoring that would make a stroke down a wide crop dotted while the same
    stroke across it came out solid.
    """
    wide = cutout.bridge_dabs((0.0, 0.0, 0.02), (0.0, 1.0, 0.02), 0.25)
    square = cutout.bridge_dabs((0.0, 0.0, 0.02), (0.0, 1.0, 0.02), 1.0)
    assert len(wide) < len(square)


def test_bridge_dabs_stays_bounded_for_the_smallest_brush():
    """A radius near zero must not turn one drag into an unbounded list."""
    bridged = cutout.bridge_dabs((0.0, 0.5, 0.0), (1.0, 0.5, 0.0), 1.0)
    assert len(bridged) <= 1 / cutout.MINIMUM_DAB_STEP + 1
