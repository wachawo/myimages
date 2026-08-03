"""Finding duplicate and near-duplicate media.

Two distinct problems live here, because users care about both. *Exact*
duplicates (the same bytes copied twice, e.g. a re-download) are found with a
cryptographic file hash, which is cheap and certain. *Visual* duplicates (the
same photo re-encoded, resized, or lightly edited) have different bytes, so we
fall back to perceptual hashing: we shrink the image to a tiny fingerprint and
compare fingerprints with a Hamming distance. Neither path needs Qt, so this
module stays importable in a headless test run and reusable by any UI.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from myimages.core.media import MediaFile, MediaKind


def file_hash(
    path: str | Path,
    *,
    algorithm: str = "sha256",
    chunk_size: int = 65536,
) -> str:
    """Return the hex digest of a file's contents.

    The file is read in bounded chunks rather than all at once so that hashing
    a multi-gigabyte video never has to hold the whole file in memory.
    """
    digest = hashlib.new(algorithm)
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class DuplicateGroup:
    """A set of files judged to be duplicates of one another.

    ``reason`` records *why* they were grouped (exact bytes vs. visual
    similarity) so the UI can explain the match to the user instead of
    silently proposing deletions. The group is frozen because it is a finding
    to be presented, not a mutable collection to be edited in place.
    """

    reason: str
    paths: list[Path]

    @property
    def representative(self) -> Path:
        """The file the group speaks for: the first one encountered.

        Callers use it as the "keep this one" default, so it must be stable and
        reflect discovery order rather than any arbitrary re-sorting.
        """
        return self.paths[0]


def find_exact_duplicates(files: Iterable[MediaFile]) -> list[DuplicateGroup]:
    """Group files that are byte-for-byte identical.

    Grouping is keyed on the content hash, which makes identical files collide
    regardless of their names or locations. Insertion-ordered dicts and plain
    appends preserve first-seen order for both groups and their members, so the
    output is deterministic and matches the order the user scanned in.
    """
    groups_by_hash: dict[str, list[Path]] = {}
    for media in files:
        groups_by_hash.setdefault(file_hash(media.path), []).append(media.path)
    return [
        DuplicateGroup(reason="identical bytes", paths=paths)
        for paths in groups_by_hash.values()
        if len(paths) > 1
    ]


def load_grayscale(path: str | Path, size: tuple[int, int]) -> list[int]:
    """Return the pixels of ``path`` shrunk to ``size`` as flat grayscale.

    Both perceptual hashes start from the same reduced, colour-stripped view of
    the image, so this shared step keeps them consistent and avoids opening the
    file twice. LANCZOS resampling preserves structure better than nearest
    neighbour, which matters when the fingerprint is only a few pixels wide.
    """
    with Image.open(path) as image:
        reduced = image.convert("L").resize(size, Image.Resampling.LANCZOS)
        # Mode "L" is one byte per pixel in row-major order, so the raw bytes
        # are exactly the grayscale values without a per-pixel Python loop.
        return list(reduced.tobytes())


def average_hash(path: str | Path, *, hash_size: int = 8) -> int:
    """Compute the aHash fingerprint of an image as an integer.

    Each pixel of the shrunken image contributes one bit: set when the pixel is
    brighter than the image's mean. Comparing against the mean makes the hash
    robust to uniform brightness shifts, which is exactly what we want when the
    "same" photo has been re-exported at a different exposure.
    """
    pixels = load_grayscale(path, (hash_size, hash_size))
    average = sum(pixels) / len(pixels)
    bits = 0
    for value in pixels:
        bits = (bits << 1) | (1 if value > average else 0)
    return bits


def difference_hash(path: str | Path, *, hash_size: int = 8) -> int:
    """Compute the dHash fingerprint of an image as an integer.

    Instead of absolute brightness, each bit records whether a pixel is
    brighter than its right-hand neighbour, so the hash captures gradients. The
    image is resized one column wider than tall precisely so every row yields
    ``hash_size`` adjacent comparisons.
    """
    width = hash_size + 1
    pixels = load_grayscale(path, (width, hash_size))
    bits = 0
    for row in range(hash_size):
        for column in range(hash_size):
            left = pixels[row * width + column]
            right = pixels[row * width + column + 1]
            bits = (bits << 1) | (1 if left > right else 0)
    return bits


def hamming_distance(left: int, right: int) -> int:
    """Count the differing bits between two integer fingerprints.

    This is the natural distance for perceptual hashes: a small count means the
    images differ in only a few of their fingerprint bits, i.e. they look
    nearly the same.
    """
    return bin(left ^ right).count("1")


def find_similar_images(
    files: Iterable[MediaFile],
    *,
    max_distance: int = 5,
) -> list[DuplicateGroup]:
    """Group images whose perceptual fingerprints are close.

    Only images are considered, since perceptual hashing is meaningless for
    videos and other files. Each image is compared against the anchor (first
    member) of every existing cluster and joins the first one within
    ``max_distance``; otherwise it seeds a new cluster. This greedy single-pass
    approach is O(files x clusters) and keeps the anchor stable, which is enough
    for the modest galleries this app scans. Files that cannot be read as images
    are skipped rather than aborting the whole scan.
    """
    clusters: list[list[Path]] = []
    anchor_hashes: list[int] = []
    for media in files:
        if media.kind is not MediaKind.IMAGE:
            continue
        # A single unreadable or corrupt file must not abort the whole scan,
        # so any failure to fingerprint it is treated as "not similar".
        try:
            signature = average_hash(media.path)
        except Exception:
            continue
        for index, anchor in enumerate(anchor_hashes):
            if hamming_distance(signature, anchor) <= max_distance:
                clusters[index].append(media.path)
                break
        else:
            clusters.append([media.path])
            anchor_hashes.append(signature)
    return [
        DuplicateGroup(reason="visually similar", paths=paths)
        for paths in clusters
        if len(paths) > 1
    ]
