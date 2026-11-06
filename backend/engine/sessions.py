"""The working week, and the house rules inside it.

A consultant is not ten blank hours a day. Until the scheduler knows about
clinic sessions, the ward round, teaching and lunch, it will keep producing a
day nobody would accept — and every one of those bookings then has to be
undone by hand.

Two kinds of constraint live here:

* **Session blocks** are structural. A ``clinic`` block is where booking is
  *allowed*; every other kind (ward round, teaching, lunch, admin) is time
  the slot search must treat like a leave window.
* **Case-mix rules** are about the shape of the day — how much of one sort of
  work may be stacked, and when it may happen. They depend on what else is
  booked, so they are checked at booking time rather than baked into the grid.

Backwards compatible by design: a doctor with no sessions behaves exactly as
before, available across the whole working day.

Pure module: no I/O, no clock.
"""

from __future__ import annotations

from datetime import date as _date
from typing import Optional

from .state import SystemState, Doctor, AppointmentStatus, WEEKDAYS
from .timeutils import to_min, to_hhmm

#: Statuses that count towards the shape of a doctor's day.
_LIVE = (AppointmentStatus.BOOKED, AppointmentStatus.RESCHEDULED,
         AppointmentStatus.ACTIVE, AppointmentStatus.OVERRUN)


def weekday(day_iso: str) -> str:
    """"2026-10-31" -> "sat". Unparseable dates fall back to every day."""
    try:
        y, m, d = (int(x) for x in day_iso.split("-"))
        return WEEKDAYS[_date(y, m, d).weekday()]
    except (ValueError, TypeError, IndexError):
        return ""


# --------------------------------------------------------------------------- #
# Session blocks
# --------------------------------------------------------------------------- #
def blocks_for(doctor: Doctor, day_iso: str) -> list:
    wd = weekday(day_iso)
    if not wd:
        return []
    return [b for b in doctor.sessions if b.covers_day(wd)]


def clinic_windows(doctor: Doctor, day_iso: str) -> list[tuple[str, str]]:
    """Windows booking is allowed in. Empty list = no restriction."""
    return [(b.start, b.end) for b in blocks_for(doctor, day_iso) if b.bookable]


def bookable_windows(doctor: Optional[Doctor], day_iso: str,
                     day_start: str = "08:00",
                     day_end: str = "18:00") -> list[tuple[str, str]]:
    """When this doctor can actually see patients on that day.

    Three cases, and the middle one is the one that gets missed:

    * no session template at all -> the whole working day;
    * a template, but no clinic session on this weekday -> **nothing**;
    * a template with clinic sessions -> those windows.
    """
    if doctor is None:
        return [(day_start, day_end)]
    if not doctor.sessions:
        return [(day_start, day_end)]
    return clinic_windows(doctor, day_iso)


def blocked_windows(doctor: Doctor, day_iso: str) -> list[tuple[str, str]]:
    """Ward rounds, teaching, lunch — time the doctor is not seeing patients."""
    return [(b.start, b.end) for b in blocks_for(doctor, day_iso)
            if not b.bookable]


def session_conflict(doctor: Optional[Doctor], day_iso: str, s: str,
                     e: str) -> Optional[str]:
    """Why this window clashes with the doctor's week, or ``None``.

    A doctor with no sessions at all is unconstrained, exactly as before.
    """
    if doctor is None or not doctor.sessions:
        return None
    s_m, e_m = to_min(s), to_min(e)

    for b in blocks_for(doctor, day_iso):
        if b.bookable:
            continue
        if s_m < to_min(b.end) and e_m > to_min(b.start):
            name = b.label or b.kind.replace("_", " ")
            return f"{name} ({b.start}–{b.end})"

    windows = clinic_windows(doctor, day_iso)
    if windows:
        inside = any(s_m >= to_min(ws) and e_m <= to_min(we)
                     for ws, we in windows)
        if not inside:
            shown = ", ".join(f"{a}–{b}" for a, b in sorted(windows))
            return f"outside clinic hours ({shown})"
    elif doctor.sessions:
        # sessions exist but none is a clinic on this weekday -> no clinic today
        return "no clinic session on this day"
    return None


