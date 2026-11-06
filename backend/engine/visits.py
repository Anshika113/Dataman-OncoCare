"""Visit types and how long a visit actually takes.

The scheduler used to book every consult as a flat 30 minutes, so an 8-minute
follow-up and a 50-minute counselling visit occupied identical boxes and the
clinic drifted behind by mid-morning. A visit type carries a *planned*
duration; once enough real visits have been recorded for a doctor, the median
of what they actually ran becomes a **suggestion** the doctor can accept or
ignore. Nothing here ever changes a schedule on its own.

Pure module: no I/O, no clock.
"""

from __future__ import annotations

from typing import Any, Optional

from .timeutils import to_min

# Catalogue of consult visit types. ``default_min`` is the starting planned
# length; a clinic can tune these and the learned median refines them per
# doctor.
VISIT_TYPES: dict[str, dict[str, Any]] = {
    "follow_up":    {"label": "Follow-up",    "default_min": 10},
    "new_case":     {"label": "New case",     "default_min": 30},
    "counselling":  {"label": "Counselling",  "default_min": 45},
    "chemo_review": {"label": "Chemo review", "default_min": 15},
}

DEFAULT_VISIT_TYPE = "new_case"

#: Minimum completed visits before a learned duration is worth showing.
MIN_SAMPLES = 5
#: How far back to look when learning.
LOOKBACK = 40
#: Learned durations are rounded up to this grid so they stay bookable.
ROUND_TO = 5
#: Only suggest a change when the median differs from the plan by this much.
SUGGEST_DELTA = 3

MIN_DURATION = 5
MAX_DURATION = 240


def is_visit_type(key: str) -> bool:
    return key in VISIT_TYPES


def label(key: str) -> str:
    vt = VISIT_TYPES.get(key)
    return vt["label"] if vt else key


def default_duration(key: str) -> int:
    vt = VISIT_TYPES.get(key)
    return int(vt["default_min"]) if vt else VISIT_TYPES[DEFAULT_VISIT_TYPE]["default_min"]


def clamp_duration(minutes: Any, fallback: int = 30) -> int:
    """Coerce a requested duration into a sane bookable length."""
    try:
        m = int(minutes)
    except (TypeError, ValueError):
        return fallback
    return max(MIN_DURATION, min(MAX_DURATION, m))


def _round_up(minutes: float) -> int:
    return int(ROUND_TO * ((minutes + ROUND_TO - 1) // ROUND_TO))


def _median(values: list[int]) -> float:
    xs = sorted(values)
    n = len(xs)
    mid = n // 2
    return float(xs[mid]) if n % 2 else (xs[mid - 1] + xs[mid]) / 2.0


def observed_durations(state, doctor_id: str, visit_type: str) -> list[int]:
    """Actual minutes of completed visits for this doctor + visit type.

    A visit counts only once it has both a real start (the patient went in)
    and a completion, so a booked-but-never-seen slot can never skew it.
    """
    out: list[int] = []
    for a in state.appointments.values():
        if a.doctor_id != doctor_id or a.eff_visit_type != visit_type:
            continue
        if not a.started_at or not a.completed_at:
            continue
        mins = to_min(a.completed_at) - to_min(a.started_at)
        if MIN_DURATION <= mins <= MAX_DURATION:
            out.append(mins)
    return out[-LOOKBACK:]


def learned_duration(state, doctor_id: str, visit_type: str) -> Optional[dict]:
    """What this doctor's visits of this type really take.

    ``None`` until there are enough samples — an honest "we don't know yet"
    beats a confident number drawn from three visits.
    """
    samples = observed_durations(state, doctor_id, visit_type)
    if len(samples) < MIN_SAMPLES:
        return None
    med = _median(samples)
    planned = default_duration(visit_type)
    suggested = max(MIN_DURATION, _round_up(med))
    return {
        "visit_type": visit_type,
        "label": label(visit_type),
        "planned_min": planned,
        "median_min": round(med, 1),
        "samples": len(samples),
        "suggested_min": suggested,
        "differs": abs(med - planned) >= SUGGEST_DELTA,
    }


def catalogue(state=None, doctor_id: str = "") -> list[dict]:
    """The visit-type list the booking form renders.

    With a doctor, each entry also carries that doctor's learned duration
    when one exists.
    """
    out: list[dict] = []
    for key, vt in VISIT_TYPES.items():
        row = {
            "key": key,
            "label": vt["label"],
            "default_min": int(vt["default_min"]),
            "learned": None,
        }
        if state is not None and doctor_id:
            row["learned"] = learned_duration(state, doctor_id, key)
        out.append(row)
    return out
