"""Separate a subject from its background by hand, with Pillow alone.

Two tools, deliberately dumb ones. The wand takes a point and clears every
connected pixel whose colour is within a tolerance of it; the brushes clear or
restore circles the user drags over. Neither knows what a subject is, so both
work on a product shot against a sweep and both fail on hair against foliage —
that is what the model in :mod:`myimages.imaging.segment` is for. These stay
because they are instant, need no download, and are how you fix the edge the
model got wrong.

The important structure here is that an edit is *geometry, not pixels*. Every
edit is recorded as normalised coordinates and the whole list is folded into a
single alpha mask on demand, against the untouched original. That buys three
things at once: undo is dropping the last entry, the preview and the exported
file run the same code so they cannot drift, and a mask computed for a
screen-sized preview reproduces exactly at full resolution.

Coordinates are normalised to the image's own dimensions — positions against
width and height, brush radii against width — so the same list applies to any
scale of the same picture. Radii use width rather than the diagonal on purpose:
the diagonal makes a circle drawn on a wide crop come back the wrong size.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from PIL import Image, ImageChops, ImageDraw, ImageFilter

# Two fill colours for the region trick below. Any two distinct colours work;
# these are chosen to be far from anything a photograph is likely to contain.
FIRST_SENTINEL = (255, 0, 255)
SECOND_SENTINEL = (0, 255, 0)

# A brush dab is never allowed to vanish entirely on a small preview.
MINIMUM_RADIUS = 1.0

# How far apart consecutive dabs may sit, as a share of the brush radius. Half a
# radius makes the circles overlap, which is what turns a row of dots into a
# stroke.
DAB_SPACING = 0.5

# A floor on that spacing, as a fraction of the image width, so the smallest
# brush cannot turn one long drag into an unbounded list of dabs.
MINIMUM_DAB_STEP = 0.002

# Fully opaque and fully clear, as alpha values.
OPAQUE = 255
CLEAR = 0


@dataclass(frozen=True)
class RegionPick:
    """One wand click: the connected patch of similar colour around a point.

    ``x`` and ``y`` are fractions of width and height. ``tolerance`` is the
    per-channel distance, in 0-255, that still counts as the same colour.
    """

    x: float
    y: float
    tolerance: int


@dataclass(frozen=True)
class BrushStroke:
    """One press-drag-release of the eraser, or of the restore brush.

    A stroke holds every dab it laid down so undo steps back a whole gesture
    rather than a single mouse-move. Each dab is ``(x, y, radius)`` with the
    position against width and height and the radius against width.
    """

    dabs: tuple[tuple[float, float, float], ...]
    restore: bool


@dataclass(frozen=True)
class SubjectMask:
    """One background-removal run, kept at the resolution the model produced.

    The other two edits are geometry and re-derive their pixels from whatever
    image the list is folded against. A model result cannot: ISNet's input is a
    fixed 1024 square, so its answer is always exactly those pixels. Storing
    that square preserves the property the list actually depends on -- one
    record serving the preview fold and the full-resolution export fold -- at
    the cost of one megabyte held in memory until Undo drops it.

    ``scaled`` is a memo, not state. Re-stretching a 1024 square to preview size
    costs about ten milliseconds, which is affordable once and not affordable on
    every pointer move of a brush drag. It is excluded from equality so two
    records holding the same mask compare equal whatever either has been
    stretched to.
    """

    mask: Image.Image
    scaled: dict[tuple[int, int], Image.Image] = field(
        default_factory=dict, compare=False, repr=False
    )

    def at(self, size: tuple[int, int]) -> Image.Image:
        """The stored square stretched to ``size``, un-squashing the aspect."""
        cached = self.scaled.get(size)
        if cached is not None:
            return cached
        # Only one size is ever wanted at a time: the editor alternates between
        # the preview and, once, the full-resolution save.
        self.scaled.clear()
        stretched = self.mask.resize(size, Image.Resampling.LANCZOS)
        self.scaled[size] = stretched
        return stretched


Edit = RegionPick | BrushStroke | SubjectMask


def pixel_position(x: float, y: float, size: tuple[int, int]) -> tuple[int, int]:
    """Turn a normalised point into a pixel inside the image bounds."""
    width, height = size
    column = min(width - 1, max(0, round(x * width)))
    row = min(height - 1, max(0, round(y * height)))
    return column, row


def changed_pixels(filled: Image.Image, original: Image.Image) -> Image.Image:
    """A 0/255 mask of every pixel the flood fill actually altered.

    The per-band maximum rather than a greyscale conversion: converting to ``L``
    averages the channels, so a difference of one in a single channel rounds
    away and the region gets a ragged hole in it.
    """
    difference = ImageChops.difference(filled, original)
    red, green, blue = difference.split()
    strongest = ImageChops.lighter(ImageChops.lighter(red, green), blue)
    return strongest.point(lambda value: OPAQUE if value > 0 else CLEAR)


def region_mask(image: Image.Image, pick: RegionPick) -> Image.Image:
    """A mask of the connected patch of similar colour around ``pick``.

    Pillow's flood fill works in place and reports nothing, so the region has to
    be recovered by comparing before and after. Doing that once is a trap: if
    the region already happens to be the fill colour, nothing changes and the
    mask comes back empty. Filling twice with different colours and taking the
    union means a pixel can match at most one of them, so every pixel in the
    region registers in one comparison or the other.
    """
    rgb = image.convert("RGB")
    seed = pixel_position(pick.x, pick.y, rgb.size)

    first = rgb.copy()
    ImageDraw.floodfill(first, seed, FIRST_SENTINEL, thresh=pick.tolerance)
    second = rgb.copy()
    ImageDraw.floodfill(second, seed, SECOND_SENTINEL, thresh=pick.tolerance)

    return ImageChops.lighter(changed_pixels(first, rgb), changed_pixels(second, rgb))


def paint_stroke(mask: Image.Image, stroke: BrushStroke) -> None:
    """Draw one stroke's dabs into ``mask``, clearing or restoring."""
    draw = ImageDraw.Draw(mask)
    width, height = mask.size
    value = OPAQUE if stroke.restore else CLEAR
    for x, y, radius in stroke.dabs:
        centre_x = x * width
        centre_y = y * height
        pixels = max(MINIMUM_RADIUS, radius * width)
        draw.ellipse(
            [
                centre_x - pixels,
                centre_y - pixels,
                centre_x + pixels,
                centre_y + pixels,
            ],
            fill=value,
        )


