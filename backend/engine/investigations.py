"""Investigation gating: treatment waits for results, the room does not.

The day this models is the ordinary one. Bloods go at 09:20, the chair is
booked for 10:00, the counts come back at 10:48. Until now the scheduler had
no idea any of that was happening: it held the chair empty and then marked a
patient sitting in the waiting room a no-show.

Gating splits the two. The *patient* keeps their place and is never
no-showed; the *chair* goes back to the pool so someone else can use it, and
the treatment is re-pencilled once the result lands. An abnormal result never
decides anything on its own — it is handed to the doctor.

Pure module: no I/O, no clock.
"""

from __future__ import annotations

from typing import Optional

from .state import (
    SystemState, Investigation, Appointment, AppointmentStatus, new_id,
)
from .result import EngineResult, Action, SeverityCode
from .timeutils import to_min, duration_min

#: Statuses whose treatment can still be gated.
_GATEABLE = (AppointmentStatus.BOOKED, AppointmentStatus.RESCHEDULED,
             AppointmentStatus.ACTIVE)


# --------------------------------------------------------------------------- #
# Ordering and resulting
# --------------------------------------------------------------------------- #
def order(state: SystemState, patient_id: str, kind: str, now: str, day: str,
          appointment_id: str = "", eta: str = "", blocking: bool = True,
          note: str = "") -> EngineResult:
    """Record an investigation, optionally gating an appointment."""
    if state.patient(patient_id) is None:
        return EngineResult(False, Action.INFO, "patient not found",
                            SeverityCode.WARNING)
    if appointment_id and state.appointment(appointment_id) is None:
        return EngineResult(False, Action.INFO, "appointment not found",
                            SeverityCode.WARNING)
    inv = Investigation(
        id=new_id("INV"), patient_id=patient_id, kind=kind,
        appointment_id=appointment_id, ordered_at=now, ordered_on=day,
        eta=eta, blocking=blocking, note=note)
    state.investigations[inv.id] = inv
    state.add_log("investigation_ordered", appointment_id, "",
                  f"{kind}@{now}", note or kind, now)
    return EngineResult(True, Action.INFO,
                        f"{kind} ordered for {state.patient(patient_id).name}",
                        data={"investigation": inv.to_dict()})


def result(state: SystemState, inv_id: str, value: str, now: str,
           flagged: bool = False, note: str = "") -> EngineResult:
    """File a result. ``flagged`` means it is outside protocol and the
    treatment still needs a doctor's decision."""
    inv = state.investigation(inv_id)
    if inv is None:
        return EngineResult(False, Action.INFO, "investigation not found",
                            SeverityCode.WARNING)
    if inv.status in ("resulted", "flagged"):
        return EngineResult(False, Action.INFO, "already resulted",
                            SeverityCode.WARNING)
    inv.status = "flagged" if flagged else "resulted"
    inv.value = value
    inv.resulted_at = now
    if note:
        inv.note = note
    state.add_log("investigation_resulted", inv.appointment_id, inv.kind,
                  f"{value}@{now}", inv.status, now)
    return EngineResult(
        True, Action.INFO,
        f"{inv.kind} resulted: {value}" + (" — flagged for review" if flagged else ""),
        SeverityCode.WARNING if flagged else SeverityCode.INFO,
        data={"investigation": inv.to_dict()})


def clear_flag(state: SystemState, inv_id: str, now: str,
               by: str = "", note: str = "") -> EngineResult:
    """A doctor has reviewed an out-of-protocol result and accepted it.

    This is the one way a flagged investigation stops blocking, and it is
    always a person's decision — recorded with who made it.
    """
    i = state.investigation(inv_id)
    if i is None:
        return EngineResult(False, Action.INFO, "investigation not found",
                            SeverityCode.WARNING)
    if i.status != "flagged":
        return EngineResult(False, Action.INFO,
                            f"nothing to clear: status is {i.status}",
                            SeverityCode.WARNING)
    i.status = "resulted"
    i.note = note or f"reviewed by {by}" if (note or by) else i.note
    state.add_log("investigation_cleared_flag", i.appointment_id, "flagged",
                  "resulted", note or f"reviewed by {by or 'clinician'}", now)
    return EngineResult(True, Action.INFO,
                        f"{i.kind} flag cleared — treatment may proceed")


# --------------------------------------------------------------------------- #
# Readiness
# --------------------------------------------------------------------------- #
def readiness(state: SystemState, appointment_id: str) -> dict:
    """Is this treatment clear to go ahead?

    ``ready``   — nothing blocking is outstanding.
    ``waiting`` — results are still in the lab.
    ``blocked`` — something came back outside protocol; a doctor must decide.
    """
    items = state.investigations_for(appointment_id)
    pending = [i for i in items if i.blocking and i.status == "pending"]
    flagged = [i for i in items if i.blocking and i.status == "flagged"]
    if flagged:
        status = "blocked"
    elif pending:
        status = "waiting"
    else:
        status = "ready"
    return {
        "appointment_id": appointment_id,
        "status": status,
        "ready": status == "ready",
        "pending": [i.to_dict() for i in pending],
        "flagged": [i.to_dict() for i in flagged],
        "all": [i.to_dict() for i in items],
        "eta": min((i.eta for i in pending if i.eta), default=""),
    }


