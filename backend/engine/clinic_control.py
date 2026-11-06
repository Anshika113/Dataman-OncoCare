"""The controls a doctor already has in the corridor, made real in the system.

Every one of these is something a consultant says out loud today — "give me
ten more minutes", "send the next one in", "swap those two", "can you take
this patient", "I'm closing at one" — and which the schedule then finds out
about late, if at all. Wiring them up is what turns the doctor from a subject
of the scheduler into its operator.

Three rules hold throughout:

* A doctor's action touches **their own list only**. The single exception is
  a hand-off, which names one colleague and is validated against that
  colleague's specialty, leave and daily cap.
* Nothing is silent. Each action files an :mod:`actions` record with a
  before/after snapshot and a reason, so it can be read and undone.
* The engine refuses rather than guesses. If a move cannot be made legally it
  says which constraint stopped it.

Pure module: no I/O, no clock.
"""

from __future__ import annotations

from typing import Optional

from .state import (
    SystemState, Appointment, AppointmentStatus, DoctorStatus,
)
from .result import EngineResult, Action, SeverityCode
from .slots import SlotRegistry
from .timeutils import to_min, to_hhmm, duration_min
from . import actions as act

#: Statuses a doctor may still rearrange.
LIVE = (AppointmentStatus.BOOKED, AppointmentStatus.RESCHEDULED,
        AppointmentStatus.ACTIVE, AppointmentStatus.OVERRUN)

DAY_END = "18:00"
MAX_EXTEND = 120


def _day_list(state: SystemState, doctor_id: str, day: str) -> list[Appointment]:
    """A doctor's live appointments for a day, in clock order."""
    return sorted(
        [a for a in state.appointments.values()
         if a.doctor_id == doctor_id and a.eff_date == day and a.status in LIVE],
        key=lambda a: to_min(a.slot_start))


def _name(state: SystemState, appt: Appointment) -> str:
    p = state.patient(appt.patient_id)
    return p.name if p else appt.patient_id


# --------------------------------------------------------------------------- #
# "Give me ten more minutes with this patient"
# --------------------------------------------------------------------------- #
def extend(state: SystemState, appt_id: str, minutes: int, now: str,
           by: str = "") -> EngineResult:
    """Lengthen a visit and push only this doctor's own later patients."""
    appt = state.appointment(appt_id)
    if appt is None:
        return EngineResult(False, Action.RESCHEDULED, "appointment not found",
                            SeverityCode.WARNING)
    if appt.status not in LIVE:
        return EngineResult(False, Action.INFO,
                            f"cannot extend: status is {appt.status.value}",
                            SeverityCode.WARNING)
    minutes = int(minutes)
    if not 1 <= minutes <= MAX_EXTEND:
        return EngineResult(False, Action.INFO,
                            f"extend by 1–{MAX_EXTEND} minutes",
                            SeverityCode.WARNING)

    day = appt.eff_date
    before: dict[str, dict] = {appt.id: act.snapshot(appt)}

    new_end = to_min(appt.slot_end) + minutes
    appt.slot_end = to_hhmm(new_end)

    # push the doctor's own later patients just enough to clear the overrun
    cursor = new_end
    pushed: list[str] = []
    for other in _day_list(state, appt.doctor_id, day):
        if other.id == appt.id or to_min(other.slot_start) >= cursor:
            continue
        if to_min(other.slot_start) < to_min(appt.slot_start):
            continue  # already finished or running earlier; leave alone
        before.setdefault(other.id, act.snapshot(other))
        length = duration_min(other.slot_start, other.slot_end)
        other.slot_start = to_hhmm(cursor)
        other.slot_end = to_hhmm(cursor + length)
        other.status = AppointmentStatus.RESCHEDULED
        pushed.append((other.patient_id, _name(state, other)))
        cursor += length

    over = [a for a in _day_list(state, appt.doctor_id, day)
            if to_min(a.slot_end) > to_min(DAY_END)]

    summary = (f"{_name(state, appt)} extended by {minutes} min"
               + (f"; {len(pushed)} patient(s) pushed" if pushed else ""))
    rec = act.record(state, "extend", now, day, before, summary,
                     why=f"doctor asked for {minutes} more minutes",
                     by=by, doctor_id=appt.doctor_id)
    for pid, _pname in pushed:
        state.add_notification(
            pid, "sms",
            "Your appointment is running a little late today. We will see "
            "you as soon as the doctor is free.", now, kind="delay")
    state.add_log("extend", appt.id, "", f"+{minutes}min", summary, now)

    msg = summary
    if over:
        msg += (f" — warning: {len(over)} now ends after {DAY_END} "
                f"({', '.join(_name(state, a) for a in over)})")
    return EngineResult(True, Action.RESCHEDULED, msg,
                        SeverityCode.WARNING if over else SeverityCode.INFO,
                        data={"action_id": rec.id,
                              "pushed": [n for _pid, n in pushed],
                              "past_day_end": [a.id for a in over]})


