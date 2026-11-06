"""No-show risk, and the one thing a scheduler must never do unasked.

Detecting a no-show fifteen minutes after it happened is not managing it —
the half hour is already gone. This scores tomorrow's list from what the
clinic already knows, so a reminder can go out early and a doctor can decide
whether they want a safety booking behind a high-risk slot.

Two deliberate limits:

* Only factors the datastore actually holds are used. No invented distance,
  no invented deprivation index — a score built from guesses is worse than
  no score.
* Overbooking is **never** applied automatically. It is a suggestion, and it
  only appears for a doctor who has switched it on for their own clinic.

Pure module: no I/O, no clock.
"""

from __future__ import annotations

from typing import Optional

from .state import SystemState, Appointment, AppointmentStatus
from .timeutils import to_min

HIGH = 60
MEDIUM = 30

#: A patient needs this much history before their record says anything.
MIN_HISTORY = 3


def _history(state: SystemState, patient_id: str,
             before_id: str) -> tuple[int, int]:
    """(no-shows, completed) in this patient's past, excluding this booking."""
    misses = seen = 0
    for a in state.appointments.values():
        if a.patient_id != patient_id or a.id == before_id:
            continue
        if a.status == AppointmentStatus.NO_SHOW:
            misses += 1
        elif a.status in (AppointmentStatus.VISITED,
                          AppointmentStatus.COMPLETED):
            seen += 1
    return misses, seen


def score(state: SystemState, appt: Appointment) -> dict:
    """Risk that this patient does not turn up, with the reasons."""
    points = 0
    factors: list[str] = []

    misses, seen = _history(state, appt.patient_id, appt.id)
    total = misses + seen
    if total >= MIN_HISTORY:
        rate = misses / total
        if rate >= 0.4:
            points += 45
            factors.append(f"missed {misses} of last {total}")
        elif rate >= 0.2:
            points += 25
            factors.append(f"missed {misses} of last {total}")
        elif misses:
            points += 10
            factors.append(f"missed {misses} of last {total}")
        else:
            points -= 10
            factors.append(f"attended all {total}")
    else:
        points += 10
        factors.append("little history to go on")

    if appt.confirmed == "yes":
        points -= 35
        factors.append("confirmed by reply")
    elif appt.confirmed == "no":
        points += 50
        factors.append("replied that they cannot come")
    else:
        points += 15
        factors.append("never confirmed")

    # Genuinely new to the clinic — not merely "has never completed one",
    # which would also describe a patient with a string of no-shows.
    if appt.visit_count == 0 and total == 0:
        points += 10
        factors.append("first visit")

    if to_min(appt.slot_start) <= to_min("09:00"):
        points += 10
        factors.append("first slot of the day")

    if appt.walk_in:
        points -= 20
        factors.append("walked in today")

    # A patient who has said they cannot come is not a probability, it is a
    # fact the clinic has to act on — good history must not bury it.
    if appt.confirmed == "no":
        points = max(points, HIGH)

    points = max(0, min(100, points))
    level = "high" if points >= HIGH else "medium" if points >= MEDIUM else "low"
    return {
        "appointment_id": appt.id,
        "patient_id": appt.patient_id,
        "slot_start": appt.slot_start,
        "slot_end": appt.slot_end,
        "doctor_id": appt.doctor_id,
        "score": points,
        "level": level,
        "factors": factors,
    }


def day_risk(state: SystemState, day: Optional[str] = None,
             doctor_id: str = "") -> list[dict]:
    """Risk for every live appointment on a day, worst first."""
    d = day or state.day()
    out = []
    for a in state.appointments.values():
        if a.eff_date != d:
            continue
        if a.status not in (AppointmentStatus.BOOKED,
                            AppointmentStatus.RESCHEDULED):
            continue
        if doctor_id and a.doctor_id != doctor_id:
            continue
        row = score(state, a)
        p = state.patient(a.patient_id)
        doc = state.doctor(a.doctor_id)
        row["patient_name"] = p.name if p else a.patient_id
        row["doctor_name"] = doc.name if doc else a.doctor_id
        out.append(row)
    out.sort(key=lambda r: (-r["score"], r["slot_start"]))
    return out


def suggestions(state: SystemState, day: Optional[str] = None,
                doctor_id: str = "") -> dict:
    """What could be done about the risk, and what the clinic is allowed to do.

    ``safety_bookings`` is only populated for doctors who have opted in. For
    everyone else the advice is the cheap one: ask earlier.
    """
    rows = day_risk(state, day, doctor_id)
    high = [r for r in rows if r["level"] == "high"]
    unconfirmed = [r for r in rows if "never confirmed" in r["factors"]]

    safety: list[dict] = []
    blocked: list[dict] = []
    for r in high:
        doc = state.doctor(r["doctor_id"])
        target = safety if (doc and doc.allow_safety_booking) else blocked
        target.append({
            "appointment_id": r["appointment_id"],
            "doctor_id": r["doctor_id"],
            "doctor_name": r["doctor_name"],
            "slot_start": r["slot_start"],
            "slot_end": r["slot_end"],
            "patient_name": r["patient_name"],
            "score": r["score"],
            "why": r["factors"],
        })

    return {
        "date": day or state.day(),
        "counts": {
            "high": len(high),
            "medium": len([r for r in rows if r["level"] == "medium"]),
            "low": len([r for r in rows if r["level"] == "low"]),
        },
        "remind_early": [
            {"appointment_id": r["appointment_id"],
             "patient_name": r["patient_name"],
             "slot_start": r["slot_start"],
             "score": r["score"]}
            for r in unconfirmed[:10]
        ],
        "safety_bookings": safety,
        "needs_doctor_opt_in": blocked,
        "rows": rows,
    }
