"""Tests for the save-destination policy (myimages.imaging.save_policy).

The format facts asserted here were measured against the installed Pillow, not
taken from documentation, because the interesting cases are the ones where a
format accepts the save and quietly changes the picture.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from myimages.imaging import save_policy


def transparent_image(size: tuple[int, int] = (8, 8)) -> Image.Image:
    """A fully transparent RGBA square."""
    return Image.new("RGBA", size, (255, 0, 0, 0))


def graded_image(width: int = 16) -> Image.Image:
    """A one-pixel-tall strip whose alpha ramps from clear to opaque."""
    strip = Image.new("RGBA", (width, 1))
    for x in range(width):
        strip.putpixel((x, 0), (255, 0, 0, round(x * 255 / (width - 1))))
    return strip


def alpha_values(path: Path) -> set[int]:
    """Every distinct alpha value in the saved file, read back from disk.

    ``getcolors`` rather than the pixel sequence: it is stable across the
    Pillow versions this project supports, where the pixel accessors were
    renamed.
    """
    reopened = Image.open(path).convert("RGBA")
    counted = reopened.getchannel("A").getcolors(maxcolors=256) or []
    return {value for count, value in counted}


def test_alpha_safe_suffixes_keep_transparency(tmp_path):
    """png, webp and tiff round-trip a transparent pixel unchanged."""
    for suffix in sorted(save_policy.ALPHA_SAFE_SUFFIXES):
        destination = tmp_path / f"clear{suffix}"
        transparent_image().save(destination)
        assert alpha_values(destination) == {0}, suffix
        assert save_policy.supports_alpha(suffix), suffix


def test_gif_survives_a_flat_cutout_but_destroys_a_graded_edge(tmp_path):
    """Why GIF is excluded: it keeps a clear pixel but flattens a soft edge."""
    flat = tmp_path / "flat.gif"
    transparent_image().save(flat)
    assert alpha_values(flat) == {0}

    graded = tmp_path / "graded.gif"
    graded_image().save(graded)
    assert alpha_values(graded) == {255}
    assert not save_policy.supports_alpha(".gif")


def test_bmp_discards_transparency_without_complaining(tmp_path):
    """Why BMP is excluded: the save succeeds and the alpha is simply gone."""
    destination = tmp_path / "clear.bmp"
    transparent_image().save(destination)
    assert alpha_values(destination) == {255}
    assert not save_policy.supports_alpha(".bmp")


def test_jpeg_refuses_an_alpha_mode_whatever_the_pixels_hold():
    """Pillow rejects the mode, not the transparency; opaque RGBA fails too."""
    with pytest.raises(OSError):
        Image.new("RGBA", (8, 8), (1, 2, 3, 255)).save("/dev/null", format="JPEG")


def test_has_transparency_looks_at_pixels_not_only_at_the_mode():
    """An opaque RGBA image loses nothing by being flattened, so it is not it."""
    assert save_policy.has_transparency(transparent_image())
    assert not save_policy.has_transparency(Image.new("RGBA", (8, 8), (0, 0, 0, 255)))
    assert not save_policy.has_transparency(Image.new("RGB", (8, 8)))
    assert save_policy.has_transparency(Image.new("LA", (8, 8), (10, 0)))


def test_has_transparency_reads_a_palette_images_info():
    """Palette transparency lives in ``info``, not in a channel."""
    palette = Image.new("P", (8, 8))
    assert not save_policy.has_transparency(palette)
    palette.info["transparency"] = 0
    assert save_policy.has_transparency(palette)


def test_overwrite_keeps_the_path_when_the_result_is_opaque(tmp_path):
    """The common case: nothing transparent, so nothing is diverted."""
    source = tmp_path / "photo.jpg"
    plan = save_policy.overwrite_plan(source, transparent=False)
    assert plan == save_policy.SavePlan(source, retargeted=False)


def test_overwrite_keeps_the_path_when_the_format_holds_alpha(tmp_path):
    """A cut-out over a PNG genuinely overwrites it."""
    source = tmp_path / "photo.png"
    plan = save_policy.overwrite_plan(source, transparent=True)
    assert plan == save_policy.SavePlan(source, retargeted=False)


def test_overwrite_diverts_a_cutout_to_a_sibling_png(tmp_path):
    """The rule that protects the photograph: the JPEG is not touched."""
    source = tmp_path / "photo.jpg"
    source.write_bytes(b"original")
    plan = save_policy.overwrite_plan(source, transparent=True)
    assert plan.destination == tmp_path / "photo.png"
    assert plan.retargeted
    assert source.read_bytes() == b"original"


def test_overwrite_avoids_clobbering_an_existing_sibling(tmp_path):
    """A photo.png already beside photo.jpg is somebody else's file."""
    (tmp_path / "photo.png").write_bytes(b"someone else")
    plan = save_policy.overwrite_plan(tmp_path / "photo.jpg", transparent=True)
    assert plan.destination == tmp_path / "photo_2.png"

    (tmp_path / "photo_2.png").write_bytes(b"also taken")
    plan = save_policy.overwrite_plan(tmp_path / "photo.jpg", transparent=True)
    assert plan.destination == tmp_path / "photo_3.png"


def test_copy_plan_keeps_the_suffix_for_an_opaque_result(tmp_path):
    """Save as Copy of a normal edit stays in the source format."""
    plan = save_policy.copy_plan(tmp_path / "photo.jpg", transparent=False)
    assert plan == save_policy.SavePlan(tmp_path / "photo_copy.jpg", retargeted=False)


def test_copy_plan_switches_to_png_for_a_cutout(tmp_path):
    """A transparent copy of a JPEG has to change format to survive."""
    plan = save_policy.copy_plan(tmp_path / "photo.jpg", transparent=True)
    assert plan == save_policy.SavePlan(tmp_path / "photo_copy.png", retargeted=True)


def test_copy_plan_counts_up_past_existing_copies(tmp_path):
    """The clash loop runs against the new suffix, not the source's."""
    (tmp_path / "photo_copy.png").write_bytes(b"taken")
    plan = save_policy.copy_plan(tmp_path / "photo.jpg", transparent=True)
    assert plan.destination == tmp_path / "photo_copy2.png"


def test_flatten_replaces_transparency_with_the_chosen_colour():
    """Transparent regions become the background, not Pillow's default black."""
    flattened = save_policy.flatten_onto_background(transparent_image(), (0, 0, 255))
    assert flattened.mode == "RGB"
    assert flattened.getpixel((0, 0)) == (0, 0, 255)
