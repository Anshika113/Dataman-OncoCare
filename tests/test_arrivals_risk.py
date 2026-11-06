"""Arrivals board and no-show risk.

Covers Bucket A / features 5 and 7. The board turns check-in timestamps into
something a front desk can work from; the risk score is built only from what
the datastore really knows, and overbooking never happens without the
doctor's own switch.
"""

from __future__ import annotations

import pytest

from engine import (
    SystemState, Doctor, Patient, Appointment, AppointmentType,
    AppointmentStatus, DoctorStatus, arrivals as arr, risk as rk,
)


@pytest.fixture
def state() -> SystemState:
    s = SystemState()
    s.doctors = {
        "D1": Doctor("D1", "Dr One", "oncology", 20, DoctorStatus.AVAILABLE),
        "D2": Doctor("D2", "Dr Two", "oncology", 20, DoctorStatus.AVAILABLE),
    }
    s.patients = {
        "P1": Patient("P1", "Asha", "+1", 1),
        "P2": Patient("P2", "Bilal", "+2", 1),
        "P3": Patient("P3", "Carol", "+3", 1),
    }
    return s


def _appt(s, aid, pid, did, start, end, **kw):
    a = Appointment(aid, pid, did, start, end, AppointmentType.CONSULT)
    for k, v in kw.items():
        setattr(a, k, v)
    s.appointments[aid] = a
    return a


# --------------------------------------------------------------------------- #
# Arrivals board
# --------------------------------------------------------------------------- #
def test_not_arrived_patient_shows_as_such(state):
    _appt(state, "A1", "P1", "D1", "10:00", "10:30")
    row = arr.board(state, "09:50")[0]
    assert row["stage"] == "not_arrived"
    assert row["token"] == ""
    assert row["waiting_min"] == 0


def test_arrival_issues_a_token_in_arrival_order(state):
    _appt(state, "A1", "P1", "D1", "10:00", "10:30",
          checked_in=True, checked_in_at="09:58")
    _appt(state, "A2", "P2", "D1", "09:30", "10:00",
          checked_in=True, checked_in_at="09:40")
    rows = {r["patient_name"]: r for r in arr.board(state, "10:00")}
    assert rows["Bilal"]["token"] == "A-01"   # arrived first
    assert rows["Asha"]["token"] == "A-02"


def test_waiting_time_runs_from_arrival_to_being_called(state):
    _appt(state, "A1", "P1", "D1", "10:00", "10:30",
          checked_in=True, checked_in_at="09:40")
    assert arr.board(state, "10:12")[0]["waiting_min"] == 32
    state.appointments["A1"].started_at = "10:05"
    assert arr.board(state, "10:30")[0]["waiting_min"] == 25   # stops at 10:05


def test_stages_are_distinguished(state):
    _appt(state, "A1", "P1", "D1", "10:00", "10:30",
          checked_in=True, checked_in_at="09:58")
    _appt(state, "A2", "P2", "D1", "10:30", "11:00",
          checked_in=True, checked_in_at="10:10", awaiting_results=True)
    _appt(state, "A3", "P3", "D2", "09:00", "09:30",
          checked_in=True, checked_in_at="08:55", started_at="09:00")
    rows = {r["patient_name"]: r["stage"] for r in arr.board(state, "10:15")}
    assert rows == {"Asha": "ready", "Bilal": "in_labs", "Carol": "with_doctor"}


def test_next_up_is_the_longest_waiting_ready_patient(state):
    _appt(state, "A1", "P1", "D1", "10:00", "10:30",
          checked_in=True, checked_in_at="09:58")
    _appt(state, "A2", "P2", "D1", "10:30", "11:00",
          checked_in=True, checked_in_at="09:30")
    assert arr.next_up(state, "10:15")["patient_name"] == "Bilal"


def test_next_up_is_none_when_nobody_is_ready(state):
    _appt(state, "A1", "P1", "D1", "10:00", "10:30")
    assert arr.next_up(state, "10:15") is None


def test_running_late_counts_only_patients_who_turned_up(state):
    _appt(state, "A1", "P1", "D1", "09:30", "10:00",
          checked_in=True, checked_in_at="09:25")
    _appt(state, "A2", "P2", "D1", "09:45", "10:15")     # never arrived
    late = arr.running_late(state, "10:00")
    assert len(late) == 1
    assert late[0]["doctor_name"] == "Dr One"
    assert late[0]["behind_min"] == 30
    assert late[0]["affected"] == 1


