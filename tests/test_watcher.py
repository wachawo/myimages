"""Behavioural tests for :mod:`myimages.core.watcher`.

The module answers one question -- "did this folder change while we were looking
at it?" -- so the tests are written in those terms: a file appears, vanishes, is
re-saved, or is rewritten so cunningly that ``stat`` cannot tell. Real files on
disk and the real md5 hasher are used wherever the answer depends on actual
bytes; only the "was this path hashed at all?" cases inject a recording hasher,
because that fact is invisible from the outside otherwise.

No Qt is involved: this is the pure half of the folder-watching feature.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable
from pathlib import Path

from myimages.core.media import build_media_file
from myimages.core.watcher import (
    CHECKSUM_ALGORITHM,
    CHECKSUMS_PER_PASS,
    FileStamp,
    FolderChanges,
    carry_over_checksums,
    checksum_batch,
    diff_stamps,
    stamp_media,
    verify_checksums,
)


def recording_hasher(digests: dict[str, str], seen: list[str]) -> Callable[[str], str]:
    """A hasher that reports canned digests and records what it was asked for.

    Used only where the behaviour under test is *which paths get hashed*, which
    a real digest cannot reveal.
    """

    def hasher(path: str) -> str:
        seen.append(path)
        return digests[path]

    return hasher


# --------------------------------------------------------------------------
# FileStamp.differs_from
# --------------------------------------------------------------------------


def test_identical_stamps_do_not_differ() -> None:
    stamp = FileStamp(size=1024, modified_time=100.0)
    assert stamp.differs_from(FileStamp(size=1024, modified_time=100.0)) is False


def test_a_different_size_counts_as_changed() -> None:
    grown = FileStamp(size=2048, modified_time=100.0)
    assert grown.differs_from(FileStamp(size=1024, modified_time=100.0)) is True


def test_a_different_modified_time_counts_as_changed() -> None:
    touched = FileStamp(size=1024, modified_time=200.0)
    assert touched.differs_from(FileStamp(size=1024, modified_time=100.0)) is True


def test_two_known_checksums_that_disagree_count_as_changed() -> None:
    """The whole point of hashing: same size, same mtime, different bytes."""
    after = FileStamp(size=1024, modified_time=100.0, checksum="bbbb")
    before = FileStamp(size=1024, modified_time=100.0, checksum="aaaa")
    assert after.differs_from(before) is True


def test_two_matching_checksums_do_not_count_as_changed() -> None:
    after = FileStamp(size=1024, modified_time=100.0, checksum="aaaa")
    before = FileStamp(size=1024, modified_time=100.0, checksum="aaaa")
    assert after.differs_from(before) is False


def test_a_missing_checksum_means_unverified_not_changed() -> None:
    """A file the rotating batch has not reached yet must not look modified."""
    hashed = FileStamp(size=1024, modified_time=100.0, checksum="aaaa")
    unhashed = FileStamp(size=1024, modified_time=100.0)
    assert hashed.differs_from(unhashed) is False
    assert unhashed.differs_from(hashed) is False


# --------------------------------------------------------------------------
# FolderChanges
# --------------------------------------------------------------------------


def test_an_empty_change_set_reports_nothing_to_do() -> None:
    quiet = FolderChanges()
    assert quiet.has_changes is False
    assert quiet.stale_paths == ()


def test_any_single_kind_of_change_is_reported() -> None:
    assert FolderChanges(added=("/new.png",)).has_changes is True
    assert FolderChanges(removed=("/gone.png",)).has_changes is True
    assert FolderChanges(modified=("/edited.png",)).has_changes is True


def test_stale_paths_are_the_removed_and_modified_ones() -> None:
    """A brand new file has no cached thumbnail, so it is not stale."""
    changes = FolderChanges(
        added=("/new.png",), removed=("/gone.png",), modified=("/edited.png",)
    )
    assert changes.stale_paths == ("/gone.png", "/edited.png")
    assert "/new.png" not in changes.stale_paths


# --------------------------------------------------------------------------
# stamp_media
# --------------------------------------------------------------------------


def test_stamp_media_records_size_and_mtime_of_real_files(image_dir: Path) -> None:
    files = [build_media_file(path) for path in sorted(image_dir.iterdir())]

    stamps = stamp_media(files)

    assert set(stamps) == {str(path) for path in image_dir.iterdir()}
    for media_file in files:
        stat = media_file.path.stat()
        stamp = stamps[str(media_file.path)]
        assert stamp.size == stat.st_size
        assert stamp.modified_time == stat.st_mtime
        # A fresh snapshot has hashed nothing yet.
        assert stamp.checksum is None


def test_stamp_media_of_an_empty_scan_is_empty() -> None:
    assert stamp_media([]) == {}


def test_stamp_media_notices_a_file_that_grew(make_image: Callable[..., Path]) -> None:
    path = make_image("growing.png")
    before = stamp_media([build_media_file(path)])
    path.write_bytes(path.read_bytes() + b"trailing junk")
    after = stamp_media([build_media_file(path)])

    key = str(path)
    assert after[key].differs_from(before[key]) is True


# --------------------------------------------------------------------------
# carry_over_checksums
# --------------------------------------------------------------------------


def test_a_checksum_survives_a_pass_when_stat_is_unchanged() -> None:
    previous = {"/a.png": FileStamp(size=10, modified_time=1.0, checksum="aaaa")}
    current = {"/a.png": FileStamp(size=10, modified_time=1.0)}

    carried = carry_over_checksums(previous, current)

    assert carried["/a.png"].checksum == "aaaa"
    assert carried["/a.png"].size == 10
    assert carried["/a.png"].modified_time == 1.0


def test_a_checksum_is_dropped_when_the_size_moved() -> None:
    previous = {"/a.png": FileStamp(size=10, modified_time=1.0, checksum="aaaa")}
    current = {"/a.png": FileStamp(size=99, modified_time=1.0)}

    assert carry_over_checksums(previous, current)["/a.png"].checksum is None


def test_a_checksum_is_dropped_when_the_modified_time_moved() -> None:
    previous = {"/a.png": FileStamp(size=10, modified_time=1.0, checksum="aaaa")}
    current = {"/a.png": FileStamp(size=10, modified_time=2.0)}

    assert carry_over_checksums(previous, current)["/a.png"].checksum is None


def test_carrying_over_ignores_paths_the_new_snapshot_does_not_have() -> None:
    """Vanished files leave no trace, and brand new files start unverified."""
    previous = {
        "/gone.png": FileStamp(size=10, modified_time=1.0, checksum="aaaa"),
        "/kept.png": FileStamp(size=20, modified_time=2.0, checksum="bbbb"),
    }
    current = {
        "/kept.png": FileStamp(size=20, modified_time=2.0),
        "/fresh.png": FileStamp(size=30, modified_time=3.0),
    }

    carried = carry_over_checksums(previous, current)

    assert set(carried) == {"/kept.png", "/fresh.png"}
    assert carried["/kept.png"].checksum == "bbbb"
    assert carried["/fresh.png"].checksum is None


def test_carrying_over_never_invents_a_checksum_from_nothing() -> None:
    previous = {"/a.png": FileStamp(size=10, modified_time=1.0)}
    current = {"/a.png": FileStamp(size=10, modified_time=1.0)}

    assert carry_over_checksums(previous, current) == current


# --------------------------------------------------------------------------
# checksum_batch
# --------------------------------------------------------------------------


def test_a_batch_starts_at_the_cursor() -> None:
    paths = ["a", "b", "c", "d", "e"]
    assert checksum_batch(paths, 0, 2) == ["a", "b"]
    assert checksum_batch(paths, 2, 2) == ["c", "d"]


def test_a_batch_wraps_around_the_end_of_the_folder() -> None:
    paths = ["a", "b", "c", "d", "e"]
    assert checksum_batch(paths, 4, 3) == ["e", "a", "b"]


def test_a_cursor_past_the_end_wraps_back_to_the_start() -> None:
    """The cursor keeps growing across passes; only its remainder matters."""
    paths = ["a", "b", "c", "d", "e"]
    assert checksum_batch(paths, 7, 2) == ["c", "d"]
    assert checksum_batch(paths, 12, 2) == ["c", "d"]


def test_an_empty_folder_yields_no_work() -> None:
    assert checksum_batch([], 0, 4) == []
    assert checksum_batch([], 3, 4) == []


def test_a_batch_bigger_than_the_folder_hashes_each_file_once() -> None:
    paths = ["a", "b", "c"]
    batch = checksum_batch(paths, 1, 10)
    assert batch == ["b", "c", "a"]
    assert sorted(batch) == paths


def test_a_non_positive_batch_size_hashes_nothing() -> None:
    paths = ["a", "b", "c"]
    assert checksum_batch(paths, 0, 0) == []
    assert checksum_batch(paths, 1, -5) == []


def test_repeated_passes_eventually_cover_the_whole_folder() -> None:
    """The rotation exists so no file is left permanently unverified."""
    paths = [f"file{index}.png" for index in range(11)]
    seen: set[str] = set()
    for step in range(10):
        cursor = step * CHECKSUMS_PER_PASS
        seen.update(checksum_batch(paths, cursor, CHECKSUMS_PER_PASS))
    assert seen == set(paths)


# --------------------------------------------------------------------------
# verify_checksums
# --------------------------------------------------------------------------


def test_verifying_fills_in_checksums_without_touching_the_input() -> None:
    stamps = {"/a.png": FileStamp(size=10, modified_time=1.0)}
    seen: list[str] = []

    updated, content_changed = verify_checksums(
        stamps, ["/a.png"], recording_hasher({"/a.png": "aaaa"}, seen)
    )

    assert updated["/a.png"] == FileStamp(size=10, modified_time=1.0, checksum="aaaa")
    assert seen == ["/a.png"]
    # A first hash has nothing to disagree with, so it is not a change.
    assert content_changed == []
    # The caller's snapshot is left alone.
    assert stamps["/a.png"].checksum is None


def test_verifying_reports_a_digest_that_moved_while_stat_stood_still() -> None:
    stamps = {"/a.png": FileStamp(size=10, modified_time=1.0, checksum="aaaa")}
    seen: list[str] = []

    updated, content_changed = verify_checksums(
        stamps, ["/a.png"], recording_hasher({"/a.png": "bbbb"}, seen)
    )

    assert content_changed == ["/a.png"]
    assert updated["/a.png"].checksum == "bbbb"
    assert updated["/a.png"].size == 10
    assert updated["/a.png"].modified_time == 1.0


def test_verifying_stays_quiet_when_the_digest_is_unchanged() -> None:
    stamps = {"/a.png": FileStamp(size=10, modified_time=1.0, checksum="aaaa")}
    seen: list[str] = []

    updated, content_changed = verify_checksums(
        stamps, ["/a.png"], recording_hasher({"/a.png": "aaaa"}, seen)
    )

    assert content_changed == []
    assert updated == stamps


def test_verifying_skips_paths_the_snapshot_never_heard_of() -> None:
    stamps = {"/a.png": FileStamp(size=10, modified_time=1.0)}
    seen: list[str] = []

    updated, content_changed = verify_checksums(
        stamps,
        ["/stranger.png", "/a.png"],
        recording_hasher({"/a.png": "aaaa"}, seen),
    )

    assert set(updated) == {"/a.png"}
    assert content_changed == []
    # The stranger was never opened, let alone hashed.
    assert seen == ["/a.png"]


def test_a_file_deleted_mid_pass_is_skipped_not_raised(
    make_image: Callable[..., Path],
) -> None:
    """Uses the real hasher: the deleted file really is missing from disk."""
    survivor = make_image("survivor.png", colour=(1, 2, 3))
    doomed = make_image("doomed.png", colour=(4, 5, 6))
    stamps = stamp_media([build_media_file(path) for path in (survivor, doomed)])
    doomed_stamp = stamps[str(doomed)]
    doomed.unlink()

    updated, content_changed = verify_checksums(stamps, [str(doomed), str(survivor)])

    assert content_changed == []
    # The vanished file keeps its old stamp; the next snapshot calls it removed.
    assert updated[str(doomed)] == doomed_stamp
    assert updated[str(doomed)].checksum is None
    # Its disappearance did not stop the rest of the batch from being hashed.
    assert (
        updated[str(survivor)].checksum
        == hashlib.md5(survivor.read_bytes()).hexdigest()
    )


def test_verifying_nothing_returns_the_snapshot_untouched() -> None:
    stamps = {"/a.png": FileStamp(size=10, modified_time=1.0)}
    updated, content_changed = verify_checksums(stamps, [])
    assert updated == stamps
    assert content_changed == []


def test_the_default_hasher_is_the_declared_algorithm(
    make_image: Callable[..., Path],
) -> None:
    path = make_image("digest.png")
    stamps = stamp_media([build_media_file(path)])

    updated, content_changed = verify_checksums(stamps, [str(path)])

    expected = hashlib.new(CHECKSUM_ALGORITHM, path.read_bytes()).hexdigest()
    assert updated[str(path)].checksum == expected
    assert content_changed == []


# --------------------------------------------------------------------------
# diff_stamps
# --------------------------------------------------------------------------


def test_diffing_two_identical_snapshots_finds_nothing() -> None:
    snapshot = {"/a.png": FileStamp(size=10, modified_time=1.0)}
    changes = diff_stamps(snapshot, dict(snapshot))
    assert changes == FolderChanges()
    assert changes.has_changes is False


def test_diffing_separates_added_removed_and_modified() -> None:
    previous = {
        "/kept.png": FileStamp(size=10, modified_time=1.0),
        "/gone.png": FileStamp(size=20, modified_time=2.0),
        "/edited.png": FileStamp(size=30, modified_time=3.0),
    }
    current = {
        "/kept.png": FileStamp(size=10, modified_time=1.0),
        "/edited.png": FileStamp(size=31, modified_time=9.0),
        "/new.png": FileStamp(size=40, modified_time=4.0),
    }

    changes = diff_stamps(previous, current)

    assert changes.added == ("/new.png",)
    assert changes.removed == ("/gone.png",)
    assert changes.modified == ("/edited.png",)
    assert changes.has_changes is True
    assert changes.stale_paths == ("/gone.png", "/edited.png")


def test_diff_results_are_sorted_for_a_stable_report() -> None:
    previous = {"/z.png": FileStamp(size=1, modified_time=1.0)}
    current = {
        "/b.png": FileStamp(size=1, modified_time=1.0),
        "/a.png": FileStamp(size=1, modified_time=1.0),
    }

    changes = diff_stamps(previous, current)

    assert changes.added == ("/a.png", "/b.png")
    assert changes.removed == ("/z.png",)


def test_a_content_change_is_folded_into_modified() -> None:
    """Stat says nothing happened; the checksum pass says otherwise."""
    snapshot = {
        "/a.png": FileStamp(size=10, modified_time=1.0),
        "/b.png": FileStamp(size=20, modified_time=2.0),
    }

    changes = diff_stamps(snapshot, dict(snapshot), content_changed=["/b.png"])

    assert changes.modified == ("/b.png",)
    assert changes.has_changes is True
    assert changes.stale_paths == ("/b.png",)


def test_a_content_change_is_never_reported_twice() -> None:
    previous = {"/a.png": FileStamp(size=10, modified_time=1.0)}
    current = {"/a.png": FileStamp(size=11, modified_time=5.0)}

    changes = diff_stamps(previous, current, content_changed=["/a.png"])

    assert changes.modified == ("/a.png",)


def test_a_content_change_for_a_vanished_file_is_ignored() -> None:
    """Hashed, then deleted before the snapshot: it is removed, not modified."""
    previous = {"/a.png": FileStamp(size=10, modified_time=1.0)}
    current: dict[str, FileStamp] = {}

    changes = diff_stamps(previous, current, content_changed=["/a.png"])

    assert changes.removed == ("/a.png",)
    assert changes.modified == ()
    assert changes.stale_paths == ("/a.png",)


def test_diffing_real_snapshots_of_a_real_folder(image_dir: Path) -> None:
    from PIL import Image

    before = stamp_media([build_media_file(path) for path in image_dir.iterdir()])
    (image_dir / "charlie.png").unlink()
    Image.new("RGB", (12, 12), (7, 7, 7)).save(image_dir / "delta.png")

    after = stamp_media([build_media_file(path) for path in image_dir.iterdir()])
    changes = diff_stamps(before, after)

    assert changes.added == (str(image_dir / "delta.png"),)
    assert changes.removed == (str(image_dir / "charlie.png"),)
    assert changes.modified == ()


# --------------------------------------------------------------------------
# End to end: the rewrite that stat cannot see
# --------------------------------------------------------------------------


def test_a_rewrite_preserving_size_and_mtime_is_caught_only_by_checksums(
    make_image: Callable[..., Path],
) -> None:
    """The case the whole checksum machinery exists for.

    A real file is hashed with the real md5 hasher, then rewritten in place with
    the same byte count and its modified time restored to the exact nanosecond.
    A stat-only diff is blind to that; the checksum pass reports it.
    """
    path = make_image("sneaky.png", colour=(9, 9, 9))
    key = str(path)

    before = stamp_media([build_media_file(path)])
    verified, first_pass = verify_checksums(before, [key])
    # Nothing to compare a first digest against, so the first pass is quiet.
    assert first_pass == []
    original_digest = verified[key].checksum
    assert original_digest == hashlib.md5(path.read_bytes()).hexdigest()

    original_stat = os.stat(path)
    rewritten = bytearray(path.read_bytes())
    rewritten[-1] ^= 0xFF
    path.write_bytes(bytes(rewritten))
    os.utime(path, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))

    # The rewrite really is invisible to stat.
    after_stat = os.stat(path)
    assert after_stat.st_size == original_stat.st_size
    assert after_stat.st_mtime == original_stat.st_mtime

    current = stamp_media([build_media_file(path)])
    assert diff_stamps(verified, current).has_changes is False

    carried = carry_over_checksums(verified, current)
    assert carried[key].checksum == original_digest

    checked, content_changed = verify_checksums(
        carried, checksum_batch([key], 0, CHECKSUMS_PER_PASS)
    )

    assert content_changed == [key]
    assert checked[key].checksum == hashlib.md5(path.read_bytes()).hexdigest()
    assert checked[key].checksum != original_digest

    changes = diff_stamps(verified, checked, content_changed)
    assert changes.modified == (key,)
    assert changes.stale_paths == (key,)
    assert changes.has_changes is True


# -- bounded verification --------------------------------------------------


def test_verification_stops_at_the_byte_budget():
    """Four large videos must not mean gigabytes of reading in one pass."""
    from myimages.core.watcher import FileStamp, verify_checksums

    stamps = {
        f"big{index}": FileStamp(size=40 * 1024 * 1024, modified_time=1.0)
        for index in range(4)
    }
    hashed: list[str] = []

    verify_checksums(
        stamps, sorted(stamps), hasher=lambda path: hashed.append(path) or "digest"
    )

    assert len(hashed) == 1  # the second file would blow a 64 MiB budget


def test_a_single_oversized_file_is_still_hashed_eventually():
    """The budget bounds a pass; it must not make a huge file unverifiable."""
    from myimages.core.watcher import FileStamp, verify_checksums

    stamps = {"huge": FileStamp(size=500 * 1024 * 1024, modified_time=1.0)}
    hashed: list[str] = []

    verify_checksums(
        stamps, ["huge"], hasher=lambda path: hashed.append(path) or "digest"
    )

    assert hashed == ["huge"]
