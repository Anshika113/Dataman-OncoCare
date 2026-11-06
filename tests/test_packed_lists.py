"""Packed list cells: the separator mismatch that silently broke cover and kit.

The seed writes `backup_compatible`, `equipment` and `required_equipment`
semicolon-separated; `to_dict` joins them with commas. Parsing only on commas
turned each into a single opaque string, so cross-specialty cover never
matched and a drug could only be given in a room whose equipment string
happened to be character-for-character identical.

These tests pin the tolerant parse so the regression cannot come back.
"""

from __future__ import annotations

import pytest

from engine import (
    SystemState, Doctor, ChemRoom, Drug, RoomType, TimeWindow,
    SlotRegistry, ConflictDetector,
)


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("raw,expected", [
    ("hematology;oncology", ["hematology", "oncology"]),
    ("hematology,oncology", ["hematology", "oncology"]),
    ("hematology; oncology , radiation",
     ["hematology", "oncology", "radiation"]),
    ("", []),
    (None, []),
    ("oncology", ["oncology"]),
])
def test_doctor_cover_list_accepts_either_separator(raw, expected):
    d = Doctor.from_dict({
        "id": "D1", "name": "Dr One", "specialty": "hematology",
        "backup_compatible": raw,
    })
    assert d.backup_compatible == expected


def test_room_equipment_accepts_either_separator():
    r = ChemRoom.from_dict({
        "id": "R1", "name": "Infusion 1", "type": "infusion_chair",
        "equipment": "pump;monitor;iv", "status": "available",
    })
    assert r.equipment == ["pump", "monitor", "iv"]


def test_drug_requirements_accept_either_separator():
    g = Drug.from_dict({
        "id": "G1", "name": "Cisplatin", "tw_start": "08:00",
        "tw_end": "12:00", "grace_minutes": 15,
        "required_equipment": "pump;monitor",
    })
    assert g.required_equipment == ["pump", "monitor"]


# --------------------------------------------------------------------------- #
# What the mismatch actually broke
# --------------------------------------------------------------------------- #
@pytest.fixture
def state() -> SystemState:
    s = SystemState()
    s.doctors = {
        "D1": Doctor.from_dict({
            "id": "D1", "name": "Dr One", "specialty": "hematology",
            "backup_compatible": "hematology;oncology"}),
        "D2": Doctor.from_dict({
            "id": "D2", "name": "Dr Two", "specialty": "oncology",
            "backup_compatible": "oncology;hematology"}),
    }
    s.rooms = {
        "R1": ChemRoom.from_dict({
            "id": "R1", "name": "Infusion 1", "type": "infusion_chair",
            "equipment": "pump;monitor;iv", "status": "available"}),
    }
    s.drugs = {
        "G1": Drug.from_dict({
            "id": "G1", "name": "Cisplatin", "tw_start": "08:00",
            "tw_end": "12:00", "grace_minutes": 15,
            "required_equipment": "pump;monitor"}),
    }
    return s


def test_a_room_with_the_kit_is_not_reported_as_missing_it(state):
    det = ConflictDetector(state, SlotRegistry(state))
    # Infusion 1 has pump, monitor and iv; Cisplatin needs pump and monitor
    assert det._room_missing_equipment(state.room("R1"), "G1") is False


def test_a_room_genuinely_short_of_kit_is_still_rejected(state):
    state.rooms["R2"] = ChemRoom.from_dict({
        "id": "R2", "name": "Exam 1", "type": "exam",
        "equipment": "exam_table", "status": "available"})
    det = ConflictDetector(state, SlotRegistry(state))
    assert det._room_missing_equipment(state.room("R2"), "G1") is True


def test_cross_specialty_cover_matches(state):
    d1 = state.doctor("D1")
    assert "oncology" in d1.backup_compatible
    assert state.doctor("D2").specialty in d1.backup_compatible


def test_round_trip_through_to_dict_still_parses(state):
    # to_dict joins with commas; from_dict must read its own output back
    again = Doctor.from_dict(state.doctor("D1").to_dict())
    assert again.backup_compatible == ["hematology", "oncology"]
    room_again = ChemRoom.from_dict(state.room("R1").to_dict())
    assert room_again.equipment == ["pump", "monitor", "iv"]
