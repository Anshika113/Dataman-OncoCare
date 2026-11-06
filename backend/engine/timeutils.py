"""Time utilities.

Within a single working day the engine reasons in **minutes** (``to_min``) and
``HH:MM`` strings. Across days it needs a **date + time** pair, so the higher
level uses :func:`dt_key` / :func:`overlaps_dt` which compare absolute
(date, time) instants. The two compose: a candidate slot is a
``(date, slot_start, slot_end)`` triple, and two slots overlap only if their
dates are equal and their minute ranges overlap (appointments never span
midnight in this model — a chemo session ends by 18:00).
"""

from __future__ import annotations

from datetime import date as _date, datetime, timedelta


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


# --------------------------------------------------------------------------- #
# Date-aware helpers
# --------------------------------------------------------------------------- #
def today() -> str:
    """Current working day as YYYY-MM-DD (local time)."""
    return datetime.now().astimezone().strftime("%Y-%m-%d")


def norm_date(d: str | None) -> str:
    """Normalise a YYYY-MM-DD string; empty/None -> today."""
    if not d:
        return today()
    d = d.strip()
    # accept a leading date portion of an ISO datetime too
    if "T" in d:
        d = d.split("T", 1)[0]
    try:
        return _date.fromisoformat(d).isoformat()
    except ValueError:
        return today()


def dt_key(d: str, hhmm: str) -> tuple[int, int]:
    """Absolute instant as (days_since_epoch, minutes_since_midnight).

    Comparing these tuples is equivalent to comparing instants, which is what
    day-boundary logic (is this slot in the future? has this leave expired?)
    needs.
    """
    try:
        y, m, dd = (int(x) for x in d.split("-"))
    except (ValueError, AttributeError):
        d = today()
        y, m, dd = (int(x) for x in d.split("-"))
    epoch = _date(1970, 1, 1)
    days = (_date(y, m, dd) - epoch).days
    return (days, to_min(hhmm))


def add_days(d: str, n: int) -> str:
    """Return the date ``n`` days from ``d`` as YYYY-MM-DD."""
    try:
        y, m, dd = (int(x) for x in d.split("-"))
    except (ValueError, AttributeError):
        d = today()
        y, m, dd = (int(x) for x in d.split("-"))
    return (_date(y, m, dd) + timedelta(days=n)).isoformat()


def overlaps_dt(a_date: str, a_start: str, a_end: str,
                b_date: str, b_start: str, b_end: str) -> bool:
    """True if two (date, [start,end)) slots overlap.

    Different dates never overlap. Same date -> minute-range overlap.
    """
    if norm_date(a_date) != norm_date(b_date):
        return False
    return overlaps_m(to_min(a_start), to_min(a_end), to_min(b_start), to_min(b_end))


def dt_in_past(d: str, hhmm: str, now_date: str, now_hhmm: str) -> bool:
    """True if instant (d, hhmm) is strictly before the current instant."""
    return dt_key(d, hhmm) < dt_key(now_date, now_hhmm)


def dt_in_future(d: str, hhmm: str, now_date: str, now_hhmm: str) -> bool:
    """True if instant (d, hhmm) is strictly after the current instant."""
    return dt_key(d, hhmm) > dt_key(now_date, now_hhmm)
