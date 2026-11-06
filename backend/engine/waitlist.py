"""Waitlist and slot backfill.

A cancellation used to leave a hole and an INFO card nobody acted on. This
module answers the only question that matters in that moment: *who could
actually take this slot?* — ranked by whether they can physically get here,
not by who booked first.

Offers go to several patients at once and the first acceptance wins; the rest
are told the slot is gone. Pure module: no I/O, no clock.
"""

from __future__ import annotations

from typing import Optional

from .state import (
    SystemState, WaitlistEntry, Appointment, AppointmentStatus, new_id,
)
from .result import EngineResult, Action, SeverityCode
from .timeutils import to_min, duration_min
from . import visits

#: An offer is only sensible if the patient can plausibly arrive in time.
#: Someone already in the building is always reachable.
LATE_GRACE_MIN = 5


# --------------------------------------------------------------------------- #
# Managing the list
# --------------------------------------------------------------------------- #
def add(state: SystemState, patient_id: str, now: str, day: str,
        doctor_id: str = "", visit_type: str = "", reason: str = "",
        earliest: str = "08:00", latest: str = "18:00",
        travel_min: int = 30, in_building: bool = False,
        note: str = "") -> EngineResult:
    """Put a patient on the waitlist for an earlier slot."""
    if state.patient(patient_id) is None:
        return EngineResult(False, Action.INFO, "patient not found",
                            SeverityCode.WARNING)
    if doctor_id and state.doctor(doctor_id) is None:
        return EngineResult(False, Action.INFO, "doctor not found",
                            SeverityCode.WARNING)
    for e in state.waitlist.values():
        if e.active and e.patient_id == patient_id and e.doctor_id == doctor_id:
            return EngineResult(False, Action.INFO,
                                "already on the waitlist",
                                SeverityCode.WARNING)
    entry = WaitlistEntry(
        id=new_id("WL"), patient_id=patient_id, doctor_id=doctor_id,
        visit_type=visit_type if visits.is_visit_type(visit_type) else "",
        reason=reason, earliest=earliest, latest=latest,
        travel_min=max(0, int(travel_min)), in_building=in_building,
        added_at=now, added_on=day, note=note)
    state.waitlist[entry.id] = entry
    state.add_log("waitlist_add", "", "", entry.id, reason or "waitlist", now)
    name = state.patient(patient_id).name
    return EngineResult(True, Action.INFO, f"{name} added to the waitlist",
                        data={"entry": entry.to_dict()})


def remove(state: SystemState, entry_id: str, now: str,
           reason: str = "removed") -> EngineResult:
    entry = state.waitlist_entry(entry_id)
    if entry is None:
        return EngineResult(False, Action.INFO, "waitlist entry not found",
                            SeverityCode.WARNING)
    entry.status = "removed"
    entry.offered_slot = ""
    state.add_log("waitlist_remove", "", entry_id, reason, reason, now)
    return EngineResult(True, Action.INFO, "removed from the waitlist")


# --------------------------------------------------------------------------- #
# Matching a freed slot
# --------------------------------------------------------------------------- #
def _reach(entry: WaitlistEntry, slot_start: str, now: str) -> tuple[bool, int]:
    """Can this patient be here by ``slot_start``? Returns (reachable, eta)."""
    if entry.in_building:
        return True, 0
    minutes_until = to_min(slot_start) - to_min(now)
    return (entry.travel_min <= minutes_until + LATE_GRACE_MIN,
            entry.travel_min)


def candidates(state: SystemState, doctor_id: str, slot_start: str,
               slot_end: str, now: str, limit: int = 5) -> list[dict]:
    """Who could take this freed slot, best first.

    Ranked by: already here, then reachable in time, then longest wait on the
    list. Each row carries the reasons, so the desk can see *why* someone is
    ranked where they are instead of trusting a number.
    """
    slot_min = duration_min(slot_start, slot_end)
    out: list[dict] = []
    for e in state.waitlist.values():
        if not e.active or not e.accepts(doctor_id):
            continue
        if to_min(slot_start) < to_min(e.earliest):
            continue
        if to_min(slot_end) > to_min(e.latest):
            continue
        needed = (visits.default_duration(e.visit_type) if e.visit_type
                  else slot_min)
        if needed > slot_min:
            continue
        reachable, eta = _reach(e, slot_start, now)
        patient = state.patient(e.patient_id)
        waited = max(0, to_min(now) - to_min(e.added_at)) if e.added_at else 0
        why: list[str] = []
        if e.in_building:
            why.append("already in the building")
        elif reachable:
            why.append(f"~{eta} min away")
        else:
            why.append(f"needs {eta} min, slot is in "
                       f"{max(0, to_min(slot_start) - to_min(now))}")
        if e.reason:
            why.append(e.reason)
        if waited:
            why.append(f"waiting {waited} min")
        out.append({
            "entry_id": e.id,
            "patient_id": e.patient_id,
            "patient_name": patient.name if patient else e.patient_id,
            "doctor_id": doctor_id,
            "visit_type": e.visit_type,
            "needed_min": needed,
            "in_building": e.in_building,
            "reachable": reachable,
            "eta_min": eta,
            "waited_min": waited,
            "status": e.status,
            "why": why,
        })
    out.sort(key=lambda r: (not r["in_building"], not r["reachable"],
                            -r["waited_min"], r["patient_name"]))
    return out[:limit]


