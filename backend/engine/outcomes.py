"""Did any of it actually help?

Everything else in this engine changes the day. This module is the only one
that reports on it — and it exists because the brief's own success criteria
are waiting times, utilisation and bottlenecks, and until now the system
collected the timestamps for all three and never once added them up.

Two principles run through it:

* **Say "not measured" rather than zero.** A median drawn from two visits is
  a number that lies. Every block carries how many visits it was computed
  from, and a block with too few says so instead of printing a figure.
* **Compare against a real day, not a target.** Improvement only means
  something next to the clinic's own previous day, so the comparison picks
  the most recent earlier day that actually has data.

Pure module: no I/O, no clock.
"""

from __future__ import annotations

from typing import Optional

from .state import SystemState, Appointment, AppointmentStatus
from .timeutils import to_min
from . import sessions as sess

#: Below this, a median is noise rather than a measurement.
MIN_SAMPLE = 3

#: Called in within this many minutes of the booked time counts as on time.
ON_TIME_MIN = 15

DAY_START = "08:00"
DAY_END = "18:00"

_SEEN = (AppointmentStatus.VISITED, AppointmentStatus.COMPLETED)
_LIVE = (AppointmentStatus.BOOKED, AppointmentStatus.RESCHEDULED,
         AppointmentStatus.ACTIVE, AppointmentStatus.OVERRUN)


def _median(xs: list[int]) -> float:
    ys = sorted(xs)
    n = len(ys)
    mid = n // 2
    return float(ys[mid]) if n % 2 else (ys[mid - 1] + ys[mid]) / 2.0


def _pct(part: float, whole: float) -> Optional[int]:
    if whole <= 0:
        return None
    return int(round(100.0 * part / whole))


def _day_appointments(state: SystemState, day: str,
                      doctor_id: str = "") -> list[Appointment]:
    return [
        a for a in state.appointments.values()
        if a.eff_date == day and (not doctor_id or a.doctor_id == doctor_id)
    ]


# --------------------------------------------------------------------------- #
# The blocks
# --------------------------------------------------------------------------- #
def _waiting(appts: list[Appointment], state: SystemState) -> dict:
    """How long patients actually sat there: arrival to being called in.

    A patient held for lab results is left out. Their clock keeps running
    while the lab works, and that wait is not the queue's doing — counting it
    here would punish the clinic for gating, which is the one thing that gave
    the chair back. They are counted in ``held_excluded`` so the omission is
    visible rather than silent.
    """
    waits: list[tuple[int, Appointment]] = []
    held = 0
    for a in appts:
        if not a.checked_in_at or not a.started_at:
            continue
        if a.chair_released_min > 0:
            held += 1
            continue
        mins = to_min(a.started_at) - to_min(a.checked_in_at)
        if mins >= 0:
            waits.append((mins, a))

    if len(waits) < MIN_SAMPLE:
        return {"measured": len(waits), "enough": False,
                "held_excluded": held,
                "why": f"needs {MIN_SAMPLE} timed visits, has {len(waits)}"}

    mins = [m for m, _a in waits]
    worst_min, worst_appt = max(waits, key=lambda t: t[0])
    p = state.patient(worst_appt.patient_id)
    return {
        "measured": len(waits),
        "enough": True,
        "held_excluded": held,
        "median_min": round(_median(mins), 1),
        "mean_min": round(sum(mins) / len(mins), 1),
        "worst_min": worst_min,
        "worst_patient": p.name if p else worst_appt.patient_id,
    }


def _punctuality(appts: list[Appointment]) -> dict:
    """Were patients called in near the time they were given?

    Gated treatments are left out for the same reason as in :func:`_waiting`:
    they were deliberately moved to wait on a lab, so measuring them against
    their original slot says nothing about the clinic's timekeeping.
    """
    rows = [a for a in appts if a.started_at and not a.chair_released_min]
    held = len([a for a in appts if a.started_at and a.chair_released_min])
    if len(rows) < MIN_SAMPLE:
        return {"measured": len(rows), "enough": False,
                "held_excluded": held,
                "why": f"needs {MIN_SAMPLE} started visits, has {len(rows)}"}
    late = [to_min(a.started_at) - to_min(a.slot_start) for a in rows]
    on_time = sum(1 for d in late if d <= ON_TIME_MIN)
    return {
        "measured": len(rows),
        "enough": True,
        "held_excluded": held,
        "on_time": on_time,
        "on_time_pct": _pct(on_time, len(rows)),
        "median_late_min": round(_median([max(0, d) for d in late]), 1),
    }


def _available_minutes(state: SystemState, day: str, doctor_id: str = "") -> int:
    """Clinic minutes the department actually had on that day.

    A doctor with a session template contributes only their clinic windows; a
    doctor on leave contributes nothing for that window.
    """
    docs = ([state.doctor(doctor_id)] if doctor_id
            else list(state.doctors.values()))
    total = 0
    for doc in docs:
        if doc is None or doc.on_leave:
            continue
        windows = sess.bookable_windows(doc, day, DAY_START, DAY_END)
        mins = sum(to_min(e) - to_min(s) for s, e in windows)
        for ls, le in doc.unavailable_windows_for(day):
            mins -= max(0, to_min(le) - to_min(ls))
        total += max(0, mins)
    return total


