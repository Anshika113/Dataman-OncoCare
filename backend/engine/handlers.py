"""Edge-case handlers.

Every handler is a pure function over :class:`SystemState` that mutates state
and returns an :class:`EngineResult`. Two primitive operations back them all:

* ``reschedule_affected`` — a constraint changed, re-solve affected appointments
* ``advance_clock``       — time advanced / event fired, update the live queue

The six product edge cases map to:

===========  =========================  =================================================
Handler      Primitive                  Scenario
===========  =========================  =================================================
sick_leave   reschedule_affected        A. doctor on sick leave mid-day
overrun      advance_clock              B. chemo session overruns (grace + cascade)
emergency    resolve + queue            C. two emergencies at the same time
breakdown    reschedule_affected        D. room equipment breakdown
no_show      advance_clock              E. patient no-show (release + notify next)
(time-window constraint F lives in the allocator/conflict detector)
===========  =========================  =================================================
"""

from __future__ import annotations

from typing import Optional

from .state import (
    SystemState, AppointmentStatus, DoctorStatus, RoomStatus, Severity,
    Appointment, AppointmentType, LeaveEntry, new_id,
)
from .result import EngineResult, Action, SeverityCode
from .allocator import AppointmentAllocator
from .emergency import resolve_emergencies, two_emergencies_at_once
from .timeutils import to_min, to_hhmm, add_min, overlaps


def _alloc(state: SystemState) -> AppointmentAllocator:
    from .slots import SlotRegistry
    reg = SlotRegistry(state)
    return AppointmentAllocator(state, reg)


def _recompute_doctor_status(doc) -> None:
    """Set the doctor's status from their active leaves.

    - on_leave flag set  -> ON_LEAVE (whole day)
    - any active leave   -> PARTIALLY_UNAVAILABLE
    - none               -> AVAILABLE
    """
    if doc.on_leave:
        doc.status = DoctorStatus.ON_LEAVE
        return
    if doc.active_leaves:
        doc.status = DoctorStatus.PARTIALLY_UNAVAILABLE
    else:
        doc.status = DoctorStatus.AVAILABLE


# --------------------------------------------------------------------------- #
# G. Doctor availability / leave management (time-bounded)
# --------------------------------------------------------------------------- #
def handle_doctor_take_leave(state: SystemState, doctor_id: str, now: str,
                             start: str, end: str,
                             reason: str = "leave",
                             full_day: bool = False,
                             date: str = "") -> EngineResult:
    """Put a doctor on leave for [start, end].

    full_day=True marks the whole day (sick leave). Otherwise a time-bounded
    leave is added to the doctor's leaves list and their status is recomputed.
    Future appointments inside the window are auto-rescheduled to backups.
    """
    doc = state.doctor(doctor_id)
    if doc is None:
        return EngineResult(False, Action.RESCHEDULE_OFFERED, "doctor not found")

    if full_day:
        doc.status = DoctorStatus.ON_LEAVE
        doc.leave_reason = reason
        start, end = "08:00", "18:00"

    leave = LeaveEntry(new_id("LV"), start=start, end=end, reason=reason,
                       date=date, created_at=now)
    doc.leaves.append(leave)
    _recompute_doctor_status(doc)
    state.add_log("leave_taken", doctor_id, "available",
                  f"{start}-{end}", reason, now)

    # reschedule future appointments that now fall inside the leave window
    res = _alloc(state)
    affected = [
        a for a in state.active_appointments(doctor_id)
        if a.doctor_id == doctor_id
        and overlaps(a.slot_start, a.slot_end, start, end)
        and to_min(a.slot_start) >= to_min(now)
    ]
    moved, offered = [], []
    for appt in affected:
        r = res.reschedule_auto(appt.id, at=now, reason=f"{doc.name} leave {start}-{end}",
                                only_doctor=False)
        (moved if r.success else offered).append(appt.id)
        state.add_notification(
            appt.patient_id, "sms",
            f"Dr {doc.name} is unavailable {start}-{end}. Your appointment was "
            f"{'moved' if appt.id in moved else 'needs rebooking'}.", now)

    msg = (f"{doc.name} unavailable {start}-{end} ({reason}); "
           f"{len(moved)} auto-rescheduled, {len(offered)} need manual rebooking")
    return EngineResult(True, Action.RESCHEDULED if moved else Action.RESCHEDULED,
                        msg, SeverityCode.WARNING,
                        data={"affected": [a.id for a in affected],
                              "moved": moved, "offered": offered,
                              "status": doc.status.value})


