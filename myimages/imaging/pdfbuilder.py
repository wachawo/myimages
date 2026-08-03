"""Combine images into a single, size-bounded PDF, built on :mod:`transform`.

Exporting a photo set as one PDF is a headless batch job -- it must run in tests
and on servers with no display -- so this module never imports Qt and reuses the
pure loaders/resamplers in :mod:`myimages.imaging.transform` rather than decoding
pixels itself.

The subtle requirement is *size control*. Pillow's PDF writer stores ``RGB`` and
``L`` pages with a DCT (JPEG) filter, but it re-encodes them at a fixed quality
of its own, so merely asking Pillow for a lower quality would not shrink the
file. To make ``target_mib`` actually bite we first round-trip every page through
a JPEG buffer at the chosen quality: that bakes the quantisation loss into the
pixels, so when Pillow re-encodes the page for the PDF the resulting DCT stream
-- and therefore the file -- tracks the quality we asked for. When even the
lowest quality is still too big we additionally down-scale every page and sweep
again, always remembering the smallest rendering produced, so a best effort is
returned instead of a failure.
"""

from __future__ import annotations

import io
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from myimages.imaging.transform import load_image, scale_image, to_grayscale

# One mebibyte in bytes; ``target_mib`` is expressed in these human-facing units
# but every size comparison happens in bytes.
BYTES_PER_MIB: int = 1024 * 1024

# The quality sweep starts at the caller's quality and steps down by this much,
# never dropping below the floor: past that point the image is so degraded that
# lowering quality further hurts legibility more than it saves bytes.
QUALITY_STEP: int = 10
QUALITY_FLOOR: int = 20

# When no quality fits the budget we shed pixels instead, multiplying every edge
# by this factor, up to this many times: beyond a point pixel count, not JPEG
# quality, dominates the file size.
SHRINK_FACTOR: float = 0.8
MAX_SHRINK_ROUNDS: int = 3


@dataclass
class PdfOptions:
    """Knobs for a PDF export, with defaults tuned for everyday sharing.

    ``max_edge_px`` caps each page's longest side so a folder of phone shots does
    not produce a needlessly huge document, and ``target_mib`` (when positive)
    asks the builder to trade quality for a size ceiling, e.g. an email limit.
    ``jpeg_pages`` selects between the size-controlled JPEG pipeline and
    original-size pages: no downscaling and a single top-quality encode
    (Pillow always DCT-encodes PDF pages, so truly lossless embedding is not
    available), where the size knobs do not apply.
    """

    quality: int = 85
    grayscale: bool = False
    max_edge_px: int = 2200
    target_mib: float = 0.0
    jpeg_pages: bool = True


# The single encode quality used for original-size pages; also reported as
# ``quality_used`` so the UI can show what the file actually contains.
ORIGINAL_QUALITY: int = 95


@dataclass(frozen=True)
class PdfResult:
    """What a build produced, so a caller need not re-stat or re-open the file.

    ``quality_used`` is reported because a size target can force it below the
    requested quality, and the UI should be able to tell the user what it settled
    on. The result is frozen so it can be handed around as a plain value object.
    """

    path: Path
    size_bytes: int
    page_count: int
    quality_used: int


class PdfError(ValueError):
    """Raised when a PDF request is malformed, e.g. no sources were given.

    Subclassing :class:`ValueError` keeps it in the same family as the other
    input-validation errors in this package, so callers can catch it without
    importing this module specifically.
    """


def jpeg_reencode(image: Image.Image, quality: int) -> Image.Image:
    """Return ``image`` after a lossy JPEG round-trip at ``quality``.

    Baking the quantisation loss into the pixels here is what lets the final
    PDF's size respond to ``quality`` at all: Pillow re-encodes PDF pages at a
    fixed JPEG quality, so the degradation has to be applied *before* that step
    to have any effect.
    """
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=quality)
    buffer.seek(0)
    encoded = Image.open(buffer)
    # Force a full decode now so the returned image no longer depends on the
    # local buffer once this function returns.
    encoded.load()
    return encoded


def render_pdf_bytes(pages: Sequence[Image.Image], quality: int) -> bytes:
    """Encode ``pages`` as one JPEG-backed PDF and return its bytes.

    Rendering to an in-memory buffer rather than straight to disk lets the size
    sweep compare candidates cheaply, so only the winning rendering ever has to
    touch the filesystem.
    """
    encoded_pages = [jpeg_reencode(page, quality) for page in pages]
    first, *rest = encoded_pages
    buffer = io.BytesIO()
    first.save(buffer, format="PDF", save_all=True, append_images=rest)
    return buffer.getvalue()


