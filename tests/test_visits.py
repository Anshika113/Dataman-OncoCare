"""Variable-length visits: visit types, candidate slot search, learned durations.

Covers Bucket A / feature 6 ("smarter slots"): a consult is as long as its
visit type says, short visits fit gaps a 30-minute slot cannot use, and the
learned median is only offered once there is enough evidence for it.
"""

from __future__ import annotations

import pytest

from engine import (
    SystemState, Doctor, Patient, Appointment, AppointmentType,
    AppointmentStatus, DoctorStatus, SlotRegistry, AppointmentAllocator,
)
from engine import visits


@pytest.fixture
def state() -> SystemState:
    s = SystemState()
    s.doctors = {
        "D1": Doctor("D1", "Dr One", "oncology", 20, DoctorStatus.AVAILABLE,
                     ["oncology"]),
    }
    s.patients = {
        "P1": Patient("P1", "Alice", "+1", 1),
        "P2": Patient("P2", "Bob", "+2", 1),
    }
    return s


def _alloc(s):
    return AppointmentAllocator(s, SlotRegistry(s))


# --------------------------------------------------------------------------- #
# Visit type catalogue
# --------------------------------------------------------------------------- #
def test_catalogue_exposes_planned_durations():
    rows = {r["key"]: r for r in visits.catalogue()}
    assert rows["follow_up"]["default_min"] == 10
    assert rows["counselling"]["default_min"] == 45
    # no doctor given -> nothing learned
    assert all(r["learned"] is None for r in rows.values())


def test_clamp_duration_rejects_nonsense():
    assert visits.clamp_duration(0) == visits.MIN_DURATION
    assert visits.clamp_duration(9999) == visits.MAX_DURATION
    assert visits.clamp_duration("not a number", fallback=30) == 30


# --------------------------------------------------------------------------- #
# Booking honours the visit type's length
# --------------------------------------------------------------------------- #
def test_follow_up_books_ten_minutes(state):
    r = _alloc(state).book_consult("P1", "D1", "09:00", "09:10", at="08:00",
                                   visit_type="follow_up")
    assert r.success
    appt = next(iter(state.appointments.values()))
    assert appt.visit_type == "follow_up"
    assert appt.planned_min == 10


def test_unknown_visit_type_is_not_stored(state):
    r = _alloc(state).book_consult("P1", "D1", "09:00", "09:30", at="08:00",
                                   visit_type="tea_break")
    assert r.success
    appt = next(iter(state.appointments.values()))
    assert appt.visit_type == ""
    # falls back to the default type rather than guessing
    assert appt.eff_visit_type == visits.DEFAULT_VISIT_TYPE


def test_legacy_consult_defaults_to_new_case(state):
    state.appointments["A1"] = Appointment(
        "A1", "P1", "D1", "09:00", "09:30", AppointmentType.CONSULT)
    assert state.appointments["A1"].eff_visit_type == "new_case"


# --------------------------------------------------------------------------- #
# Candidate slot search is no longer stuck on the 30-minute grid
# --------------------------------------------------------------------------- #
def test_short_visit_fits_a_gap_a_full_slot_cannot(state):
    # 09:00-09:45 and 10:00-10:30 busy -> only a 15-minute gap at 09:45
    state.appointments["A1"] = Appointment(
        "A1", "P1", "D1", "09:00", "09:45", AppointmentType.CONSULT)
    state.appointments["A2"] = Appointment(
        "A2", "P2", "D1", "10:00", "10:30", AppointmentType.CONSULT)
    reg = SlotRegistry(state)

    starts_30 = [s for s, _ in reg.doctor_candidate_slots("D1", 30)]
    starts_10 = [s for s, _ in reg.doctor_candidate_slots("D1", 10)]

    assert "09:45" not in starts_30   # a 30-min visit cannot use the gap
    assert "09:45" in starts_10       # a 10-min follow-up can


def test_candidate_slots_respect_buffers(state):
    state.appointments["A1"] = Appointment(
        "A1", "P1", "D1", "10:00", "10:30", AppointmentType.CONSULT,
        buffer_before=15, buffer_after=15)
    reg = SlotRegistry(state)
    starts = [s for s, _ in reg.doctor_candidate_slots("D1", 10)]
    assert "09:50" not in starts   # would enter the pre-buffer
    assert "10:30" not in starts   # would enter the post-buffer
    assert "10:45" in starts       # clear of it


def test_free_gaps_merge_around_appointments(state):
    state.appointments["A1"] = Appointment(
        "A1", "P1", "D1", "09:00", "09:30", AppointmentType.CONSULT)
    state.appointments["A2"] = Appointment(
        "A2", "P2", "D1", "09:30", "10:00", AppointmentType.CONSULT)
    gaps = SlotRegistry(state).doctor_free_gaps("D1")
    assert ("08:00", "09:00") in gaps
    assert ("10:00", "18:00") in gaps
    # the two back-to-back appointments leave no gap between them
    assert all(not (g[0] == "09:30" and g[1] == "09:30") for g in gaps)


def test_recommendations_are_the_requested_length(state):
    recs = _alloc(state).recommend_consult_slots("D1", "09:00", duration=10)
    assert recs
    assert all(r["slot_end"] != r["slot_start"] for r in recs)
    first = recs[0]
    from engine import to_min
    assert to_min(first["slot_end"]) - to_min(first["slot_start"]) == 10


# --------------------------------------------------------------------------- #
# Learned durations
# --------------------------------------------------------------------------- #
def _completed(aid, start, end, visit_type="follow_up"):
    a = Appointment(aid, "P1", "D1", start, end, AppointmentType.CONSULT,
                    AppointmentStatus.VISITED)
    a.visit_type = visit_type
    a.started_at = start
    a.completed_at = end
    return a


def test_learned_duration_needs_enough_samples(state):
    for i in range(visits.MIN_SAMPLES - 1):
        state.appointments[f"A{i}"] = _completed(f"A{i}", "09:00", "09:13")
    assert visits.learned_duration(state, "D1", "follow_up") is None


def test_learned_duration_reports_the_median(state):
    for i in range(6):
        state.appointments[f"A{i}"] = _completed(f"A{i}", "09:00", "09:13")
    out = visits.learned_duration(state, "D1", "follow_up")
    assert out is not None
    assert out["median_min"] == 13
    assert out["planned_min"] == 10
    assert out["suggested_min"] == 15      # rounded up to a bookable length
    assert out["differs"] is True
    assert out["samples"] == 6


def test_unfinished_visits_never_skew_the_median(state):
    for i in range(6):
        state.appointments[f"A{i}"] = _completed(f"A{i}", "09:00", "09:13")
    # a booked-but-never-seen slot carries no timestamps
    state.appointments["X"] = Appointment(
        "X", "P2", "D1", "11:00", "11:10", AppointmentType.CONSULT)
    state.appointments["X"].visit_type = "follow_up"
    assert visits.learned_duration(state, "D1", "follow_up")["samples"] == 6


def test_learned_duration_is_per_visit_type(state):
    for i in range(6):
        state.appointments[f"A{i}"] = _completed(f"A{i}", "09:00", "09:13")
    assert visits.learned_duration(state, "D1", "counselling") is None


def test_actual_min_is_none_until_the_visit_finishes(state):
    a = Appointment("A1", "P1", "D1", "09:00", "09:30", AppointmentType.CONSULT)
    assert a.actual_min is None
    a.started_at = "09:05"
    assert a.actual_min is None
    a.completed_at = "09:22"
    assert a.actual_min == 17