def test_a_doctor_on_time_is_not_reported_late(state):
    _appt(state, "A1", "P1", "D1", "10:30", "11:00",
          checked_in=True, checked_in_at="10:00")
    assert arr.running_late(state, "10:05") == []


def test_a_doctor_is_not_late_for_someone_the_lab_still_has(state):
    _appt(state, "A1", "P1", "D1", "09:00", "09:30", checked_in=True,
          checked_in_at="08:50", awaiting_results=True)
    assert arr.running_late(state, "11:30") == []


def test_a_patient_due_this_minute_does_not_make_a_doctor_late(state):
    _appt(state, "A1", "P1", "D1", "10:00", "10:30",
          checked_in=True, checked_in_at="09:50")
    assert arr.running_late(state, "10:00") == []


# --------------------------------------------------------------------------- #
# Risk scoring
# --------------------------------------------------------------------------- #
def _history(s, pid, misses, seen):
    for i in range(misses):
        s.appointments[f"H{pid}m{i}"] = Appointment(
            f"H{pid}m{i}", pid, "D1", "09:00", "09:30",
            AppointmentType.CONSULT, AppointmentStatus.NO_SHOW)
    for i in range(seen):
        s.appointments[f"H{pid}s{i}"] = Appointment(
            f"H{pid}s{i}", pid, "D1", "09:00", "09:30",
            AppointmentType.CONSULT, AppointmentStatus.VISITED)


def test_repeat_misser_scores_high(state):
    _history(state, "P1", misses=3, seen=4)
    a = _appt(state, "A1", "P1", "D1", "11:00", "11:30")
    out = rk.score(state, a)
    assert out["level"] == "high"
    assert any("missed 3 of last 7" in f for f in out["factors"])


def test_confirmed_patient_scores_low(state):
    _history(state, "P1", misses=0, seen=6)
    a = _appt(state, "A1", "P1", "D1", "11:00", "11:30", confirmed="yes")
    out = rk.score(state, a)
    assert out["level"] == "low"
    assert "confirmed by reply" in out["factors"]


def test_explicit_decline_scores_highest(state):
    _history(state, "P1", misses=0, seen=6)
    a = _appt(state, "A1", "P1", "D1", "11:00", "11:30", confirmed="no")
    assert rk.score(state, a)["level"] == "high"


def test_thin_history_is_admitted_not_guessed(state):
    a = _appt(state, "A1", "P1", "D1", "11:00", "11:30")
    assert "little history to go on" in rk.score(state, a)["factors"]


def test_every_factor_is_explained(state):
    _history(state, "P1", misses=2, seen=3)
    a = _appt(state, "A1", "P1", "D1", "08:30", "09:00")
    out = rk.score(state, a)
    assert out["factors"]            # never an unexplained number
    assert 0 <= out["score"] <= 100


def test_day_risk_is_worst_first(state):
    _history(state, "P1", misses=3, seen=1)
    _appt(state, "A1", "P1", "D1", "11:00", "11:30")
    _history(state, "P2", misses=0, seen=8)
    _appt(state, "A2", "P2", "D1", "12:00", "12:30", confirmed="yes")
    rows = rk.day_risk(state)
    assert [r["patient_name"] for r in rows] == ["Asha", "Bilal"]


# --------------------------------------------------------------------------- #
# Overbooking stays the doctor's decision
# --------------------------------------------------------------------------- #
def test_no_safety_booking_without_the_doctors_opt_in(state):
    _history(state, "P1", misses=3, seen=1)
    _appt(state, "A1", "P1", "D1", "11:00", "11:30")
    out = rk.suggestions(state)
    assert out["safety_bookings"] == []
    assert len(out["needs_doctor_opt_in"]) == 1


def test_safety_booking_appears_once_the_doctor_opts_in(state):
    state.doctors["D1"].allow_safety_booking = True
    _history(state, "P1", misses=3, seen=1)
    _appt(state, "A1", "P1", "D1", "11:00", "11:30")
    out = rk.suggestions(state)
    assert len(out["safety_bookings"]) == 1
    assert out["safety_bookings"][0]["patient_name"] == "Asha"
    assert out["needs_doctor_opt_in"] == []


def test_unconfirmed_patients_are_offered_the_cheap_fix(state):
    _history(state, "P1", misses=0, seen=5)
    _appt(state, "A1", "P1", "D1", "11:00", "11:30")
    out = rk.suggestions(state)
    assert out["remind_early"]
    assert out["remind_early"][0]["patient_name"] == "Asha"
