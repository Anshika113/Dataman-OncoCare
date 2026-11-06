"""The arrivals board: who is actually in the waiting room.

The only queue the system had was the emergency queue, so eleven routine
patients could be sitting outside and appear nowhere. This module turns
check-in timestamps into the board a front desk works from — a token, how
long someone has been waiting, and what they are waiting *for*.

Pure module: no I/O, no clock.
"""

from __future__ import annotations

from typing import Optional

from .state import SystemState, Appointment, AppointmentStatus
from .timeutils import to_min

#: Waits past these marks are worth the desk's attention.
WAIT_WARN_MIN = 20
WAIT_CRIT_MIN = 40

_LIVE = (AppointmentStatus.BOOKED, AppointmentStatus.RESCHEDULED,
         AppointmentStatus.ACTIVE, AppointmentStatus.OVERRUN)


def _stage(appt: Appointment) -> str:
    """Where this patient is in their visit."""
    if appt.status in (AppointmentStatus.VISITED, AppointmentStatus.COMPLETED):
        return "done"
    if appt.started_at:
        return "with_doctor"
    if appt.awaiting_results:
        return "in_labs"
    if appt.checked_in:
        return "ready"
    return "not_arrived"


def _waiting_min(appt: Appointment, now: str) -> int:
    """How long they have been sitting there, from arrival to being called."""
    if not appt.checked_in_at:
        return 0
    end = appt.started_at or now
    return max(0, to_min(end) - to_min(appt.checked_in_at))


def board(state: SystemState, now: str, day: Optional[str] = None) -> list[dict]:
    """Everyone expected today, in the order the desk should think about them.

    Tokens are issued in arrival order (A-01, A-02 …) so they are stable and
    mean something; patients who have not arrived keep their slot order.
    """
    d = day or state.day()
    todays = [a for a in state.appointments.values()
              if a.eff_date == d
              and a.status in _LIVE + (AppointmentStatus.VISITED,)]

    arrived = sorted([a for a in todays if a.checked_in_at],
                     key=lambda a: (a.checked_in_at, a.slot_start))
    tokens = {a.id: f"A-{i + 1:02d}" for i, a in enumerate(arrived)}

    rows: list[dict] = []
    for a in todays:
        stage = _stage(a)
        waited = _waiting_min(a, now)
        p = state.patient(a.patient_id)
        doc = state.doctor(a.doctor_id)
        rows.append({
            "appointment_id": a.id,
            "token": tokens.get(a.id, ""),
            "patient_id": a.patient_id,
            "patient_name": p.name if p else a.patient_id,
            "doctor_id": a.doctor_id,
            "doctor_name": doc.name if doc else "",
            "slot_start": a.slot_start,
            "slot_end": a.slot_end,
            "arrived_at": a.checked_in_at,
            "started_at": a.started_at,
            "waiting_min": waited,
            "stage": stage,
            "walk_in": a.walk_in,
            "confirmed": a.confirmed,
            "severity": ("critical" if waited >= WAIT_CRIT_MIN
                         else "warning" if waited >= WAIT_WARN_MIN
                         else "ok"),
        })

    order = {"ready": 0, "in_labs": 1, "with_doctor": 2,
             "not_arrived": 3, "done": 4}
    rows.sort(key=lambda r: (order.get(r["stage"], 9), -r["waiting_min"],
                             r["slot_start"]))
    return rows


def next_up(state: SystemState, now: str, doctor_id: str = "",
            day: Optional[str] = None) -> Optional[dict]:
    """The patient who should be called next: ready, longest wait first."""
    ready = [r for r in board(state, now, day)
             if r["stage"] == "ready"
             and (not doctor_id or r["doctor_id"] == doctor_id)]
    return ready[0] if ready else None


def running_late(state: SystemState, now: str,
                 day: Optional[str] = None) -> list[dict]:
    """Which doctors are behind, by how much, and who is affected.

    "Behind" is measured against patients who have actually turned up — a
    doctor is not late for someone who has not arrived, nor for someone the
    lab still has.
    """
    d = day or state.day()
    now_m = to_min(now)
    by_doctor: dict[str, list[dict]] = {}
    for r in board(state, now, d):
        if r["stage"] != "ready":
            continue
        if to_min(r["slot_start"]) >= now_m:
            continue
        by_doctor.setdefault(r["doctor_id"], []).append(r)

    out: list[dict] = []
    for did, rows in by_doctor.items():
        behind = max(now_m - to_min(r["slot_start"]) for r in rows)
        longest = max(r["waiting_min"] for r in rows)
        doc = state.doctor(did)
        out.append({
            "doctor_id": did,
            "doctor_name": doc.name if doc else did,
            "behind_min": behind,
            "affected": len(rows),
            "longest_wait_min": longest,
            "patients": [r["patient_name"] for r in rows],
        })
    out.sort(key=lambda r: -r["behind_min"])
    return out
