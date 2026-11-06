"""Who this patient is, today, at the moment the doctor opens the door.

The day list was four columns — time, name, room, status — so to know which
cycle Meera is on, whether her counts are back, or whether she even confirmed
she was coming, the doctor had to open another record or ask her.

Nothing here is a new clinical record. Every field is a *reading* of data the
system already holds: the chemo history gives the cycle, the drug gives the
regimen, the investigations give the lab status, the reply gives the
confirmation. That distinction matters — this is an operations tool surfacing
its own data, not a chart.

Pure module: no I/O, no clock.
"""

from __future__ import annotations

from typing import Optional

from .state import (
    SystemState, Appointment, AppointmentType, AppointmentStatus,
)
from .timeutils import to_min
from . import visits, investigations as inv

#: Statuses that mean the visit actually happened.
_SEEN = (AppointmentStatus.VISITED, AppointmentStatus.COMPLETED)
_LIVE = (AppointmentStatus.BOOKED, AppointmentStatus.RESCHEDULED,
         AppointmentStatus.ACTIVE, AppointmentStatus.OVERRUN)


def cycle_number(state: SystemState, appt: Appointment) -> Optional[int]:
    """Which cycle of this drug this is, counting the ones already given.

    ``None`` for anything that is not chemo — a follow-up has no cycle, and
    inventing one would be worse than leaving it blank.
    """
    if appt.type != AppointmentType.CHEMO or not appt.drug_id:
        return None
    given = [
        a for a in state.appointments.values()
        if a.patient_id == appt.patient_id
        and a.drug_id == appt.drug_id
        and a.id != appt.id
        and a.status in _SEEN
    ]
    return len(given) + 1


def _last_seen(state: SystemState, appt: Appointment) -> Optional[Appointment]:
    past = [
        a for a in state.appointments.values()
        if a.patient_id == appt.patient_id and a.id != appt.id
        and a.status in _SEEN
    ]
    if not past:
        return None
    return sorted(past, key=lambda a: (a.eff_date, a.slot_start))[-1]


def _lab_summary(state: SystemState, appt: Appointment) -> dict:
    rd = inv.readiness(state, appt.id)
    chips = []
    for i in rd["all"]:
        if i["status"] == "flagged":
            chips.append({"text": f"{i['kind']} {i['value']} — needs review",
                          "tone": "alert"})
        elif i["status"] == "resulted":
            chips.append({"text": f"{i['kind']} resulted"
                                  + (f" {i['value']}" if i["value"] else ""),
                          "tone": "ok"})
        else:
            chips.append({"text": f"{i['kind']} pending"
                                  + (f" · ETA {i['eta']}" if i["eta"] else ""),
                          "tone": "waiting"})
    return {"status": rd["status"], "ready": rd["ready"], "chips": chips}


def patient_context(state: SystemState, appt: Appointment) -> dict:
    """The one-line-plus context a doctor needs before the patient walks in."""
    patient = state.patient(appt.patient_id)
    drug = state.drug(appt.drug_id) if appt.drug_id else None
    cycle = cycle_number(state, appt)
    last = _last_seen(state, appt)
    labs = _lab_summary(state, appt)

    flags: list[dict] = []
    if appt.confirmed == "no":
        flags.append({"text": "replied that they cannot come", "tone": "alert"})
    elif appt.confirmed == "yes":
        flags.append({"text": "confirmed by reply", "tone": "ok"})
    else:
        flags.append({"text": "never confirmed", "tone": "waiting"})

    if appt.walk_in:
        flags.append({"text": "walked in today", "tone": "info"})
    if appt.awaiting_results:
        flags.append({"text": "held for results", "tone": "waiting"})
    if appt.handoff_note:
        # a flag as well as the note itself, so a doctor scanning the list
        # sees that there is something to read before they call the patient in
        flags.append({
            "text": (f"note from {appt.handoff_from}" if appt.handoff_from
                     else "handover note"),
            "tone": "info",
        })
    if last is None:
        flags.append({"text": "first visit here", "tone": "info"})

    notes: list[str] = []
    if appt.reason:
        notes.append(appt.reason)
    if patient and patient.allergies:
        notes.append(f"allergies: {patient.allergies}")

    return {
        "appointment_id": appt.id,
        "patient_id": appt.patient_id,
        "patient_name": patient.name if patient else appt.patient_id,
        "slot_start": appt.slot_start,
        "slot_end": appt.slot_end,
        "visit_label": (f"C{cycle}D1" if cycle
                        else visits.label(appt.eff_visit_type)),
        "cycle": cycle,
        "regimen": drug.name if drug else "",
        "room": (state.room(appt.room_id).name
                 if appt.room_id and state.room(appt.room_id) else ""),
        "labs": labs,
        "flags": flags,
        "last_seen": (f"{last.eff_date}" if last else ""),
        "notes": notes,
        "handoff_note": appt.handoff_note,
        "handoff_from": appt.handoff_from,
        "status": appt.status.value,
    }


def day_context(state: SystemState, doctor_id: str,
                day: Optional[str] = None) -> list[dict]:
    """The doctor's list for a day, each row carrying its own context."""
    d = day or state.day()
    rows = [
        a for a in state.appointments.values()
        if a.doctor_id == doctor_id and a.eff_date == d
        and a.status in _LIVE + _SEEN
    ]
    rows.sort(key=lambda a: to_min(a.slot_start))
    return [patient_context(state, a) for a in rows]
