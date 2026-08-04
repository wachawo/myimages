"""Tests for the ISNet background-removal module.

Nothing here touches the network or the real 170 MiB model. A 179-byte ONNX
fixture with the same interface stands in for the weights, so the real
preprocess/run/postprocess path executes against a real onnxruntime session.
"""

from __future__ import annotations

import hashlib
import importlib.util
import io
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from PIL import Image

from myimages.imaging import segment

FIXTURE = Path(__file__).parent / "data" / "tiny_isnet.onnx"


@pytest.fixture(autouse=True)
def clear_sessions():
    """Never let one test's cached session answer another test's question."""
    segment.release_session()
    yield
    segment.release_session()


@pytest.fixture
def tiny_model(monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the module at the committed fixture instead of the real weights."""
    monkeypatch.setenv(segment.MODEL_PATH_ENV, str(FIXTURE))
    return FIXTURE


class FakeResponse(io.BytesIO):
    """A urlopen stand-in: a byte source that is also a context manager."""

    def __init__(self, body: bytes, headers: dict[str, str] | None = None) -> None:
        super().__init__(body)
        self.headers = headers if headers is not None else {}

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *unused: object) -> None:
        self.close()


def fake_opener(body: bytes, headers: dict[str, str] | None = None):
    """An opener that serves ``body`` instead of reaching the network."""

    def opener(url: str) -> FakeResponse:
        return FakeResponse(body, headers)

    return opener


def gradient(size: tuple[int, int] = (40, 24)) -> Image.Image:
    """A picture whose channels vary, so a mask off it varies too."""
    image = Image.new("RGB", size)
    width, height = size
    image.putdata(
        [
            (x * 255 // max(1, width - 1), y * 255 // max(1, height - 1), 128)
            for y in range(height)
            for x in range(width)
        ]
    )
    return image


def test_is_available_reports_both_packages(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    assert segment.is_available() is True
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
    assert segment.is_available() is False


def test_is_available_needs_numpy_as_well(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        importlib.util, "find_spec", lambda name: None if name == "numpy" else object()
    )
    assert segment.is_available() is False


def test_model_path_defaults_into_the_data_dir(isolated_data_dir: Path) -> None:
    assert segment.model_path() == isolated_data_dir / "models" / segment.MODEL_FILENAME


def test_model_path_honours_the_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(segment.MODEL_PATH_ENV, str(tmp_path / "other.onnx"))
    assert segment.model_path() == tmp_path / "other.onnx"


def test_empty_override_falls_back_rather_than_the_cwd(
    monkeypatch: pytest.MonkeyPatch, isolated_data_dir: Path
) -> None:
    monkeypatch.setenv(segment.MODEL_PATH_ENV, "")
    assert segment.model_path().parent == isolated_data_dir / "models"


def test_model_present_follows_the_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    target = tmp_path / "weights.onnx"
    monkeypatch.setenv(segment.MODEL_PATH_ENV, str(target))
    assert segment.model_present() is False
    target.write_bytes(b"x")
    assert segment.model_present() is True


def test_file_digest_reads_in_chunks(tmp_path: Path) -> None:
    body = bytes(range(256)) * 4096  # comfortably more than one chunk
    path = tmp_path / "blob.bin"
    path.write_bytes(body)
    assert segment.file_digest(path) == hashlib.sha256(body).hexdigest()


def test_response_total_falls_back_without_a_header() -> None:
    assert segment.response_total(FakeResponse(b"", {})) == segment.MODEL_BYTES
    assert segment.response_total(FakeResponse(b"", {"Content-Length": "7"})) == 7
    assert (
        segment.response_total(FakeResponse(b"", {"Content-Length": "nonsense"}))
        == segment.MODEL_BYTES
    )


def test_download_writes_verifies_and_renames(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    body = FIXTURE.read_bytes()
    destination = tmp_path / "models" / "weights.onnx"
    monkeypatch.setenv(segment.MODEL_PATH_ENV, str(destination))
    monkeypatch.setattr(segment, "MODEL_SHA256", hashlib.sha256(body).hexdigest())
    ticks: list[tuple[int, int]] = []

    result = segment.download_model(
        on_progress=lambda done, total: ticks.append((done, total)),
        opener=fake_opener(body, {"Content-Length": str(len(body))}),
    )

    assert result == destination
    assert destination.read_bytes() == body
    assert list(destination.parent.glob("*.part")) == []
    assert ticks[-1] == (len(body), len(body))


def test_download_rejects_a_bad_checksum(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    destination = tmp_path / "models" / "weights.onnx"
    monkeypatch.setenv(segment.MODEL_PATH_ENV, str(destination))

    with pytest.raises(segment.SegmentationUnavailable, match="checksum"):
        segment.download_model(opener=fake_opener(b"not the model"))

    assert destination.exists() is False
    assert list(destination.parent.glob("*.part")) == []


def test_download_cancels_between_chunks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    destination = tmp_path / "models" / "weights.onnx"
    monkeypatch.setenv(segment.MODEL_PATH_ENV, str(destination))
    monkeypatch.setattr(segment, "CHUNK_BYTES", 8)
    seen: list[int] = []

    def cancel_after_one() -> bool:
        seen.append(1)
        return len(seen) > 1

    with pytest.raises(segment.SegmentationUnavailable, match="cancelled"):
        segment.download_model(
            should_cancel=cancel_after_one, opener=fake_opener(b"x" * 64)
        )

    assert destination.exists() is False
    assert list(destination.parent.glob("*.part")) == []


def test_download_leaves_nothing_behind_when_the_connection_dies(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    destination = tmp_path / "models" / "weights.onnx"
    monkeypatch.setenv(segment.MODEL_PATH_ENV, str(destination))

    def dying_opener(url: str) -> FakeResponse:
        raise urllib.error.URLError("no route to host")

    with pytest.raises(urllib.error.URLError):
        segment.download_model(opener=dying_opener)

    assert destination.exists() is False
    assert list(destination.parent.glob("*.part")) == []


def test_two_attempts_use_distinct_temporary_names(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Two editor windows share one process, so a per-process name would clash."""
    destination = tmp_path / "models" / "weights.onnx"
    monkeypatch.setenv(segment.MODEL_PATH_ENV, str(destination))
    names: list[str] = []

    class RecordingResponse(FakeResponse):
        """Notes which partial file exists at the moment the body is read."""

        def read(self, size: int = -1) -> bytes:
            names.extend(item.name for item in destination.parent.glob("*.part"))
            return super().read(size)

    for attempt in range(2):
        with pytest.raises(segment.SegmentationUnavailable):
            segment.download_model(opener=lambda url: RecordingResponse(b"wrong"))

    assert len(set(names)) == 2


def test_preprocess_produces_the_declared_tensor() -> None:
    tensor = segment.preprocess(gradient((1600, 400)))
    assert tensor.shape == (1, 3, 1024, 1024)
    assert tensor.dtype.name == "float32"
    assert tensor.flags["C_CONTIGUOUS"] is True


def test_preprocess_divides_by_the_peak_not_by_255() -> None:
    """The inherited rembg divisor. Correcting it changes every saved cut-out."""
    dim = Image.new("RGB", (64, 64), (200, 100, 50))
    assert segment.preprocess(dim).max() == pytest.approx(0.5)


def test_preprocess_survives_an_all_black_image() -> None:
    tensor = segment.preprocess(Image.new("RGB", (8, 8), (0, 0, 0)))
    assert float(tensor.min()) == pytest.approx(-0.5)
    assert float(tensor.max()) == pytest.approx(-0.5)


def test_postprocess_stretches_and_truncates() -> None:
    import numpy

    prediction = numpy.array([[[[0.0, 0.25], [0.5, 1.0]]]], dtype=numpy.float32)
    mask = segment.postprocess(prediction)
    assert mask.mode == "L"
    assert mask.size == (2, 2)
    # 0.25 * 255 = 63.75, truncated to 63 rather than rounded to 64.
    assert list(mask.tobytes()) == [0, 63, 127, 255]


def test_postprocess_of_a_flat_prediction_is_black_not_nan() -> None:
    import numpy

    mask = segment.postprocess(numpy.full((1, 1, 4, 4), 3.0, dtype=numpy.float32))
    assert set(mask.tobytes()) == {0}


def test_load_session_without_the_extra(
    monkeypatch: pytest.MonkeyPatch, tiny_model: Path
) -> None:
    monkeypatch.setattr(segment, "is_available", lambda: False)
    with pytest.raises(segment.SegmentationUnavailable, match="onnxruntime"):
        segment.load_session()


def test_load_session_without_the_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(segment.MODEL_PATH_ENV, str(tmp_path / "absent.onnx"))
    with pytest.raises(segment.SegmentationUnavailable, match="missing"):
        segment.load_session()


def test_load_session_on_a_damaged_file_says_so(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A truncated download and a captive-portal login page both land here."""
    broken = tmp_path / "broken.onnx"
    broken.write_bytes(b"<html>404</html>")
    monkeypatch.setenv(segment.MODEL_PATH_ENV, str(broken))
    with pytest.raises(segment.SegmentationUnavailable, match="could not be loaded"):
        segment.load_session()


def test_load_session_caches_and_release_clears(tiny_model: Path) -> None:
    first = segment.load_session()
    assert segment.load_session() is first
    segment.release_session()
    assert segment.SESSIONS == {}


def test_subject_mask_runs_the_real_path(tiny_model: Path) -> None:
    mask = segment.subject_mask(gradient())
    assert mask.mode == "L"
    assert mask.size == segment.INPUT_SIZE
    low, high = mask.getextrema()
    assert low < high


def test_subject_mask_reads_the_graphs_names(tiny_model: Path) -> None:
    """The fixture names its tensors 'input'/'output', not the model's names."""
    session = segment.load_session()
    assert session.get_inputs()[0].name == "input"
    assert segment.subject_mask(gradient(), session=session).size == segment.INPUT_SIZE


def test_the_suite_never_downloads_the_real_model(isolated_data_dir: Path) -> None:
    """Fails loudly if a real 179 MB fetch ever escapes into CI."""
    assert list(isolated_data_dir.rglob("*.onnx")) == []


def test_open_model_url_passes_a_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """A stalled socket must fail rather than hold a worker thread for ever."""
    seen: dict[str, object] = {}

    def fake_urlopen(url: str, timeout: int | None = None) -> str:
        seen["url"] = url
        seen["timeout"] = timeout
        return "response"

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert segment.open_model_url(segment.MODEL_URL) == "response"
    assert seen == {"url": segment.MODEL_URL, "timeout": segment.REQUEST_TIMEOUT}
