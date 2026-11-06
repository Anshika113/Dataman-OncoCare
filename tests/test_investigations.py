"""Investigation gating.

Covers Bucket A / feature 2. The behaviour that matters clinically: a patient
waiting on bloods is never treated as absent, the chair they were holding goes
back to the pool, an abnormal result blocks rather than reschedules itself,
and nothing proceeds until a doctor clears it.
"""

from __future__ import annotations

import pytest

from engine import (
    SystemState, Doctor, ChemRoom, Drug, Patient, Appointment,
    AppointmentType, AppointmentStatus, RoomType, DoctorStatus, TimeWindow,
    SlotRegistry, AppointmentAllocator, advance_clock,
    investigations as iv,
)


@pytest.fixture
def state() -> SystemState:
    s = SystemState()
    s.doctors = {
        "D1": Doctor("D1", "Dr One", "oncology", 20, DoctorStatus.AVAILABLE,
                     ["oncology"]),
    }
    s.rooms = {
        "R1": ChemRoom("R1", "Infusion 1", RoomType.INFUSION_CHAIR,
                       ["pump", "monitor", "iv"]),
        "R2": ChemRoom("R2", "Infusion 2", RoomType.INFUSION_CHAIR,
                       ["pump", "monitor", "iv"]),
    }
    s.drugs = {
        "G1": Drug("G1", "AnytimeDrug", TimeWindow("08:00", "18:00"), 10,
                   ["pump"]),
    }
    s.patients = {"P1": Patient("P1", "Meera", "+1", 1)}
    s.appointments = {
        "A1": Appointment("A1", "P1", "D1", "10:00", "11:30",
                          AppointmentType.CHEMO, AppointmentStatus.BOOKED,
                          room_id="R1", drug_id="G1"),
    }
    return s


def _alloc(s):
    return AppointmentAllocator(s, SlotRegistry(s))


# --------------------------------------------------------------------------- #
# Ordering and resulting
# --------------------------------------------------------------------------- #
def test_order_attaches_to_the_appointment(state):
    r = iv.order(state, "P1", "CBC", now="09:20", day=state.day(),
                 appointment_id="A1", eta="11:30")
    assert r.success
    assert len(state.investigations_for("A1")) == 1


def test_result_records_the_value(state):
    r = iv.order(state, "P1", "CBC", now="09:20", day=state.day(),
                 appointment_id="A1")
    iid = r.data["investigation"]["id"]
    assert iv.result(state, iid, "Hb 11.2", now="10:48").success
    assert state.investigation(iid).status == "resulted"
    assert state.investigation(iid).resulted_at == "10:48"


def test_cannot_result_twice(state):
    r = iv.order(state, "P1", "CBC", now="09:20", day=state.day(),
                 appointment_id="A1")
    iid = r.data["investigation"]["id"]
    iv.result(state, iid, "Hb 11.2", now="10:48")
    assert not iv.result(state, iid, "Hb 9", now="11:00").success


# --------------------------------------------------------------------------- #
# Readiness
# --------------------------------------------------------------------------- #
def test_no_investigations_means_ready(state):
    assert iv.readiness(state, "A1")["status"] == "ready"


def test_pending_blocking_result_means_waiting(state):
    iv.order(state, "P1", "CBC", now="09:20", day=state.day(),
             appointment_id="A1", eta="11:30")
    rd = iv.readiness(state, "A1")
    assert rd["status"] == "waiting"
    assert rd["ready"] is False
    assert rd["eta"] == "11:30"


def test_flagged_result_blocks_rather_than_clears(state):
    r = iv.order(state, "P1", "CBC", now="09:20", day=state.day(),
                 appointment_id="A1")
    iv.result(state, r.data["investigation"]["id"], "ANC 0.9", now="10:48",
              flagged=True)
    rd = iv.readiness(state, "A1")
    assert rd["status"] == "blocked"
    assert rd["ready"] is False


