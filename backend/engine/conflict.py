"""Conflict detection: decide whether a candidate (doctor, room, drug, slot)
combination is valid, and why not if it is not.

All rules are hard constraints; the allocator (score-based soft ranking) runs
on the survivors.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .state import SystemState, AppointmentType
from .slots import SlotRegistry
from .timeutils import to_min


@dataclass
class Verdict:
    ok: bool
    reasons: list[str]


class ConflictDetector:
    def __init__(self, state: SystemState, registry: SlotRegistry) -> None:
        self.state = state
        self.reg = registry

    # -- master check ------------------------------------------------------- #
    def check(
        self,
        doctor_id: str,
        room_id: Optional[str],
        drug_id: Optional[str],
        slot_start: str,
        slot_end: str,
        appt_type: AppointmentType,
        appt_id: Optional[str] = None,
    ) -> Verdict:
        reasons: list[str] = []

        doctor = self.state.doctor(doctor_id)
        if doctor is None:
            return Verdict(False, ["unknown doctor"])
        if doctor.status.value != "available":
            reasons.append(f"doctor {doctor.name} is {doctor.status.value}")

        if appt_type == AppointmentType.CHEMO:
            if room_id is None:
                reasons.append("chemo requires a room")
            else:
                room = self.state.room(room_id)
                if room is None:
                    reasons.append("unknown room")
                else:
                    if room.status.value != "available":
                        reasons.append(f"room {room.name} is unavailable")
                    if drug_id and self._room_missing_equipment(room, drug_id):
                        reasons.append(f"room {room.name} lacks required equipment")

        if drug_id is not None:
            drug = self.state.drug(drug_id)
            if drug is None:
                reasons.append("unknown drug")
            elif not drug.time_window.contains(slot_start):
                reasons.append(
                    f"{drug.name} only allowed {drug.time_window.start}-{drug.time_window.end}"
                )

        # slot must be free for the doctor
        if not self.reg.is_doctor_slot_free(doctor_id, slot_start, slot_end):
            reasons.append("doctor slot not free (conflict or buffer)")

        # slot must be free for the room
        if room_id and not self.reg.is_room_slot_free(room_id, slot_start, slot_end):
            reasons.append("room slot not free")

        # daily capacity
        if appt_type != AppointmentType.EMERGENCY:
            if doctor and self.state.doctor_appointment_count(doctor_id) >= doctor.daily_cap:
                reasons.append(f"doctor {doctor.name} at daily cap")

        return Verdict(not reasons, reasons)

    # -- targeted helpers --------------------------------------------------- #
    def doctor_busy_at(self, doctor_id: str, s: str, e: str) -> bool:
        return not self.reg.is_doctor_slot_free(doctor_id, s, e)

    def room_missing_equipment(self, room_id: str, drug_id: str) -> bool:
        room = self.state.room(room_id)
        drug = self.state.drug(drug_id)
        if room is None or drug is None:
            return False
        return self._room_missing_equipment(room, drug_id)

    def _room_missing_equipment(self, room, drug_id: str) -> bool:
        drug = self.state.drug(drug_id)
        if drug is None:
            return False
        have = set(room.equipment)
        return not set(drug.required_equipment).issubset(have)

    def drug_window_violation(self, drug_id: str, slot_start: str) -> bool:
        drug = self.state.drug(drug_id)
        if drug is None:
            return False
        return not drug.time_window.contains(slot_start)
