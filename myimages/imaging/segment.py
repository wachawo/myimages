"""Find a photo's subject with the ISNet model, through onnxruntime alone.

The weights are the ones the popular background removers use, but reached
directly rather than through rembg: rembg pulls in scipy, opencv and
scikit-image for post-processing this app does not want -- about 460 MB of
transitive closure -- where the ISNet path itself needs only numpy on top of
onnxruntime. The 170 MiB model is fetched on first use rather than shipped,
because most users never touch the feature and bundling it would nearly triple
every release artifact.

Nothing beyond the standard library and Pillow is imported at module scope: the
whole point of the ``bgremove`` extra is that the app starts and runs without
it, so every heavy import happens inside the function that needs it and the
annotations that name those packages are strings under PEP 563.

This module returns a *mask*, never a composited RGBA image. Compositing here
would have to replace the alpha channel, which would silently throw away every
brush stroke the user had already made; instead the mask joins the ordered edit
list in :mod:`myimages.imaging.cutout` and folds in with everything else.
"""

from __future__ import annotations

import hashlib
import importlib.util
import os
import threading
import urllib.request
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PIL import Image

from myimages.paths import models_dir

if TYPE_CHECKING:
    import numpy as np
    import numpy.typing as npt
    import onnxruntime as ort

MODEL_URL = (
    "https://github.com/danielgatis/rembg/releases/download/v0.0.0/"
    "isnet-general-use.onnx"
)
MODEL_SHA256 = "60920e99c45464f2ba57bee2ad08c919a52bbf852739e96947fbb4358c0d964a"
MODEL_FILENAME = "isnet-general-use.onnx"
MODEL_BYTES = 178_648_008

# Tests and power users point this at another file. It is also how the suite
# runs the real inference path against a tiny fixture instead of the weights.
MODEL_PATH_ENV = "MYIMAGES_ISNET_MODEL"

# The graph declares a fixed 1024x1024 input with no dynamic axes, so this is
# the model's own size rather than a tuning knob.
INPUT_SIZE = (1024, 1024)

# Read the body in chunks so a 170 MiB download never sits in memory whole, and
# so cancelling is answered within one chunk rather than at the end.
CHUNK_BYTES = 256 * 1024

# A stalled socket has to fail rather than hold a worker thread for ever.
REQUEST_TIMEOUT = 30

# Inference is deliberately not given every core. Saturating a 24-core machine
# for half a second makes the whole interface stutter, and the tools around
# this one stay live while it runs.
INFERENCE_THREADS = 4

ProgressHandler = Callable[[int, int], None]
CancelCheck = Callable[[], bool]
Opener = Callable[[str], Any]

SESSIONS: dict[Path, ort.InferenceSession] = {}

# Building a session costs about half a second and several hundred megabytes.
# Two workers racing into an empty cache would each pay that and one would be
# thrown away after the peak allocation had already happened.
SESSION_LOCK = threading.Lock()


class SegmentationUnavailable(RuntimeError):
    """Background removal cannot run, with a sentence saying why.

    Carries text written to be shown to a user rather than logged: the GUI runs
    this module through a worker seam that reduces an exception to ``str``, so
    the message is the only thing that survives to the interface.
    """


def is_available() -> bool:
    """Whether onnxruntime and numpy can both be imported right now."""
    return all(
        importlib.util.find_spec(name) is not None for name in ("numpy", "onnxruntime")
    )


def model_path() -> Path:
    """Where the weights live; ``MYIMAGES_ISNET_MODEL`` overrides the default.

    Reads the variable with ``or`` rather than a ``getenv`` default so that a
    variable set to the empty string falls back instead of resolving to
    ``Path("")``, which is the current directory.
    """
    override = os.environ.get(MODEL_PATH_ENV) or ""
    if override:
        return Path(override).expanduser()
    return models_dir() / MODEL_FILENAME


def model_present() -> bool:
    """Whether the weights have already been fetched.

    Existence alone, with no size or digest check: :func:`download_model` never
    puts anything at this path until it has verified it, so a truncated file
    cannot arrive here in the first place.
    """
    return model_path().is_file()