# --------------------------------------------------------------------------- #
# Gating: hold the patient's place, release the chair
# --------------------------------------------------------------------------- #
def gate(state: SystemState, appointment_id: str, now: str) -> EngineResult:
    """Mark a treatment as waiting on results and free its room.

    The appointment is NOT cancelled and the patient is NOT no-showed — they
    are here, their bloods are in the lab. Only the chair goes back.
    """
    appt = state.appointment(appointment_id)
    if appt is None:
        return EngineResult(False, Action.INFO, "appointment not found",
                            SeverityCode.WARNING)
    if appt.status not in _GATEABLE:
        return EngineResult(False, Action.INFO,
                            f"cannot gate: status is {appt.status.value}",
                            SeverityCode.WARNING)
    rd = readiness(state, appointment_id)
    if rd["ready"]:
        return EngineResult(False, Action.INFO,
                            "nothing outstanding — no need to gate",
                            SeverityCode.INFO)

    appt.awaiting_results = True
    released = ""
    if appt.room_id:
        released = appt.room_id
        appt.held_room_id = appt.room_id
        appt.room_id = None
        # The chair is back in the pool for exactly this long. Recorded now,
        # not derived later: repencil() clears held_room_id.
        appt.chair_released_min += max(
            0, duration_min(appt.slot_start, appt.slot_end))
    room = state.room(released) if released else None
    state.add_log("investigation_gate", appointment_id,
                  released or "no room", "awaiting results",
                  rd["status"], now)
    msg = f"held for results ({rd['status']})"
    if room:
        msg += f"; {room.name} released {appt.slot_start}–{appt.slot_end}"
    return EngineResult(True, Action.INFO, msg,
                        data={"released_room_id": released,
                              "released_room_name": room.name if room else "",
                              "slot_start": appt.slot_start,
                              "slot_end": appt.slot_end,
                              "readiness": rd})


def repencil(state: SystemState, appointment_id: str, allocator, now: str,
             date: Optional[str] = None) -> EngineResult:
    """Results are in — find the treatment a new slot and chair.

    Refuses while anything blocking is still open, so a flagged count cannot
    be scheduled around.
    """
    appt = state.appointment(appointment_id)
    if appt is None:
        return EngineResult(False, Action.RESCHEDULED, "appointment not found",
                            SeverityCode.WARNING)
    rd = readiness(state, appointment_id)
    if not rd["ready"]:
        return EngineResult(
            False, Action.RESCHEDULED,
            f"still {rd['status']} — a doctor must clear this first",
            SeverityCode.WARNING, data={"readiness": rd})

    mins = max(duration_min(appt.slot_start, appt.slot_end), 15)
    d = date or appt.eff_date

    if appt.drug_id:
        cands = [c for c in allocator.rooms.find_best_chemo(
            appt.doctor_id, appt.drug_id, now, mins)
            if to_min(c.start) >= to_min(now)]
        if not cands:
            return EngineResult(False, Action.RESCHEDULE_OFFERED,
                                "no chair and slot left today inside the drug's "
                                "time window", SeverityCode.WARNING)
        best = cands[0]
        r = allocator.reschedule(appointment_id, None, best.room_id,
                                 best.start, best.end, at=now,
                                 reason="results back", date=d)
    else:
        slots = [s for s in allocator.reg.doctor_candidate_slots(
            appt.doctor_id, mins, step=15) if to_min(s[0]) >= to_min(now)]
        if not slots:
            return EngineResult(False, Action.RESCHEDULE_OFFERED,
                                "no slot left today", SeverityCode.WARNING)
        s, e = slots[0]
        r = allocator.reschedule(appointment_id, None, appt.room_id, s, e,
                                 at=now, reason="results back", date=d)

    if r.success:
        appt.awaiting_results = False
        appt.held_room_id = ""
        state.add_log("investigation_cleared", appointment_id, "waiting",
                      f"{appt.slot_start}@{appt.room_id or 'no room'}",
                      "results back", now)
    return r


def gated_appointments(state: SystemState, day: Optional[str] = None) -> list[dict]:
    """Everything currently held for results, with why and for how long."""
    d = day or state.day()
    out = []
    for a in state.appointments.values():
        if not a.awaiting_results or a.eff_date != d:
            continue
        rd = readiness(state, a.id)
        p = state.patient(a.patient_id)
        out.append({
            "appointment_id": a.id,
            "patient_id": a.patient_id,
            "patient_name": p.name if p else a.patient_id,
            "doctor_id": a.doctor_id,
            "slot_start": a.slot_start,
            "slot_end": a.slot_end,
            "held_room_id": a.held_room_id,
            "readiness": rd,
        })
    out.sort(key=lambda r: r["slot_start"])
    return out
