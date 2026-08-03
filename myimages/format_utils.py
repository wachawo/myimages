"""Human-readable formatting helpers shared by the interface."""

from __future__ import annotations

SIZE_UNITS: tuple[str, ...] = ("B", "KB", "MB", "GB", "TB")


def human_readable_size(num_bytes: int) -> str:
    """Format a byte count as e.g. ``1.4 MB`` (base-1024)."""
    size = float(max(num_bytes, 0))
    for unit in SIZE_UNITS:
        if size < 1024 or unit == SIZE_UNITS[-1]:
            precision = 0 if unit == "B" else 1
            return f"{size:.{precision}f} {unit}"
        size /= 1024
    return f"{size:.1f} {SIZE_UNITS[-1]}"  # pragma: no cover - loop always returns


def human_readable_duration(seconds: float) -> str:
    """Format a duration in seconds as ``M:SS`` or ``H:MM:SS``."""
    total = int(round(max(seconds, 0)))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"
