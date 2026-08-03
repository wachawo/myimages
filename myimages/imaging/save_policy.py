"""What each image format can store, and where a transparent result may go.

This module deliberately imports nothing from the rest of the package. It is the
shared bottom of the imaging layer: :mod:`myimages.imaging.convert` already
imports :mod:`myimages.imaging.transform`, so the format tables cannot live in
either of them without one importing the other back.

The rule it encodes: a picture with see-through pixels must never be written to
a format that cannot hold them. Pillow opens the destination file for writing
*before* the encoder is consulted, so a rejected save leaves the original
truncated to nothing. Callers therefore ask here first and are handed a
:class:`SavePlan` naming a destination that can actually hold the image.

The safe set is smaller than it looks. It was measured, not assumed:

* ``.png``, ``.webp``, ``.tiff`` round-trip alpha exactly.
* ``.gif`` carries one fully transparent palette entry and 256 colours in
  total; a softened cut-out edge comes back completely opaque.
* ``.bmp`` discards alpha silently, which is worse than JPEG's loud failure.
* ``.jpg`` has no alpha channel at all and raises.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import cast

from PIL import Image

# Extension -> Pillow format name. Both the alias suffixes (.jpeg, .tif) and the
# canonical ones map to the same format so callers need not normalise first.
SUPPORTED_FORMATS: dict[str, str] = {
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".png": "PNG",
    ".webp": "WEBP",
    ".bmp": "BMP",
    ".tiff": "TIFF",
    ".tif": "TIFF",
    ".gif": "GIF",
}

# Formats that cannot encode an alpha channel; images with transparency must be
# flattened onto a background before they can be written to one of these.
FORMATS_WITHOUT_ALPHA: frozenset[str] = frozenset({"JPEG", "BMP"})

# Formats whose encoders honour a ``quality`` argument. Passing ``quality`` to a
# lossless encoder such as PNG is at best ignored and at worst an error, so we
# only forward it here.
FORMATS_WITH_QUALITY: frozenset[str] = frozenset({"JPEG", "WEBP"})

# Pixel modes that may carry transparency and therefore need flattening when the
# target format cannot store alpha (``P`` can hold a transparent palette entry).
ALPHA_MODES: frozenset[str] = frozenset({"RGBA", "LA", "P"})

# Suffixes a partially transparent image may be written to unchanged. GIF is
# absent on purpose: it survives fully transparent pixels but flattens a graded
# edge, so a cut-out saved to GIF looks correct in a thumbnail and ragged at
# full size.
ALPHA_SAFE_SUFFIXES: frozenset[str] = frozenset({".png", ".webp", ".tiff", ".tif"})

# Where a transparent result goes when the source format cannot hold it.
FALLBACK_SUFFIX = ".png"


class AlphaFormatError(ValueError):
    """Raised when a transparent image is asked to be written without alpha.

    Subclassing :class:`ValueError` keeps the failure in the same family as the
    other input-validation errors this package raises, so callers can catch it
    without importing this module specifically.
    """


@dataclass(frozen=True)
class SavePlan:
    """Where an image will actually be written, and whether that was a change.

    ``retargeted`` is true when the requested destination could not hold the
    image's transparency and ``destination`` names a sibling file instead. The
    interface uses it to relabel the button and to report the path it used, so
    a press of "Save" never silently writes somewhere else.
    """

    destination: Path
    retargeted: bool


def supports_alpha(suffix: str) -> bool:
    """True when a file with this suffix can store partial transparency."""
    return suffix.lower() in ALPHA_SAFE_SUFFIXES


def has_transparency(image: Image.Image) -> bool:
    """True when the image actually has see-through pixels, not merely a mode.

    The mode alone is not the question: a fully opaque RGBA image loses nothing
    by being flattened, so it must not be treated as transparent and diverted to
    another file. Palette images carry their transparency in ``info`` rather
    than in a channel.
    """
    if image.mode == "P":
        return "transparency" in image.info
    if image.mode not in ALPHA_MODES:
        return False
    # getextrema() is typed as a union because it returns one pair per band; a
    # single extracted channel always yields exactly one pair.
    lowest, _highest = cast("tuple[int, int]", image.getchannel("A").getextrema())
    return lowest < 255


def flatten_onto_background(
    image: Image.Image, background: tuple[int, int, int]
) -> Image.Image:
    """Composite ``image`` over an opaque ``background`` colour.

    Used before writing to alpha-less formats: pasting through the alpha channel
    preserves the visible pixels while replacing the transparent regions with a
    predictable colour rather than the black Pillow would otherwise produce.
    """
    with_alpha = image.convert("RGBA")
    canvas = Image.new("RGB", with_alpha.size, background)
    canvas.paste(with_alpha, mask=with_alpha.split()[-1])
    return canvas


def sibling_destination(path: Path, suffix: str) -> Path:
    """The same name beside ``path`` with ``suffix``, avoiding any clash."""
    candidate = path.with_suffix(suffix)
    if candidate != path and not candidate.exists():
        return candidate
    counter = 2
    while True:
        candidate = path.with_name(f"{path.stem}_{counter}{suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def overwrite_plan(path: Path, transparent: bool) -> SavePlan:
    """Plan an in-place save, retargeting when the format cannot hold alpha.

    An opaque image always overwrites ``path``. A transparent one overwrites it
    only when the suffix supports alpha; otherwise it is written to a sibling
    PNG and the original file is left untouched.
    """
    if not transparent or supports_alpha(path.suffix):
        return SavePlan(path, retargeted=False)
    return SavePlan(sibling_destination(path, FALLBACK_SUFFIX), retargeted=True)


def copy_plan(path: Path, transparent: bool) -> SavePlan:
    """Plan a save-as-copy, using PNG when the source format cannot hold alpha."""
    suffix = path.suffix
    retargeted = transparent and not supports_alpha(suffix)
    if retargeted:
        suffix = FALLBACK_SUFFIX
    candidate = path.with_name(f"{path.stem}_copy{suffix}")
    counter = 2
    while candidate.exists():
        candidate = path.with_name(f"{path.stem}_copy{counter}{suffix}")
        counter += 1
    return SavePlan(candidate, retargeted=retargeted)
