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
from .timeutils import to_min, duration_min


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
            for s, e in self.reg.doctor_free_slots(doctor_id):
                # duration fit
                if duration_min(s, e) < duration:
                    continue
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
    ) -> EngineResult:
        v = self.det.check(doctor_id, None, None, slot_start, slot_end,
                           AppointmentType.CONSULT)
        if not v.ok:
            return EngineResult(False, Action.BOOKED,
                                "cannot book: " + "; ".join(v.reasons),
                                SeverityCode.WARNING)
        appt = self._create(patient_id, doctor_id, None, None,
                            slot_start, slot_end, AppointmentType.CONSULT, at)
        return EngineResult(True, Action.BOOKED,
                            f"booked consult {appt.id} for {self.state.patient(patient_id).name} "
                            f"with {self.state.doctor(doctor_id).name} at {slot_start}")

    # -- slot recommendations (used when a preferred slot is unavailable) -- #
    def recommend_consult_slots(
        self,
        doctor_id: str,
        preferred_start: Optional[str],
        limit: int = 8,
    ) -> list[dict]:
        """Ranked free 30-min slots for a doctor, closest to the preferred time."""
        out: list[dict] = []
        pref = to_min(preferred_start) if preferred_start else to_min("12:00")
        for s, e in self.reg.doctor_free_slots(doctor_id):
            delta = abs(to_min(s) - pref)
            out.append({
                "slot_start": s, "slot_end": e,
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
    ) -> list[dict]:
        """Ranked free chemo slots (room + doctor + drug window) for a doctor."""
        cands = self.rooms.find_best_chemo(doctor_id, drug_id, preferred_start,
                                           duration, max_candidates=limit)
        out = []
        pref = to_min(preferred_start) if preferred_start else to_min("12:00")
        for c in cands:
            room = self.state.room(c.room_id) if c.room_id else None
            out.append({
                "slot_start": c.start, "slot_end": c.end,
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
                           best.start, best.end, AppointmentType.CHEMO)
        if not v.ok:
            return EngineResult(False, Action.BOOKED,
                                "best candidate failed final check: " + "; ".join(v.reasons),
                                SeverityCode.WARNING)
        appt = self._create(patient_id, best.doctor_id, best.room_id, drug_id,
                            best.start, best.end, AppointmentType.CHEMO, at)
        room_name = self.state.room(best.room_id).name
        return EngineResult(
            True, Action.BOOKED,
            f"booked chemo {appt.id} at {best.start} in {room_name}",
            data={"room_id": best.room_id, "score": best.score,
                  "candidates": [_cand_dict(c) for c in cands[:5]]},
        )

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
    ) -> EngineResult:
        appt = self.state.appointment(appt_id)
        if appt is None:
            return EngineResult(False, Action.RESCHEDULED, "appointment not found")
        before = f"{appt.slot_start}-{appt.slot_end}@{appt.doctor_id}"
        doctor_id = new_doctor_id or appt.doctor_id
        room_id = new_room_id if new_room_id is not None else appt.room_id
        v = self.det.check(doctor_id, room_id, appt.drug_id, new_start, new_end,
                           appt.type, appt_id=appt_id)
        if not v.ok and not _is_self_conflict(v.reasons):
            return EngineResult(False, Action.RESCHEDULED,
                                "reschedule blocked: " + "; ".join(v.reasons),
                                SeverityCode.WARNING)
        appt.doctor_id = doctor_id
        appt.room_id = room_id
        appt.slot_start = new_start
        appt.slot_end = new_end
        appt.status = AppointmentStatus.RESCHEDULED
        appt.reschedule_reason = reason
        after = f"{new_start}-{new_end}@{doctor_id}"
        self.state.add_log("reschedule", appt_id, before, after, reason, at)
        patient = self.state.patient(appt.patient_id)
        if patient:
            self.state.add_notification(
                appt.patient_id, "sms",
                f"Your appointment was rescheduled to {new_start}.", at)
        return EngineResult(True, Action.RESCHEDULED,
                            f"rescheduled {appt_id} to {new_start}",
                            data={"before": before, "after": after})

    def reschedule_auto(
        self,
        appt_id: str,
        at: str,
        reason: str = "auto-reschedule",
        only_doctor: bool = True,
    ) -> EngineResult:
        """Find a new valid slot (same or backup doctor) and apply it.

        Returns ``RESCHEDULE_OFFERED`` with candidate slots if no perfect slot
        is found so a human/patient can pick.
        """
        appt = self.state.appointment(appt_id)
        if appt is None:
            return EngineResult(False, Action.RESCHEDULE_OFFERED, "not found")

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
                s: str, e: str, typ: AppointmentType, at: str) -> Appointment:
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
        )
        self.state.appointments[appt.id] = appt
        self.state.add_log("book", appt.id, "", f"{s}@{doctor_id}",
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