# --------------------------------------------------------------------------- #
# "Send the next one in"
# --------------------------------------------------------------------------- #
def pull_forward(state: SystemState, doctor_id: str, now: str,
                 day: Optional[str] = None, by: str = "") -> EngineResult:
    """Move this doctor's next patient into the gap that just opened.

    Prefers someone who has actually arrived — pulling forward a patient who
    is not in the building only moves the problem.
    """
    d = day or state.day()
    upcoming = [a for a in _day_list(state, doctor_id, d)
                if to_min(a.slot_start) > to_min(now)]
    if not upcoming:
        return EngineResult(False, Action.INFO, "nobody left to pull forward",
                            SeverityCode.INFO)

    here = [a for a in upcoming if a.checked_in]
    target = here[0] if here else upcoming[0]
    waiting_note = ("" if here else
                    " (not checked in yet — they may not be here)")

    reg = SlotRegistry(state, day=d)
    length = duration_min(target.slot_start, target.slot_end)
    before_min = to_min(target.slot_start)
    candidates = [s for s, _ in reg.doctor_candidate_slots(doctor_id, length, step=5)
                  if to_min(s) >= to_min(now) and to_min(s) < before_min]
    if not candidates:
        return EngineResult(False, Action.INFO,
                            f"no earlier gap for {_name(state, target)}",
                            SeverityCode.INFO)

    before = {target.id: act.snapshot(target)}
    gained = before_min - to_min(candidates[0])
    target.slot_start = candidates[0]
    target.slot_end = to_hhmm(to_min(candidates[0]) + length)
    target.status = AppointmentStatus.RESCHEDULED

    summary = f"{_name(state, target)} pulled forward to {target.slot_start}"
    rec = act.record(state, "pull_forward", now, d, before, summary,
                     why=f"a gap opened; saves {gained} min of waiting",
                     by=by, doctor_id=doctor_id)
    state.add_notification(target.patient_id, "sms",
                           f"The doctor can see you earlier — please come to "
                           f"the room now ({target.slot_start}).", now,
                           kind="appointment", ref=target.id)
    state.add_log("pull_forward", target.id, "", target.slot_start, summary, now)
    return EngineResult(True, Action.RESCHEDULED, summary + waiting_note,
                        data={"action_id": rec.id, "gained_min": gained,
                              "appointment_id": target.id})


# --------------------------------------------------------------------------- #
# "Swap those two"
# --------------------------------------------------------------------------- #
def swap(state: SystemState, a_id: str, b_id: str, now: str,
         by: str = "") -> EngineResult:
    """Exchange the slots of two of this doctor's own patients."""
    a, b = state.appointment(a_id), state.appointment(b_id)
    if a is None or b is None:
        return EngineResult(False, Action.RESCHEDULED, "appointment not found",
                            SeverityCode.WARNING)
    if a.id == b.id:
        return EngineResult(False, Action.INFO, "those are the same appointment",
                            SeverityCode.WARNING)
    if a.doctor_id != b.doctor_id:
        return EngineResult(False, Action.INFO,
                            "both appointments must be with the same doctor",
                            SeverityCode.WARNING)
    if a.eff_date != b.eff_date:
        return EngineResult(False, Action.INFO, "both must be on the same day",
                            SeverityCode.WARNING)
    for x in (a, b):
        if x.status not in LIVE:
            return EngineResult(False, Action.INFO,
                                f"cannot swap: {_name(state, x)} is "
                                f"{x.status.value}", SeverityCode.WARNING)
    if duration_min(a.slot_start, a.slot_end) != duration_min(b.slot_start, b.slot_end):
        # different lengths would silently resize someone's visit
        return EngineResult(
            False, Action.INFO,
            "those visits are different lengths — move one instead of swapping",
            SeverityCode.WARNING)

    before = {a.id: act.snapshot(a), b.id: act.snapshot(b)}
    a.slot_start, b.slot_start = b.slot_start, a.slot_start
    a.slot_end, b.slot_end = b.slot_end, a.slot_end
    a.status = b.status = AppointmentStatus.RESCHEDULED

    summary = (f"{_name(state, a)} and {_name(state, b)} swapped "
               f"({a.slot_start} / {b.slot_start})")
    rec = act.record(state, "swap", now, a.eff_date, before, summary,
                     why="doctor reordered their own list", by=by,
                     doctor_id=a.doctor_id)
    for x in (a, b):
        state.add_notification(x.patient_id, "sms",
                               f"Your appointment time today is now "
                               f"{x.slot_start}.", now,
                               kind="appointment", ref=x.id)
    state.add_log("swap", a.id, b.id, summary, "manual swap", now)
    return EngineResult(True, Action.RESCHEDULED, summary,
                        data={"action_id": rec.id})


