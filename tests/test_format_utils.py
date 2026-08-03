"""Tests for :mod:`myimages.format_utils`.

Both helpers are pure functions, so the tests assert exact formatted strings at
every unit boundary and for the zero/negative edge cases.
"""

from __future__ import annotations

import pytest

from myimages.format_utils import human_readable_duration, human_readable_size


@pytest.mark.parametrize(
    ("num_bytes", "expected"),
    [
        (0, "0 B"),
        (-1, "0 B"),
        (-4096, "0 B"),
        (1, "1 B"),
        (500, "500 B"),
        (1023, "1023 B"),
        (1024, "1.0 KB"),
        (1536, "1.5 KB"),
        (1024 * 1024 - 1, "1024.0 KB"),
        (1024 * 1024, "1.0 MB"),
        (int(2.5 * 1024 * 1024), "2.5 MB"),
        (1024**3, "1.0 GB"),
        (3 * 1024**3, "3.0 GB"),
        (1024**4, "1.0 TB"),
        (5 * 1024**4, "5.0 TB"),
    ],
)
def test_human_readable_size(num_bytes: int, expected: str) -> None:
    assert human_readable_size(num_bytes) == expected


def test_human_readable_size_beyond_tb_stays_in_tb() -> None:
    # Nothing larger than TB exists, so huge values remain expressed in TB.
    assert human_readable_size(1024**5) == "1024.0 TB"


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0, "0:00"),
        (-5, "0:00"),
        (5, "0:05"),
        (45, "0:45"),
        (59, "0:59"),
        (60, "1:00"),
        (90, "1:30"),
        (599, "9:59"),
        (600, "10:00"),
        (3600, "1:00:00"),
        (3661, "1:01:01"),
        (7262, "2:01:02"),
        (36000, "10:00:00"),
    ],
)
def test_human_readable_duration(seconds: int, expected: str) -> None:
    assert human_readable_duration(seconds) == expected


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0.4, "0:00"),
        (59.6, "1:00"),
        (65.4, "1:05"),
        (3599.6, "1:00:00"),
    ],
)
def test_human_readable_duration_rounds_fractional_seconds(
    seconds: float, expected: str
) -> None:
    assert human_readable_duration(seconds) == expected