def file_digest(path: Path) -> str:
    """SHA-256 of a file, read in chunks so 170 MiB never lands in memory."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK_BYTES), b""):
            digest.update(block)
    return digest.hexdigest()


def open_model_url(url: str) -> Any:
    """Open the model URL with a timeout, so a dead connection cannot hang.

    Returns ``Any`` rather than a context-manager type because typeshed gives
    ``urlopen`` no useful one, and declaring a concrete type here only produces
    a ``no-any-return`` error at the boundary.
    """
    return urllib.request.urlopen(url, timeout=REQUEST_TIMEOUT)  # noqa: S310


def response_total(response: Any) -> int:
    """The download's size in bytes, falling back to the known model size.

    A proxy that strips ``Content-Length`` would otherwise leave the progress
    bar indeterminate for a 179 MB transfer, which is exactly the transfer that
    most needs a determinate one.
    """
    raw = response.headers.get("Content-Length")
    if raw is None:
        return MODEL_BYTES
    try:
        return int(raw)
    except ValueError:
        return MODEL_BYTES


def download_model(
    on_progress: ProgressHandler | None = None,
    should_cancel: CancelCheck | None = None,
    opener: Opener = open_model_url,
) -> Path:
    """Fetch, verify and install the weights, or raise saying what stopped it.

    Writes to a uniquely named neighbour and renames only after the digest
    matches, so a file at the destination is always a file that verified. The
    temporary name is unique per *attempt* rather than per process because two
    editor windows share one process and would otherwise interleave two byte
    streams into one file.
    """
    destination = model_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_name(f"{destination.name}.{uuid.uuid4().hex}.part")
    try:
        received = 0
        with opener(MODEL_URL) as response, partial.open("wb") as handle:
            total = response_total(response)
            for block in iter(lambda: response.read(CHUNK_BYTES), b""):
                if should_cancel is not None and should_cancel():
                    raise SegmentationUnavailable("Download cancelled")
                handle.write(block)
                received += len(block)
                if on_progress is not None:
                    on_progress(received, total)
        if file_digest(partial) != MODEL_SHA256:
            raise SegmentationUnavailable(
                "The downloaded model did not match its checksum, so it was "
                "discarded. The download was interrupted or altered in transit."
            )
        partial.replace(destination)
    except BaseException:
        # BaseException rather than Exception so that Ctrl-C cannot leave a
        # 179 MB orphan behind either.
        partial.unlink(missing_ok=True)
        raise
    return destination


def load_session(path: Path | None = None) -> ort.InferenceSession:
    """Build, or hand back, the inference session for the weights at ``path``.

    Raises :class:`SegmentationUnavailable` when the extra is not installed,
    when the file is absent, or when onnxruntime cannot parse it -- the last of
    which is what a half-downloaded or bit-rotted file looks like, and would
    otherwise surface as a protobuf error no user can act on. Sessions are
    cached by path so that changing the override rebuilds rather than silently
    returning a stale one.
    """
    if not is_available():
        raise SegmentationUnavailable(
            "Automatic background removal needs the onnxruntime package."
        )
    resolved = path if path is not None else model_path()
    if not resolved.is_file():
        raise SegmentationUnavailable(f"The model file is missing: {resolved}")
    import onnxruntime

    with SESSION_LOCK:
        cached = SESSIONS.get(resolved)
        if cached is not None:
            return cached
        options = onnxruntime.SessionOptions()
        options.intra_op_num_threads = INFERENCE_THREADS
        try:
            session = onnxruntime.InferenceSession(
                str(resolved), options, providers=["CPUExecutionProvider"]
            )
        except Exception as error:  # noqa: BLE001 - reported to the user as text
            raise SegmentationUnavailable(
                f"The model file could not be loaded: {type(error).__name__}"
            ) from error
        SESSIONS[resolved] = session
        return session


def release_session() -> None:
    """Drop every cached session, handing back the memory it held.

    One session plus one inference costs roughly a gigabyte of resident memory
    and onnxruntime never gives it back on its own. A photo manager left open
    all day should not carry that because someone removed one background at
    lunchtime; the price is about a second to rebuild if they come back. Safe
    while an inference is running: that worker holds its own reference.
    """
    with SESSION_LOCK:
        SESSIONS.clear()


def preprocess(image: Image.Image) -> npt.NDArray[np.float32]:
    """Turn a picture into ISNet's 1x3x1024x1024 float32 input tensor.

    Transcribed step for step from rembg, including two things that look like
    mistakes and are not to be corrected. The resize to a square ignores aspect
    ratio with no padding -- the distortion is undone when the mask is stretched
    back at fold time -- and the tensor is divided by the image's own peak value
    rather than by 255. The ISNet reference divides by 255; the divide-by-peak
    comes from U-2-Net's preprocessing, which rembg applied to every model it
    hosts. It is kept because these are rembg's weights, and changing the
    preprocessing changes every cut-out this feature produces.
    """
    import numpy

    resized = image.convert("RGB").resize(INPUT_SIZE, Image.Resampling.LANCZOS)
    array = numpy.asarray(resized, dtype=numpy.float32)
    # A single scalar over height, width and channel jointly. A per-channel
    # peak would be a white-balance change rather than an exposure one.
    peak = float(array.max())
    if peak > 0:
        array = array / peak
    array = array - 0.5
    planar = array.transpose(2, 0, 1)[numpy.newaxis, ...]
    # ascontiguousarray earns its place twice: onnxruntime wants a contiguous
    # buffer, and numpy's newer stubs lose the dtype through .transpose(), so
    # returning the chain directly would be returning Any under strict mypy.
    return numpy.ascontiguousarray(planar, dtype=numpy.float32)


def postprocess(prediction: Any) -> Image.Image:
    """Turn one raw model output into an 'L' mask at the model's own size.

    Deliberately does not resize to any source: the mask is stored at 1024
    square and stretched at fold time, so one inference serves both the preview
    and the full-resolution save. ``prediction`` is typed ``Any`` because
    onnxruntime ships no type information and everything out of a session is
    genuinely unknown to the checker.
    """
    import numpy

    plane = numpy.asarray(prediction, dtype=numpy.float32)[0, 0]
    low = float(plane.min())
    high = float(plane.max())
    # The epsilon is what keeps a flat prediction from dividing by zero and
    # producing a mask full of nan; rembg divides bare and does produce one.
    scaled = (plane - low) / (high - low + 1e-8)
    # astype truncates rather than rounds, which is what rembg does, so the
    # values match the tool these weights came from.
    return Image.fromarray(numpy.asarray(scaled * 255, dtype=numpy.uint8), mode="L")


def subject_mask(
    image: Image.Image, session: ort.InferenceSession | None = None
) -> Image.Image:
    """Where the model thinks the subject is, as a 1024x1024 'L' mask.

    White is subject, black is background. The cost does not depend on
    ``image``: the graph only ever sees a 1024 square, so a screen-sized
    preview and a 6000px original take the same half-second.
    """
    active = session if session is not None else load_session()
    tensor = preprocess(image)
    # Both names are read off the graph rather than written down. The real
    # model declares twelve outputs, of which the first carries the mask;
    # naming it avoids wrapping the other ~120 MB into numpy on every call.
    input_name = active.get_inputs()[0].name
    output_name = active.get_outputs()[0].name
    outputs = active.run([output_name], {input_name: tensor})
    return postprocess(outputs[0])
