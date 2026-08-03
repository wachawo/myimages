"""Mask-based batch renaming: turn a naming pattern into concrete file moves.

Renaming many files at once is really two problems. First we must decide the
new names *without* touching disk, so the UI can preview them and we can spot
clashes while everything is still reversible. Second, we must perform the moves
in a way that survives cycles (``a`` -> ``b`` while ``b`` -> ``a``), which a
naive one-at-a-time rename would corrupt by overwriting a file before it has
been moved out of the way.

The module therefore splits into a pure planning phase (:func:`build_rename_plan`),
an up-front safety check (:func:`find_collisions`), and a collision-guarded,
two-phase apply phase (:func:`apply_rename_plan`) so callers can preview a plan
and only commit it when it is provably safe.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from myimages.core.media import MediaFile


class RenameError(ValueError):
    """Raised when a pattern is invalid or a plan cannot be applied safely.

    It subclasses ``ValueError`` because both causes -- a malformed pattern and
    a colliding plan -- are problems with the caller's input, so callers can
    catch it alongside other value errors yet still single it out when they want
    to surface a rename-specific message.
    """


@dataclass(frozen=True)
class RenamePlanItem:
    """One planned move: rename ``source`` to ``target``.

    Frozen so a computed plan is a stable value that cannot be mutated between
    the moment it is shown to the user and the moment it is applied.
    """

    source: Path
    target: Path


def source_path_and_mtime(entry: MediaFile | Path) -> tuple[Path, float]:
    """Return the on-disk path and modified time for either accepted input.

    Callers may hand us already-probed :class:`MediaFile` snapshots or raw
    paths. Supporting both means the planner works before *and* after the media
    model has been built, and avoids a redundant ``stat`` when the caller has
    already read one.
    """
    if isinstance(entry, MediaFile):
        return entry.path, entry.modified_time
    return entry, entry.stat().st_mtime


def build_rename_plan(
    files: Sequence[MediaFile] | Sequence[Path],
    pattern: str,
    *,
    start: int = 1,
    step: int = 1,
) -> list[RenamePlanItem]:
    """Compute each file's target from a ``str.format`` naming ``pattern``.

    Planning is kept pure (no disk writes) so the result can be previewed and
    validated first. The pattern may reference ``{name}`` (stem), ``{ext}``
    (suffix without the dot), ``{n}`` (the running sequence number), ``{index}``
    (zero-based position), ``{date}`` (``YYYYMMDD`` of the modified time) and
    ``{parent}`` (containing directory name). For the file at position ``i`` the
    sequence number is ``start + i * step``.
    """
    plan: list[RenamePlanItem] = []
    # Index rather than ``enumerate`` so mypy distributes ``files[index]`` over
    # the ``Sequence[MediaFile] | Sequence[Path]`` union to ``MediaFile | Path``
    # instead of collapsing the element type to ``object``.
    for index in range(len(files)):
        source, modified_time = source_path_and_mtime(files[index])
        sequence = start + index * step
        date = datetime.fromtimestamp(modified_time).strftime("%Y%m%d")
        try:
            rendered = pattern.format(
                name=source.stem,
                ext=source.suffix.removeprefix("."),
                n=sequence,
                index=index,
                date=date,
                parent=source.parent.name,
            )
        except (KeyError, ValueError, IndexError) as exc:
            raise RenameError(f"Invalid rename pattern {pattern!r}: {exc}") from exc
        plan.append(RenamePlanItem(source=source, target=source.parent / rendered))
    return plan


def find_collisions(plan: Sequence[RenamePlanItem]) -> list[Path]:
    """List targets that would clobber another file, sorted and de-duplicated.

    A target is unsafe when two items map to it (an in-plan clash) or when it
    already exists on disk and is not itself one of the plan's sources (an
    on-disk clash). The source exemption is what lets swaps and chains succeed:
    a file about to be moved away does not count as blocking its own slot.
    Surfacing these up front lets :func:`apply_rename_plan` refuse to start
    rather than lose data halfway through.
    """
    targets = [item.target for item in plan]
    sources = {item.source for item in plan}
    seen: set[Path] = set()
    collisions: set[Path] = set()
    for target in targets:
        if target in seen:
            collisions.add(target)
        seen.add(target)
        if target.exists() and target not in sources:
            collisions.add(target)
    return sorted(collisions)


def apply_rename_plan(plan: Sequence[RenamePlanItem]) -> list[tuple[Path, Path]]:
    """Execute ``plan`` safely, returning the ``(source, target)`` moves made.

    The moves run in two phases -- every source is first renamed to a unique
    temporary name in its own folder, then each temporary is renamed to its
    final target -- because a direct move can destroy data when the plan
    contains a swap or cycle (``a`` -> ``b`` while ``b`` -> ``a``). The plan is
    rejected up front if any collision exists, so a partial, half-applied
    rename can never occur.
    """
    collisions = find_collisions(plan)
    if collisions:
        listing = ", ".join(str(path) for path in collisions)
        raise RenameError(f"Cannot apply rename plan; targets collide: {listing}")

    staged: list[tuple[Path, Path, Path]] = []  # (original source, temp, target)
    for item in plan:
        temp = item.source.with_name(f"{item.source.name}.{uuid4().hex}.tmprename")
        item.source.rename(temp)
        staged.append((item.source, temp, item.target))

    results: list[tuple[Path, Path]] = []
    for original, temp, target in staged:
        target.parent.mkdir(parents=True, exist_ok=True)
        temp.rename(target)
        results.append((original, target))
    return results