def handle_doctor_cancel_leave(state: SystemState, doctor_id: str, now: str,
                               leave_id: Optional[str] = None) -> EngineResult:
    """Cancel a leave (by id, or the full-day on_leave flag).

    Cancelling frees the window. Existing appointments are NOT auto-moved back
    (they may have been rebooked elsewhere); the doctor simply becomes available
    again for new bookings in that window.
    """
    doc = state.doctor(doctor_id)
    if doc is None:
        return EngineResult(False, Action.INFO, "doctor not found")

    freed = []
    if leave_id:
        for l in doc.leaves:
            if l.id == leave_id and not l.cancelled:
                l.cancelled = True
                freed.append(f"{l.start}-{l.end}")
    if doc.on_leave and leave_id is None:
        doc.status = DoctorStatus.AVAILABLE
        doc.leave_reason = ""
        freed.append("full day")

    _recompute_doctor_status(doc)
    state.add_log("leave_cancelled", doctor_id,
                  ",".join(freed) or "none", "available",
                  "leave cancelled", now)

    msg = (f"{doc.name} is now {doc.status.value}"
           + (f" (freed {', '.join(freed)})" if freed else ""))
    return EngineResult(True, Action.INFO, msg, SeverityCode.INFO,
                        data={"status": doc.status.value, "freed": freed})


def handle_doctor_mark_available(state: SystemState, doctor_id: str, now: str) -> EngineResult:
    """Force a doctor back to available: cancel all leaves + on_leave flag."""
    doc = state.doctor(doctor_id)
    if doc is None:
        return EngineResult(False, Action.INFO, "doctor not found")
    for l in doc.leaves:
        l.cancelled = True
    doc.status = DoctorStatus.AVAILABLE
    doc.leave_reason = ""
    state.add_log("doctor_available", doctor_id, "unavailable", "available",
                  "manually marked available", now)
    return EngineResult(True, Action.INFO, f"{doc.name} marked available",
                        SeverityCode.INFO, data={"status": doc.status.value})


def expire_leaves(state: SystemState, now: str) -> list[str]:
    """Auto-expire leaves whose end time has passed; recompute statuses.

    Returns the list of doctor ids whose status changed to more available.
    This is called by the watchdog so a doctor automatically becomes available
    again when their leave window ends — no manual action required.
    """
    changed = []
    for doc in state.doctors.values():
        # drop active leaves that have ended
        before = len(doc.active_leaves)
        still_active = []
        for l in doc.leaves:
            if l.cancelled:
                continue
            if to_min(now) > to_min(l.end):
                l.cancelled = True  # expired
                state.add_log("leave_expired", doc.id, f"{l.start}-{l.end}",
                              "expired", f"leave ended at {l.end}", now)
            else:
                still_active.append(l)
        _recompute_doctor_status(doc)
        if doc.status == DoctorStatus.AVAILABLE and before > 0:
            changed.append(doc.id)
    return changed


