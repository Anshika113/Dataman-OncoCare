"""Walk-in intake: fitting an unbooked patient into today without moving anyone.

Covers Bucket A / feature 1. The guarantees under test are the ones the desk
and the doctor actually care about: a walk-in only lands in a gap that was
already free, the daily cap is reported rather than silently exceeded, and
urgency narrows how far ahead the system is willing to look.
"""

from __future__ import annotations

import pytest

from engine import (
    SystemState, Doctor, Patient, Appointment, AppointmentType,
    AppointmentStatus, DoctorStatus, SlotRegistry, AppointmentAllocator,
    LeaveEntry,
)


@pytest.fixture
def state() -> SystemState:
    s = SystemState()
    s.doctors = {
        "D1": Doctor("D1", "Dr One", "oncology", 20, DoctorStatus.AVAILABLE,
                     ["oncology"]),
        "D2": Doctor("D2", "Dr Two", "oncology", 20, DoctorStatus.AVAILABLE,
                     ["oncology"]),
    }
    s.patients = {
        "P1": Patient("P1", "Alice", "+1", 1),
        "P2": Patient("P2", "Bob", "+2", 1),
        "P9": Patient("P9", "Walk In", "+9", 1),
    }
    return s


def _alloc(s):
    return AppointmentAllocator(s, SlotRegistry(s))


def _busy(s, aid, doctor, start, end, patient="P1"):
    s.appointments[aid] = Appointment(aid, patient, doctor, start, end,
                                      AppointmentType.CONSULT)


# --------------------------------------------------------------------------- #
# Finding a gap
# --------------------------------------------------------------------------- #
def test_offers_the_earliest_gap_after_now(state):
    out = _alloc(state).walk_in_options(duration=15, now="10:00")
    assert out["options"]
    assert all(o["slot_start"] >= "10:00" for o in out["options"])
    assert out["options"][0]["slot_start"] == "10:00"


def test_never_offers_a_slot_in_the_past(state):
    out = _alloc(state).walk_in_options(duration=15, now="14:20")
    assert all(o["slot_start"] >= "14:20" for o in out["options"])


def test_walk_in_does_not_displace_a_booked_patient(state):
    _busy(state, "A1", "D1", "10:00", "11:00")
    out = _alloc(state).walk_in_options(duration=15, now="10:00",
                                        doctor_id="D1")
    # the only offer must sit outside the booked block
    assert out["options"]
    for o in out["options"]:
        assert not (o["slot_start"] < "11:00" and o["slot_end"] > "10:00")
    # and nothing was mutated by looking
    assert state.appointments["A1"].slot_start == "10:00"


def test_reports_the_gap_it_found_and_who_is_before(state):
    _busy(state, "A1", "D1", "10:00", "10:30")
    out = _alloc(state).walk_in_options(duration=15, now="10:30",
                                        doctor_id="D1")
    best = out["options"][0]
    assert best["after"] == "Alice"
    assert best["gap_min"] >= 15
    assert best["cap_total"] == 20


def test_one_option_per_doctor(state):
    out = _alloc(state).walk_in_options(duration=15, now="09:00", limit=5)
    ids = [o["doctor_id"] for o in out["options"]]
    assert len(ids) == len(set(ids))
    assert set(ids) <= {"D1", "D2"}


# --------------------------------------------------------------------------- #
# Urgency narrows the horizon
# --------------------------------------------------------------------------- #
def test_urgent_only_looks_an_hour_ahead(state):
    # block D1 and D2 for the next two hours
    _busy(state, "A1", "D1", "09:00", "11:30")
    _busy(state, "A2", "D2", "09:00", "11:30", patient="P2")
    out = _alloc(state).walk_in_options(duration=15, now="09:00",
                                        urgency="urgent")
    assert out["options"] == []
    assert out["searched_until"] == "10:00"


def test_routine_finds_the_afternoon_when_the_morning_is_full(state):
    _busy(state, "A1", "D1", "09:00", "11:30")
    _busy(state, "A2", "D2", "09:00", "11:30", patient="P2")
    out = _alloc(state).walk_in_options(duration=15, now="09:00",
                                        urgency="routine")
    assert out["options"]
    assert out["options"][0]["slot_start"] >= "11:30"


# --------------------------------------------------------------------------- #
# Capacity and availability are respected, not bypassed
# --------------------------------------------------------------------------- #
def test_doctor_at_cap_is_reported_not_squeezed(state):
    state.doctors["D1"].daily_cap = 1
    _busy(state, "A1", "D1", "09:00", "09:30")
    out = _alloc(state).walk_in_options(duration=15, now="09:30",
                                        doctor_id="D1")
    assert out["options"] == []
    assert "Dr One" in out["at_cap"]


def test_booking_refuses_once_the_cap_is_reached(state):
    state.doctors["D1"].daily_cap = 1
    _busy(state, "A1", "D1", "09:00", "09:30")
    r = _alloc(state).book_walk_in("P9", "D1", "10:00", "10:15", at="09:30")
    assert not r.success
    assert "cap" in r.message


def test_doctor_on_leave_is_not_offered(state):
    state.doctors["D1"].status = DoctorStatus.ON_LEAVE
    out = _alloc(state).walk_in_options(duration=15, now="09:00")
    assert all(o["doctor_id"] != "D1" for o in out["options"])


def test_partial_leave_window_is_skipped(state):
    state.doctors["D1"].status = DoctorStatus.PARTIALLY_UNAVAILABLE
    state.doctors["D1"].leaves = [
        LeaveEntry("L1", "09:00", "12:00", "teaching", state.day())]
    out = _alloc(state).walk_in_options(duration=15, now="09:00",
                                        doctor_id="D1")
    assert all(o["slot_start"] >= "12:00" for o in out["options"])


# --------------------------------------------------------------------------- #
# Booking
# --------------------------------------------------------------------------- #
def test_booking_records_reason_and_marks_it_a_walk_in(state):
    r = _alloc(state).book_walk_in("P9", "D1", "11:00", "11:15", at="10:40",
                                   reason="mouth sores since C2",
                                   visit_type="follow_up")
    assert r.success
    appt = state.appointment(r.data["appt_id"])
    assert appt.walk_in is True
    assert appt.reason == "mouth sores since C2"
    assert appt.visit_type == "follow_up"
    assert appt.planned_min == 15


def test_booking_a_taken_slot_is_refused(state):
    _busy(state, "A1", "D1", "11:00", "11:30")
    r = _alloc(state).book_walk_in("P9", "D1", "11:00", "11:15", at="10:40")
    assert not r.success
    assert "cannot fit" in r.message


def test_booking_notifies_the_patient(state):
    before = len(state.notifications)
    r = _alloc(state).book_walk_in("P9", "D1", "11:00", "11:15", at="10:40")
    assert r.success
    assert len(state.notifications) == before + 1
    assert state.notifications[-1].patient_id == "P9"


def test_walk_in_is_logged_for_audit(state):
    _alloc(state).book_walk_in("P9", "D1", "11:00", "11:15", at="10:40",
                               reason="fever")
    kinds = [lg.kind for lg in state.logs]
    assert "walk_in" in kinds