def test_non_blocking_order_does_not_gate(state):
    iv.order(state, "P1", "LFT", now="09:20", day=state.day(),
             appointment_id="A1", blocking=False)
    assert iv.readiness(state, "A1")["ready"] is True


# --------------------------------------------------------------------------- #
# Gating: the patient keeps the place, the chair goes back
# --------------------------------------------------------------------------- #
def test_gating_releases_the_chair_but_keeps_the_appointment(state):
    iv.order(state, "P1", "CBC", now="09:20", day=state.day(),
             appointment_id="A1", eta="11:30")
    r = iv.gate(state, "A1", now="10:00")
    assert r.success
    appt = state.appointment("A1")
    assert appt.awaiting_results is True
    assert appt.room_id is None            # chair released
    assert appt.held_room_id == "R1"       # remembered
    assert appt.status == AppointmentStatus.BOOKED   # not cancelled
    assert r.data["released_room_name"] == "Infusion 1"


def test_released_chair_is_free_for_someone_else(state):
    iv.order(state, "P1", "CBC", now="09:20", day=state.day(),
             appointment_id="A1")
    reg = SlotRegistry(state)
    assert reg.is_room_slot_free("R1", "10:00", "11:30") is False
    iv.gate(state, "A1", now="10:00")
    assert reg.is_room_slot_free("R1", "10:00", "11:30") is True


def test_gated_patient_is_never_marked_no_show(state):
    iv.order(state, "P1", "CBC", now="09:20", day=state.day(),
             appointment_id="A1")
    iv.gate(state, "A1", now="10:00")
    out = advance_clock(state, "11:00", no_show_min=15)   # 60 min past start
    assert out["no_shows"] == []
    assert state.appointment("A1").status == AppointmentStatus.BOOKED


def test_ungated_patient_is_still_no_showed(state):
    out = advance_clock(state, "11:00", no_show_min=15)
    assert "A1" in out["no_shows"]


def test_gating_a_ready_appointment_is_refused(state):
    r = iv.gate(state, "A1", now="10:00")
    assert not r.success
    assert "no need to gate" in r.message


# --------------------------------------------------------------------------- #
# Re-pencilling once results are in
# --------------------------------------------------------------------------- #
def test_repencil_refuses_while_still_waiting(state):
    iv.order(state, "P1", "CBC", now="09:20", day=state.day(),
             appointment_id="A1")
    iv.gate(state, "A1", now="10:00")
    r = iv.repencil(state, "A1", _alloc(state), now="10:30")
    assert not r.success
    assert "waiting" in r.message


def test_repencil_refuses_on_a_flagged_result(state):
    o = iv.order(state, "P1", "CBC", now="09:20", day=state.day(),
                 appointment_id="A1")
    iv.gate(state, "A1", now="10:00")
    iv.result(state, o.data["investigation"]["id"], "ANC 0.9", now="10:48",
              flagged=True)
    r = iv.repencil(state, "A1", _alloc(state), now="11:00")
    assert not r.success
    assert "doctor must clear" in r.message


def test_repencil_places_it_after_now_once_clear(state):
    o = iv.order(state, "P1", "CBC", now="09:20", day=state.day(),
                 appointment_id="A1")
    iv.gate(state, "A1", now="10:00")
    iv.result(state, o.data["investigation"]["id"], "Hb 11.2", now="10:48")
    r = iv.repencil(state, "A1", _alloc(state), now="11:00")
    assert r.success, r.message
    appt = state.appointment("A1")
    assert appt.awaiting_results is False
    assert appt.slot_start >= "11:00"
    assert appt.room_id                      # has a chair again


def test_gated_list_reports_why_and_which_chair(state):
    iv.order(state, "P1", "CBC", now="09:20", day=state.day(),
             appointment_id="A1", eta="11:30")
    iv.gate(state, "A1", now="10:00")
    rows = iv.gated_appointments(state)
    assert len(rows) == 1
    assert rows[0]["patient_name"] == "Meera"
    assert rows[0]["held_room_id"] == "R1"
    assert rows[0]["readiness"]["status"] == "waiting"