# --------------------------------------------------------------------------- #
# A. Doctor sick leave mid-day
# --------------------------------------------------------------------------- #
def handle_doctor_sick_leave(state: SystemState, doctor_id: str, now: str,
                             reason: str = "sick leave") -> EngineResult:
    doctor = state.doctor(doctor_id)
    if doctor is None:
        return EngineResult(False, Action.RESCHEDULE_OFFERED, "doctor not found")

    doctor.status = DoctorStatus.ON_LEAVE
    doctor.leave_reason = reason

    # affected = future appointments of this doctor (slot_end > now)
    affected = [
        a for a in state.active_appointments(doctor_id)
        if a.doctor_id == doctor_id and to_min(a.slot_end) > to_min(now)
    ]

    res = _alloc(state)
    moved, offered = [], []
    for appt in affected:
        r = res.reschedule_auto(appt.id, at=now, reason=f"{doctor.name} on leave",
                                only_doctor=False)
        if r.action == Action.RESCHEDULED:
            moved.append(appt.id)
        else:
            offered.append(appt.id)

    # notify each affected patient
    for appt in affected:
        state.add_notification(
            appt.patient_id, "sms",
            f"Dr {doctor.name} is unavailable. "
            f"Your appointment was {'moved' if appt.id in moved else 'needs rebooking'}.",
            now,
        )

    state.add_log("sick_leave", doctor_id, "available", "on_leave",
                  reason + f"; {len(affected)} affected", now)

    msg = (f"{doctor.name} on leave; {len(moved)} auto-rescheduled, "
           f"{len(offered)} need manual rebooking")
    return EngineResult(True, Action.RESCHEDULED if moved else Action.RESCHEDULE_OFFERED,
                        msg,
                        SeverityCode.WARNING,
                        data={"affected": [a.id for a in affected],
                              "moved": moved, "offered": offered})


# --------------------------------------------------------------------------- #
# B. Chemo session overrun (grace + cascade)
# --------------------------------------------------------------------------- #
def handle_chemo_overrun(state: SystemState, appt_id: str, now: str) -> EngineResult:
    appt = state.appointment(appt_id)
    if appt is None:
        return EngineResult(False, Action.OVERRUN_LOGGED, "appointment not found")

    drug = state.drug(appt.drug_id) if appt.drug_id else None
    grace = drug.grace_minutes if drug else 10

    planned_end_m = to_min(appt.slot_end)
    over_min = to_min(now) - planned_end_m
    grace_passed = over_min > grace

    if not grace_passed:
        return EngineResult(True, Action.INFO,  # type: ignore
                            f"within grace period ({over_min}/{grace} min)",
                            data={"overrun_min": over_min, "grace_min": grace})

    # mark overrun
    appt.status = AppointmentStatus.OVERRUN
    state.add_log("overrun", appt_id,
                  f"planned_end {appt.slot_end}",
                  f"actual {now} (+{over_min}m)", f"grace {grace}m exceeded", now)

    # cascade: push the NEXT appointment in this room later by the overrun delta
    next_appt = _next_in_room(state, appt, now)
    pushed = False
    if next_appt is not None:
        res = _alloc(state)
        # try to shift next_appt forward by the overrun (same room/doctor if free)
        new_start = add_min(next_appt.slot_start, over_min)
        new_end = add_min(next_appt.slot_end, over_min)
        r = res.reschedule(next_appt.id, next_appt.doctor_id, next_appt.room_id,
                           new_start, new_end, at=now,
                           reason=f"overrun cascade +{over_min}m")
        if r.success:
            pushed = True
            state.add_log("overrun_cascade", next_appt.id,
                          f"{next_appt.slot_start}", new_start,
                          f"pushed +{over_min}m", now)
            state.add_notification(
                next_appt.patient_id, "sms",
                f"Your appointment is now at {new_start} (running late).", now)
        else:
            # fallback: auto-search a later slot
            r2 = res.reschedule_auto(next_appt.id, at=now,
                                     reason=f"overrun cascade +{over_min}m")
            pushed = r2.success

    return EngineResult(
        True, Action.OVERRUN_LOGGED,
        f"overrun logged (+{over_min}m); next patient "
        f"{'pushed' if pushed else 'could not be pushed'}",
        SeverityCode.WARNING,
        actions=["grace period exceeded",
                 f"cascade applied: +{over_min}m to next room appointment" if pushed
                 else "no cascade (no next appointment)"],
        data={"overrun_min": over_min, "grace_min": grace,
              "next_pushed": pushed, "next_appt": next_appt.id if next_appt else None},
    )


