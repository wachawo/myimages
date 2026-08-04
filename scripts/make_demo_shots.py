#!/usr/bin/env python3
"""Render the screenshots the README shows, with no display and no photographs.

Two halves. The first paints a folder of sample pictures with Pillow alone:
there is no stock photography in this repository, and a gallery of flat coloured
rectangles would make the application look like a toy. The second drives the
real application over that folder under the offscreen Qt platform and grabs the
window, so every pixel of interface in the result was drawn by the code that
ships.

Usage: ``python scripts/make_demo_shots.py`` — it writes ``demo/*.png``.

Everything is deterministic: the same command produces the same bytes, so a
regenerated screenshot only turns up in ``git status`` when the interface really
did change.
"""

from __future__ import annotations

import os
import random
import shutil
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps

if TYPE_CHECKING:  # pragma: no cover - these need the Qt environment in place
    from PySide6.QtWidgets import QApplication, QWidget

    from myimages.gui.duplicates_dialog import DuplicatesDialog
    from myimages.gui.image_editor import ImageEditor
    from myimages.gui.main_window import MainWindow

Colour = tuple[int, int, int]
Stop = tuple[float, Colour]
Size = tuple[int, int]

# A scene is painted from a size, a seed for its detail, and a framing position
# in 0..1. The seed alone is not enough: seeds drawn from a continuous range
# collide, and two sea sunsets whose horizons landed within half a percent of
# each other are one photograph printed twice as far as anybody looking at the
# gallery — or the duplicate finder — is concerned. The framing is therefore
# spread deliberately across each family instead of left to luck.
Scene = Callable[[Size, int, float], Image.Image]

GRID_COLUMNS = 3

# What the duplicate finder is set to out of the box. Two samples that are not
# meant to be a pair have to stay further apart than this, or the screenshot
# shows the application offering to delete photographs that differ.
DEFAULT_DISTANCE = 5

# How far each family's framing travels from its first member to its last: the
# horizon of a sunset, the skyline of a range, the share of a dune frame given
# to sky. They live together because they are one decision — these are what
# keeps the samples far enough apart for check_samples_distinct to pass, and
# tuning one in isolation tends to push another pair together.
SEA_HORIZON = (0.26, 0.62)
MOUNTAIN_SKYLINE = (0.42, 0.58)
DUNE_SKYLINE = (0.03, 0.42)

# Rendered at 2x so the text is legible, then filed down to a width GitHub can
# show without the browser resampling it into mush.
SCALE_FACTOR = "2"
OUTPUT_WIDTH = 1600

# WebP rather than PNG. These four came to 4.0 MB as PNG, and every refresh adds
# that again to the history permanently; at quality 95 they come to 0.77 MB and
# the hardest case for a lossy codec — a screenshot's text — is indistinguishable
# from the PNG at 2x zoom. GitHub renders WebP in a README. Going back is this
# constant and the four names in main().
SHOT_SUFFIX = ".webp"
SHOT_QUALITY = 95

# Where the sample folder is built, and what the folder box is told to say.
#
# The application prints the paths it was given — the duplicate finder lists
# them in full — so the scratch directory would end up on show in the README.
# The run therefore happens *inside* the working directory and opens the folder
# by this relative path, which is what those lists then read. Only the box at
# the top is substituted, and only by the same path under a home directory.
GALLERY_FOLDER = Path("Pictures") / "2026-05 travel"
DISPLAY_FOLDER = f"~/{GALLERY_FOLDER}"

LANDSCAPE: Size = (1600, 1067)
PORTRAIT: Size = (1067, 1600)
STUDIO: Size = (1400, 1050)

# How long the event loop may spin waiting for the thumbnail workers.
THUMBNAIL_TIMEOUT = 20.0

# The duplicate finder is grabbed on its own and placed over the window, so its
# width is ours to choose: wide enough that no path is elided, narrow enough to
# leave the gallery behind it recognisable. Its height is grown to fit whatever
# the scan found, plus this much slack below the last row.
DUPLICATES_WIDTH = 820
DUPLICATES_MARGIN = 6


def output_dir() -> Path:
    """Where the screenshots land: this folder when it is ``demo``, else its
    sibling of that name."""
    here = Path(__file__).resolve().parent
    return here if here.name == "demo" else here.parent / "demo"


# -- painting helpers -------------------------------------------------------
#
# Everything below works on whole images through Pillow's own operations. A
# per-pixel Python loop over a 1600x1067 frame costs seconds; a resize, a
# composite and a point-lookup cost milliseconds and say the same thing.


def lerp(one: float, two: float, position: float) -> float:
    """Interpolate between two numbers."""
    return one + (two - one) * position


def mix(one: Colour, two: Colour, position: float) -> Colour:
    """Blend two colours."""
    return (
        round(lerp(one[0], two[0], position)),
        round(lerp(one[1], two[1], position)),
        round(lerp(one[2], two[2], position)),
    )


def sample_ramp(stops: list[Stop], steps: int = 256) -> list[Colour]:
    """Flatten a multi-stop colour ramp into ``steps`` evenly spaced colours."""
    ordered = sorted(stops, key=lambda stop: stop[0])
    colours: list[Colour] = []
    for index in range(steps):
        position = index / (steps - 1)
        low, high = ordered[0], ordered[-1]
        for first, second in zip(ordered, ordered[1:], strict=False):
            if first[0] <= position <= second[0]:
                low, high = first, second
                break
        span = max(high[0] - low[0], 1e-6)
        colours.append(mix(low[1], high[1], (position - low[0]) / span))
    return colours


def vertical_gradient(size: Size, stops: list[Stop]) -> Image.Image:
    """A smooth top-to-bottom gradient, built as a 1px strip and stretched.

    Photographs hardly ever contain a flat area of colour: skies, walls and
    studio sweeps all fall off across the frame. Making a gradient the base of
    every scene is the cheapest way to stay out of the poster-art register.
    """
    colours = sample_ramp(stops)
    strip = Image.new("RGB", (1, len(colours)))
    strip.putdata(colours)
    return strip.resize(size, Image.Resampling.BICUBIC)


def value_noise(size: Size, cells: Size, seed: int) -> Image.Image:
    """Smooth grey noise, upsampled from a tiny random grid."""
    rng = random.Random(seed)
    small = Image.new("L", cells)
    small.putdata([rng.randrange(256) for index in range(cells[0] * cells[1])])
    return small.resize(size, Image.Resampling.BICUBIC)


