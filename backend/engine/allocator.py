"""Score-based allocation.

The :class:`RoomAllocator` ranks candidate chemo rooms/slots; the
:class:`AppointmentAllocator` is the public "book / reschedule" facade that
combines the slot registry + conflict detector + room allocator.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .state import (
    SystemState, Appointment, AppointmentType, AppointmentStatus,
    Doctor, ChemRoom, new_id,
)
from .slots import SlotRegistry
from .conflict import ConflictDetector
from .result import EngineResult, Action, SeverityCode
from .timeutils import to_min, to_hhmm, duration_min
from . import visits
from . import actions as _act


#: How far ahead a walk-in may be placed, by how urgent the desk says it is.
WALK_IN_HORIZON = {"urgent": 60, "soon": 180, "routine": 10 * 60}


# --------------------------------------------------------------------------- #
# Candidate data
# --------------------------------------------------------------------------- #
@dataclass
class Candidate:
    doctor_id: str
    room_id: Optional[str]
    start: str
    end: str
    score: float = 0.0
    reasons: list[str] = None  # type: ignore

    def __post_init__(self):
        if self.reasons is None:
            self.reasons = []


# --------------------------------------------------------------------------- #
# Room / slot scoring
# --------------------------------------------------------------------------- #
class RoomAllocator:
    """Score candidate (doctor, room, slot) combos. Higher is better."""

    def __init__(self, state: SystemState, registry: SlotRegistry,
                 detector: ConflictDetector) -> None:
        self.state = state
        self.reg = registry
        self.det = detector

    def score_slot(self, doctor: Doctor, room: Optional[ChemRoom],
                   drug_id: Optional[str], s: str, e: str) -> tuple[float, list[str]]:
        reasons: list[str] = []
        score = 0.0

        # 1) prefer earlier slots (less waiting)
        start_m = to_min(s)
        score += max(0.0, (24 * 60 - start_m)) * 0.05
        reasons.append(f"earlier-preference@{s}")

        # 2) chemo: room type must fit
        if room is not None:
            if doctor.specialty and room.type.value in ("infusion_chair", "isolation"):
                score += 10
            # 3) equipment headroom: prefer rooms with spare equipment capacity
            score += len(room.equipment) * 0.5

        # 4) prefer doctors with same specialty match already implied
        # 5) lower existing load on the doctor is marginally better
        load = self.state.doctor_appointment_count(doctor.id)
        score += max(0.0, (doctor.daily_cap - load)) * 0.2

        # 6) prefer rooms that are not about to go unavailable
        if room is not None and room.available_until:
            if to_min(room.available_until) < to_min(e):
                return -1.0, ["room unavailable by slot end"]

        return score, reasons

    # -- search ------------------------------------------------------------ #
    def find_best_chemo(
        self,
        doctor_id: str,
        drug_id: str,
        preferred_start: Optional[str] = None,
        duration: int = 30,
        max_candidates: int = 50,
    ) -> list[Candidate]:
        """Return ranked candidate chemo slots for a doctor+drug."""
        doctor = self.state.doctor(doctor_id)
        if doctor is None:
            return []

        drug = self.state.drug(drug_id)
        if drug is None:
            return []

        # 1) candidate rooms of any chemo type
        rooms = [
            r for r in self.state.rooms.values()
            if r.type.value in ("infusion_chair", "isolation")
        ]

        cands: list[Candidate] = []
        # 2) for each room, for each free slot of the doctor, check room too
        for room in rooms:
            if self.det._room_missing_equipment(room, drug_id):
                continue
            for s, e in self.reg.doctor_candidate_slots(doctor_id, duration,
                                                        step=15):
                if not self.reg.is_room_slot_free(room.id, s, e):
                    continue
                if drug.time_window and not drug.time_window.contains(s):
                    continue
                score, reasons = self.score_slot(doctor, room, drug_id, s, e)
                if score < 0:
                    continue
                # proximity to preferred start
                if preferred_start:
                    delta = abs(to_min(s) - to_min(preferred_start))
                    score -= delta * 0.1
                    reasons.append(f"delta-{delta}min-from-pref")
                cands.append(Candidate(doctor.id, room.id, s, e, score, reasons))

        cands.sort(key=lambda c: c.score, reverse=True)
        return cands[:max_candidates]


# --------------------------------------------------------------------------- #
# Booking / reschedule facade
# --------------------------------------------------------------------------- #
class AppointmentAllocator:
    def __init__(self, state: SystemState, registry: SlotRegistry) -> None:
        self.state = state
        self.reg = registry
        self.det = ConflictDetector(state, registry)
        self.rooms = RoomAllocator(state, registry, self.det)

    # -- book a consult (doctor only) -------------------------------------- #
    def book_consult(
        self,
        patient_id: str,
        doctor_id: str,
        slot_start: str,
        slot_end: str,
        at: str,
        date: Optional[str] = None,
        visit_type: Optional[str] = None,
    ) -> EngineResult:
        v = self.det.check(doctor_id, None, None, slot_start, slot_end,
                           AppointmentType.CONSULT, date=date,
                           visit_type=visit_type)
        if not v.ok:
            return EngineResult(False, Action.BOOKED,
                                "cannot book: " + "; ".join(v.reasons),
                                SeverityCode.WARNING)
        appt = self._create(patient_id, doctor_id, None, None,
                            slot_start, slot_end, AppointmentType.CONSULT, at,
                            date=date, visit_type=visit_type)
        kind = visits.label(appt.eff_visit_type).lower()
        return EngineResult(True, Action.BOOKED,
                            f"booked {kind} ({appt.planned_min} min) for "
                            f"{self.state.patient(patient_id).name} with "
                            f"{self.state.doctor(doctor_id).name} at {slot_start}")

    # -- slot recommendations (used when a preferred slot is unavailable) -- #
    def recommend_consult_slots(
        self,
        doctor_id: str,
        preferred_start: Optional[str],
        limit: int = 8,
        date: Optional[str] = None,
        duration: int = 30,
    ) -> list[dict]:
        """Ranked free windows of ``duration`` minutes for a doctor on ``date``
        (default: active day), closest to the preferred time.

        Searched on a 15-minute grid rather than the fixed 30-minute one, so a
        short visit can use a gap a full slot could not.
        """
        out: list[dict] = []
        d = date or self.state.day()
        pref = to_min(preferred_start) if preferred_start else to_min("12:00")
        for s, e in self.reg.doctor_candidate_slots(doctor_id, duration, step=15):
            delta = abs(to_min(s) - pref)
            out.append({
                "slot_start": s, "slot_end": e, "date": d,
                "score": -delta, "delta_min": delta,
                "reason": "nearest free slot" if delta == 0 else f"{delta} min from preferred",
            })
        out.sort(key=lambda r: (r["delta_min"], r["slot_start"]))
        return out[:limit]

    def recommend_chemo_slots(
        self,
        doctor_id: str,
        drug_id: str,
        preferred_start: Optional[str],
        limit: int = 8,
        duration: int = 30,
        date: Optional[str] = None,
    ) -> list[dict]:
        """Ranked free chemo slots (room + doctor + drug window) for a doctor
        on ``date`` (default: active day)."""
        cands = self.rooms.find_best_chemo(doctor_id, drug_id, preferred_start,
                                           duration, max_candidates=limit)
        out = []
        d = date or self.state.day()
        pref = to_min(preferred_start) if preferred_start else to_min("12:00")
        for c in cands:
            room = self.state.room(c.room_id) if c.room_id else None
            out.append({
                "slot_start": c.start, "slot_end": c.end, "date": d,
                "room_id": c.room_id,
                "room_name": room.name if room else "",
                "score": round(c.score, 2),
                "delta_min": abs(to_min(c.start) - pref),
                "reason": "best scored slot",
            })
        out.sort(key=lambda r: (r["delta_min"], -r["score"]))
        return out[:limit]

    # -- book a chemo (doctor + drug, room auto-selected) ------------------ #
    def book_chemo(
        self,
        patient_id: str,
        doctor_id: str,
        drug_id: str,
        preferred_start: Optional[str],
        at: str,
        duration: int = 30,
        date: Optional[str] = None,
    ) -> EngineResult:
        cands = self.rooms.find_best_chemo(doctor_id, drug_id, preferred_start,
                                           duration)
        if not cands:
            return EngineResult(False, Action.BOOKED,
                                "no chemo slot satisfies all constraints",
                                SeverityCode.WARNING,
                                data={"candidates": []})
        best = cands[0]
        # re-verify full conflict (defensive)
        v = self.det.check(best.doctor_id, best.room_id, drug_id,
                           best.start, best.end, AppointmentType.CHEMO,
                           date=date)
        if not v.ok:
            return EngineResult(False, Action.BOOKED,
                                "best candidate failed final check: " + "; ".join(v.reasons),
                                SeverityCode.WARNING)
        appt = self._create(patient_id, best.doctor_id, best.room_id, drug_id,
                            best.start, best.end, AppointmentType.CHEMO, at,
                            date=date)
        room_name = self.state.room(best.room_id).name
        return EngineResult(
            True, Action.BOOKED,
            f"booked chemo {appt.id} at {best.start} in {room_name}",
            data={"room_id": best.room_id, "score": best.score,
                  "candidates": [_cand_dict(c) for c in cands[:5]]},
        )

    # -- walk-ins ---------------------------------------------------------- #
    def walk_in_options(
        self,
        duration: int,
        now: str,
        doctor_id: Optional[str] = None,
        urgency: str = "routine",
        specialty: Optional[str] = None,
        limit: int = 3,
        date: Optional[str] = None,
    ) -> dict:
        """Where a walk-in could be seen today **without moving anybody**.

        Only real gaps in the remaining day are considered, every candidate is
        validated by the usual rules (leave, buffers, working hours), and a
        doctor already at their daily cap is reported rather than squeezed.
        Returns options; it books nothing.
        """
        d = date or self.state.day()
        self.reg._fixed_day = d
        now_m = to_min(now)
        horizon_min = WALK_IN_HORIZON.get(urgency, WALK_IN_HORIZON["routine"])
        horizon = now_m + horizon_min

        if doctor_id:
            doc = self.state.doctor(doctor_id)
            doctors = [doc] if doc else []
        else:
            doctors = [
                dd for dd in self.state.doctors.values()
                if dd.status.value in ("available", "partially_unavailable")
                and (specialty is None or dd.specialty == specialty)
            ]

        options: list[dict] = []
        at_cap: list[str] = []
        for doc in doctors:
            used = self.state.doctor_appointment_count(doc.id, day=d)
            if used >= doc.daily_cap:
                at_cap.append(doc.name)
                continue
            gaps = self.reg.doctor_free_gaps(doc.id)
            same_day = sorted(
                self.state.active_appointments(doc.id, day=d),
                key=lambda a: to_min(a.slot_start))
            for s, e in self.reg.doctor_candidate_slots(doc.id, duration, step=15):
                s_m = to_min(s)
                if s_m < now_m or s_m > horizon:
                    continue
                gap = next((g for g in gaps
                            if to_min(g[0]) <= s_m and to_min(g[1]) >= to_min(e)),
                           None)
                prev = [a for a in same_day if to_min(a.slot_end) <= s_m]
                after = prev[-1] if prev else None
                after_patient = self.state.patient(after.patient_id) if after else None
                options.append({
                    "doctor_id": doc.id,
                    "doctor_name": doc.name,
                    "slot_start": s, "slot_end": e, "date": d,
                    "duration_min": duration,
                    "gap_min": (to_min(gap[1]) - to_min(gap[0])) if gap else duration,
                    "minutes_away": s_m - now_m,
                    "after": after_patient.name if after_patient else "",
                    "cap_used": used, "cap_total": doc.daily_cap,
                })

        # earliest first; a tighter gap wins a tie so big gaps stay bookable
        options.sort(key=lambda o: (o["minutes_away"], o["gap_min"]))
        # one option per doctor keeps the choice readable
        seen: set[str] = set()
        best: list[dict] = []
        for o in options:
            if o["doctor_id"] in seen:
                continue
            seen.add(o["doctor_id"])
            best.append(o)
            if len(best) >= limit:
                break

        return {
            "options": best,
            "at_cap": at_cap,
            "date": d,
            "searched_until": to_hhmm(min(horizon, to_min(self.reg.day_end))),
            "urgency": urgency,
        }

    def book_walk_in(
        self,
        patient_id: str,
        doctor_id: str,
        slot_start: str,
        slot_end: str,
        at: str,
        reason: str = "",
        visit_type: Optional[str] = None,
        date: Optional[str] = None,
    ) -> EngineResult:
        """Place a walk-in in a gap that was already free."""
        doc = self.state.doctor(doctor_id)
        if doc is None:
            return EngineResult(False, Action.BOOKED, "doctor not found")
        d = date or self.state.day()
        used = self.state.doctor_appointment_count(doctor_id, day=d)
        if used >= doc.daily_cap:
            return EngineResult(
                False, Action.BOOKED,
                f"{doc.name} is at the daily cap ({used}/{doc.daily_cap})",
                SeverityCode.WARNING)
        v = self.det.check(doctor_id, None, None, slot_start, slot_end,
                           AppointmentType.CONSULT, date=d,
                           visit_type=visit_type)
        if not v.ok:
            return EngineResult(False, Action.BOOKED,
                                "cannot fit the walk-in: " + "; ".join(v.reasons),
                                SeverityCode.WARNING)
        appt = self._create(patient_id, doctor_id, None, None,
                            slot_start, slot_end, AppointmentType.CONSULT, at,
                            date=d, visit_type=visit_type, walk_in=True,
                            reason=reason)
        patient = self.state.patient(patient_id)
        self.state.add_log("walk_in", appt.id, "", f"{d} {slot_start}@{doctor_id}",
                           reason or "walk-in", at)
        if patient:
            self.state.add_notification(
                patient_id, "sms",
                f"You are booked with {doc.name} at {slot_start} today.", at)
        return EngineResult(
            True, Action.BOOKED,
            f"walk-in placed with {doc.name} at {slot_start} "
            f"({appt.planned_min} min), no booked patient moved",
            data={"appt_id": appt.id, "doctor_id": doctor_id,
                  "slot_start": slot_start, "slot_end": slot_end})

    # -- reschedule an existing appointment -------------------------------- #
    def reschedule(
        self,
        appt_id: str,
        new_doctor_id: Optional[str],
        new_room_id: Optional[str],
        new_start: str,
        new_end: str,
        at: str,
        reason: str = "reschedule",
        date: Optional[str] = None,
    ) -> EngineResult:
        appt = self.state.appointment(appt_id)
        if appt is None:
            return EngineResult(False, Action.RESCHEDULED, "appointment not found")
        before = f"{appt.date or appt.eff_date} {appt.slot_start}-{appt.slot_end}@{appt.doctor_id}"
        doctor_id = new_doctor_id or appt.doctor_id
        room_id = new_room_id if new_room_id is not None else appt.room_id
        # The new day defaults to the appointment's current day.
        new_date = date or appt.eff_date
        v = self.det.check(doctor_id, room_id, appt.drug_id, new_start, new_end,
                           appt.type, appt_id=appt_id, date=new_date)
        if not v.ok and not _is_self_conflict(v.reasons):
            return EngineResult(False, Action.RESCHEDULED,
                                "reschedule blocked: " + "; ".join(v.reasons),
                                SeverityCode.WARNING)
        snap = _act.snapshot(appt)
        appt.doctor_id = doctor_id
        appt.room_id = room_id
        appt.slot_start = new_start
        appt.slot_end = new_end
        appt.date = new_date
        appt.status = AppointmentStatus.RESCHEDULED
        appt.reschedule_reason = reason
        patient = self.state.patient(appt.patient_id)
        _act.record(
            self.state, "reschedule", at, new_date, {appt.id: snap},
            summary=f"{patient.name if patient else appt.patient_id} moved to "
                    f"{new_start}",
            why=reason, by="system", doctor_id=doctor_id)
        after = f"{new_date} {new_start}-{new_end}@{doctor_id}"
        self.state.add_log("reschedule", appt_id, before, after, reason, at)
        patient = self.state.patient(appt.patient_id)
        if patient:
            self.state.add_notification(
                appt.patient_id, "sms",
                f"Your appointment was rescheduled to {new_date} {new_start}.", at)
        return EngineResult(True, Action.RESCHEDULED,
                            f"rescheduled {appt_id} to {new_date} {new_start}",
                            data={"before": before, "after": after})

    def reschedule_auto(
        self,
        appt_id: str,
        at: str,
        reason: str = "auto-reschedule",
        only_doctor: bool = True,
        date: Optional[str] = None,
    ) -> EngineResult:
        """Find a new valid slot (same or backup doctor) **on the same day** and
        apply it. Returns ``RESCHEDULE_OFFERED`` with candidate slots if no
        perfect slot is found so a human/patient can pick.
        """
        appt = self.state.appointment(appt_id)
        if appt is None:
            return EngineResult(False, Action.RESCHEDULE_OFFERED, "not found")
        # Operate on the appointment's own day so a reschedule never jumps days.
        self.reg._fixed_day = date or appt.eff_date

        # candidate doctor set
        if only_doctor:
            doctors = [appt.doctor_id]
        else:
            orig = self.state.doctor(appt.doctor_id)
            backup_specs = set(orig.backup_compatible) if orig else set()
            backup_specs.add(orig.specialty) if orig else None
            doctors = [
                d.id for d in self.state.doctors.values()
                if d.status.value == "available"
                and (d.specialty in backup_specs
                     or (orig and d.id in orig.backup_compatible))
            ]
            if not doctors:
                doctors = [appt.doctor_id]

        # free the old slot first
        before = f"{appt.slot_start}@{appt.doctor_id}"

        if appt.is_chemo:
            candidates = []
            for did in doctors:
                candidates.extend(
                    self.rooms.find_best_chemo(
                        did, appt.drug_id or "", preferred_start=appt.slot_start))
            if not candidates:
                return self._offer(appt_id, before, [], at, reason)
            best = candidates[0]
            appt.doctor_id = best.doctor_id
            appt.room_id = best.room_id
            appt.slot_start = best.start
            appt.slot_end = best.end
            appt.date = self.reg.day()
        else:
            # find any free doctor slot near the original time
            chosen = None
            for did in doctors:
                for s, e in self.reg.doctor_free_slots(did):
                    chosen = (did, s, e)
                    break
                if chosen:
                    break
            if not chosen:
                return self._offer(appt_id, before, [], at, reason)
            did, s, e = chosen
            appt.doctor_id = did
            appt.slot_start = s
            appt.slot_end = e
            appt.date = self.reg.day()

        appt.status = AppointmentStatus.RESCHEDULED
        appt.reschedule_reason = reason
        after = f"{appt.slot_start}@{appt.doctor_id}"
        self.state.add_log("reschedule", appt_id, before, after, reason, at)
        patient = self.state.patient(appt.patient_id)
        if patient:
            self.state.add_notification(
                appt.patient_id, "sms",
                f"Your appointment was moved to {appt.slot_start} "
                f"with {self.state.doctor(appt.doctor_id).name}.", at)
        return EngineResult(True, Action.RESCHEDULED,
                            f"auto-rescheduled {appt_id} to {appt.slot_start}",
                            data={"before": before, "after": after,
                                  "candidates": [_cand_dict(candidates[0]) if appt.is_chemo else None]})

    def _offer(self, appt_id: str, before: str, cands: list, at: str,
               reason: str) -> EngineResult:
        appt = self.state.appointment(appt_id)
        self.state.add_log("reschedule_offered", appt_id, before, "(none)",
                           reason + ": offering choices", at)
        patient = self.state.patient(appt.patient_id)
        if patient:
            self.state.add_notification(
                appt.patient_id, "sms",
                "We could not auto-reschedule you. New options will be sent shortly.", at)
        return EngineResult(False, Action.RESCHEDULE_OFFERED,
                            "no perfect slot; offering choices",
                            SeverityCode.WARNING,
                            data={"candidates": [_cand_dict(c) for c in cands[:5]]})

    # -- internal ----------------------------------------------------------- #
    def _create(self, patient_id: str, doctor_id: str, room_id, drug_id,
                s: str, e: str, typ: AppointmentType, at: str,
                date: Optional[str] = None,
                visit_type: Optional[str] = None,
                walk_in: bool = False, reason: str = "") -> Appointment:
        d = date or self.state.day()
        appt = Appointment(
            id=new_id("APT"),
            patient_id=patient_id,
            doctor_id=doctor_id,
            room_id=room_id,
            drug_id=drug_id,
            slot_start=s,
            slot_end=e,
            type=typ,
            status=AppointmentStatus.BOOKED,
            date=d,
            visit_type=(visit_type or "") if visits.is_visit_type(visit_type or "") else "",
            walk_in=walk_in,
            reason=reason,
        )
        self.state.appointments[appt.id] = appt
        self.state.add_log("book", appt.id, "", f"{d} {s}@{doctor_id}",
                           "new booking", at)
        return appt


def _is_self_conflict(reasons: list[str]) -> bool:
    """When rescheduling in place, the old slot still looks busy. If every
    reported reason is just that self-occupancy, the move is actually valid."""
    selfish = {"doctor slot not free (conflict or buffer)",
               "room slot not free"}
    if not reasons:
        return False
    return all(r in selfish for r in reasons)


def _cand_dict(c) -> dict:
    if c is None:
        return {}
    return {
        "doctor_id": c.doctor_id,
        "room_id": c.room_id,
        "start": c.start,
        "end": c.end,
        "score": round(c.score, 2),
    }
