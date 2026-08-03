"""Tests for :mod:`myimages.core.rename`.

These exercise real files on ``tmp_path`` rather than mocks, because the point
of the module is safe, correct filesystem moves -- especially the two-phase
swap -- which only a genuine rename on disk can prove.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import pytest

from myimages.core.media import build_media_file
from myimages.core.rename import (
    RenameError,
    RenamePlanItem,
    apply_rename_plan,
    build_rename_plan,
    find_collisions,
)


def write_file(path: Path, text: str = "x") -> Path:
    """Create a small real file so renames have something to move."""
    path.write_text(text)
    return path


def test_pattern_tokens_render_expected_names(tmp_path: Path) -> None:
    first = write_file(tmp_path / "a.jpg")
    second = write_file(tmp_path / "b.png")
    plan = build_rename_plan([first, second], "{parent}_{name}_{n:03}.{ext}")
    parent = tmp_path.name
    assert plan[0].target == tmp_path / f"{parent}_a_001.jpg"
    assert plan[1].target == tmp_path / f"{parent}_b_002.png"


def test_date_token_uses_modified_time_of_media_file(tmp_path: Path) -> None:
    photo = write_file(tmp_path / "p.jpg")
    when = datetime(2021, 6, 15, 12, 0).timestamp()
    os.utime(photo, (when, when))
    media = build_media_file(photo)  # exercises the MediaFile input branch
    plan = build_rename_plan([media], "shot_{date}.{ext}")
    assert plan[0].target.name == "shot_20210615.jpg"


def test_start_and_step_control_the_sequence(tmp_path: Path) -> None:
    files = [write_file(tmp_path / f"f{i}.txt") for i in range(3)]
    plan = build_rename_plan(files, "{n}.{ext}", start=10, step=5)
    assert [item.target.name for item in plan] == ["10.txt", "15.txt", "20.txt"]


def test_index_token_is_zero_based(tmp_path: Path) -> None:
    files = [write_file(tmp_path / f"f{i}.txt") for i in range(2)]
    plan = build_rename_plan(files, "{index}.{ext}")
    assert [item.target.name for item in plan] == ["0.txt", "1.txt"]


def test_unknown_token_raises_rename_error(tmp_path: Path) -> None:
    photo = write_file(tmp_path / "p.jpg")
    with pytest.raises(RenameError):
        build_rename_plan([photo], "{nope}.{ext}")


def test_duplicate_targets_are_collisions(tmp_path: Path) -> None:
    a = write_file(tmp_path / "a.jpg")
    b = write_file(tmp_path / "b.jpg")
    plan = build_rename_plan([a, b], "same.jpg")  # both map to one name
    assert find_collisions(plan) == [tmp_path / "same.jpg"]


def test_existing_target_collides_unless_it_is_a_source(tmp_path: Path) -> None:
    a = write_file(tmp_path / "a.jpg")
    write_file(tmp_path / "occupied.jpg")
    plan = build_rename_plan([a], "occupied.jpg")
    assert find_collisions(plan) == [tmp_path / "occupied.jpg"]

    b = write_file(tmp_path / "b.jpg")
    swap = [
        RenamePlanItem(source=a, target=b),
        RenamePlanItem(source=b, target=a),
    ]
    assert find_collisions(swap) == []  # each existing target is a plan source


def test_swap_applies_via_two_phase_rename(tmp_path: Path) -> None:
    a = write_file(tmp_path / "a.txt", "content-a")
    b = write_file(tmp_path / "b.txt", "content-b")
    plan = [
        RenamePlanItem(source=a, target=b),
        RenamePlanItem(source=b, target=a),
    ]
    results = apply_rename_plan(plan)
    assert a.read_text() == "content-b"
    assert b.read_text() == "content-a"
    assert results == [(a, b), (b, a)]


def test_apply_refuses_when_targets_collide(tmp_path: Path) -> None:
    a = write_file(tmp_path / "a.jpg")
    b = write_file(tmp_path / "b.jpg")
    plan = build_rename_plan([a, b], "same.jpg")
    with pytest.raises(RenameError):
        apply_rename_plan(plan)
    assert a.exists()  # guard runs before any move, so nothing was touched
    assert b.exists()


def test_apply_creates_missing_target_directories(tmp_path: Path) -> None:
    photo = write_file(tmp_path / "p.jpg", "data")
    plan = build_rename_plan([photo], "sub/renamed_{n:03}.{ext}")
    results = apply_rename_plan(plan)
    moved = tmp_path / "sub" / "renamed_001.jpg"
    assert moved.read_text() == "data"
    assert not photo.exists()
    assert results == [(photo, moved)]