def offer(state: SystemState, entry_ids: list[str], doctor_id: str,
          slot_start: str, slot_end: str, now: str) -> EngineResult:
    """Offer one freed slot to several patients; the first to accept wins."""
    doctor = state.doctor(doctor_id)
    if doctor is None:
        return EngineResult(False, Action.INFO, "doctor not found",
                            SeverityCode.WARNING)
    tag = f"{slot_start}-{slot_end}@{doctor_id}"
    offered: list[str] = []
    for eid in entry_ids:
        e = state.waitlist_entry(eid)
        if e is None or not e.active:
            continue
        e.status = "offered"
        e.offered_slot = tag
        offered.append(e.id)
        state.add_notification(
            e.patient_id, "sms",
            f"A slot opened with {doctor.name} at {slot_start} today. "
            f"Reply YES to take it — first reply gets it.", now,
            kind="waitlist_offer", ref=e.id)
        state.add_log("waitlist_offer", "", e.id, tag, "slot offered", now)
    if not offered:
        return EngineResult(False, Action.INFO, "no one left to offer it to",
                            SeverityCode.WARNING)
    return EngineResult(
        True, Action.INFO,
        f"offered {slot_start} to {len(offered)} patient(s) — first accept wins",
        data={"offered": offered, "slot": tag})


def accept(state: SystemState, entry_id: str, allocator, now: str,
           doctor_id: str = "", slot_start: str = "", slot_end: str = "",
           date: Optional[str] = None) -> EngineResult:
    """First acceptance wins: book it and close the offer for everyone else."""
    entry = state.waitlist_entry(entry_id)
    if entry is None:
        return EngineResult(False, Action.BOOKED, "waitlist entry not found",
                            SeverityCode.WARNING)
    if entry.status == "booked":
        return EngineResult(False, Action.BOOKED, "already booked",
                            SeverityCode.WARNING)

    # fall back to the slot this entry was offered
    if not (doctor_id and slot_start and slot_end) and entry.offered_slot:
        span, _, did = entry.offered_slot.partition("@")
        s, _, e = span.partition("-")
        doctor_id = doctor_id or did
        slot_start = slot_start or s
        slot_end = slot_end or e
    if not (doctor_id and slot_start and slot_end):
        return EngineResult(False, Action.BOOKED,
                            "no slot to accept — offer one first",
                            SeverityCode.WARNING)

    tag = f"{slot_start}-{slot_end}@{doctor_id}"
    r = allocator.book_consult(entry.patient_id, doctor_id, slot_start,
                               slot_end, at=now, date=date,
                               visit_type=entry.visit_type or None)
    if not r.success:
        # someone got there first, or the slot went away
        return EngineResult(False, Action.BOOKED,
                            f"slot no longer available: {r.message}",
                            SeverityCode.WARNING)

    entry.status = "booked"
    entry.offered_slot = ""
    state.add_log("waitlist_accept", "", entry.id, tag, "backfilled", now)

    # everyone else offered this exact slot goes back on the list
    passed_over = 0
    for e in state.waitlist.values():
        if e.id != entry.id and e.status == "offered" and e.offered_slot == tag:
            e.status = "waiting"
            e.offered_slot = ""
            passed_over += 1
            state.add_notification(
                e.patient_id, "sms",
                f"The {slot_start} slot has been taken. You are still on the "
                f"list for the next one.", now)

    patient = state.patient(entry.patient_id)
    return EngineResult(
        True, Action.BOOKED,
        f"{patient.name if patient else entry.patient_id} backfilled into "
        f"{slot_start}" + (f"; {passed_over} other(s) told it is gone"
                           if passed_over else ""),
        data={"entry_id": entry.id, "slot": tag, "passed_over": passed_over})


def active_entries(state: SystemState) -> list[WaitlistEntry]:
    return [e for e in state.waitlist.values() if e.active]
