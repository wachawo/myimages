"""Tests for :mod:`myimages.imaging.watermark`.

The interesting behaviour is visual, so the tests build pictures whose expected
outcome is unambiguous: a bright emblem painted onto a smooth gradient must
disappear (the area ends up as smooth as its neighbours), while a picture with
no emblem must come back untouched.
"""

from __future__ import annotations

from PIL import Image, ImageDraw, ImageStat

from myimages.imaging import watermark


def gradient(width: int = 400, height: int = 300) -> Image.Image:
    """A smooth dark background, the easy case an inpaint must handle perfectly."""
    image = Image.new("RGB", (width, height))
    pixels = image.load()
    assert pixels is not None
    for y in range(height):
        for x in range(width):
            shade = 40 + (x * 20) // width + (y * 15) // height
            pixels[x, y] = (shade, shade - 5, shade - 10)
    return image


def with_emblem(image: Image.Image) -> Image.Image:
    """Paint a bright four-pointed mark into the bottom-right corner."""
    marked = image.copy()
    draw = ImageDraw.Draw(marked)
    centre_x, centre_y = int(image.width * 0.87), int(image.height * 0.93)
    draw.polygon(
        [
            (centre_x, centre_y - 18),
            (centre_x + 7, centre_y),
            (centre_x, centre_y + 18),
            (centre_x - 7, centre_y),
        ],
        fill=(200, 200, 200),
    )
    return marked


def corner_spread(image: Image.Image) -> float:
    """How much the bottom-right corner varies; an emblem spikes this."""
    return float(
        ImageStat.Stat(image.crop(watermark.corner_box(*image.size))).stddev[0]
    )


# -- geometry and helpers --------------------------------------------------


def test_corner_box_sits_in_the_bottom_right():
    left, top, right, bottom = watermark.corner_box(1000, 800)
    assert (right, bottom) == (1000, 800)
    assert 0 < left < 1000 and 0 < top < 800
    assert right - left == round(1000 * watermark.CORNER_WIDTH_FRACTION)


def test_corner_box_stays_usable_on_a_tiny_image():
    left, top, right, bottom = watermark.corner_box(20, 12)
    assert right - left >= 8 and bottom - top >= 8


def test_growth_size_is_odd_and_scales_with_the_region():
    small = watermark.growth_size(Image.new("RGB", (40, 30)))
    large = watermark.growth_size(Image.new("RGB", (400, 300)))
    assert small % 2 == 1 and large % 2 == 1
    assert small >= 3
    assert large > small  # a bigger area needs a bigger dilation


def test_blur_schedule_runs_coarse_to_fine():
    radii = watermark.blur_schedule(41)
    assert radii == tuple(sorted(radii, reverse=True))
    assert min(radii) >= 2


def test_coverage_reports_the_masked_fraction():
    blank = Image.new("L", (10, 10), 0)
    full = Image.new("L", (10, 10), 255)
    assert watermark.coverage(blank) == 0.0
    assert watermark.coverage(full) == 1.0


# -- detection -------------------------------------------------------------


def test_detect_mask_finds_the_emblem_and_ignores_a_clean_gradient():
    clean = gradient()
    marked = with_emblem(clean)
    box = watermark.corner_box(*marked.size)

    on_mark = watermark.coverage(watermark.detect_mask(marked.crop(box)))
    on_clean = watermark.coverage(watermark.detect_mask(clean.crop(box)))

    assert on_mark > 0.02  # the emblem and its surroundings are flagged
    assert on_clean < 0.005  # a smooth gradient is left alone


# -- removal ---------------------------------------------------------------


def test_removal_erases_the_emblem():
    marked = with_emblem(gradient())
    before = corner_spread(marked)

    result = watermark.remove_watermark(marked)

    assert result.found is True
    assert 0 < result.covered_fraction < watermark.MAXIMUM_COVERAGE
    # The corner is now as uniform as the gradient it sits on.
    assert corner_spread(result.image) < before / 3


def test_removal_leaves_a_clean_photo_alone():
    clean = gradient()
    result = watermark.remove_watermark(clean)
    assert result.found is False
    assert result.image.tobytes() == clean.tobytes()


def test_removal_refuses_a_busy_area_instead_of_smearing_it():
    """Detection latching onto the picture itself must not repaint the photo."""
    noisy = Image.effect_noise((300, 220), 90).convert("RGB")
    result = watermark.remove_watermark(noisy)
    assert result.found is False
    assert result.image.tobytes() == noisy.tobytes()


def brightness(image: Image.Image, box: tuple[int, int, int, int]) -> float:
    return float(ImageStat.Stat(image.crop(box)).mean[0])


def test_removal_honours_an_explicit_box():
    """A caller can point at a mark the corner search would never look at."""
    clean = gradient()
    marked = clean.copy()
    ImageDraw.Draw(marked).ellipse((30, 30, 70, 70), fill=(210, 210, 210))
    box = (10, 10, 110, 110)
    middle = (40, 40, 60, 60)  # deep inside the blob, the hardest place to fill

    result = watermark.remove_watermark(marked, box)

    assert result.found is True
    # The repainted middle must land near the background it replaced, not keep
    # a pale ghost of the blob.
    assert brightness(marked, middle) > 200  # the blob really was bright
    assert abs(brightness(result.image, middle) - brightness(clean, middle)) < 30


def test_a_solid_mark_is_filled_all_the_way_through():
    """A solid shape only registers at its edges; its interior must be recovered.

    Without closing the mask the fill leaves a pale ghost exactly in the middle
    of a large emblem, which is the most visible failure this tool can have.
    """
    region = Image.new("RGB", (120, 120), (50, 45, 40))
    ImageDraw.Draw(region).rectangle((40, 40, 80, 80), fill=(220, 220, 220))
    edges_only = watermark.detect_mask(region)
    centre = (58, 58, 62, 62)

    # The closed mask covers the interior that the raw edge detection misses.
    assert watermark.coverage(edges_only.crop(centre)) == 1.0

    filled = watermark.inpaint(region, edges_only)
    assert brightness(filled, centre) < 100  # no bright ghost left behind


def test_fill_enclosed_closes_a_ring_but_leaves_open_shapes_alone():
    ring = Image.new("L", (60, 60), 0)
    ImageDraw.Draw(ring).ellipse((10, 10, 50, 50), outline=255, width=4)
    closed = watermark.fill_enclosed(ring)
    assert watermark.coverage(closed) > watermark.coverage(ring)
    assert closed.getpixel((30, 30)) == 255  # the hole in the middle is now set

    stroke = Image.new("L", (60, 60), 0)
    ImageDraw.Draw(stroke).line((0, 30, 59, 30), fill=255, width=4)
    assert watermark.coverage(watermark.fill_enclosed(stroke)) == watermark.coverage(
        stroke
    )


def test_removal_keeps_an_alpha_channel_intact():
    marked = with_emblem(gradient()).convert("RGBA")
    result = watermark.remove_watermark(marked)
    assert result.found is True
    assert result.image.mode == "RGBA"
    assert result.image.size == marked.size


def test_removal_on_a_grayscale_image_keeps_its_mode():
    marked = with_emblem(gradient()).convert("L")
    result = watermark.remove_watermark(marked)
    assert result.image.mode == "L"


def test_a_region_too_small_to_judge_is_returned_untouched():
    tiny = Image.new("RGB", (4, 4), (10, 20, 30))
    result = watermark.remove_watermark(tiny, (0, 0, 2, 2))
    assert result.found is False
    assert result.covered_fraction == 0.0