def fractal_noise(size: Size, octaves: int, seed: int, base: int = 3) -> Image.Image:
    """Sum octaves of value noise into a cloud-like field."""
    field = value_noise(size, (base, max(2, base * size[1] // size[0])), seed)
    weight = 0.5
    for octave in range(1, octaves):
        cells_x = base * (2**octave)
        cells = (cells_x, max(2, cells_x * size[1] // size[0]))
        field = Image.blend(
            field, value_noise(size, cells, seed + octave * 977), weight
        )
        weight *= 0.62
    return field


def ridge_profile(width: int, seed: int, roughness: float) -> list[float]:
    """A 1-D fractal height profile in 0..1 for a mountain or dune silhouette.

    Midpoint displacement rather than a sum of sines: a horizon made of sines
    reads as a wave, and what says "landscape" is self-similar detail — a big
    shape carrying smaller ones that carry smaller ones still.
    """
    rng = random.Random(seed)
    points = [rng.random(), rng.random()]
    amplitude = roughness
    for octave in range(6):
        refined: list[float] = []
        for index in range(len(points) - 1):
            middle = (points[index] + points[index + 1]) / 2
            refined.append(points[index])
            refined.append(middle + rng.uniform(-1.0, 1.0) * amplitude)
        refined.append(points[-1])
        points = refined
        amplitude *= 0.5
    low, high = min(points), max(points)
    span = max(high - low, 1e-6)
    scaled = [(value - low) / span for value in points]

    profile: list[float] = []
    for x in range(width):
        position = x * (len(scaled) - 1) / max(width - 1, 1)
        left = int(position)
        right = min(left + 1, len(scaled) - 1)
        profile.append(lerp(scaled[left], scaled[right], position - left))
    return profile


def grain(image: Image.Image, amount: float, seed: int) -> Image.Image:
    """Overlay fine luminance noise.

    Grain is the strongest "this came out of a camera" cue there is: a perfectly
    clean gradient is something only software makes. Two uniform draws are
    averaged into a triangular distribution, close enough to film and — unlike
    Pillow's own noise generator — dependent on nothing but the seed.
    """
    count = image.width * image.height
    rng = random.Random(seed)
    first = Image.frombytes("L", image.size, rng.randbytes(count))
    second = Image.frombytes("L", image.size, rng.randbytes(count))
    noise = Image.blend(first, second, 0.5).point(
        lambda value: round(128 + (value - 128) * amount)
    )
    return ImageChops.overlay(image, Image.merge("RGB", (noise, noise, noise)))


def vignette(image: Image.Image, strength: float) -> Image.Image:
    """Darken the corners, the way a real lens does."""
    mask = Image.radial_gradient("L").resize(image.size, Image.Resampling.BILINEAR)
    falloff = mask.point(lambda value: round(255 - value * strength))
    return Image.composite(image, Image.new("RGB", image.size, (0, 0, 0)), falloff)


def bloom(
    image: Image.Image, threshold: int, radius: float, amount: float
) -> Image.Image:
    """Bleed light out of the highlights, as a bright scene does through glass."""
    keep = image.convert("L").point(lambda value: 255 if value > threshold else 0)
    highlights = Image.composite(image, Image.new("RGB", image.size), keep)
    spread = highlights.filter(ImageFilter.GaussianBlur(radius))
    return Image.blend(image, ImageChops.screen(image, spread), amount)


def silhouette_mask(
    size: Size, profile: list[float], base_y: float, amplitude: float
) -> Image.Image:
    """Fill everything below a height profile: one ridge, one dune, one hill."""
    mask = Image.new("L", size, 0)
    outline = [(x, base_y - profile[x] * amplitude) for x in range(size[0])]
    ImageDraw.Draw(mask).polygon([*outline, (size[0], size[1]), (0, size[1])], fill=255)
    return mask


def paste_masked(
    scene: Image.Image, patch: Image.Image, mask: Image.Image, at: tuple[int, int]
) -> None:
    """Composite ``patch`` into ``scene`` through ``mask`` at a pixel offset."""
    box = (at[0], at[1], at[0] + patch.width, at[1] + patch.height)
    scene.paste(Image.composite(patch, scene.crop(box), mask), at)


# -- the scenes -------------------------------------------------------------


def bokeh_lights(size: Size, seed: int, variant: float) -> Image.Image:
    """Night lights thrown out of focus: soft discs over a dark graded field.

    The most convincing of the set, because an out-of-focus photograph is one of
    the few things whose real appearance is genuinely this simple — bright
    circles with a brighter rim, overlapping, over almost nothing.

    ``variant`` opens the aperture: further along the family the discs are
    larger and fewer, which is what a longer lens or a nearer subject does.
    """
    width, height = size
    rng = random.Random(seed)
    scene = vertical_gradient(
        size,
        [
            (0.0, (10, 12, 26)),
            (0.55, (22, 20, 40)),
            (1.0, mix((44, 26, 34), (26, 34, 48), rng.random())),
        ],
    )
    palette = [
        (255, 196, 120),
        (255, 148, 96),
        (140, 190, 255),
        (255, 232, 190),
        (196, 148, 255),
    ]
    sprite = Image.new("L", (256, 256), 0)
    pen = ImageDraw.Draw(sprite)
    pen.ellipse((6, 6, 250, 250), fill=190)
    pen.ellipse((6, 6, 250, 250), outline=255, width=14)
    sprite = sprite.filter(ImageFilter.GaussianBlur(9))

    for index in range(round(lerp(88, 40, variant))):
        radius = round(rng.uniform(0.02, 0.09 + 0.10 * variant) * width)
        centre_x = round(rng.uniform(-0.05, 1.05) * width)
        centre_y = round(rng.uniform(-0.05, 1.05) * height)
        alpha = rng.uniform(0.18, 0.85)
        disc = sprite.resize((radius * 2, radius * 2), Image.Resampling.BILINEAR)
        disc = disc.point(lambda value, level=alpha: round(value * level))
        patch = Image.new("RGB", disc.size, rng.choice(palette))
        paste_masked(scene, patch, disc, (centre_x - radius, centre_y - radius))

    scene = bloom(scene, 150, width * 0.03, 0.6)
    return grain(vignette(scene, 0.45), 0.10, seed)


def mountain_ridges(size: Size, seed: int, variant: float) -> Image.Image:
    """Ridges receding into mist under a graded sky.

    Depth is carried by atmospheric perspective — every further ridge is lighter
    and closer to the sky's own colour — and by a band of mist in each valley.
    Both are things a camera records and neither costs anything to fake.
    """
    width, height = size
    rng = random.Random(seed)
    warmth = rng.random()
    # Where the furthest ridge meets the sky. Held fixed, as it once was, the
    # mountain photographs differed only in colour and a perceptual hash could
    # not tell one from another. The range stops well short of the bottom of the
    # frame: pushed lower the picture becomes a dark strip under an empty sky,
    # which is neither a photograph anybody would keep nor, to a coarse
    # fingerprint, distinguishable from a sunset.
    skyline = lerp(*MOUNTAIN_SKYLINE, variant)
    # Daylight, the whole family. These used to be shot at dusk like everything
    # else in the folder, and a dark sky over a lit band over dark ground *is* a
    # sunset: the app's own perceptual hash put a mountain photograph five bits
    # from a photograph of the sea, close enough for it to offer to delete one
    # of them. Daylight inverts the frame — bright above, dark below — and a
    # folder in which every landscape was taken at golden hour was the least
    # convincing thing about the set anyway.
    scene = vertical_gradient(
        size,
        [
            (0.0, mix((56, 104, 174), (78, 120, 172), warmth)),
            (max(0.02, skyline - 0.30), mix((142, 180, 214), (158, 186, 208), warmth)),
            (max(0.04, skyline - 0.02), (210, 224, 232)),
            (1.0, (194, 206, 214)),
        ],
    )
    clouds = fractal_noise(size, 5, seed + 11, base=4)
    upper = vertical_gradient(
        size, [(0.0, (255, 255, 255)), (0.55, (60, 60, 60)), (1.0, (0, 0, 0))]
    ).convert("L")
    cloud_mask = ImageChops.multiply(
        clouds.point(lambda value: max(0, value - 120) * 2), upper
    )
    scene = Image.composite(Image.new("RGB", size, (255, 232, 208)), scene, cloud_mask)

    # A broad bloom of haze where the light comes from, rather than a disc. The
    # sun is up and out of frame in these, so what a lens gives you is a bright
    # quarter of sky, not a ball sitting on a ridge.
    glare_x = round(width * rng.uniform(0.25, 0.78))
    glare = Image.new("L", size, 0)
    ImageDraw.Draw(glare).ellipse(
        (
            glare_x - width * 0.16,
            height * (skyline - 0.34),
            glare_x + width * 0.16,
            height * (skyline - 0.02),
        ),
        fill=190,
    )
    scene = Image.composite(
        Image.new("RGB", size, (244, 248, 252)),
        scene,
        glare.filter(ImageFilter.GaussianBlur(width * 0.075)),
    )

    layers = 5
    for index in range(layers):
        depth = index / (layers - 1)
        profile = ridge_profile(width, seed + index * 31, 0.55 - depth * 0.2)
        # From the skyline down to the bottom of the frame, whatever the skyline
        # is. Packed into a narrow strip — which is what a fixed 0.16 span did
        # once the skyline was allowed to move up — everything below the nearest
        # ridge came out as a featureless dark band, which is what a landscape
        # looks like when it is composed by arithmetic rather than by somebody
        # standing there.
        base_y = height * lerp(skyline, min(0.94, skyline + 0.36), depth)
        mask = silhouette_mask(size, profile, base_y, height * (0.17 + depth * 0.15))
        rock = Image.new("RGB", size, mix((60, 64, 86), (176, 172, 190), 1.0 - depth))
        texture = fractal_noise(size, 4, seed + 400 + index, base=7).point(
            lambda value: round(132 + value * 0.45)
        )
        rock = ImageChops.multiply(
            rock, Image.merge("RGB", (texture, texture, texture))
        )
        scene = Image.composite(rock, scene, mask)

        valley = vertical_gradient(
            size,
            [
                (0.0, (0, 0, 0)),
                (max(0.0, base_y / height - 0.06), (0, 0, 0)),
                (min(1.0, base_y / height + 0.03), (255, 255, 255)),
                (1.0, (0, 0, 0)),
            ],
        ).convert("L")
        mist = ImageChops.multiply(
            mask.filter(ImageFilter.GaussianBlur(height * 0.045)), valley
        ).point(lambda value, level=depth: round(value * (0.75 - 0.55 * level)))
        haze = Image.new("RGB", size, mix((222, 234, 242), (206, 214, 232), depth))
        scene = Image.composite(haze, scene, mist)

    # High, because a daylight sky already sits near where the old threshold
    # was and would otherwise halo across the whole top of the frame.
    scene = bloom(scene, 244, width * 0.02, 0.45)
    return grain(vignette(scene, 0.26), 0.09, seed)


def desert_dunes(size: Size, seed: int, variant: float) -> Image.Image:
    """Sand ridges under a low sun: lit crests, flanks falling into shadow.

    Every dune is shaded relative to its *own* crest rather than to the frame,
    which is what puts a ridge line in the picture. An earlier version graded
    each band across the whole height, and the result was a stack of soft
    horizontal stripes that read at thumbnail size as a blank orange rectangle.

    The horizon and the time of day move with ``variant``, the number of dunes
    and their slant with the seed, for the same reason: with all of them fixed,
    every dune photograph came out the same picture in a different colour, the
    gallery showed four interchangeable tiles, and the duplicate finder —
    correctly, on the evidence it had — called them duplicates.
    """
    width, height = size
    rng = random.Random(seed)
    # From a frame that is nearly all sand to one with a third of it sky.
    skyline = lerp(*DUNE_SKYLINE, variant)
    warmth = rng.random()
    # The half of the family with the most sky in it is shot at dusk, which is
    # when anybody would bother including that much sky. The difference is not
    # decoration: at noon a pale sky sits over mid sand, at dusk a dark sky sits
    # over lit crests, so the two invert which half of the frame is the bright
    # one. That is the largest fact about the picture and the first thing a
    # coarse fingerprint reads, so holding it constant was most of what made
    # every dune photograph here a duplicate of every other.
    dusk = variant >= 0.5
    if dusk:
        # No bright line along the horizon, on purpose. A dark sky with a lit
        # band under it is a *sunset*, and one of these came out four bits from
        # a picture of the sea for exactly that reason. At dusk in a desert the
        # sand keeps the light and the sky is simply darker than it.
        sky_stops = [
            (0.0, mix((38, 44, 88), (52, 44, 80), warmth)),
            (max(0.0, skyline - 0.05), mix((112, 88, 126), (134, 96, 106), warmth)),
            (skyline, mix((186, 140, 112), (172, 128, 104), warmth)),
            (1.0, mix((92, 56, 48), (74, 48, 52), warmth)),
        ]
    else:
        sky_stops = [
            (0.0, mix((96, 150, 208), (146, 170, 198), warmth)),
            (max(0.0, skyline - 0.05), mix((206, 214, 214), (240, 206, 170), warmth)),
            (skyline, mix((238, 198, 148), (212, 168, 118), warmth)),
            (1.0, mix((150, 92, 52), (124, 76, 60), warmth)),
        ]
    scene = vertical_gradient(size, sky_stops)
    count = rng.randrange(5, 9)
    # How hard the ridges run downhill across the frame. A dune crest lies at an
    # angle to the camera far more often than it lies level, and the slant is
    # also the biggest thing in the picture, so it carries most of what makes
    # one of these different from the next.
    tilt = rng.uniform(-0.75, 0.75)
    for index in range(count):
        depth = index / max(count - 1, 1)
        fractal = ridge_profile(width, seed + index * 71, rng.uniform(0.30, 0.62))
        slope = tilt * (0.3 + 0.7 * depth)
        profile = [
            value + slope * (x / max(width - 1, 1) - 0.5)
            for x, value in enumerate(fractal)
        ]
        base_y = height * (skyline + 0.03 + depth * (0.99 - skyline))
        relief = height * (0.05 + depth * 0.24)
        mask = silhouette_mask(size, profile, base_y, relief)
        # Haze lightens what is far away, so the near dunes are the warmer and
        # deeper ones — but only so far. Taken further the foreground went dark,
        # and a frame that is dark at the bottom, bright across the middle and
        # dark at the top is a picture of a sunset as far as an 8x8 fingerprint
        # is concerned, whatever it is a picture of.
        crest = mix((248, 216, 164), (216, 152, 98), depth)
        if dusk:
            # Warm and still bright. A dusk frame wants the sand to hold the
            # light and the sky to be the dark half — two broad bands. Deepen
            # these shadows and the sand breaks into light and dark stripes,
            # which averages out to a picture whose fingerprint is a sunset's.
            crest = mix(crest, (252, 190, 128), 0.4)
        depth_of_shade = (0.32, 0.10) if dusk else (0.42, 0.16)
        shadow = mix(crest, (64, 36, 30), depth_of_shade[0] + depth_of_shade[1] * depth)
        top = (base_y - relief) / height
        # Bright along the crest, dark down the flank behind it, recovering
        # toward the next crest: the two-tone break is the whole reason a dune
        # reads as a solid shape instead of as a change of colour.
        band = vertical_gradient(
            size,
            [
                (0.0, crest),
                (max(0.0, top), crest),
                (min(1.0, top + 0.055 + 0.06 * depth), shadow),
                (1.0, mix(shadow, crest, 0.4)),
            ],
        )
        scene = Image.composite(band, scene, mask)

    # Wind ripples: noise stretched wide and flat, multiplied in below the
    # horizon only, so the sky stays clean the way an empty sky is.
    ripple = value_noise(size, (24, 170), seed + 909).filter(
        ImageFilter.GaussianBlur(1.5)
    )
    sand_only = vertical_gradient(
        size,
        [
            (0.0, (0, 0, 0)),
            (skyline, (0, 0, 0)),
            (min(1.0, skyline + 0.05), (255, 255, 255)),
            (1.0, (255, 255, 255)),
        ],
    ).convert("L")
    shading = ripple.point(lambda value: round(218 + value * 0.15))
    textured = ImageChops.multiply(scene, Image.merge("RGB", (shading,) * 3))
    scene = Image.composite(textured, scene, sand_only)
    return grain(vignette(scene, 0.28), 0.09, seed)


def sea_sunset(size: Size, seed: int, variant: float) -> Image.Image:
    """A low sun over water, its reflection broken up by the swell.

    The reflection is horizontally smeared noise inside a widening cone, and it
    does more for the picture than the sky above it: a mirror-flat highlight
    reads as a diagram, and every eye knows what water does to a light.
    """
    width, height = size
    rng = random.Random(seed)
    # Spread across the frame, not drawn at random. Left to a random draw inside
    # a narrow range, two of these landed within half a percent of each other,
    # every sunset put its bright band in the same row of an 8x8 fingerprint,
    # and the duplicate finder read five different photographs as one.
    horizon = round(height * lerp(*SEA_HORIZON, variant))
    level = horizon / height
    key = lerp(1.0, 0.55, variant)
    lift = lerp(0.0, 0.085, variant)
    scene = vertical_gradient(
        size,
        [
            (0.0, mix((28, 44, 90), (12, 18, 44), 1.0 - key)),
            (level * 0.45, mix((96, 92, 148), (44, 46, 88), 1.0 - key)),
            (level * 0.78, mix((212, 130, 116), (120, 74, 92), 1.0 - key)),
            (level - 0.01, mix((255, 198, 126), (190, 122, 92), 1.0 - key)),
            (level + 0.002, mix((236, 164, 104), (150, 96, 84), 1.0 - key)),
            (min(1.0, level + 0.36), mix((92, 76, 102), (44, 38, 64), 1.0 - key)),
            (1.0, mix((26, 28, 54), (12, 12, 30), 1.0 - key)),
        ],
    )
    sun_x = round(width * rng.uniform(0.22, 0.74))
    # Sometimes clear of the water, sometimes touching it: the gap changes where
    # the highlight sits relative to the horizon, which is the one thing about
    # this picture a coarse fingerprint can see.
    sun_y = round(horizon - height * lift)
    radius = round(width * rng.uniform(0.020, 0.034))
    disc = Image.new("L", size, 0)
    ImageDraw.Draw(disc).ellipse(
        (sun_x - radius, sun_y - radius, sun_x + radius, sun_y + radius), fill=255
    )
    scene = Image.composite(
        Image.new("RGB", size, (255, 240, 202)),
        scene,
        disc.filter(ImageFilter.GaussianBlur(width * 0.055)),
    )
    scene = Image.composite(
        Image.new("RGB", size, (255, 252, 236)),
        scene,
        disc.filter(ImageFilter.GaussianBlur(radius * 0.22)),
    )

    streaks = value_noise(size, (70, 240), seed + 5)
    streaks = streaks.filter(ImageFilter.GaussianBlur(1.2)).point(
        lambda value: max(0, value - 122) * 3
    )
    cone = Image.new("L", size, 0)
    ImageDraw.Draw(cone).polygon(
        [
            (sun_x - width * 0.03, horizon),
            (sun_x + width * 0.03, horizon),
            (sun_x + width * 0.20, height),
            (sun_x - width * 0.20, height),
        ],
        fill=255,
    )
    below = vertical_gradient(
        size,
        [
            (0.0, (0, 0, 0)),
            (level, (0, 0, 0)),
            (min(1.0, level + 0.012), (255, 255, 255)),
            (1.0, (140, 140, 140)),
        ],
    ).convert("L")
    reflection = ImageChops.multiply(
        ImageChops.multiply(
            streaks, cone.filter(ImageFilter.GaussianBlur(width * 0.035))
        ),
        below,
    )
    scene = Image.composite(Image.new("RGB", size, (255, 226, 168)), scene, reflection)

    flecks = Image.new("L", size, 0)
    pen = ImageDraw.Draw(flecks)
    for index in range(90):
        y = rng.uniform(horizon + height * 0.02, height)
        depth = (y - horizon) / max(height - horizon, 1)
        x = rng.uniform(0, width)
        nearness = 1.0 - min(1.0, abs(x - sun_x) / (width * 0.45))
        length = width * (0.003 + 0.016 * depth) * rng.uniform(0.4, 1.6)
        pen.ellipse(
            (x, y, x + length, y + max(1.0, length * 0.2)),
            fill=round(rng.uniform(40, 170) * (0.25 + 0.75 * nearness)),
        )
    scene = Image.composite(
        Image.new("RGB", size, (255, 234, 200)),
        scene,
        flecks.filter(ImageFilter.GaussianBlur(1.4)),
    )

    scene = bloom(scene, 195, width * 0.025, 0.5)
    return grain(vignette(scene, 0.34), 0.09, seed)


def leaf_canopy(size: Size, seed: int, variant: float) -> Image.Image:
    """Leaves at close range, with the depth of field a wide lens would give.

    Every blade is blurred by how far back it was placed, so the frame has a
    plane of focus. Nothing says "drawing" like a picture that is uniformly
    sharp from front to back.

    ``variant`` walks the camera in: further along the family the leaves are
    larger, fewer and thrown further out of focus behind.
    """
    width, height = size
    rng = random.Random(seed)
    scene = vertical_gradient(
        size, [(0.0, (26, 44, 22)), (0.5, (42, 66, 30)), (1.0, (18, 32, 16))]
    )
    blade = Image.new("L", (512, 208), 0)
    pen = ImageDraw.Draw(blade)
    pen.ellipse((0, 4, 470, 204), fill=255)
    pen.polygon([(300, 20), (511, 104), (300, 188)], fill=255)
    blade = blade.filter(ImageFilter.GaussianBlur(2))
    palette = [
        (92, 138, 46),
        (128, 172, 54),
        (58, 108, 42),
        (172, 188, 64),
        (150, 120, 40),
    ]
    for index in range(round(lerp(150, 70, variant))):
        depth = rng.random() ** 0.8
        span = (0.11 + lerp(0.22, 0.46, variant) * (1 - depth)) * width
        sprite = blade.resize(
            (round(span), round(span * 0.4)), Image.Resampling.BILINEAR
        )
        sprite = sprite.rotate(
            rng.uniform(0, 360), expand=True, resample=Image.Resampling.BILINEAR
        )
        sprite = sprite.filter(ImageFilter.GaussianBlur(0.4 + depth * 12.0))
        colour = mix(rng.choice(palette), (16, 28, 14), depth * 0.65)
        shading = vertical_gradient(
            sprite.size,
            [
                (0.0, mix(colour, (255, 255, 220), 0.18)),
                (1.0, mix(colour, (0, 0, 0), 0.35)),
            ],
        )
        at = (
            round(rng.uniform(-0.12, 1.0) * width),
            round(rng.uniform(-0.12, 1.0) * height),
        )
        paste_masked(scene, shading, sprite, at)
    dapple = fractal_noise(size, 4, seed + 3, base=5).point(
        lambda value: max(0, value - 168) * 2
    )
    scene = Image.composite(
        Image.new("RGB", size, (232, 242, 186)),
        scene,
        dapple.filter(ImageFilter.GaussianBlur(width * 0.006)),
    )
    return grain(vignette(scene, 0.36), 0.10, seed)


def studio_sphere(size: Size, seed: int, variant: float) -> Image.Image:
    """A glazed sphere on a coloured sweep: the shot a cut-out tool is made for.

    The sweep is a cool teal and the sphere is warm, deliberately. The magic
    wand takes a connected patch of *similar colour*, so a background sharing no
    tone with the subject goes in one click, while a grey sweep leaks up the
    highlight and into the middle of the ball.

    ``variant`` sets how much of the frame the subject fills.
    """
    width, height = size
    rng = random.Random(seed)
    body = mix((198, 82, 62), (206, 118, 54), rng.random())
    floor = height * 0.76
    sweep = mix((52, 100, 114), (58, 94, 122), rng.random())
    scene = vertical_gradient(
        size,
        [
            (0.0, sweep),
            (0.55, mix(sweep, (255, 255, 255), 0.14)),
            (floor / height, mix(sweep, (255, 255, 255), 0.18)),
            (1.0, mix(sweep, (255, 255, 255), 0.06)),
        ],
    )
    centre_x = width * 0.5
    radius = min(width, height) * lerp(0.25, 0.30, variant)
    box = (centre_x - radius, floor - radius * 2, centre_x + radius, floor)

    shadow = Image.new("L", size, 0)
    pen = ImageDraw.Draw(shadow)
    pen.ellipse(
        (
            centre_x - radius * 1.9,
            floor - radius * 0.30,
            centre_x + radius * 1.30,
            floor + radius * 0.28,
        ),
        fill=120,
    )
    pen.ellipse(
        (
            centre_x - radius * 1.0,
            floor - radius * 0.15,
            centre_x + radius * 0.92,
            floor + radius * 0.12,
        ),
        fill=205,
    )
    scene = Image.composite(
        Image.new("RGB", size, (18, 40, 48)),
        scene,
        shadow.filter(ImageFilter.GaussianBlur(radius * 0.15)),
    )

    ball_mask = Image.new("L", size, 0)
    ImageDraw.Draw(ball_mask).ellipse(box, fill=255)
    ball_mask = ball_mask.filter(ImageFilter.GaussianBlur(0.8))

    falloff = Image.radial_gradient("L").resize(
        (round(radius * 5.2), round(radius * 5.2)), Image.Resampling.BILINEAR
    )
    shade = Image.new("L", size, 0)
    shade.paste(falloff, (round(centre_x - radius * 3.1), round(floor - radius * 4.15)))
    ball = Image.composite(
        Image.new("RGB", size, body),
        Image.new("RGB", size, mix(body, (10, 8, 14), 0.8)),
        shade.point(lambda value: round(255 - value * 1.4)),
    )
    mottle = fractal_noise(size, 4, seed + 17, base=9).point(
        lambda value: round(196 + value * 0.24)
    )
    ball = ImageChops.multiply(ball, Image.merge("RGB", (mottle, mottle, mottle)))

    bounce = Image.new("L", size, 0)
    ImageDraw.Draw(bounce).ellipse(
        (
            box[0] + radius * 0.2,
            box[1] + radius * 0.35,
            box[2] + radius * 0.05,
            box[3] + radius * 0.05,
        ),
        fill=255,
    )
    bounce = ImageChops.multiply(
        bounce.filter(ImageFilter.GaussianBlur(radius * 0.28)), ball_mask
    ).point(lambda value: round(value * 0.4))
    ball = Image.composite(
        Image.new("RGB", size, mix(body, (236, 196, 150), 0.4)), ball, bounce
    )

    highlight = Image.new("L", size, 0)
    ImageDraw.Draw(highlight).ellipse(
        (
            centre_x - radius * 0.60,
            floor - radius * 1.70,
            centre_x - radius * 0.18,
            floor - radius * 1.40,
        ),
        fill=255,
    )
    ball = Image.composite(
        Image.new("RGB", size, (255, 250, 242)),
        ball,
        highlight.filter(ImageFilter.GaussianBlur(radius * 0.06)),
    )

    scene = Image.composite(ball, scene, ball_mask)
    # A light vignette on purpose: a heavy one pulls the corners of the sweep so
    # far from its middle that one wand click can no longer take the lot.
    return grain(vignette(scene, 0.10), 0.06, seed)


# -- the sample folder ------------------------------------------------------

# Camera-style names, because that is what a folder of photographs looks like.
# Shapes alternate so the table view has something to report and the preview is
# not always the same rectangle.
# Weighted away from landscapes on purpose. Fourteen of the twenty-five used to
# be sky-over-ground — five sunsets, five ranges, four dune fields — and an 8x8
# average hash cannot reliably hold two of those more than five bits apart
# however they are framed, so the duplicate finder kept pairing a mountain with
# a sunset. Ten landscapes and fifteen frames with no horizon in them clears it,
# and a folder of holiday photographs that is not entirely wide vistas is the
# more believable folder anyway.
GALLERY: tuple[tuple[str, str, int, Size], ...] = (
    ("IMG_0312.jpg", "sea", 3, LANDSCAPE),
    ("IMG_0317.jpg", "mountains", 21, LANDSCAPE),
    ("IMG_0329.jpg", "bokeh", 7, LANDSCAPE),
    ("IMG_0341.jpg", "leaves", 9, LANDSCAPE),
    ("IMG_0352.jpg", "dunes", 33, LANDSCAPE),
    ("IMG_0366.jpg", "sea", 41, PORTRAIT),
    ("IMG_0378.jpg", "leaves", 52, LANDSCAPE),
    ("IMG_0384.jpg", "bokeh", 63, PORTRAIT),
    ("IMG_0390.jpg", "leaves", 74, LANDSCAPE),
    ("IMG_0402.jpg", "dunes", 85, LANDSCAPE),
    ("IMG_0415.jpg", "sea", 96, LANDSCAPE),
    ("IMG_0421.jpg", "mountains", 107, PORTRAIT),
    ("IMG_0433.jpg", "bokeh", 118, LANDSCAPE),
    ("IMG_0447.jpg", "studio", 129, STUDIO),
    ("IMG_0455.jpg", "leaves", 140, PORTRAIT),
    ("IMG_0468.jpg", "bokeh", 151, LANDSCAPE),
    ("IMG_0470.jpg", "sea", 162, LANDSCAPE),
    ("IMG_0486.jpg", "mountains", 173, LANDSCAPE),
    ("IMG_0491.jpg", "bokeh", 184, LANDSCAPE),
    ("IMG_0503.jpg", "leaves", 195, LANDSCAPE),
    ("IMG_0518.jpg", "dunes", 206, PORTRAIT),
    ("IMG_0524.jpg", "leaves", 217, LANDSCAPE),
    ("IMG_0537.jpg", "bokeh", 228, LANDSCAPE),
    ("IMG_0546.jpg", "bokeh", 239, LANDSCAPE),
    ("IMG_0559.jpg", "leaves", 250, LANDSCAPE),
)

# What the duplicate finder is there to catch: one byte-for-byte copy, as a
# re-download leaves behind, and one re-export at a lower quality and size,
# which has different bytes and the same picture.
EXACT_COPY = ("IMG_0329.jpg", "IMG_0329 (1).jpg")
REENCODED = ("IMG_0317.jpg", "IMG_0317_edited.jpg")

# The photograph each screenshot opens, and the state around it.
GALLERY_SUBJECT = "IMG_0312.jpg"
CROP_SUBJECT = "IMG_0317.jpg"
CROP_ASPECT = "16:9"
CUTOUT_SUBJECT = "IMG_0447.jpg"
FAVOURITES = ("IMG_0312.jpg", "IMG_0390.jpg", "IMG_0433.jpg")
SELECTED = ("IMG_0312.jpg", "IMG_0317.jpg", "IMG_0329.jpg")

SCENES: dict[str, Scene] = {
    "sea": sea_sunset,
    "mountains": mountain_ridges,
    "bokeh": bokeh_lights,
    "leaves": leaf_canopy,
    "dunes": desert_dunes,
    "studio": studio_sphere,
}


def framing_positions() -> dict[str, float]:
    """Give every sample its place in 0..1 along its own scene family.

    Five sunsets want five different horizons, not five draws from one range
    that may land on top of each other. Spreading them by position is what a
    photographer does anyway — you do not shoot the same frame five times — and
    it is the only version of this that cannot regress by bad luck.
    """
    families: dict[str, list[str]] = {}
    for name, scene, seed, size in GALLERY:
        families.setdefault(scene, []).append(name)
    spread: dict[str, float] = {}
    for scene, names in families.items():
        for position, name in enumerate(names):
            spread[name] = position / max(len(names) - 1, 1)
    return spread


def compose(scene: str, size: Size, seed: int, variant: float) -> Image.Image:
    """Paint one sample, turning every other seed left-to-right.

    A mirror costs one call and moves a great many fingerprint bits, because
    everything that made the frame asymmetric — which side the sun is on, which
    flank of a dune is lit — swaps ends. Without it every picture in a family
    leans the same way, and the gallery looks like one photograph reprinted.
    """
    image = SCENES[scene](size, seed, variant)
    return ImageOps.mirror(image) if seed % 2 else image


def build_gallery(folder: Path) -> None:
    """Paint every sample photograph into ``folder``, duplicates included."""
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    variants = framing_positions()
    for name, scene, seed, size in GALLERY:
        compose(scene, size, seed, variants[name]).save(folder / name, quality=90)
    shutil.copyfile(folder / EXACT_COPY[0], folder / EXACT_COPY[1])
    original = Image.open(folder / REENCODED[0])
    reduced = original.resize(
        (original.width * 3 // 4, original.height * 3 // 4), Image.Resampling.LANCZOS
    )
    reduced.save(folder / REENCODED[1], quality=70)


def check_samples_distinct(folder: Path) -> None:
    """Refuse a folder in which two unrelated samples look alike to the app.

    The duplicate finder screenshot is only worth showing if what it reports is
    right, and a reader has no way to check. When the samples were painted from
    random framing this failed on five pairs at once, and nothing about the
    picture looked wrong — it just quietly advertised a tool that offers to
    delete photographs that differ.
    """
    # The same fingerprint the application uses, from the application, so this
    # cannot pass against a reimplementation the shipped code disagrees with.
    from myimages.core import duplicates

    planted = {frozenset(EXACT_COPY), frozenset(REENCODED)}
    names = sorted(path.name for path in folder.iterdir())
    fingerprints = {name: duplicates.average_hash(folder / name) for name in names}
    for position, first in enumerate(names):
        for second in names[position + 1 :]:
            if frozenset((first, second)) in planted:
                continue
            gap = duplicates.hamming_distance(fingerprints[first], fingerprints[second])
            if gap <= DEFAULT_DISTANCE:
                raise RuntimeError(
                    f"{first} and {second} are {gap} apart, inside the finder's "
                    f"default of {DEFAULT_DISTANCE}: they would be shown as "
                    "duplicates of each other"
                )


# -- driving the application ------------------------------------------------


def configure_environment(work: Path) -> None:
    """Put the package on the import path and Qt in a scratch world.

    The repository root goes on the path so a bare checkout runs this without
    installing anything, as ``scripts/export_icon.py`` already does. The rest
    has to happen before ``PySide6`` is imported, which is why every Qt import
    in this file sits inside a function. Offscreen because there is no
    display; no video backend because QtMultimedia starts an ffmpeg thread per
    player and crashes on teardown as short-lived windows come and go; and a
    private data directory, so a demo run cannot touch the settings, favourites
    or thumbnail cache of whoever runs it.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["QT_SCALE_FACTOR"] = SCALE_FACTOR
    os.environ["MYIMAGES_NO_VIDEO"] = "1"
    os.environ["MYIMAGES_DATA_DIR"] = str(work / "state")


def settle(app: QApplication, seconds: float = 0.35) -> None:
    """Let the event loop run, so painting and posted events catch up."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)


def await_thumbnails(app: QApplication, window: MainWindow) -> int:
    """Spin until every thumbnail has arrived; returns how many never did.

    The grid builds them on worker threads, so grabbing the window too early
    photographs a panel of empty squares — the one failure that would make a
    screenshot worse than no screenshot. The count comes back so the caller can
    refuse to write a half-drawn gallery.
    """
    wanted = len(window.media_files)
    deadline = time.monotonic() + THUMBNAIL_TIMEOUT
    while time.monotonic() < deadline:
        app.processEvents()
        if len(window.loader.cache) >= wanted:
            settle(app)
            return 0
        time.sleep(0.01)
    return wanted - len(window.loader.cache)


def open_window(gallery: Path) -> tuple[QApplication, MainWindow]:
    """Build the real application over ``gallery`` and show it offscreen."""
    from PySide6.QtWidgets import QApplication

    from myimages.app import apply_theme_to_app
    from myimages.config import Settings
    from myimages.gui.main_window import MainWindow
    from myimages.gui.task_runner import synchronous_runner

    app = QApplication([])
    app.setStyle("Fusion")
    settings = Settings(
        last_folder=str(gallery),
        grid_columns=GRID_COLUMNS,
        theme="dark",
        favorites=[str(gallery / name) for name in FAVOURITES],
        # Nothing may re-scan mid-shot and reshuffle what is on screen.
        watch_folder=False,
    )
    apply_theme_to_app(settings.theme)
    # Left at the size the window opens itself at, from the settings defaults: a
    # screenshot of a window nobody would ever have is a screenshot of a
    # different program. What that size has to be good for is checked instead,
    # by check_tools_fit below.
    window = MainWindow(settings, runner=synchronous_runner)
    window.show()
    # Display only: the box is read on Return and on a folder change, neither of
    # which happens here, so the gallery stays loaded from the real path.
    window.folder_input.setText(DISPLAY_FOLDER)
    window.folder_input.setCursorPosition(0)
    return app, window


def grab_image(widget: QWidget) -> Image.Image:
    """Render a widget and hand it back as a Pillow image.

    Through a temporary PNG rather than poking at ``QImage.constBits``: the
    round trip is a few milliseconds once per screenshot and it cannot get the
    stride or the channel order wrong.
    """
    pixmap = widget.grab()
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "grab.png"
        pixmap.save(str(path), "PNG")
        with Image.open(path) as opened:
            return opened.convert("RGB")


def drop_shadow(size: Size, radius: int, spread: int) -> Image.Image:
    """A soft dark rectangle to sit under a floating window."""
    mask = Image.new("L", (size[0] + spread * 4, size[1] + spread * 4), 0)
    ImageDraw.Draw(mask).rectangle(
        (spread * 2, spread * 2 + spread, size[0] + spread * 2, size[1] + spread * 2),
        fill=210,
    )
    return mask.filter(ImageFilter.GaussianBlur(radius))


def save_shot(image: Image.Image, destination: Path) -> str:
    """Write a screenshot at the width the README wants; returns what it wrote."""
    height = round(image.height * OUTPUT_WIDTH / image.width)
    scaled = image.resize((OUTPUT_WIDTH, height), Image.Resampling.LANCZOS)
    # method=6 is the encoder's slowest search. It costs about a second a frame
    # here and buys roughly a fifth off the file, which is a good trade for a
    # thing written once and fetched by everybody who opens the README.
    scaled.save(destination, quality=SHOT_QUALITY, method=6)
    return f"{OUTPUT_WIDTH}x{height}, {destination.stat().st_size:,} bytes"


def fit_findings(dialog: DuplicatesDialog) -> None:
    """Grow the duplicate list until every row it found is whole.

    Left at a fixed height the viewport ends wherever it ends, which put a row
    of the last group through a horizontal slicer half a line from the bottom.
    On screen that is a list you scroll; in a still picture it is indis-
    tinguishable from a widget that failed to draw.
    """
    tree = dialog.tree
    rows = tree.topLevelItemCount()
    for index in range(tree.topLevelItemCount()):
        group = tree.topLevelItem(index)
        rows += group.childCount() if group is not None else 0
    first = tree.topLevelItem(0)
    if first is None:
        raise RuntimeError("the duplicate finder came back with nothing to show")
    step = tree.visualItemRect(first).height()
    chrome = tree.height() - tree.viewport().height() + tree.header().height()
    # Move the *dialog* rather than pinning the tree. The tree is the stretching
    # widget in this layout, so fixing its height parks the slack between the
    # widgets instead — a list that stops early with a band of nothing under it,
    # which looks like a mistake in a way that a list with room to spare does
    # not. Shrinking is allowed too; Qt stops at the dialog's own minimum.
    shortfall = rows * step + chrome + DUPLICATES_MARGIN - tree.height()
    dialog.resize(DUPLICATES_WIDTH, dialog.height() + shortfall)


def check_tools_fit(editor: ImageEditor) -> None:
    """Refuse a shot whose tool row had to scroll to hold its controls.

    The editor's row is allowed to scroll when the window is narrow, so a
    smaller default window would quietly push the last tools out of frame
    instead of failing. A screenshot of half a toolbar documents nothing, and
    nothing about it looks wrong until somebody counts the buttons.
    """
    overflow = editor.toolbar_area.horizontalScrollBar().maximum()
    if overflow:
        raise RuntimeError(f"the {editor.mode} tools overflow the row by {overflow}px")


def select_files(window: MainWindow, gallery: Path, names: tuple[str, ...]) -> None:
    """Pick several thumbnails, as a click and two ctrl-clicks would."""
    for name in names:
        row = window.file_list.index_by_path.get(str(gallery / name))
        if row is None:
            continue
        item = window.file_list.icon_list.item(row)
        if item is not None:
            item.setSelected(True)
    window.file_list.handle_selection_changed()


def shoot_gallery(app: QApplication, window: MainWindow, gallery: Path) -> Image.Image:
    """The main window with a photograph open and a few files picked out."""
    window.file_list.select_path(str(gallery / GALLERY_SUBJECT))
    select_files(window, gallery, SELECTED)
    settle(app)
    return grab_image(window)


def shoot_crop(app: QApplication, window: MainWindow, gallery: Path) -> Image.Image:
    """The inline editor with a 16:9 crop drawn over a landscape."""
    from myimages.imaging.transform import CropRect

    window.file_list.select_path(str(gallery / CROP_SUBJECT))
    window.open_edit()
    editor = window.editor
    editor.set_mode("crop")
    # Through the combo rather than straight to set_aspect, so the control shows
    # the shape the box is locked to instead of contradicting it.
    shape = editor.aspect_combo.findText(CROP_ASPECT)
    editor.aspect_combo.setCurrentIndex(shape)
    editor.on_aspect_chosen(shape)
    image = editor.working_image
    if image is None:
        raise RuntimeError("the editor opened without an image")
    # Off-centre and short of the frame: a crop box sitting exactly in the
    # middle looks like a default, not like somebody reframing a picture.
    width = round(image.width * 0.78)
    editor.canvas.selection = CropRect(
        round(image.width * 0.085),
        round(image.height * 0.20),
        width,
        round(width * 9 / 16),
    )
    editor.canvas.emit_selection()
    settle(app)
    check_tools_fit(editor)
    return grab_image(window)


def shoot_cutout(app: QApplication, window: MainWindow, gallery: Path) -> Image.Image:
    """The cut-out tools part way through: sweep gone, shadow being wiped."""
    window.editor.cancel()
    settle(app, 0.2)
    window.file_list.select_path(str(gallery / CUTOUT_SUBJECT))
    window.open_cutout_editor()
    editor = window.editor

    # Raise the tolerance through the stepper, so its readout agrees with what
    # the wand is really using.
    while editor.tolerance < 96:
        editor.step_tolerance(1)
    editor.arm_tool("wand")
    editor.on_point_picked(0.06, 0.45)

    # Then the eraser along the contact shadow, which is far too dark for the
    # wand to have taken with the sweep, and stopped part way across: this is a
    # screenshot of a job in progress, not of a finished one. The stroke keeps
    # to the left of the sphere — the shadow runs under it, and a brush wide
    # enough to lift the shadow would take the bottom of the subject with it.
    editor.step_brush(1)
    editor.arm_tool("erase")
    for index in range(6):
        editor.on_stroke(0.13 + index * 0.034, 0.757, index == 0)

    # The brush ring follows the pointer, so leave the pointer over the part of
    # the shadow the stroke has not reached yet.
    canvas = editor.canvas
    scale, offset_x, offset_y = canvas.current_layout()
    canvas.hover_point = (
        offset_x + canvas.pixmap.width() * scale * 0.37,
        offset_y + canvas.pixmap.height() * scale * 0.785,
    )
    canvas.update()
    settle(app)
    check_tools_fit(editor)
    return grab_image(window)


def shoot_duplicates(
    app: QApplication, window: MainWindow, background: Image.Image
) -> Image.Image:
    """The duplicate finder, over the window it was opened from.

    Qt grabs one top-level widget at a time and the offscreen platform has no
    compositor, so the dialog is rendered on its own and then placed where a
    window manager would have put it: centred on its parent, with the shadow a
    desktop draws under a window that floats above another.
    """
    from myimages.gui.duplicates_dialog import DuplicatesDialog
    from myimages.gui.task_runner import synchronous_runner

    window.editor.cancel()
    settle(app, 0.2)
    dialog = DuplicatesDialog(
        list(window.media_files), window, runner=synchronous_runner
    )
    dialog.resize(DUPLICATES_WIDTH, 520)
    dialog.show()
    dialog.start_scan()
    settle(app, 0.6)
    fit_findings(dialog)
    settle(app, 0.2)
    front = grab_image(dialog)
    dialog.close()

    composed = background.copy()
    at = (
        (composed.width - front.width) // 2,
        (composed.height - front.height) // 2,
    )
    shadow = drop_shadow(front.size, radius=28, spread=14)
    dark = Image.new("RGB", shadow.size, (0, 0, 0))
    composed.paste(
        Image.composite(
            dark,
            composed.crop(
                (
                    at[0] - 28,
                    at[1] - 28,
                    at[0] - 28 + shadow.width,
                    at[1] - 28 + shadow.height,
                )
            ),
            shadow,
        ),
        (at[0] - 28, at[1] - 28),
    )
    composed.paste(front, at)
    return composed


def main() -> None:
    """Paint the sample folder, then photograph the application showing it."""
    destination = output_dir()
    destination.mkdir(parents=True, exist_ok=True)
    work = destination / "work"
    configure_environment(work)
    # Run from inside the working directory, so the folder the application is
    # given — and prints — is the short relative one and not this machine's.
    work.mkdir(parents=True, exist_ok=True)
    started_in = Path.cwd()
    os.chdir(work)
    gallery = GALLERY_FOLDER
    build_gallery(gallery)
    check_samples_distinct(gallery)

    app, window = open_window(gallery)
    missing = await_thumbnails(app, window)
    if missing:
        raise RuntimeError(f"{missing} thumbnail(s) never arrived")

    gallery_shot = shoot_gallery(app, window, gallery)
    shots = (
        (f"gallery{SHOT_SUFFIX}", gallery_shot),
        (f"editor-crop{SHOT_SUFFIX}", shoot_crop(app, window, gallery)),
        (f"editor-cutout{SHOT_SUFFIX}", shoot_cutout(app, window, gallery)),
        (f"duplicates{SHOT_SUFFIX}", shoot_duplicates(app, window, gallery_shot)),
    )
    for name, image in shots:
        print(f"{name}: {save_shot(image, destination / name)}")
    os.chdir(started_in)
    shutil.rmtree(work)


if __name__ == "__main__":
    main()