def _utilisation(state: SystemState, day: str, appts: list[Appointment],
                 doctor_id: str = "") -> dict:
    booked = sum(
        max(0, to_min(a.slot_end) - to_min(a.slot_start))
        for a in appts if a.status in _LIVE + _SEEN
    )
    available = _available_minutes(state, day, doctor_id)
    return {
        "booked_min": booked,
        "available_min": available,
        "pct": _pct(booked, available),
    }


def _recovered(state: SystemState, day: str, appts: list[Appointment]) -> dict:
    """Time that would have been lost and was not."""
    walk_ins = [a for a in appts if a.walk_in]
    backfills = [
        r for r in state.actions.values()
        if r.kind == "waitlist_accept" and r.on == day and not r.undone
    ]
    minutes = sum(max(0, to_min(a.slot_end) - to_min(a.slot_start))
                  for a in walk_ins)
    return {
        "walk_ins": len(walk_ins),
        "backfilled": len(backfills),
        "walk_in_min": minutes,
    }


def _gating(appts: list[Appointment]) -> dict:
    """Chair time that lab waits would have burned, and did not.

    Without gating a treatment waiting on bloods holds its chair empty until
    the slot passes. Gating hands the chair back. This is the sum of what was
    handed back, straight from the appointments that were gated.
    """
    gated = [a for a in appts if a.chair_released_min > 0]
    return {
        "held": len(gated),
        "chair_min_released": sum(a.chair_released_min for a in gated),
    }


def _losses(appts: list[Appointment]) -> dict:
    no_shows = [a for a in appts if a.status == AppointmentStatus.NO_SHOW]
    cancelled = [a for a in appts if a.status == AppointmentStatus.CANCELLED]
    overruns = [a for a in appts if a.status == AppointmentStatus.OVERRUN]
    total = len(appts)
    return {
        "no_shows": len(no_shows),
        "cancelled": len(cancelled),
        "overruns": len(overruns),
        "no_show_pct": _pct(len(no_shows), total),
    }


# --------------------------------------------------------------------------- #
# A day, and a day against another
# --------------------------------------------------------------------------- #
def day_outcomes(state: SystemState, day: Optional[str] = None,
                 doctor_id: str = "") -> dict:
    d = day or state.day()
    appts = _day_appointments(state, d, doctor_id)
    seen = [a for a in appts if a.status in _SEEN]
    return {
        "date": d,
        "doctor_id": doctor_id,
        "appointments": len(appts),
        "waiting": _waiting(appts, state),
        "punctuality": _punctuality(appts),
        "utilisation": _utilisation(state, d, appts, doctor_id),
        "recovered": _recovered(state, d, appts),
        "gating": _gating(appts),
        "losses": _losses(appts),
        "throughput": {"seen": len(seen), "booked": len(appts)},
    }


def previous_day_with_data(state: SystemState, day: str,
                           doctor_id: str = "") -> Optional[str]:
    """The most recent earlier day this clinic actually ran."""
    days = {
        a.eff_date for a in state.appointments.values()
        if a.eff_date < day and (not doctor_id or a.doctor_id == doctor_id)
    }
    return max(days) if days else None


#: Metrics where a smaller number is the better one.
LOWER_IS_BETTER = {"waiting.median_min", "waiting.mean_min",
                   "punctuality.median_late_min", "losses.no_shows",
                   "losses.no_show_pct", "losses.overruns"}


def _dig(d: dict, path: str):
    cur = d
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def compare(state: SystemState, day: Optional[str] = None,
            against: Optional[str] = None, doctor_id: str = "") -> dict:
    """This day's outcomes next to an earlier one, with the direction named.

    ``better`` is explicit per metric rather than inferred from the sign,
    because a smaller wait is good and a smaller utilisation is not.
    """
    d = day or state.day()
    now = day_outcomes(state, d, doctor_id)
    prev_day = against or previous_day_with_data(state, d, doctor_id)
    if not prev_day:
        return {"now": now, "previous": None, "deltas": [],
                "why": "no earlier day with data to compare against"}

    prev = day_outcomes(state, prev_day, doctor_id)
    tracked = [
        ("gating.chair_min_released", "Chair time recovered", "min"),
        ("waiting.median_min", "Median wait", "min"),
        ("punctuality.on_time_pct", "Seen on time", "%"),
        ("utilisation.pct", "Utilisation", "%"),
        ("losses.no_show_pct", "No-show rate", "%"),
        ("throughput.seen", "Visits seen", ""),
    ]

    deltas = []
    for path, label, unit in tracked:
        a, b = _dig(now, path), _dig(prev, path)
        if a is None or b is None:
            deltas.append({"metric": path, "label": label, "unit": unit,
                           "now": a, "previous": b, "change": None,
                           "better": None,
                           "why": "not measured on one of the two days"})
            continue
        change = round(a - b, 1)
        lower_better = path in LOWER_IS_BETTER
        better = (None if change == 0
                  else (change < 0) if lower_better else (change > 0))
        deltas.append({"metric": path, "label": label, "unit": unit,
                       "now": a, "previous": b, "change": change,
                       "better": better, "why": ""})

    return {"now": now, "previous": prev, "deltas": deltas, "why": ""}