def bridge_dabs(
    start: tuple[float, float, float],
    end: tuple[float, float, float],
    aspect: float,
) -> tuple[tuple[float, float, float], ...]:
    """The dabs to lay between two pointer positions, ``start`` excluded.

    Pointer events arrive when the system feels like it, which on a quick drag is
    every several dozen pixels; one dab per event draws a dotted line rather than
    a stroke. ``start`` is left out because the caller has already laid it, so
    consecutive calls chain without doubling up on the joins.

    ``aspect`` is the image's height over its width. Without it the spacing would
    be measured in a space where a vertical step counts the same as a horizontal
    one, and a stroke down a wide crop would come out dotted while the same
    stroke across it was solid.
    """
    step = max(end[2] * DAB_SPACING, MINIMUM_DAB_STEP)
    span_x = end[0] - start[0]
    span_y = end[1] - start[1]
    distance = math.hypot(span_x, span_y * aspect)
    if distance <= step:
        return (end,)
    count = math.ceil(distance / step)
    return tuple(
        (
            start[0] + span_x * index / count,
            start[1] + span_y * index / count,
            end[2],
        )
        for index in range(1, count + 1)
    )


def build_mask(
    image: Image.Image, edits: Iterable[Edit], soften: float = 0.0
) -> Image.Image:
    """Fold an ordered edit list into one alpha mask for ``image``.

    Every edit is measured against the untouched original, so the order matters
    only where the edits overlap: a restore stroke after an erase brings those
    pixels back, which is the whole point of keeping the list rather than
    painting into the picture.
    """
    mask = Image.new("L", image.size, OPAQUE)
    for edit in edits:
        if isinstance(edit, RegionPick):
            mask = ImageChops.subtract(mask, region_mask(image, edit))
        elif isinstance(edit, SubjectMask):
            mask = ImageChops.multiply(mask, edit.at(image.size))
        else:
            paint_stroke(mask, edit)
    if soften > 0:
        mask = mask.filter(ImageFilter.GaussianBlur(soften))
    return mask


def apply_edits(
    image: Image.Image, edits: Sequence[Edit], soften: float = 0.0
) -> Image.Image:
    """Return an RGBA copy of ``image`` with the edit list's areas cleared.

    Any transparency the source already carried is kept: the mask multiplies
    the existing alpha rather than replacing it, so re-editing a cut-out does
    not resurrect pixels an earlier pass removed.
    """
    rgba = image.convert("RGBA")
    mask = build_mask(rgba, edits, soften)
    result = rgba.copy()
    result.putalpha(ImageChops.multiply(rgba.getchannel("A"), mask))
    return result


def coverage_fraction(image: Image.Image) -> float:
    """How much of the image is not fully opaque, from 0 to 1.

    The interface uses this to notice that a wand click took nearly everything,
    which is what happens when the subject and the background are too close in
    colour for the tolerance in force.
    """
    if image.mode not in {"RGBA", "LA"}:
        return 0.0
    histogram = image.getchannel("A").histogram()
    return (sum(histogram) - histogram[OPAQUE]) / sum(histogram)
