"""Tests for the model mask as an entry in the cut-out edit list."""

from __future__ import annotations

from PIL import Image

from myimages.imaging import cutout


def soft_mask(values: list[int], size: tuple[int, int] = (4, 1)) -> Image.Image:
    """An 'L' mask with the given pixel values."""
    mask = Image.new("L", size)
    mask.putdata(values)
    return mask


def gradient_mask(size: tuple[int, int] = (64, 64)) -> Image.Image:
    """A left-to-right ramp standing in for a model result."""
    mask = Image.new("L", size)
    width, height = size
    mask.putdata(
        [x * 255 // (width - 1) for row in range(height) for x in range(width)]
    )
    return mask


def test_subject_mask_multiplies_into_the_fold() -> None:
    image = Image.new("RGB", (4, 1), (10, 20, 30))
    edit = cutout.SubjectMask(mask=soft_mask([255, 192, 128, 0]))
    folded = cutout.build_mask(image, [edit])
    assert list(folded.tobytes()) == [255, 192, 128, 0]


def test_an_earlier_erase_survives_the_model() -> None:
    """Multiply, not replace: a hand edit made first is not undone by the model."""
    image = Image.new("RGB", (4, 1), (10, 20, 30))
    erase = cutout.BrushStroke(dabs=((0.0, 0.5, 0.05),), restore=False)
    edit = cutout.SubjectMask(mask=soft_mask([255, 255, 255, 255]))
    folded = cutout.build_mask(image, [erase, edit])
    assert list(folded.tobytes())[0] == 0


def test_a_later_restore_brings_pixels_back() -> None:
    image = Image.new("RGB", (4, 1), (10, 20, 30))
    edit = cutout.SubjectMask(mask=soft_mask([0, 0, 0, 0]))
    restore = cutout.BrushStroke(dabs=((0.0, 0.5, 0.05),), restore=True)
    folded = cutout.build_mask(image, [edit, restore])
    assert list(folded.tobytes())[0] == 255


def test_the_stored_square_is_stretched_to_whatever_is_folded() -> None:
    edit = cutout.SubjectMask(mask=gradient_mask())
    for size in ((40, 24), (200, 150)):
        assert cutout.build_mask(Image.new("RGB", size), [edit]).size == size


def test_preview_and_full_resolution_agree() -> None:
    """One record has to serve both folds, or the saved file is not the preview."""
    edit = cutout.SubjectMask(mask=gradient_mask())
    small = cutout.apply_edits(Image.new("RGB", (200, 150)), [edit])
    large = cutout.apply_edits(Image.new("RGB", (600, 450)), [edit])
    assert (
        cutout.coverage_fraction(small) == round(cutout.coverage_fraction(large), 10)
        or abs(cutout.coverage_fraction(small) - cutout.coverage_fraction(large))
        < 0.005
    )


def test_the_memo_returns_the_same_object_and_holds_one_size() -> None:
    edit = cutout.SubjectMask(mask=gradient_mask())
    first = edit.at((40, 24))
    assert edit.at((40, 24)) is first
    edit.at((80, 48))
    assert list(edit.scaled) == [(80, 48)]


def test_two_records_with_the_same_mask_compare_equal() -> None:
    """The memo must not leak into equality, or undo state stops comparing."""
    mask = gradient_mask()
    first = cutout.SubjectMask(mask=mask)
    second = cutout.SubjectMask(mask=mask)
    first.at((40, 24))
    assert first == second


def test_soften_feathers_a_model_edge_too() -> None:
    image = Image.new("RGB", (64, 64), (10, 20, 30))
    edit = cutout.SubjectMask(mask=soft_mask([0, 0, 255, 255], (4, 1)))
    hard = cutout.build_mask(image, [edit])
    soft = cutout.build_mask(image, [edit], soften=3.0)
    assert len(set(soft.tobytes())) > len(set(hard.tobytes()))
