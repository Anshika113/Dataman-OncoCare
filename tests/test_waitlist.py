"""Waitlist and slot backfill.

Covers Bucket A / feature 3. The promises under test: a freed slot is matched
against people who can genuinely take it, a slot can be offered to several at
once, the first acceptance books and everyone else is told it is gone.
"""

from __future__ import annotations

import pytest

from engine import (
    SystemState, Doctor, Patient, Appointment, AppointmentType,
    AppointmentStatus, DoctorStatus, SlotRegistry, AppointmentAllocator,
    waitlist as wl,
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
        "P1": Patient("P1", "Asha", "+1", 1),
        "P2": Patient("P2", "Bilal", "+2", 1),
        "P3": Patient("P3", "Carol", "+3", 1),
    }
    return s


def _alloc(s):
    return AppointmentAllocator(s, SlotRegistry(s))


def _add(s, pid, **kw):
    kw.setdefault("now", "10:00")
    kw.setdefault("day", s.day())
    r = wl.add(s, pid, **kw)
    assert r.success, r.message
    return r.data["entry"]["id"]


# --------------------------------------------------------------------------- #
# Managing the list
# --------------------------------------------------------------------------- #
def test_add_and_list(state):
    _add(state, "P1", doctor_id="D1", reason="overdue 6 days")
    assert len(wl.active_entries(state)) == 1


def test_cannot_add_the_same_patient_twice_for_one_doctor(state):
    _add(state, "P1", doctor_id="D1")
    r = wl.add(state, "P1", now="10:00", day=state.day(), doctor_id="D1")
    assert not r.success


def test_same_patient_may_wait_for_a_different_doctor(state):
    _add(state, "P1", doctor_id="D1")
    r = wl.add(state, "P1", now="10:00", day=state.day(), doctor_id="D2")
    assert r.success


def test_remove_takes_them_off_the_list(state):
    eid = _add(state, "P1", doctor_id="D1")
    assert wl.remove(state, eid, "10:05").success
    assert wl.active_entries(state) == []


def test_unknown_patient_is_refused(state):
    r = wl.add(state, "NOPE", now="10:00", day=state.day())
    assert not r.success


# --------------------------------------------------------------------------- #
# Matching a freed slot
# --------------------------------------------------------------------------- #
def test_patient_in_the_building_ranks_first(state):
    _add(state, "P2", doctor_id="D1", travel_min=10)
    _add(state, "P1", doctor_id="D1", in_building=True)
    out = wl.candidates(state, "D1", "11:00", "11:30", now="10:00")
    assert out[0]["patient_name"] == "Asha"
    assert "already in the building" in out[0]["why"]


def test_unreachable_patient_ranks_below_a_reachable_one(state):
    _add(state, "P1", doctor_id="D1", travel_min=120)   # cannot make it
    _add(state, "P2", doctor_id="D1", travel_min=10)
    out = wl.candidates(state, "D1", "10:30", "11:00", now="10:00")
    assert [r["patient_name"] for r in out] == ["Bilal", "Asha"]
    assert out[0]["reachable"] is True
    assert out[1]["reachable"] is False


def test_entry_for_another_doctor_is_not_matched(state):
    _add(state, "P1", doctor_id="D2")
    assert wl.candidates(state, "D1", "11:00", "11:30", now="10:00") == []


def test_entry_with_no_doctor_preference_matches_anyone(state):
    _add(state, "P1")
    assert len(wl.candidates(state, "D1", "11:00", "11:30", now="10:00")) == 1


def test_slot_outside_the_patients_window_is_skipped(state):
    _add(state, "P1", doctor_id="D1", earliest="14:00")
    assert wl.candidates(state, "D1", "11:00", "11:30", now="10:00") == []
    assert len(wl.candidates(state, "D1", "14:00", "14:30", now="10:00")) == 1


def test_slot_too_short_for_the_visit_is_skipped(state):
    _add(state, "P1", doctor_id="D1", visit_type="counselling")   # needs 45
    assert wl.candidates(state, "D1", "11:00", "11:30", now="10:00") == []
    assert len(wl.candidates(state, "D1", "11:00", "11:45", now="10:00")) == 1


# --------------------------------------------------------------------------- #
# Offer and accept
# --------------------------------------------------------------------------- #
def test_offering_notifies_everyone_offered(state):
    a = _add(state, "P1", doctor_id="D1")
    b = _add(state, "P2", doctor_id="D1")
    before = len(state.notifications)
    r = wl.offer(state, [a, b], "D1", "11:00", "11:30", now="10:00")
    assert r.success
    assert len(state.notifications) == before + 2
    assert state.waitlist_entry(a).status == "offered"


def test_first_accept_books_and_closes_the_offer(state):
    a = _add(state, "P1", doctor_id="D1")
    b = _add(state, "P2", doctor_id="D1")
    wl.offer(state, [a, b], "D1", "11:00", "11:30", now="10:00")

    r = wl.accept(state, a, _alloc(state), now="10:05")
    assert r.success
    assert state.waitlist_entry(a).status == "booked"
    # the other goes back on the list rather than silently vanishing
    assert state.waitlist_entry(b).status == "waiting"
    assert r.data["passed_over"] == 1
    # and a real appointment exists in the freed slot
    booked = [x for x in state.appointments.values()
              if x.slot_start == "11:00" and x.patient_id == "P1"]
    assert len(booked) == 1


def test_second_accept_finds_the_slot_gone(state):
    a = _add(state, "P1", doctor_id="D1")
    b = _add(state, "P2", doctor_id="D1")
    wl.offer(state, [a, b], "D1", "11:00", "11:30", now="10:00")
    alloc = _alloc(state)
    assert wl.accept(state, a, alloc, now="10:05").success

    r = wl.accept(state, b, alloc, now="10:06",
                  doctor_id="D1", slot_start="11:00", slot_end="11:30")
    assert not r.success
    assert "no longer available" in r.message


def test_accept_without_an_offer_is_refused(state):
    a = _add(state, "P1", doctor_id="D1")
    r = wl.accept(state, a, _alloc(state), now="10:05")
    assert not r.success
    assert "offer one first" in r.message


def test_accept_carries_the_visit_type_through(state):
    a = _add(state, "P1", doctor_id="D1", visit_type="follow_up")
    wl.offer(state, [a], "D1", "11:00", "11:10", now="10:00")
    assert wl.accept(state, a, _alloc(state), now="10:05").success
    appt = next(x for x in state.appointments.values() if x.patient_id == "P1")
    assert appt.visit_type == "follow_up"
    assert appt.planned_min == 10


def test_backfill_is_logged(state):
    a = _add(state, "P1", doctor_id="D1")
    wl.offer(state, [a], "D1", "11:00", "11:30", now="10:00")
    wl.accept(state, a, _alloc(state), now="10:05")
    kinds = [lg.kind for lg in state.logs]
    assert "waitlist_offer" in kinds and "waitlist_accept" in kinds