def _next_in_room(state: SystemState, appt: Appointment, now: str) -> Optional[Appointment]:
    """Next live appointment in the same room strictly after `appt` ends."""
    if appt.room_id is None:
        return None
    cands = [
        a for a in state.active_appointments()
        if a.room_id == appt.room_id and a.id != appt.id
        and to_min(a.slot_start) >= to_min(appt.slot_end)
    ]
    if not cands:
        return None
    cands.sort(key=lambda a: to_min(a.slot_start))
    return cands[0]


# --------------------------------------------------------------------------- #
# C. Two emergencies at the same time
# --------------------------------------------------------------------------- #
def handle_emergency_pair(state: SystemState, e1_id: str, e2_id: str,
                          now: str) -> EngineResult:
    e1 = state.emergencies.get(e1_id)
    e2 = state.emergencies.get(e2_id)
    if e1 is None or e2 is None:
        return EngineResult(False, Action.EMERGENCY_WAITING, "emergency not found")

    out = two_emergencies_at_once(state, e1, e2, now)

    if out["different_doctors"]:
        msg = (f"assigned to different doctors: "
               f"{e1.name if False else e1_id}->{out['assigned'].get(e1_id)}, "
               f"{e2_id}->{out['assigned'].get(e2_id)}")
        sev = SeverityCode.CRITICAL
        act = Action.EMERGENCY_ASSIGNED
    else:
        winner = [k for k in out["assigned"]][0] if out["assigned"] else None
        loser = out["waiting"][0] if out["waiting"] else None
        w_em = state.emergencies.get(winner) if winner else None
        l_em = state.emergencies.get(loser) if loser else None
        msg = (f"only one free doctor; {winner} (severity "
               f"{w_em.severity.value}, subscore {w_em.subscore}) sees first; "
               f"{loser} (severity {l_em.severity.value}, subscore {l_em.subscore}) "
               f"waits in priority queue" if winner and loser
               else "no free doctors; both waiting by priority")
        sev = SeverityCode.CRITICAL
        act = Action.EMERGENCY_WAITING

    for em in (e1, e2):
        if em.status == "assigned":
            patient = state.patient(em.patient_id)
            if patient:
                doc = state.doctor(em.assigned_doctor_id)
                state.add_notification(
                    em.patient_id, "sms",
                    f"Emergency: Dr {doc.name} is with you now.", now)
        else:
            patient = state.patient(em.patient_id)
            if patient:
                state.add_notification(
                    em.patient_id, "sms",
                    "Emergency: you are in the priority queue. Please wait.", now)

    return EngineResult(True, act, msg, sev,
                        data=out)


