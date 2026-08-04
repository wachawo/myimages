"""Geometric and tonal image transforms, built on Pillow.

These are pure functions over ``PIL.Image.Image`` objects (plus small helpers
to load and save), so they are trivial to unit-test and are reused by the PDF
builder, the thumbnailer and the interactive crop tool. The cropping maths is
kept separate from the pixel work in :func:`aspect_crop_rect` so it can be
verified without decoding an image.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

from myimages.imaging.save_policy import (
    ALPHA_MODES,
    ALPHA_SAFE_SUFFIXES,
    FORMATS_WITHOUT_ALPHA,
    SUPPORTED_FORMATS,
    AlphaFormatError,
    flatten_onto_background,
    has_transparency,
    stores_dpi,
    supports_alpha,
)

ANCHORS: frozenset[str] = frozenset(
    {"center", "top", "bottom", "left", "right", "topleft"}
)

# Suffixes whose encoders honour a ``quality`` argument when saving.
QUALITY_SUFFIXES: frozenset[str] = frozenset({".jpg", ".jpeg", ".webp"})


@dataclass(frozen=True)
class CropRect:
    """A rectangle in pixel coordinates, top-left origin."""

    left: int
    top: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height

    def clamped(self, image_width: int, image_height: int) -> CropRect:
        """Return a copy guaranteed to lie inside the given image bounds."""
        left = max(0, min(self.left, image_width))
        top = max(0, min(self.top, image_height))
        width = max(1, min(self.width, image_width - left))
        height = max(1, min(self.height, image_height - top))
        return CropRect(left, top, width, height)


def load_image(path: str | Path) -> Image.Image:
    """Open an image, applying its EXIF orientation so it looks upright."""
    image = Image.open(path)
    image.load()
    return ImageOps.exif_transpose(image)


def save_image(
    image: Image.Image,
    dest: str | Path,
    *,
    quality: int = 90,
    background: tuple[int, int, int] = (255, 255, 255),
    dpi: tuple[float, float] | None = None,
) -> Path:
    """Save an image, inferring the format from ``dest``'s suffix.

    Transparency is checked before the file is opened, because Pillow truncates
    the destination to zero bytes and only then asks the encoder whether it can
    write the image — so a rejected save destroys whatever was already there.
    A transparent image bound for a format that cannot hold alpha raises
    :class:`AlphaFormatError`; callers pick a different destination with
    :mod:`myimages.imaging.save_policy` rather than losing the file.

    An image that is merely in an alpha-capable mode without using it (an opaque
    RGBA screenshot, say) is flattened onto ``background`` instead, since that
    discards nothing the viewer could see.

    The source's physical resolution is carried across unless ``dpi`` overrides
    it. Pillow reads that from the ``save`` arguments and never from the image's
    own ``info``, so a saver that does not pass it forward writes a file with no
    density at all -- and for TIFF and BMP writes a *wrong* one, since those
    encoders default to 1 and 96 rather than to nothing.
    """
    destination = Path(dest)
    suffix = destination.suffix.lower()
    # Read before anything below can rebind ``image``: flattening builds a fresh
    # picture whose info is empty, and the number would be gone by then.
    carried = image.info.get("dpi")
    if has_transparency(image) and not supports_alpha(suffix):
        raise AlphaFormatError(
            f"{suffix or 'that format'} cannot store transparency; "
            f"save to one of {', '.join(sorted(ALPHA_SAFE_SUFFIXES))} instead"
        )

    target_format = SUPPORTED_FORMATS.get(suffix)
    if target_format in FORMATS_WITHOUT_ALPHA and image.mode in ALPHA_MODES:
        image = flatten_onto_background(image, background)

    # ``Any`` rather than ``object``: mypy resolves save's second positional as
    # ``format: str | None`` and rejects a stricter mapping splatted into it.
    options: dict[str, Any] = {}
    if suffix in QUALITY_SUFFIXES:
        options["quality"] = quality
    resolution = dpi if dpi is not None else carried
    if resolution is not None and stores_dpi(suffix):
        options["dpi"] = resolution

    destination.parent.mkdir(parents=True, exist_ok=True)
    image.save(destination, **options)
    return destination


def to_grayscale(image: Image.Image) -> Image.Image:
    """Convert an image to single-channel greyscale."""
    return ImageOps.grayscale(image)


def rotate_image(image: Image.Image, degrees: int) -> Image.Image:
    """Rotate clockwise. Right-angle turns are lossless transposes."""
    turns = degrees % 360
    if turns == 0:
        return image.copy()
    if turns == 90:
        return image.transpose(Image.Transpose.ROTATE_270)
    if turns == 180:
        return image.transpose(Image.Transpose.ROTATE_180)
    if turns == 270:
        return image.transpose(Image.Transpose.ROTATE_90)
    return image.rotate(-degrees, expand=True)


def flip_image(image: Image.Image, horizontal: bool) -> Image.Image:
    """Mirror an image left-to-right, or top-to-bottom when ``horizontal`` is False.

    Mirroring is a lossless pixel rearrangement, so it is a transpose rather than
    a resample: no quality is lost however many times it is applied.
    """
    axis = (
        Image.Transpose.FLIP_LEFT_RIGHT
        if horizontal
        else Image.Transpose.FLIP_TOP_BOTTOM
    )
    return image.transpose(axis)


def crop_image(image: Image.Image, rect: CropRect) -> Image.Image:
    """Crop to ``rect`` after clamping it to the image bounds."""
    safe = rect.clamped(image.width, image.height)
    return image.crop((safe.left, safe.top, safe.right, safe.bottom))


def aspect_crop_rect(
    width: int,
    height: int,
    aspect_width: int,
    aspect_height: int,
    anchor: str = "center",
) -> CropRect:
    """Largest rectangle of the given aspect ratio that fits in ``width×height``.

    This is the maths behind "crop to 16:9"; it never scales, only chooses a
    sub-rectangle and where to place it via ``anchor``.
    """
    if aspect_width <= 0 or aspect_height <= 0:
        raise ValueError("aspect ratio components must be positive")
    target = aspect_width / aspect_height
    if width / height > target:
        crop_height = height
        crop_width = round(height * target)
    else:
        crop_width = width
        crop_height = round(width / target)
    crop_width = max(1, min(crop_width, width))
    crop_height = max(1, min(crop_height, height))

    if anchor in {"topleft", "left", "top"}:
        left = 0
    elif anchor == "right":
        left = width - crop_width
    else:
        left = (width - crop_width) // 2
    if anchor in {"topleft", "top", "left"}:
        top = 0 if anchor != "left" else (height - crop_height) // 2
    elif anchor == "bottom":
        top = height - crop_height
    else:
        top = (height - crop_height) // 2
    return CropRect(left, max(0, top), crop_width, crop_height)


def crop_to_aspect(
    image: Image.Image,
    aspect_width: int,
    aspect_height: int,
    anchor: str = "center",
) -> Image.Image:
    """Crop an image to a target aspect ratio."""
    rect = aspect_crop_rect(
        image.width, image.height, aspect_width, aspect_height, anchor
    )
    return crop_image(image, rect)


def scale_image(
    image: Image.Image,
    *,
    width: int | None = None,
    height: int | None = None,
    max_edge: int | None = None,
    keep_aspect: bool = True,
) -> Image.Image:
    """Resize an image; never upscales when constrained by ``max_edge``.

    The source's dpi is deliberately dropped: it describes a pixel count this
    result no longer has, so carrying it forward would make a 128-pixel
    thumbnail claim the density of the photograph it came from.
    """
    source_width, source_height = image.width, image.height
    if max_edge is not None:
        longest = max(source_width, source_height)
        if longest <= max_edge:
            return image.copy()
        factor = max_edge / longest
        target = (round(source_width * factor), round(source_height * factor))
    elif width is not None and height is not None and not keep_aspect:
        target = (width, height)
    elif width is not None:
        factor = width / source_width
        target = (width, max(1, round(source_height * factor)))
    elif height is not None:
        factor = height / source_height
        target = (max(1, round(source_width * factor)), height)
    else:
        return image.copy()
    target = (max(1, target[0]), max(1, target[1]))
    resized = image.resize(target, Image.Resampling.LANCZOS)
    resized.info.pop("dpi", None)
    return resized