def is_bookable(doctor: Optional[Doctor], day_iso: str, s: str, e: str) -> bool:
    return session_conflict(doctor, day_iso, s, e) is None


# --------------------------------------------------------------------------- #
# Case-mix rules
# --------------------------------------------------------------------------- #
def _day_list(state: SystemState, doctor_id: str, day_iso: str,
              exclude: str = "") -> list:
    return sorted(
        [a for a in state.appointments.values()
         if a.doctor_id == doctor_id and a.eff_date == day_iso
         and a.status in _LIVE and a.id != exclude],
        key=lambda a: to_min(a.slot_start))


def _longest_run(types: list[str], want: str) -> int:
    best = run = 0
    for t in types:
        run = run + 1 if t == want else 0
        best = max(best, run)
    return best


def case_mix_conflict(state: SystemState, doctor_id: str, day_iso: str,
                      visit_type: str, slot_start: str, slot_end: str,
                      exclude: str = "") -> Optional[str]:
    """Why this booking breaks one of the doctor's own rules, or ``None``."""
    doc = state.doctor(doctor_id)
    if doc is None or not doc.rules or not visit_type:
        return None

    for rule in doc.rules:
        if not rule.enabled or rule.visit_type != visit_type:
            continue

        if rule.kind == "not_after" and to_min(slot_start) > to_min(rule.value):
            return rule.describe()
        if rule.kind == "not_before" and to_min(slot_start) < to_min(rule.value):
            return rule.describe()

        if rule.kind == "max_consecutive":
            others = _day_list(state, doctor_id, day_iso, exclude=exclude)
            seq = [(to_min(a.slot_start), a.eff_visit_type) for a in others]
            seq.append((to_min(slot_start), visit_type))
            seq.sort()
            if _longest_run([t for _m, t in seq], visit_type) > rule.count:
                return rule.describe()
    return None


# --------------------------------------------------------------------------- #
# For the UI
# --------------------------------------------------------------------------- #
def day_plan(state: SystemState, doctor_id: str, day_iso: str,
             day_start: str = "08:00", day_end: str = "18:00") -> dict:
    """What this doctor's day looks like structurally: windows and blocks."""
    doc = state.doctor(doctor_id)
    if doc is None:
        return {"doctor_id": doctor_id, "weekday": "", "sessions": [],
                "clinic": [], "blocked": [], "unconstrained": True}
    wd = weekday(day_iso)
    windows = clinic_windows(doc, day_iso)
    return {
        "doctor_id": doctor_id,
        "date": day_iso,
        "weekday": wd,
        "unconstrained": not doc.sessions,
        "sessions": [b.to_dict() for b in blocks_for(doc, day_iso)],
        "clinic": [{"start": a, "end": b} for a, b in sorted(windows)]
                  or ([{"start": day_start, "end": day_end}] if not doc.sessions else []),
        "blocked": [{"start": a, "end": b} for a, b in sorted(blocked_windows(doc, day_iso))],
        "rules": [r.to_dict() for r in doc.rules],
    }


def week_plan(state: SystemState, doctor_id: str) -> dict:
    """The template itself, grouped by weekday, for an editor."""
    doc = state.doctor(doctor_id)
    if doc is None:
        return {"doctor_id": doctor_id, "days": {}, "rules": []}
    days: dict[str, list] = {d: [] for d in WEEKDAYS}
    for b in doc.sessions:
        targets = WEEKDAYS if (not b.days or "*" in b.days) else b.days
        for d in targets:
            if d in days:
                days[d].append(b.to_dict())
    for d in days:
        days[d].sort(key=lambda x: to_min(x["start"]))
    return {
        "doctor_id": doctor_id,
        "doctor_name": doc.name,
        "days": days,
        "sessions": [b.to_dict() for b in doc.sessions],
        "rules": [r.to_dict() for r in doc.rules],
    }