# --------------------------------------------------------------------------- #
# D. Room equipment breakdown
# --------------------------------------------------------------------------- #
def handle_room_breakdown(state: SystemState, room_id: str, now: str,
                          available_until: str = "23:59",
                          reason: str = "equipment breakdown") -> EngineResult:
    room = state.room(room_id)
    if room is None:
        return EngineResult(False, Action.ROOM_FLAGGED, "room not found")  # type: ignore

    room.status = RoomStatus.UNAVAILABLE
    room.available_until = available_until
    state.add_log("breakdown", room_id, "available", "unavailable",
                  reason, now)

    # affected = live appointments in this room at/after now
    affected = [
        a for a in state.active_appointments()
        if a.room_id == room_id and to_min(a.slot_start) >= to_min(now)
    ]

    res = _alloc(state)
    reassigned, offered = [], []
    for appt in affected:
        if appt.is_chemo:
            # search another compatible room for the same doctor
            from .slots import SlotRegistry
            reg = SlotRegistry(state)
            from .conflict import ConflictDetector
            det = ConflictDetector(state, reg)
            from .allocator import RoomAllocator
            ra = RoomAllocator(state, reg, det)
            cands = ra.find_best_chemo(appt.doctor_id, appt.drug_id or "",
                                       preferred_start=appt.slot_start)
            cands = [c for c in cands if c.room_id != room_id]
            if cands:
                best = cands[0]
                r = res.reschedule(appt.id, best.doctor_id, best.room_id,
                                   best.start, best.end, at=now,
                                   reason=f"room {room.name} breakdown")
                if r.success:
                    reassigned.append(appt.id)
                else:
                    offered.append(appt.id)
            else:
                offered.append(appt.id)
        else:
            # consult: just move to another free slot of same doctor
            r = res.reschedule_auto(appt.id, at=now,
                                    reason=f"room {room.name} breakdown",
                                    only_doctor=True)
            (reassigned if r.success else offered).append(appt.id)

        state.add_notification(
            appt.patient_id, "sms",
            f"Room {room.name} is unavailable. "
            f"Your session was {'reassigned' if appt.id in reassigned else 'needs rebooking'}.",
            now,
        )

    msg = (f"room {room.name} flagged unavailable until {available_until}; "
           f"{len(reassigned)} reassigned, {len(offered)} need manual rebooking")
    return EngineResult(True, Action.ROOM_FLAGGED, msg, SeverityCode.CRITICAL,
                        data={"affected": [a.id for a in affected],
                              "reassigned": reassigned, "offered": offered})


# --------------------------------------------------------------------------- #
# E. Patient no-show (release slot + notify next in queue)
# --------------------------------------------------------------------------- #
def handle_no_show(state: SystemState, appt_id: str, now: str,
                   no_show_min: int = 15) -> EngineResult:
    appt = state.appointment(appt_id)
    if appt is None:
        return EngineResult(False, Action.NO_SHOW, "appointment not found")  # type: ignore

    late_min = to_min(now) - to_min(appt.slot_start)
    if appt.checked_in or late_min < no_show_min:
        return EngineResult(True, Action.INFO,  # type: ignore
                            f"not a no-show yet ({late_min}/{no_show_min} min, "
                            f"checked_in={appt.checked_in})")

    appt.status = AppointmentStatus.NO_SHOW
    state.add_log("no_show", appt_id, appt.slot_start, f"released@{now}",
                  f"{late_min} min late, no check-in", now)

    # release the slot: mark cancelled-equivalent so doctor/room free up.
    # (appointment stays for audit but no longer blocks.)
    released_doctor = appt.doctor_id
    released_room = appt.room_id

    # find the next patient in queue for that doctor (or room)
    next_appt = _next_in_doctor_queue(state, released_doctor, now)
    notified_next = False
    if next_appt is not None:
        state.add_notification(
            next_appt.patient_id, "sms",
            f"You're up! Your slot at {next_appt.slot_start} is now available "
            f"(previous patient did not arrive).", now)
        notified_next = True
        state.add_log("no_show_next_notified", next_appt.id,
                      "", next_appt.slot_start, "slot released, next up", now)

    return EngineResult(
        True, Action.SLOT_RELEASED,
        f"no-show recorded; slot {appt.slot_start} released; "
        f"{'next patient notified' if notified_next else 'no one next in queue'}",
        SeverityCode.INFO,
        data={"released_doctor": released_doctor,
              "released_room": released_room,
              "next_notified": notified_next,
              "next_appt": next_appt.id if next_appt else None},
    )


def _next_in_doctor_queue(state: SystemState, doctor_id: str, now: str):
    """Next live appointment for the doctor after `now` (the queue)."""
    cands = [
        a for a in state.active_appointments(doctor_id)
        if a.doctor_id == doctor_id
        and a.status == AppointmentStatus.BOOKED
        and to_min(a.slot_start) >= to_min(now)
    ]
    if not cands:
        return None
    cands.sort(key=lambda a: to_min(a.slot_start))
    return cands[0]