# --------------------------------------------------------------------------- #
# "Can you take this patient"
# --------------------------------------------------------------------------- #
def hand_off(state: SystemState, appt_id: str, to_doctor_id: str, now: str,
             reason: str = "", by: str = "", note: str = "") -> EngineResult:
    """Give one patient to a named colleague, if they can actually take them.

    ``reason`` is why the list had to move; ``note`` is what the colleague
    needs to know about this patient before they call them in. They are
    different things and the second one is the one a doctor actually wants:
    "counts back at 11:05, keen to go ahead today" is not a scheduling
    reason, and putting it in ``reason`` would bury it in the audit summary.
    """
    appt = state.appointment(appt_id)
    if appt is None:
        return EngineResult(False, Action.RESCHEDULED, "appointment not found",
                            SeverityCode.WARNING)
    if appt.status not in LIVE:
        return EngineResult(False, Action.INFO,
                            f"cannot hand off: status is {appt.status.value}",
                            SeverityCode.WARNING)
    src = state.doctor(appt.doctor_id)
    dst = state.doctor(to_doctor_id)
    if dst is None:
        return EngineResult(False, Action.INFO, "that doctor does not exist",
                            SeverityCode.WARNING)
    if dst.id == appt.doctor_id:
        return EngineResult(False, Action.INFO,
                            "that is already the treating doctor",
                            SeverityCode.WARNING)
    if dst.status in (DoctorStatus.ON_LEAVE, DoctorStatus.UNAVAILABLE):
        return EngineResult(False, Action.INFO,
                            f"{dst.name} is {dst.status.value.replace('_', ' ')}",
                            SeverityCode.WARNING)

    compatible = (src is None or dst.specialty == src.specialty
                  or dst.specialty in src.backup_compatible
                  or dst.id in src.backup_compatible)
    if not compatible:
        return EngineResult(
            False, Action.INFO,
            f"{dst.name} ({dst.specialty}) is not a listed cover for "
            f"{src.specialty if src else 'this patient'}",
            SeverityCode.WARNING)

    day = appt.eff_date
    used = state.doctor_appointment_count(dst.id, day=day)
    if used >= dst.daily_cap:
        return EngineResult(False, Action.INFO,
                            f"{dst.name} is at the daily cap "
                            f"({used}/{dst.daily_cap})", SeverityCode.WARNING)

    reg = SlotRegistry(state, day=day)
    length = duration_min(appt.slot_start, appt.slot_end)
    before = {appt.id: act.snapshot(appt)}

    if reg.is_doctor_slot_free(dst.id, appt.slot_start, appt.slot_end):
        new_start, new_end = appt.slot_start, appt.slot_end
        moved = False
    else:
        options = [s for s in reg.doctor_candidate_slots(dst.id, length, step=15)
                   if to_min(s[0]) >= to_min(now)]
        if not options:
            return EngineResult(
                False, Action.INFO,
                f"{dst.name} has no free {length}-minute slot left today",
                SeverityCode.WARNING)
        new_start, new_end = options[0]
        moved = True

    appt.doctor_id = dst.id
    appt.slot_start, appt.slot_end = new_start, new_end
    appt.status = AppointmentStatus.RESCHEDULED
    appt.reschedule_reason = reason or "handed over"
    if note.strip():
        appt.handoff_note = note.strip()[:500]
        appt.handoff_from = src.name if src else ""

    summary = (f"{_name(state, appt)} handed to {dst.name} at {new_start}"
               + (" (time moved to fit)" if moved else " (same time)"))
    rec = act.record(state, "hand_off", now, day, before, summary,
                     why=reason or "doctor handed the patient over", by=by,
                     doctor_id=dst.id)
    state.add_notification(appt.patient_id, "sms",
                           f"You will be seen by {dst.name} at {new_start} today.",
                           now, kind="appointment", ref=appt.id)
    state.add_log("hand_off", appt.id, src.name if src else "", dst.name,
                  (f"note: {appt.handoff_note[:60]}" if appt.handoff_note
                   else reason or "hand-off"), now)
    return EngineResult(True, Action.RESCHEDULED, summary,
                        data={"action_id": rec.id, "to_doctor_id": dst.id,
                              "slot_start": new_start, "moved": moved,
                              "note": appt.handoff_note,
                              "note_from": appt.handoff_from})


