"""Erase a logo or emblem from a photo and fill the hole with its surroundings.

Generators and cameras stamp a small mark, almost always into a corner. Removing
it is two separate problems: deciding *which pixels* belong to the mark, and
inventing plausible pixels to put back.

Detection compares the area against a heavily blurred copy of itself. A mark is
a hard-edged shape sitting on top of whatever the photo shows, so it stands out
sharply from that local average while the photo's own gentle gradients do not.
The resulting core is then grown generously, because a semi-transparent mark
fades into a halo that is too faint to threshold but far too bright to leave
behind -- filling from contaminated edges is exactly what produces the tell-tale
glow where a watermark used to be.

The fill repeatedly blurs the picture and restores every pixel outside the mask,
which pulls colour inward from the clean rim a little further on each pass.
Working coarse-to-fine reproduces long gradients first and detail last, and
because Pillow does the blurring in C the whole thing stays fast without pulling
in a numerical stack. The trade-off is honest: the filled patch is smooth, so it
disappears on gradients and skies but cannot invent film grain or texture.
"""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageStat

# A mark has to differ from its local average by at least this much (0-255 per
# channel) to count. Low enough to catch a grey emblem on a dark background,
# high enough that sensor noise and film grain never register.
DETECTION_THRESHOLD = 16

# How far the detected core is grown, as a fraction of the shorter edge of the
# searched area. This is what swallows a semi-transparent mark's halo.
GROWTH_FRACTION = 0.14

# Where to look when the caller does not say: the bottom-right corner, which is
# where practically every generator puts its badge.
CORNER_WIDTH_FRACTION = 0.22
CORNER_HEIGHT_FRACTION = 0.14

# Refuse to "clean" an area that is mostly mask: that means detection latched
# onto the picture itself, and filling it would smear the photo.
MAXIMUM_COVERAGE = 0.6

# Blur radii used to close the hole, as fractions of the growth size, coarsest
# first so broad gradients are recreated before fine variation.
BLUR_FACTORS = (0.75, 0.55, 0.4, 0.28, 0.2, 0.14, 0.1, 0.07)
PASSES_PER_RADIUS = 6


@dataclass(frozen=True)
class WatermarkResult:
    """The cleaned image plus how much of the searched area was repainted."""

    image: Image.Image
    covered_fraction: float
    found: bool


def corner_box(width: int, height: int) -> tuple[int, int, int, int]:
    """The bottom-right area to search when the caller gives no region."""
    box_width = max(8, round(width * CORNER_WIDTH_FRACTION))
    box_height = max(8, round(height * CORNER_HEIGHT_FRACTION))
    return (width - box_width, height - box_height, width, height)


def growth_size(region: Image.Image) -> int:
    """An odd dilation size proportional to the area being searched.

    Scaling with the region keeps behaviour identical whether the mark sits in a
    400-pixel snapshot or a 4000-pixel render; ``MaxFilter`` also insists on an
    odd size of at least three.
    """
    span = min(region.width, region.height)
    size = max(3, round(span * GROWTH_FRACTION))
    return size if size % 2 else size + 1


def blur_schedule(growth: int) -> tuple[int, ...]:
    """Coarse-to-fine blur radii sized to the hole that has to be closed."""
    return tuple(max(2, round(growth * factor)) for factor in BLUR_FACTORS)


def fill_enclosed(mask: Image.Image) -> Image.Image:
    """Add any gap the mask completely surrounds.

    A solid mark only registers at its edges, because its interior matches its
    own local average exactly as well as a flat sky does. Flooding the
    background inwards from the border and keeping whatever the flood cannot
    reach recovers that interior, which is what lets the fill converge instead
    of leaving a pale ghost in the middle of a large emblem.
    """
    padded = Image.new("L", (mask.width + 2, mask.height + 2), 0)
    padded.paste(mask, (1, 1))
    outside = padded.copy()
    ImageDraw.floodfill(outside, (0, 0), 255)
    enclosed = outside.point(lambda value: 0 if value == 255 else 255)
    joined = ImageChops.lighter(padded, enclosed)
    return joined.crop((1, 1, mask.width + 1, mask.height + 1))


def detect_mask(
    region: Image.Image, threshold: int = DETECTION_THRESHOLD
) -> Image.Image:
    """Mark the pixels that look pasted on top of ``region``.

    White means "repaint this". The comparison is against a blurred copy of the
    region rather than a fixed colour, so the same threshold works on a dark
    fabric and a bright sky.
    """
    grown = growth_size(region)
    background = region.filter(ImageFilter.GaussianBlur(max(4, grown // 3)))
    difference = ImageChops.difference(region.convert("RGB"), background.convert("RGB"))
    core = difference.convert("L").point(lambda value: 255 if value > threshold else 0)
    return fill_enclosed(core.filter(ImageFilter.MaxFilter(grown)))


def coverage(mask: Image.Image) -> float:
    """The fraction of ``mask`` that is set, i.e. how much would be repainted."""
    return float(ImageStat.Stat(mask).mean[0]) / 255.0


def inpaint(region: Image.Image, mask: Image.Image) -> Image.Image:
    """Fill the masked pixels of ``region`` with colour drawn from around them."""
    known = region.convert("RGB")
    filled = known
    for radius in blur_schedule(growth_size(region)):
        for _ in range(PASSES_PER_RADIUS):
            filled = Image.composite(
                filled.filter(ImageFilter.GaussianBlur(radius)), known, mask
            )
    return filled


def remove_watermark(
    image: Image.Image,
    box: tuple[int, int, int, int] | None = None,
    threshold: int = DETECTION_THRESHOLD,
) -> WatermarkResult:
    """Return ``image`` with the mark in ``box`` (or the bottom-right) painted out.

    Passing an explicit ``box`` is how a user points at a mark the automatic
    corner search would miss. When nothing convincing is found -- or when the
    "mark" turns out to cover most of the area, which means detection failed --
    the original image is handed back untouched rather than damaged.
    """
    target = box or corner_box(image.width, image.height)
    region = image.crop(target)
    if region.width < 3 or region.height < 3:
        return WatermarkResult(image.copy(), 0.0, False)

    mask = detect_mask(region, threshold)
    covered = coverage(mask)
    if covered <= 0.0 or covered > MAXIMUM_COVERAGE:
        return WatermarkResult(image.copy(), covered, False)

    cleaned = image.copy()
    patch = inpaint(region, mask)
    if cleaned.mode == "RGBA":
        patch = patch.convert("RGB")
        cleaned.paste(patch, target[:2])
    else:
        cleaned.paste(patch.convert(cleaned.mode), target[:2])
    return WatermarkResult(cleaned, covered, True)