# --------------------------------------------------------------------------- #
# Primitive: advance the clock (drives watchdogs)
# --------------------------------------------------------------------------- #
def advance_clock(state: SystemState, now: str,
                  no_show_min: int = 15) -> dict:
    """Time-advance primitive. Returns a summary of what changed.

    Triggers:
      * auto no-show for any BOOKED appointment past its start+no_show_min
      * auto overrun flag for any ACTIVE chemo past planned_end+grace

    Idempotent: only acts on appointments still in their triggerable status.
    """
    from .slots import SlotRegistry
    reg = SlotRegistry(state)
    no_shows = []
    overruns = []

    for appt in list(state.appointments.values()):
        # no-show
        if appt.status == AppointmentStatus.BOOKED and not appt.checked_in:
            late = to_min(now) - to_min(appt.slot_start)
            if late >= no_show_min:
                r = handle_no_show(state, appt.id, now, no_show_min)
                if r.action == Action.SLOT_RELEASED:
                    no_shows.append(appt.id)
        # overrun
        elif appt.status == AppointmentStatus.ACTIVE and appt.is_chemo:
            r = handle_chemo_overrun(state, appt.id, now)
            if r.action == Action.OVERRUN_LOGGED:
                overruns.append(appt.id)

    return {"now": now, "no_shows": no_shows, "overruns": overruns}


# --------------------------------------------------------------------------- #
# H. Cancel an appointment (release slot + notify next in queue)
# --------------------------------------------------------------------------- #
# statuses a manual cancel is allowed from
_CANCELABLE = (
    AppointmentStatus.BOOKED, AppointmentStatus.RESCHEDULED,
)


def handle_cancel_appointment(state: SystemState, appt_id: str, now: str,
                              reason: str = "patient request") -> EngineResult:
    """Manually cancel a booked/rescheduled appointment.

    Releases the doctor (and room) slot and notifies the next patient in the
    queue for that doctor, mirroring the no-show release path. Already-active,
    completed, or already-cancelled appointments cannot be cancelled.
    """
    appt = state.appointment(appt_id)
    if appt is None:
        return EngineResult(False, Action.CANCELLED, "appointment not found",
                            SeverityCode.WARNING)

    if appt.status not in _CANCELABLE:
        return EngineResult(
            False, Action.INFO,
            f"cannot cancel: status is {appt.status.value}",
            SeverityCode.WARNING)

    patient = state.patient(appt.patient_id)
    doctor = state.doctor(appt.doctor_id)
    appt.status = AppointmentStatus.CANCELLED
    state.add_log("cancelled", appt_id, appt.slot_start, f"cancelled@{now}",
                  reason, now)

    if patient:
        state.add_notification(
            appt.patient_id, "sms",
            f"Your appointment at {appt.slot_start} with "
            f"{doctor.name if doctor else '?'} has been cancelled.",
            now)

    # release the slot & pull the next patient forward
    next_appt = _next_in_doctor_queue(state, appt.doctor_id, now)
    notified_next = False
    if next_appt is not None:
        state.add_notification(
            next_appt.patient_id, "sms",
            f"Good news — a slot opened up at {next_appt.slot_start}. "
            f"Please arrive on time.", now)
        notified_next = True
        state.add_log("cancel_next_notified", next_appt.id,
                      "", next_appt.slot_start, "slot freed, next up", now)

    return EngineResult(
        True, Action.CANCELLED,
        f"appointment at {appt.slot_start} cancelled; slot released"
        + ("; next patient notified" if notified_next else ""),
        SeverityCode.INFO,
        data={"cancelled": appt_id,
              "next_notified": notified_next,
              "next_appt": next_appt.id if next_appt else None},
    )


