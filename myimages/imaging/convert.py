"""Convert images between file formats, built on Pillow and :mod:`transform`.

Format conversion is deliberately kept out of the interactive editor: batch jobs
(export a folder to WebP, downgrade HEIC shots to JPEG for sharing) run headless
and must be unit-testable without a display, so this module never touches Qt and
reuses the pure loaders in :mod:`myimages.imaging.transform` rather than
re-decoding images itself.

The tricky part conversion has to get right is alpha: JPEG and BMP cannot store
transparency, so a transparent PNG saved straight to JPEG would either raise or
turn its see-through areas black. We flatten those images onto a solid colour
first so the result matches what the user saw on screen.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path

from PIL import Image

from myimages.imaging.transform import load_image, to_grayscale

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


class ConversionError(ValueError):
    """Raised when a conversion request is malformed (e.g. an unknown target).

    Subclassing :class:`ValueError` keeps the failure in the same family as the
    other input-validation errors this package raises, so callers can catch it
    without importing this module specifically.
    """


def register_heif() -> bool:
    """Enable HEIF/HEIC decoding when the optional ``pillow-heif`` extra exists.

    HEIC is the default camera format on modern phones but its codec is a heavy
    optional dependency, so support is best-effort: we return whether it is now
    active so the UI can offer or hide HEIC conversion accordingly instead of
    failing later at open time.
    """
    try:
        import pillow_heif
    except ImportError:
        return False
    pillow_heif.register_heif_opener()
    return True


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


def convert_image(
    source: str | Path,
    dest: str | Path,
    *,
    quality: int = 90,
    grayscale: bool = False,
    background: tuple[int, int, int] = (255, 255, 255),
) -> Path:
    """Convert a single image to the format implied by ``dest``'s suffix.

    The suffix, not a separate argument, chooses the output format because it is
    what the user already typed and what tools downstream will trust; an unknown
    suffix is rejected up front so we never silently write an unexpected format.
    """
    destination = Path(dest)
    target_format = SUPPORTED_FORMATS.get(destination.suffix.lower())
    if target_format is None:
        raise ConversionError(
            f"cannot convert to unsupported format {destination.suffix!r}"
        )

    image = load_image(source)
    if grayscale:
        # Re-expand to RGB so grey output stays compatible with every target
        # format (single-channel ``L`` cannot be saved as, e.g., WebP).
        image = to_grayscale(image).convert("RGB")
    if target_format in FORMATS_WITHOUT_ALPHA and image.mode in ALPHA_MODES:
        image = flatten_onto_background(image, background)

    destination.parent.mkdir(parents=True, exist_ok=True)
    if target_format in FORMATS_WITH_QUALITY:
        image.save(destination, format=target_format, quality=quality)
    else:
        image.save(destination, format=target_format)
    return destination


def convert_many(
    sources: Iterable[str | Path],
    out_dir: str | Path,
    target_extension: str,
    *,
    quality: int = 90,
    grayscale: bool = False,
    progress: Callable[[int, int], None] | None = None,
) -> list[Path]:
    """Convert many images into ``out_dir``, reusing each source's stem.

    The output name reuses the source stem so a folder round-trips predictably,
    and ``progress`` is invoked after each file (rather than before) so a caller
    driving a progress bar counts only work that actually completed.
    """
    if not target_extension.startswith("."):
        raise ConversionError(
            f"target extension must start with '.', got {target_extension!r}"
        )

    output_directory = Path(out_dir)
    pending = list(sources)
    total = len(pending)
    outputs: list[Path] = []
    for done, source in enumerate(pending, start=1):
        destination = output_directory / (Path(source).stem + target_extension)
        outputs.append(
            convert_image(source, destination, quality=quality, grayscale=grayscale)
        )
        if progress is not None:
            progress(done, total)
    return outputs