def prepare_pages(
    sources: Sequence[str | Path],
    options: PdfOptions,
    progress: Callable[[int, int], None] | None,
) -> list[Image.Image]:
    """Load, resample and colour-normalise every source into a PDF page.

    Colour normalisation matters because JPEG (and thus our DCT-backed PDF)
    cannot store an alpha channel, so each page is reduced to ``L`` or ``RGB``
    here. Progress is reported after each page completes -- never before -- so a
    caller driving a progress bar only ever counts work that actually finished.
    """
    total = len(sources)
    pages: list[Image.Image] = []
    for done, source in enumerate(sources, start=1):
        loaded = load_image(source)
        resized = scale_image(loaded, max_edge=options.max_edge_px)
        page = to_grayscale(resized) if options.grayscale else resized.convert("RGB")
        pages.append(page)
        if progress is not None:
            progress(done, total)
    return pages


def load_original_page(source: str | Path, grayscale: bool) -> Image.Image:
    """Open a source at its full resolution for an original-size page.

    Unlike the JPEG pipeline there is no downscale and no lossy round-trip; the
    only changes are EXIF uprighting (so phone shots are not sideways) and
    converting modes the PDF writer cannot store.
    """
    image = load_image(source)
    if grayscale:
        return to_grayscale(image)
    if image.mode not in {"1", "L", "RGB", "CMYK"}:
        return image.convert("RGB")
    return image


def build_original_pdf(
    sources: Sequence[str | Path],
    destination: Path,
    options: PdfOptions,
    progress: Callable[[int, int], None] | None,
) -> PdfResult:
    """Write full-size pages in one top-quality encode (no size control).

    The ``quality`` keyword is forwarded to Pillow's nested JPEG encoder --
    without it every PDF page silently drops to Pillow's default quality of 75,
    which is exactly the double compression this mode exists to avoid.
    """
    total = len(sources)
    pages: list[Image.Image] = []
    for done, source in enumerate(sources, start=1):
        pages.append(load_original_page(source, options.grayscale))
        if progress is not None:
            progress(done, total)
    first, *rest = pages
    first.save(
        destination,
        format="PDF",
        save_all=True,
        append_images=rest,
        quality=ORIGINAL_QUALITY,
    )
    return PdfResult(
        destination, destination.stat().st_size, len(pages), ORIGINAL_QUALITY
    )


def shrink_pages(pages: Sequence[Image.Image]) -> list[Image.Image]:
    """Return every page down-scaled by :data:`SHRINK_FACTOR`.

    Used only as a fallback when no quality in the sweep meets the size target:
    once quality is exhausted, shedding pixels is the only lever left for making
    the file smaller.
    """
    smaller: list[Image.Image] = []
    for page in pages:
        longest_edge = max(page.width, page.height)
        target_edge = max(1, round(longest_edge * SHRINK_FACTOR))
        smaller.append(scale_image(page, max_edge=target_edge))
    return smaller


def quality_sweep(start: int) -> list[int]:
    """Quality values to try, from ``start`` down to :data:`QUALITY_FLOOR`.

    The floor is appended explicitly so it is always attempted even when the
    step size does not divide the range evenly.
    """
    values = list(range(start, QUALITY_FLOOR, -QUALITY_STEP))
    values.append(QUALITY_FLOOR)
    return values


def build_pdf(
    sources: Sequence[str | Path],
    dest: str | Path,
    options: PdfOptions,
    *,
    progress: Callable[[int, int], None] | None = None,
) -> PdfResult:
    """Render ``sources`` into a single PDF at ``dest`` and describe the result.

    With no size target the pages are written once at ``options.quality``. With a
    target we sweep quality downward and, if that is not enough, repeatedly
    down-scale, returning the first rendering that fits the budget -- or the
    smallest one achieved if none do -- so the caller always gets a file and can
    read back the quality it settled on.
    """
    items = list(sources)
    if not items:
        raise PdfError("cannot build a PDF from an empty list of sources")

    destination = Path(dest)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not options.jpeg_pages:
        return build_original_pdf(items, destination, options, progress)
    pages = prepare_pages(items, options, progress)
    page_count = len(pages)

    if options.target_mib <= 0:
        data = render_pdf_bytes(pages, options.quality)
        destination.write_bytes(data)
        return PdfResult(
            destination, destination.stat().st_size, page_count, options.quality
        )

    budget = round(options.target_mib * BYTES_PER_MIB)
    sweep = quality_sweep(options.quality)
    smallest: bytes | None = None
    smallest_quality = options.quality
    candidate_pages: Sequence[Image.Image] = pages
    for shrink_round in range(MAX_SHRINK_ROUNDS + 1):
        for quality in sweep:
            data = render_pdf_bytes(candidate_pages, quality)
            if smallest is None or len(data) < len(smallest):
                smallest = data
                smallest_quality = quality
            if len(data) <= budget:
                destination.write_bytes(data)
                return PdfResult(
                    destination, destination.stat().st_size, page_count, quality
                )
        if shrink_round < MAX_SHRINK_ROUNDS:
            candidate_pages = shrink_pages(candidate_pages)

    # Nothing met the budget: persist the smallest rendering we managed so the
    # caller still receives a usable file rather than an error.
    assert smallest is not None
    destination.write_bytes(smallest)
    return PdfResult(
        destination, destination.stat().st_size, page_count, smallest_quality
    )