# --------------------------------------------------------------------------- #
# D2. Restore a broken-down room (inverse of handle_room_breakdown)
# --------------------------------------------------------------------------- #
def handle_room_restore(state: SystemState, room_id: str, now: str,
                        reason: str = "equipment repaired") -> EngineResult:
    """Return a broken-down room to AVAILABLE and clear its until-time.

    No auto-rebooking is performed (patients were already moved when the room
    broke down); this simply makes the room bookable again.
    """
    room = state.room(room_id)
    if room is None:
        return EngineResult(False, Action.ROOM_RESTORED, "room not found",
                            SeverityCode.WARNING)

    was_down = room.status == RoomStatus.UNAVAILABLE
    room.status = RoomStatus.AVAILABLE
    room.available_until = ""
    state.add_log("room_restored", room_id, "unavailable" if was_down else room.status.value,
                  "available", reason, now)

    return EngineResult(
        True, Action.ROOM_RESTORED,
        f"room {room.name} is available again" if was_down
        else f"room {room.name} already available",
        SeverityCode.INFO,
        data={"room_id": room_id, "was_down": was_down},
    )


# --------------------------------------------------------------------------- #
# C2. Emergency: manually assign to a specific doctor
# --------------------------------------------------------------------------- #
def handle_emergency_assign(state: SystemState, emergency_id: str, doctor_id: str,
                            now: str) -> EngineResult:
    """Assign a waiting/assigned emergency to a specific doctor (overrides auto)."""
    em = state.emergencies.get(emergency_id)
    if em is None:
        return EngineResult(False, Action.EMERGENCY_ASSIGNED_MANUAL,
                            "emergency not found", SeverityCode.WARNING)
    doc = state.doctor(doctor_id)
    if doc is None:
        return EngineResult(False, Action.EMERGENCY_ASSIGNED_MANUAL,
                            "doctor not found", SeverityCode.WARNING)
    if em.status == "completed":
        return EngineResult(False, Action.INFO,
                            "emergency already completed", SeverityCode.WARNING)

    prev = em.assigned_doctor_id
    em.assigned_doctor_id = doctor_id
    em.status = "assigned"
    state.add_log("emergency_assigned_manual", emergency_id,
                  prev or "unassigned", doctor_id,
                  f"manual assign severity {em.severity.value}", now)
    state.add_notification(
        em.patient_id, "sms",
        f"Emergency: you have been assigned to {doc.name}.", now)

    return EngineResult(
        True, Action.EMERGENCY_ASSIGNED_MANUAL,
        f"emergency assigned to {doc.name}",
        SeverityCode.INFO,
        data={"emergency_id": emergency_id, "doctor_id": doctor_id},
    )


# --------------------------------------------------------------------------- #
# C3. Emergency: mark completed / clear
# --------------------------------------------------------------------------- #
def handle_emergency_complete(state: SystemState, emergency_id: str,
                              now: str) -> EngineResult:
    """Mark an emergency as finished (done / cleared from the live queue)."""
    em = state.emergencies.get(emergency_id)
    if em is None:
        return EngineResult(False, Action.EMERGENCY_COMPLETED,
                            "emergency not found", SeverityCode.WARNING)
    if em.status == "completed":
        return EngineResult(False, Action.INFO,
                            "emergency already completed", SeverityCode.WARNING)

    doctor = state.doctor(em.assigned_doctor_id) if em.assigned_doctor_id else None
    em.status = "completed"
    state.add_log("emergency_completed", emergency_id, em.status, "completed",
                  f"severity {em.severity.value}"
                  + (f" by {doctor.name}" if doctor else ""), now)

    return EngineResult(
        True, Action.EMERGENCY_COMPLETED,
        f"emergency marked completed"
        + (f" ({doctor.name})" if doctor else ""),
        SeverityCode.INFO,
        data={"emergency_id": emergency_id},
    )
