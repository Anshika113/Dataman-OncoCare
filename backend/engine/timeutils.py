"""Time utilities: minutes arithmetic for HH:MM strings."""

from __future__ import annotations


def to_min(hhmm: str) -> int:
    """'09:30' -> 570 minutes since midnight."""
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def to_hhmm(mins: int) -> str:
    mins = max(0, mins)
    return f"{mins // 60:02d}:{mins % 60:02d}"


def add_min(hhmm: str, delta: int) -> str:
    return to_hhmm(to_min(hhmm) + delta)


def overlaps_m(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    """Half-open interval overlap on minutes: [a_start,a_end) vs [b_start,b_end)."""
    return a_start < b_end and b_start < a_end


def overlaps(a_start: str, a_end: str, b_start: str, b_end: str) -> bool:
    """Half-open interval overlap: [a_start, a_end) vs [b_start, b_end)."""
    return overlaps_m(to_min(a_start), to_min(a_end), to_min(b_start), to_min(b_end))


def duration_min(start: str, end: str) -> int:
    return to_min(end) - to_min(start)
