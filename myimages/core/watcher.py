"""Noticing that a folder changed underneath an open window.

Files come and go while the app is running -- a photo deleted in a file
manager, a new export dropped in, an image re-saved by another editor -- and the
gallery must not keep showing what is no longer there.

Detection is deliberately built on ``stat`` alone: a snapshot records each
file's size and modified time, and two snapshots are compared. Reading a
directory listing is cheap enough to repeat on a timer for any realistic folder,
whereas re-reading the *contents* of every photo would be exactly the kind of
constant disk churn a background check must avoid.

Checksums exist for the one case ``stat`` cannot see: a file rewritten with its
size and modified time preserved. They are therefore optional and applied to a
small rotating batch per pass (:func:`checksum_batch`), so verifying a large
folder is spread over many cheap passes instead of one expensive sweep.

The module holds no Qt imports so the comparison logic stays testable without a
display; :mod:`myimages.gui.folder_monitor` supplies the timers around it.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace

from myimages.core.duplicates import file_hash
from myimages.core.media import MediaFile

# md5 is the fastest widely available digest and this is an integrity check,
# never a security boundary, so its weakness against crafted collisions is
# irrelevant here.
CHECKSUM_ALGORITHM = "md5"

# How many files one pass may hash. Small enough that a pass stays unnoticeable
# even on spinning disks; the rotating cursor means the whole folder is still
# covered over time.
CHECKSUMS_PER_PASS = 4

# ...and how many bytes those files may add up to. Counting files alone is not a
# budget: four 500 MB videos would re-read two gigabytes every single pass,
# which is exactly the disk churn a background check has to stay away from.
CHECKSUM_BYTE_BUDGET = 64 * 1024 * 1024


@dataclass(frozen=True)
class FileStamp:
    """What is known about one file without opening it (plus, sometimes, a hash).

    ``checksum`` is filled in only for the files a verification pass happened to
    reach, so most stamps carry ``None`` and comparisons must not read that as
    "the content differs".
    """

    size: int
    modified_time: float
    checksum: str | None = None

    def differs_from(self, other: FileStamp) -> bool:
        """Whether these two stamps describe different file contents.

        Size or modified time changing is proof enough on its own. Checksums are
        consulted only when *both* stamps have one, because a missing checksum
        means "not verified yet", not "changed".
        """
        if self.size != other.size or self.modified_time != other.modified_time:
            return True
        if self.checksum is not None and other.checksum is not None:
            return self.checksum != other.checksum
        return False


@dataclass(frozen=True)
class FolderChanges:
    """Which paths appeared, vanished or were rewritten between two snapshots."""

    added: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    modified: tuple[str, ...] = ()

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.removed or self.modified)

    @property
    def stale_paths(self) -> tuple[str, ...]:
        """Paths whose cached thumbnail can no longer be trusted."""
        return self.removed + self.modified


def stamp_media(files: Iterable[MediaFile]) -> dict[str, FileStamp]:
    """Snapshot already-scanned media files, reusing the ``stat`` they carry.

    Taking the input from a completed scan means a snapshot costs nothing beyond
    the walk the caller already paid for, and keeps the rules about what counts
    as a media file in :mod:`myimages.core.scanner` alone.
    """
    return {
        str(media_file.path): FileStamp(
            size=media_file.size_bytes, modified_time=media_file.modified_time
        )
        for media_file in files
    }


def carry_over_checksums(
    previous: Mapping[str, FileStamp], current: Mapping[str, FileStamp]
) -> dict[str, FileStamp]:
    """Keep checksums already computed for files that ``stat`` says are untouched.

    Without this every pass would throw away the verification work of the last
    one, and a file would have to be re-hashed before its checksum could ever be
    compared against anything.
    """
    carried: dict[str, FileStamp] = {}
    for path, stamp in current.items():
        earlier = previous.get(path)
        if (
            earlier is not None
            and earlier.checksum is not None
            and earlier.size == stamp.size
            and earlier.modified_time == stamp.modified_time
        ):
            carried[path] = replace(stamp, checksum=earlier.checksum)
        else:
            carried[path] = stamp
    return carried


def checksum_batch(paths: Sequence[str], cursor: int, batch_size: int) -> list[str]:
    """The next ``batch_size`` paths to verify, wrapping around at the end.

    Rotating rather than always starting from the top is what makes the whole
    folder reachable: a fixed prefix would leave later files never verified.
    """
    if not paths or batch_size <= 0:
        return []
    start = cursor % len(paths)
    doubled = list(paths) + list(paths)
    return doubled[start : start + min(batch_size, len(paths))]


def verify_checksums(
    stamps: Mapping[str, FileStamp],
    paths: Iterable[str],
    hasher: Callable[[str], str] | None = None,
    byte_budget: int = CHECKSUM_BYTE_BUDGET,
) -> tuple[dict[str, FileStamp], list[str]]:
    """Hash ``paths`` and report which ones changed behind ``stat``'s back.

    Hashing stops once ``byte_budget`` is used up, so one pass reads a bounded
    amount however large the files are; the rotating cursor brings the skipped
    ones round again next time. A file that vanishes mid-pass is skipped rather
    than raised: the very next snapshot comparison reports it as removed, which
    is the honest answer.
    """
    compute = hasher or (lambda path: file_hash(path, algorithm=CHECKSUM_ALGORITHM))
    updated = dict(stamps)
    content_changed: list[str] = []
    spent = 0
    for path in paths:
        stamp = updated.get(path)
        if stamp is None:
            continue
        if spent and spent + stamp.size > byte_budget:
            break  # leave the rest for the next pass rather than stall this one
        try:
            digest = compute(path)
        except OSError:
            continue
        spent += stamp.size
        if stamp.checksum is not None and stamp.checksum != digest:
            content_changed.append(path)
        updated[path] = replace(stamp, checksum=digest)
    return updated, content_changed


def diff_stamps(
    previous: Mapping[str, FileStamp],
    current: Mapping[str, FileStamp],
    content_changed: Iterable[str] = (),
) -> FolderChanges:
    """Compare two snapshots into the added / removed / modified paths.

    ``content_changed`` folds in findings from a checksum pass, which sees
    rewrites that size and modified time alone cannot reveal.
    """
    before, after = set(previous), set(current)
    modified = {
        path for path in before & after if current[path].differs_from(previous[path])
    }
    modified.update(path for path in content_changed if path in after)
    return FolderChanges(
        added=tuple(sorted(after - before)),
        removed=tuple(sorted(before - after)),
        modified=tuple(sorted(modified)),
    )
