"""Emergency priority handling.

A 5-level severity (1=low .. 5=critical) plus a numeric *subscore* that breaks
ties. The :class:`PriorityQueue` is a min-heap ordered by (severity desc,
subscore desc, created_at asc). :func:`resolve_emergencies` assigns free
doctors to waiting emergencies, preferring parallel assignment when possible.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass
from typing import Optional

from .state import (
    SystemState, Emergency, Severity, DoctorStatus, AppointmentStatus,
    AppointmentType, new_id,
)
from .result import EngineResult, Action, SeverityCode


# --------------------------------------------------------------------------- #
# Subscore
# --------------------------------------------------------------------------- #
def compute_subscore(em: Emergency, state: SystemState, now: str) -> int:
    """Tie-breaker: higher == more urgent.

    subscore = severity*1000
             - minutes_waited            (longer wait = more urgent)
             + (5 - patient_priority_tier)*10   (vip tier bonus)
    """
    from .timeutils import to_min
    base = em.severity.value * 1000
    wait_min = max(0, to_min(now) - to_min(em.created_at))
    patient = state.patient(em.patient_id)
    tier_bonus = (5 - (patient.priority_tier if patient else 1)) * 10
    return base - wait_min + tier_bonus


# --------------------------------------------------------------------------- #
# Queue
# --------------------------------------------------------------------------- #
@dataclass(order=True)
class _QItem:
    sort_key: tuple
    em_id: str = None  # type: ignore


class PriorityQueue:
    """Min-heap of emergencies ordered by (severity desc, subscore desc, created asc)."""

    def __init__(self) -> None:
        self._heap: list[_QItem] = []

    @staticmethod
    def _key(em: Emergency, subscore: int) -> tuple:
        # negate so higher severity / subscore sorts first in a min-heap
        return (-em.severity.value, -subscore, em.created_at)

    def push(self, em: Emergency, subscore: int) -> None:
        heapq.heappush(self._heap, _QItem(self._key(em, subscore), em.id))

    def pop(self) -> Optional[str]:
        if not self._heap:
            return None
        return heapq.heappop(self._heap).em_id

    def peek(self) -> Optional[str]:
        return self._heap[0].em_id if self._heap else None

    def __len__(self) -> int:
        return len(self._heap)


def build_queue(state: SystemState, now: str) -> list[Emergency]:
    """Return waiting emergencies in priority order (highest first)."""
    q = PriorityQueue()
    for em in state.emergencies.values():
        if em.status == "waiting":
            q.push(em, compute_subscore(em, state, now))
    out = []
    while True:
        eid = q.pop()
        if eid is None:
            break
        out.append(state.emergencies[eid])
    return out


# --------------------------------------------------------------------------- #
# Resolution
# --------------------------------------------------------------------------- #
def resolve_emergencies(state: SystemState, now: str) -> EngineResult:
    """Assign free doctors to waiting emergencies (parallel when possible)."""
    waiting = build_queue(state, now)
    assigned: list[str] = []
    still_waiting: list[str] = []

    free_doctors = [
        d for d in state.doctors.values()
        if d.status.value == DoctorStatus.AVAILABLE.value
    ]

    # refresh subscores
    for em in waiting:
        em.subscore = compute_subscore(em, state, now)

    for em in waiting:
        # prefer a doctor who is free right now (no overlapping active appt)
        from .timeutils import overlaps
        chosen = None
        for d in free_doctors:
            busy = any(
                overlaps(a.slot_start, a.slot_end, now, _next(now))
                for a in state.active_appointments(d.id)
            )
            if not busy and d.id not in [x for x in assigned]:
                chosen = d
                break
        if chosen is None:
            still_waiting.append(em.id)
            continue
        em.assigned_doctor_id = chosen.id
        em.status = "assigned"
        assigned.append(chosen.id)
        state.add_log("emergency_assigned", em.id, "",
                      f"{now}@{chosen.id}", f"severity {em.severity.value}", now)
        patient = state.patient(em.patient_id)
        if patient:
            state.add_notification(
                em.patient_id, "sms",
                f"Emergency: you are being seen by Dr {chosen.name} immediately.", now)

    if assigned:
        msg = f"assigned {len(assigned)} emergency(ies)"
    else:
        msg = "no free doctors; all emergencies waiting by priority"
    return EngineResult(
        True,
        Action.EMERGENCY_ASSIGNED if assigned else Action.EMERGENCY_WAITING,
        msg,
        SeverityCode.CRITICAL if waiting else SeverityCode.INFO,
        data={"assigned": assigned, "still_waiting": still_waiting,
              "queue_order": [e.id for e in waiting]},
    )


def _next(now: str) -> str:
    from .timeutils import to_min, to_hhmm
    return to_hhmm(to_min(now) + 30)


def two_emergencies_at_once(state: SystemState, e1: Emergency, e2: Emergency,
                            now: str) -> dict:
    """Resolve two simultaneous emergencies.

    Strategy: assign to *different* doctors when possible; otherwise compare
    subscores and the lower one waits in the priority queue.
    """
    free_doctors = [
        d for d in state.doctors.values()
        if d.status.value == DoctorStatus.AVAILABLE.value
    ]
    for em in (e1, e2):
        em.subscore = compute_subscore(em, state, now)

    result: dict = {"different_doctors": False, "assigned": {}, "waiting": []}
    # order by severity then subscore (most urgent first)
    ordered = sorted([e1, e2], key=lambda e: (-e.severity.value, -e.subscore))
    used: list[str] = []

    for em in ordered:
        from .timeutils import overlaps
        chosen = None
        for d in free_doctors:
            if d.id in used:
                continue
            busy = any(
                overlaps(a.slot_start, a.slot_end, now, _next(now))
                for a in state.active_appointments(d.id)
            )
            if not busy:
                chosen = d
                break
        if chosen is not None:
            em.assigned_doctor_id = chosen.id
            em.status = "assigned"
            used.append(chosen.id)
            result["assigned"][em.id] = chosen.name
            state.add_log("emergency_assigned", em.id, "",
                          f"{now}@{chosen.id}",
                          f"severity {em.severity.value} subscore {em.subscore}", now)
        else:
            em.status = "waiting"
            result["waiting"].append(em.id)

    result["different_doctors"] = len(result["assigned"]) == 2
    return result