# --------------------------------------------------------------------------- #
# "I'm closing at one"
# --------------------------------------------------------------------------- #
def close_list(state: SystemState, doctor_id: str, from_time: str, now: str,
               allocator, day: Optional[str] = None, dry_run: bool = True,
               by: str = "") -> EngineResult:
    """Stop taking patients after ``from_time`` and rehome whoever is left.

    Always answer the plan first: a doctor closing their list wants to know
    who it affects before anything moves.
    """
    d = day or state.day()
    doc = state.doctor(doctor_id)
    if doc is None:
        return EngineResult(False, Action.INFO, "doctor not found",
                            SeverityCode.WARNING)
    affected = [a for a in _day_list(state, doctor_id, d)
                if to_min(a.slot_start) >= to_min(from_time)]
    if not affected:
        return EngineResult(True, Action.INFO,
                            f"nothing booked after {from_time} — list is clear",
                            data={"affected": [], "plan": []})

    reg = SlotRegistry(state, day=d)
    backups = [
        x for x in state.doctors.values()
        if x.id != doctor_id
        and x.status not in (DoctorStatus.ON_LEAVE, DoctorStatus.UNAVAILABLE)
        and (x.specialty == doc.specialty or x.specialty in doc.backup_compatible)
    ]

    plan: list[dict] = []
    for a in affected:
        length = duration_min(a.slot_start, a.slot_end)
        cover = None
        for b in backups:
            if state.doctor_appointment_count(b.id, day=d) >= b.daily_cap:
                continue
            if reg.is_doctor_slot_free(b.id, a.slot_start, a.slot_end):
                cover = (b, a.slot_start, a.slot_end)
                break
            opts = [s for s in reg.doctor_candidate_slots(b.id, length, step=15)
                    if to_min(s[0]) >= to_min(now)]
            if opts:
                cover = (b, opts[0][0], opts[0][1])
                break
        plan.append({
            "appointment_id": a.id,
            "patient_name": _name(state, a),
            "was": a.slot_start,
            "to_doctor_id": cover[0].id if cover else "",
            "to_doctor_name": cover[0].name if cover else "",
            "to_slot": cover[1] if cover else "",
            "covered": bool(cover),
        })

    uncovered = [p for p in plan if not p["covered"]]
    if dry_run:
        return EngineResult(
            True, Action.RESCHEDULE_OFFERED,
            f"{len(affected)} patient(s) after {from_time}: "
            f"{len(plan) - len(uncovered)} can be covered, {len(uncovered)} cannot",
            SeverityCode.WARNING if uncovered else SeverityCode.INFO,
            data={"plan": plan, "uncovered": uncovered, "applied": False})

    before: dict[str, dict] = {}
    moved = 0
    for p in plan:
        if not p["covered"]:
            continue
        a = state.appointment(p["appointment_id"])
        before[a.id] = act.snapshot(a)
        a.doctor_id = p["to_doctor_id"]
        a.slot_start, a.slot_end = p["to_slot"], to_hhmm(
            to_min(p["to_slot"]) + duration_min(before[a.id]["slot_start"],
                                                before[a.id]["slot_end"]))
        a.status = AppointmentStatus.RESCHEDULED
        a.reschedule_reason = f"{doc.name} closed their list at {from_time}"
        moved += 1
        state.add_notification(
            a.patient_id, "sms",
            f"Your appointment today is now with {p['to_doctor_name']} at "
            f"{a.slot_start}.", now, kind="appointment", ref=a.id)

    summary = (f"{doc.name} closed their list at {from_time}; "
               f"{moved} patient(s) rehomed"
               + (f", {len(uncovered)} still need a slot" if uncovered else ""))
    rec = act.record(state, "close_list", now, d, before, summary,
                     why=f"doctor is unavailable after {from_time}", by=by,
                     doctor_id=doctor_id)
    state.add_log("close_list", "", doctor_id, from_time, summary, now)
    return EngineResult(
        True, Action.RESCHEDULED, summary,
        SeverityCode.WARNING if uncovered else SeverityCode.INFO,
        data={"action_id": rec.id, "plan": plan, "uncovered": uncovered,
              "applied": True})
