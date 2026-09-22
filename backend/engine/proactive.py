"""Proactive operations engine.

Pure, I/O-free *analysis* over :class:`SystemState`. The edge-case handlers in
:mod:`engine.handlers` **react** to a disruption once it happens; this module
looks **ahead** at the current schedule and emits :class:`Insight` objects —
early warnings about forming bottlenecks, capacity limits, growing waits, drug
time-window pressure and under-used resources, each paired with a concrete,
actionable recommendation.

``analyze(state, now)`` only *reads* state (never mutates it) and takes the
clock explicitly, so it is deterministic and unit-testable just like the rest
of the engine. The API layer calls it on demand (``GET /api/insights``) and
folds the result into the live state payload so the dashboard can surface it
without any refresh.

A note on "bottleneck": because the scheduler enforces non-overlap per
resource, a resource can never be *double-booked* — so the meaningful forward
risk is **zero slack** (a fully packed window with no free gap). A packed
window has no buffer, so a single late session cascades. That is what
``QUEUE_OVERFLOW`` detects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .state import (
    SystemState, Appointment, Doctor, AppointmentStatus,
    DoctorStatus, RoomStatus, RoomType,
)
from .slots import SlotRegistry
from .timeutils import to_min, to_hhmm

# --------------------------------------------------------------------------- #
# Tunables
# --------------------------------------------------------------------------- #
DEFAULT_HORIZON_MIN = 60   # how far ahead the analysers look
SLOT_MIN = 30              # standard slot length (matches SlotRegistry default)
CAP_NEAR = 2               # doctor slots-left that counts as "nearing cap"
PACKED_MIN_SESSIONS = 2    # sessions needed before "no slack" is a real risk
LATE_WARN_MIN = 15         # booked, past slot start, not seen -> warn
LATE_CRIT_MIN = 30         # -> critical
EMG_WAIT_WARN_MIN = 10     # emergency waiting, no doctor -> warn
EMG_WAIT_CRIT_MIN = 20     # -> critical

# statuses that still hold a doctor/room slot in the flow (not released/done)
_FLOW = (
    AppointmentStatus.BOOKED,
    AppointmentStatus.RESCHEDULED,
    AppointmentStatus.ACTIVE,
    AppointmentStatus.OVERRUN,
)
_CHEMO_ROOMS = (RoomType.INFUSION_CHAIR, RoomType.ISOLATION)


# --------------------------------------------------------------------------- #
# Types
# --------------------------------------------------------------------------- #
class InsightKind(str, Enum):
    WAIT_TIME = "wait_time"
    QUEUE_OVERFLOW = "queue_overflow"
    DOCTOR_CAP = "doctor_cap"
    DRUG_WINDOW = "drug_window"
    LOAD_REBALANCE = "load_rebalance"
    UNDERUTILISED = "underutilised"


class InsightSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


_SEV_RANK = {
    InsightSeverity.CRITICAL: 0,
    InsightSeverity.WARNING: 1,
    InsightSeverity.INFO: 2,
}


@dataclass
class Insight:
    """A single proactive signal plus the recommendation to act on it."""

    kind: InsightKind
    severity: InsightSeverity
    title: str
    detail: str
    action: str = ""
    resource_id: str = ""
    resource_name: str = ""
    affected: list[str] = field(default_factory=list)
    metric: dict[str, Any] = field(default_factory=dict)
    horizon_min: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "severity": self.severity.value,
            "title": self.title,
            "detail": self.detail,
            "action": self.action,
            "resource_id": self.resource_id,
            "resource_name": self.resource_name,
            "affected": self.affected,
            "metric": self.metric,
            "horizon_min": self.horizon_min,
        }


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def _flow_appointments(state: SystemState, doctor_id: str | None = None,
                       room_id: str | None = None) -> list[Appointment]:
    out = []
    for a in state.appointments.values():
        if a.status not in _FLOW:
            continue
        if doctor_id is not None and a.doctor_id != doctor_id:
            continue
        if room_id is not None and a.room_id != room_id:
            continue
        out.append(a)
    return out


def _sessions_in_window(appts: list[Appointment], now_m: int,
                        end_m: int) -> list[Appointment]:
    """Appointments whose *start* falls inside [now, now+horizon)."""
    return [a for a in appts if now_m <= to_min(a.slot_start) < end_m]


def _has_free_slot(reg: SlotRegistry, is_free, rid: str, now_m: int,
                   end_m: int) -> bool:
    """True if any standard slot starts in [now, now+horizon) and is free."""
    for ws in range(now_m, end_m - SLOT_MIN + 1, SLOT_MIN):
        if is_free(rid, to_hhmm(ws), to_hhmm(ws + SLOT_MIN)):
            return True
    return False


@dataclass
class _WindowReport:
    sessions: list[Appointment]
    has_slack: bool
    packed: bool


# --------------------------------------------------------------------------- #
# Analysers — each returns a list of Insight
# --------------------------------------------------------------------------- #
def _wait_time(state: SystemState, now: str) -> list[Insight]:
    """Patients whose slot has passed (or emergencies) with no doctor yet."""
    out: list[Insight] = []
    now_m = to_min(now)

    for a in state.appointments.values():
        if a.status not in (AppointmentStatus.BOOKED,
                            AppointmentStatus.RESCHEDULED):
            continue
        if a.checked_in:
            continue
        late = now_m - to_min(a.slot_start)
        if late < LATE_WARN_MIN:
            continue
        sev = (InsightSeverity.CRITICAL if late >= LATE_CRIT_MIN
               else InsightSeverity.WARNING)
        p = state.patient(a.patient_id)
        doc = state.doctor(a.doctor_id)
        out.append(Insight(
            kind=InsightKind.WAIT_TIME, severity=sev,
            title=f"Patient waiting {late} min past slot",
            detail=(f"{p.name if p else a.patient_id} was due at "
                    f"{a.slot_start} and has not been checked in / seen."),
            action="Pull this patient forward or page the care team now.",
            resource_id=a.doctor_id,
            resource_name=doc.name if doc else "",
            affected=[a.id],
            metric={"late_min": late, "slot_start": a.slot_start},
        ))

    for em in state.emergencies.values():
        if em.status != "waiting":
            continue
        waited = now_m - to_min(em.created_at)
        if waited < EMG_WAIT_WARN_MIN:
            continue
        sev = (InsightSeverity.CRITICAL
               if waited >= EMG_WAIT_CRIT_MIN or em.severity.value >= 4
               else InsightSeverity.WARNING)
        p = state.patient(em.patient_id)
        out.append(Insight(
            kind=InsightKind.WAIT_TIME, severity=sev,
            title=f"Emergency waiting {waited} min",
            detail=(f"{p.name if p else em.patient_id} (severity "
                    f"{em.severity.value}) still has no doctor."),
            action="Free a doctor or escalate to the duty senior.",
            resource_id=em.patient_id,
            resource_name=p.name if p else em.patient_id,
            affected=[em.id],
            metric={"waited_min": waited, "severity": em.severity.value},
        ))
    return out


def _queue_overflow(state: SystemState, now: str, horizon: int) -> list[Insight]:
    """Resources with a fully-packed window (zero slack) — cascade risk."""
    out: list[Insight] = []
    reg = SlotRegistry(state)
    now_m, end_m = to_min(now), to_min(now) + horizon
    window = f"{now}–{to_hhmm(end_m)}"

    for doc in state.doctors.values():
        if doc.status == DoctorStatus.ON_LEAVE:
            continue
        sessions = _sessions_in_window(
            _flow_appointments(state, doctor_id=doc.id), now_m, end_m)
        if len(sessions) < PACKED_MIN_SESSIONS:
            continue
        slack = _has_free_slot(reg, reg.is_doctor_slot_free, doc.id, now_m, end_m)
        if slack:
            continue
        sev = (InsightSeverity.CRITICAL
               if any(a.status == AppointmentStatus.OVERRUN for a in sessions)
               else InsightSeverity.WARNING)
        out.append(Insight(
            kind=InsightKind.QUEUE_OVERFLOW, severity=sev,
            title=f"No slack with {doc.name}",
            detail=(f"Fully booked {window} — no free gap to absorb a delay. "
                    f"Any overrun cascades into the next {len(sessions)} "
                    f"session(s)."),
            action="Open an extra slot or pre-shift a lower-priority session.",
            resource_id=doc.id, resource_name=doc.name,
            affected=[a.id for a in sessions],
            metric={"sessions": len(sessions), "window_min": horizon,
                    "overrun_feeding": sev == InsightSeverity.CRITICAL},
            horizon_min=horizon,
        ))

    for room in state.rooms.values():
        if room.status != RoomStatus.AVAILABLE or room.type not in _CHEMO_ROOMS:
            continue
        sessions = _sessions_in_window(
            _flow_appointments(state, room_id=room.id), now_m, end_m)
        if len(sessions) < PACKED_MIN_SESSIONS:
            continue
        slack = _has_free_slot(reg, reg.is_room_slot_free, room.id, now_m, end_m)
        if slack:
            continue
        sev = (InsightSeverity.CRITICAL
               if any(a.status == AppointmentStatus.OVERRUN for a in sessions)
               else InsightSeverity.WARNING)
        out.append(Insight(
            kind=InsightKind.QUEUE_OVERFLOW, severity=sev,
            title=f"{room.name} is packed — no slack",
            detail=(f"{len(sessions)} chemo sessions back-to-back {window}; "
                    f"no turnover gap to absorb a delay."),
            action="Balance sessions across the free infusion rooms.",
            resource_id=room.id, resource_name=room.name,
            affected=[a.id for a in sessions],
            metric={"sessions": len(sessions), "window_min": horizon,
                    "overrun_feeding": sev == InsightSeverity.CRITICAL},
            horizon_min=horizon,
        ))
    return out


def _doctor_capacity(state: SystemState, now: str) -> list[Insight]:
    """Doctors at / nearing their daily cap, with a 'full by' projection."""
    out: list[Insight] = []
    now_m = to_min(now)
    for doc in state.doctors.values():
        if doc.status == DoctorStatus.ON_LEAVE:
            continue
        mine = _flow_appointments(state, doctor_id=doc.id)
        used = len(mine)
        remaining = doc.daily_cap - used
        future = sorted((a for a in mine if to_min(a.slot_start) >= now_m),
                        key=lambda a: to_min(a.slot_start))

        if remaining <= 0:
            out.append(Insight(
                kind=InsightKind.DOCTOR_CAP, severity=InsightSeverity.CRITICAL,
                title=f"{doc.name} is at daily capacity",
                detail=(f"{used} of {doc.daily_cap} slots used; {len(future)} "
                        f"still upcoming. No room for new walk-ins or "
                        f"emergencies."),
                action="Redirect new demand to a doctor with free capacity.",
                resource_id=doc.id, resource_name=doc.name,
                affected=[a.id for a in future],
                metric={"used": used, "cap": doc.daily_cap,
                        "remaining": remaining, "future": len(future)},
            ))
        elif remaining <= CAP_NEAR:
            full_by = (future[remaining - 1].slot_end
                       if len(future) >= remaining else "")
            out.append(Insight(
                kind=InsightKind.DOCTOR_CAP, severity=InsightSeverity.WARNING,
                title=f"{doc.name} is nearing daily capacity",
                detail=(f"{used} of {doc.daily_cap} used; {remaining} slot(s) "
                        f"left." + (f" Fully booked by {full_by}."
                                    if full_by else "")),
                action="Keep as overflow capacity only; do not over-book.",
                resource_id=doc.id, resource_name=doc.name,
                affected=[a.id for a in future],
                metric={"used": used, "cap": doc.daily_cap,
                        "remaining": remaining, "full_by": full_by},
            ))
    return out


def _drug_window(state: SystemState, now: str, horizon: int) -> list[Insight]:
    """Chemo sessions whose drug time-of-day window is closing (or breached)."""
    out: list[Insight] = []
    now_m = to_min(now)
    horizon_end = to_hhmm(now_m + horizon)
    for a in state.appointments.values():
        if not a.is_chemo or a.status not in (AppointmentStatus.BOOKED,
                                              AppointmentStatus.RESCHEDULED):
            continue
        if to_min(a.slot_start) < now_m:
            continue
        drug = state.drug(a.drug_id) if a.drug_id else None
        if drug is None:
            continue
        # a full-day window (ends at/after the horizon) is never at risk
        if to_min(drug.time_window.end) > to_min(horizon_end):
            continue
        window = f"{drug.time_window.start}–{drug.time_window.end}"
        if not drug.time_window.contains(a.slot_start):
            out.append(Insight(
                kind=InsightKind.DRUG_WINDOW, severity=InsightSeverity.CRITICAL,
                title=f"Chemo outside drug window ({drug.name})",
                detail=(f"{drug.name} may only be given {window}, but this "
                        f"session starts {a.slot_start}."),
                action="Move this session back inside the allowed window.",
                resource_id=a.id, resource_name=drug.name,
                affected=[a.id],
                metric={"window": window, "slot_start": a.slot_start},
            ))
        else:
            out.append(Insight(
                kind=InsightKind.DRUG_WINDOW, severity=InsightSeverity.WARNING,
                title=f"Drug window closing for {drug.name}",
                detail=(f"The {a.slot_start} session must start before the "
                        f"window closes at {drug.time_window.end}."),
                action="Protect this slot — do not push it any later.",
                resource_id=a.id, resource_name=drug.name,
                affected=[a.id],
                metric={"window": window, "slot_start": a.slot_start},
            ))
    return out


def _load_rebalance(state: SystemState, now: str, horizon: int) -> list[Insight]:
    """Shift load off a fully-packed doctor onto a compatible idle one."""
    reg = SlotRegistry(state)
    now_m, end_m = to_min(now), to_min(now) + horizon

    reports: list[tuple[Doctor, _WindowReport, int]] = []
    for doc in state.doctors.values():
        if doc.status == DoctorStatus.ON_LEAVE:
            continue
        sessions = _sessions_in_window(
            _flow_appointments(state, doctor_id=doc.id), now_m, end_m)
        slack = _has_free_slot(reg, reg.is_doctor_slot_free, doc.id, now_m, end_m)
        remaining = doc.daily_cap - len(_flow_appointments(
            state, doctor_id=doc.id))
        reports.append((doc, _WindowReport(sessions, slack,
                                           (not slack) and len(sessions) >= PACKED_MIN_SESSIONS),
                        remaining))
    if len(reports) < 2:
        return []

    packed = [r for r in reports if r[1].packed]
    if not packed:
        return []
    busiest_doc, busiest_rep, busiest_rem = max(
        packed, key=lambda r: (len(r[1].sessions), -r[2]))

    ok_specs = {busiest_doc.specialty} | set(busiest_doc.backup_compatible)
    idle = [r for r in reports
            if r[1].has_slack and not r[1].sessions and r[2] > busiest_rem
            and r[0].specialty in ok_specs]
    if not idle:
        return []
    idle_doc = max(idle, key=lambda r: r[2])[0]

    future = sorted(
        (a for a in state.appointments.values()
         if a.doctor_id == busiest_doc.id
         and a.status in (AppointmentStatus.BOOKED, AppointmentStatus.RESCHEDULED)
         and to_min(a.slot_start) >= now_m),
        key=lambda a: to_min(a.slot_start))
    move = future[0] if future else None

    detail = (f"{busiest_doc.name} is fully packed {now}–{to_hhmm(end_m)} "
              f"({busiest_rem} slot(s) left) while {idle_doc.name} is free.")
    if move:
        detail += f" Suggest moving the {move.slot_start} session to " \
                  f"{idle_doc.name}."
        action = (f"Reschedule the {move.slot_start} session from "
                  f"{busiest_doc.name} to {idle_doc.name}.")
        affected = [move.id]
    else:
        action = f"Direct new bookings to {idle_doc.name}."
        affected = []

    return [Insight(
        kind=InsightKind.LOAD_REBALANCE, severity=InsightSeverity.WARNING,
        title="Rebalance workload",
        detail=detail,
        action=action,
        resource_id=busiest_doc.id, resource_name=busiest_doc.name,
        affected=affected,
        metric={"busy": busiest_doc.id, "idle": idle_doc.id,
                "busy_sessions": len(busiest_rep.sessions),
                "busy_remaining": busiest_rem,
                "move_appt": move.id if move else ""},
        horizon_min=horizon,
    )]


def _underutilised(state: SystemState, now: str, horizon: int) -> list[Insight]:
    """Spare capacity in the near term — where overflow can go."""
    out: list[Insight] = []
    now_m, end_m = to_min(now), to_min(now) + horizon

    for doc in state.doctors.values():
        if doc.status == DoctorStatus.ON_LEAVE:
            continue
        if _sessions_in_window(
                _flow_appointments(state, doctor_id=doc.id), now_m, end_m):
            continue
        out.append(Insight(
            kind=InsightKind.UNDERUTILISED, severity=InsightSeverity.INFO,
            title=f"{doc.name} is free",
            detail=(f"No sessions starting in the next {horizon} min — "
                    f"available to absorb redirected demand."),
            action="Route overflow bookings here.",
            resource_id=doc.id, resource_name=doc.name,
            metric={"free_window_min": horizon},
            horizon_min=horizon,
        ))

    for room in state.rooms.values():
        if room.status != RoomStatus.AVAILABLE or room.type not in _CHEMO_ROOMS:
            continue
        if _sessions_in_window(
                _flow_appointments(state, room_id=room.id), now_m, end_m):
            continue
        out.append(Insight(
            kind=InsightKind.UNDERUTILISED, severity=InsightSeverity.INFO,
            title=f"{room.name} is idle",
            detail=f"No chemo sessions starting in the next {horizon} min.",
            action="Use it to relieve a busy infusion room.",
            resource_id=room.id, resource_name=room.name,
            metric={"free_window_min": horizon},
            horizon_min=horizon,
        ))
    return out


# --------------------------------------------------------------------------- #
# Orchestrator
# --------------------------------------------------------------------------- #
def analyze(state: SystemState, now: str,
            horizon_min: int = DEFAULT_HORIZON_MIN,
            limit: int = 24) -> list[Insight]:
    """Return the current proactive insights, most severe first.

    Pure: reads ``state`` only, never mutates it. ``now`` is the department
    clock (HH:MM). Higher-severity, more actionable insights sort to the top;
    informational "underutilised" notes sink to the bottom.
    """
    insights: list[Insight] = []
    insights += _wait_time(state, now)
    insights += _queue_overflow(state, now, horizon_min)
    insights += _doctor_capacity(state, now)
    insights += _drug_window(state, now, horizon_min)
    insights += _load_rebalance(state, now, horizon_min)
    insights += _underutilised(state, now, horizon_min)
    insights.sort(key=lambda i: (_SEV_RANK[i.severity], i.kind.value))
    return insights[:limit]
