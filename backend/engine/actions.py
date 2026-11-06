"""What changed, why, and how to put it back.

The scheduler is allowed to move people — that is the point of it. What it was
not allowed to do, until now, was move them silently. Every reversible change
records a before/after snapshot per appointment plus the reason, so a doctor
who finds their afternoon rearranged can read what happened and undo it in one
step.

Undo is deliberately conservative: it refuses when the world has moved on
(the patient has been seen, the appointment was cancelled, or a later action
touched the same appointment), because a half-applied undo is worse than
none.

Pure module: no I/O, no clock.
"""

from __future__ import annotations

from typing import Iterable, Optional

from .state import SystemState, Appointment, AppointmentStatus, ActionRecord, new_id
from .result import EngineResult, Action, SeverityCode

#: Fields an undo restores. Everything here is schedule placement — never
#: clinical content, which undo has no business rewriting.
TRACKED = ("doctor_id", "room_id", "slot_start", "slot_end", "date", "status")

#: Once a visit has happened, moving it back is meaningless.
_FROZEN = (AppointmentStatus.VISITED, AppointmentStatus.COMPLETED)


def snapshot(appt: Appointment) -> dict:
    """The placement fields of an appointment, as plain data."""
    out = {}
    for f in TRACKED:
        v = getattr(appt, f)
        out[f] = v.value if hasattr(v, "value") else (v or "")
    return out


def _apply(appt: Appointment, data: dict) -> None:
    for f in TRACKED:
        if f not in data:
            continue
        if f == "status":
            appt.status = AppointmentStatus(data[f])
        elif f == "room_id":
            appt.room_id = data[f] or None
        else:
            setattr(appt, f, data[f])


def record(state: SystemState, kind: str, now: str, day: str,
           before: dict[str, dict], summary: str, why: str,
           by: str = "", doctor_id: str = "") -> ActionRecord:
    """File a reversible change.

    ``before`` maps appointment id -> the snapshot taken *before* the change;
    the after-state is read from the appointments as they now stand.
    """
    changes = []
    for aid, prev in before.items():
        appt = state.appointment(aid)
        if appt is None:
            continue
        now_state = snapshot(appt)
        if now_state == prev:
            continue  # nothing actually moved; don't clutter the history
        changes.append({"appointment_id": aid, "before": prev, "after": now_state})

    rec = ActionRecord(
        id=new_id("ACT"), kind=kind, at=now, on=day, by=by or "system",
        doctor_id=doctor_id, summary=summary, why=why, changes=changes)
    state.actions[rec.id] = rec
    return rec


def _blocked_by_later(state: SystemState, rec: ActionRecord) -> Optional[str]:
    """Has a newer, still-standing action touched any of these appointments?"""
    mine = {c["appointment_id"] for c in rec.changes}
    for other in state.actions.values():
        if other.id == rec.id or other.undone:
            continue
        if (other.on, other.at) < (rec.on, rec.at):
            continue
        if mine & {c["appointment_id"] for c in other.changes}:
            return other.summary or other.kind
    return None


def undo(state: SystemState, action_id: str, now: str,
         by: str = "") -> EngineResult:
    """Put the schedule back the way it was before ``action_id``."""
    rec = state.action(action_id)
    if rec is None:
        return EngineResult(False, Action.INFO, "action not found",
                            SeverityCode.WARNING)
    if rec.undone:
        return EngineResult(False, Action.INFO, "already undone",
                            SeverityCode.WARNING)
    if not rec.changes:
        return EngineResult(False, Action.INFO, "nothing to undo",
                            SeverityCode.WARNING)

    later = _blocked_by_later(state, rec)
    if later:
        return EngineResult(
            False, Action.INFO,
            f"cannot undo: \"{later}\" happened afterwards and touches the "
            f"same appointments",
            SeverityCode.WARNING)

    for c in rec.changes:
        appt = state.appointment(c["appointment_id"])
        if appt is None:
            return EngineResult(False, Action.INFO,
                                "cannot undo: an appointment no longer exists",
                                SeverityCode.WARNING)
        if appt.status in _FROZEN:
            return EngineResult(
                False, Action.INFO,
                f"cannot undo: {state.patient(appt.patient_id).name if state.patient(appt.patient_id) else appt.patient_id}"
                f" has already been seen",
                SeverityCode.WARNING)

    for c in rec.changes:
        _apply(state.appointment(c["appointment_id"]), c["before"])

    rec.undone = True
    state.add_log("undo", "", rec.id, rec.kind, rec.summary, now)
    return EngineResult(True, Action.RESCHEDULED,
                        f"undone: {rec.summary}",
                        data={"action_id": rec.id,
                              "restored": len(rec.changes)})


def recent(state: SystemState, doctor_id: str = "", limit: int = 20,
           day: Optional[str] = None) -> list[dict]:
    """The change history a doctor should be shown, newest first."""
    rows = [
        r for r in state.actions.values()
        if (not doctor_id or r.doctor_id == doctor_id
            or any(_touches(state, c, doctor_id) for c in r.changes))
        and (day is None or r.on == day)
    ]
    rows.sort(key=lambda r: (r.on, r.at), reverse=True)
    out = []
    for r in rows[:limit]:
        d = r.to_dict()
        d["changes"] = r.changes          # the UI wants structure, not JSON text
        d["reversible"] = r.reversible
        d["blocked_by"] = None if r.undone else _blocked_by_later(state, r)
        out.append(d)
    return out


def _touches(state: SystemState, change: dict, doctor_id: str) -> bool:
    before, after = change.get("before", {}), change.get("after", {})
    return doctor_id in (before.get("doctor_id"), after.get("doctor_id"))
