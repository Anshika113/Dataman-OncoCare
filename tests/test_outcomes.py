"""Outcome reporting: did any of it help?

The brief's success criteria are waiting times, utilisation and bottlenecks.
These tests pin the two properties that make the report trustworthy: it
refuses to publish a median drawn from too few visits, and it names the
direction of each change rather than leaving the sign to be interpreted
(a smaller wait is good, a smaller utilisation is not).
"""

from __future__ import annotations

import pytest

from engine import (
    SystemState, Doctor, Patient, Appointment, AppointmentType,
    AppointmentStatus, DoctorStatus, SessionBlock, ActionRecord,
    outcomes as out,
)

TODAY = "2026-11-02"
YESTERDAY = "2026-10-30"


@pytest.fixture
def state() -> SystemState:
    s = SystemState()
    s.doctors = {"D1": Doctor("D1", "Dr One", "oncology", 20,
                              DoctorStatus.AVAILABLE)}
    s.patients = {f"P{i}": Patient(f"P{i}", f"Patient {i}", "+1", 1)
                  for i in range(1, 9)}
    s.active_day = TODAY
    return s


def _visit(s, aid, pid, arrived, called, done=None, slot=None, day=TODAY,
           status=AppointmentStatus.VISITED):
    start = slot or called
    a = Appointment(aid, pid, "D1", start, done or called,
                    AppointmentType.CONSULT, status)
    a.date = day
    a.checked_in = True
    a.checked_in_at = arrived
    a.started_at = called
    a.completed_at = done or called
    s.appointments[aid] = a
    return a


# --------------------------------------------------------------------------- #
# It refuses to publish a figure it cannot stand behind
# --------------------------------------------------------------------------- #
def test_waiting_is_not_reported_from_two_visits(state):
    _visit(state, "A1", "P1", "09:00", "09:20", "09:30")
    _visit(state, "A2", "P2", "09:30", "09:40", "09:50")
    w = out.day_outcomes(state, TODAY)["waiting"]
    assert w["enough"] is False
    assert w["measured"] == 2
    assert "needs 3" in w["why"]
    assert "median_min" not in w


def test_waiting_is_reported_once_there_are_enough(state):
    _visit(state, "A1", "P1", "09:00", "09:20", "09:30")   # 20
    _visit(state, "A2", "P2", "09:30", "09:40", "09:50")   # 10
    _visit(state, "A3", "P3", "10:00", "10:30", "10:40")   # 30
    w = out.day_outcomes(state, TODAY)["waiting"]
    assert w["enough"] is True
    assert w["measured"] == 3
    assert w["median_min"] == 20
    assert w["worst_min"] == 30
    assert w["worst_patient"] == "Patient 3"


def test_a_visit_without_timestamps_is_not_counted(state):
    _visit(state, "A1", "P1", "09:00", "09:20", "09:30")
    _visit(state, "A2", "P2", "09:30", "09:40", "09:50")
    _visit(state, "A3", "P3", "10:00", "10:30", "10:40")
    booked = Appointment("A4", "P4", "D1", "11:00", "11:30",
                         AppointmentType.CONSULT)
    booked.date = TODAY
    state.appointments["A4"] = booked
    assert out.day_outcomes(state, TODAY)["waiting"]["measured"] == 3


# --------------------------------------------------------------------------- #
# Punctuality
# --------------------------------------------------------------------------- #
def test_punctuality_counts_who_was_seen_near_their_time(state):
    _visit(state, "A1", "P1", "08:50", "09:05", "09:20", slot="09:00")  # 5 late
    _visit(state, "A2", "P2", "09:20", "10:10", "10:20", slot="09:30")  # 40 late
    _visit(state, "A3", "P3", "09:50", "10:00", "10:10", slot="10:00")  # on time
    p = out.day_outcomes(state, TODAY)["punctuality"]
    assert p["enough"] is True
    assert p["on_time"] == 2
    assert p["on_time_pct"] == 67


# --------------------------------------------------------------------------- #
# Utilisation uses the hours the clinic actually had
# --------------------------------------------------------------------------- #
def test_utilisation_against_the_full_working_day(state):
    a = Appointment("A1", "P1", "D1", "09:00", "11:00",
                    AppointmentType.CONSULT)
    a.date = TODAY
    state.appointments["A1"] = a
    u = out.day_outcomes(state, TODAY)["utilisation"]
    assert u["available_min"] == 600     # 08:00-18:00
    assert u["booked_min"] == 120
    assert u["pct"] == 20


def test_a_session_template_shrinks_the_available_hours(state):
    state.doctor("D1").sessions = [
        SessionBlock("S1", ["*"], "09:00", "13:00", "clinic", "OPD")]
    a = Appointment("A1", "P1", "D1", "09:00", "11:00",
                    AppointmentType.CONSULT)
    a.date = TODAY
    state.appointments["A1"] = a
    u = out.day_outcomes(state, TODAY)["utilisation"]
    assert u["available_min"] == 240     # only the clinic window counts
    assert u["pct"] == 50


def test_a_doctor_on_leave_contributes_no_capacity(state):
    state.doctor("D1").status = DoctorStatus.ON_LEAVE
    u = out.day_outcomes(state, TODAY)["utilisation"]
    assert u["available_min"] == 0
    assert u["pct"] is None          # not a divide-by-zero zero


# --------------------------------------------------------------------------- #
# Recovered time and losses
# --------------------------------------------------------------------------- #
def test_walk_ins_and_backfills_count_as_recovered(state):
    w = Appointment("A1", "P1", "D1", "11:00", "11:15",
                    AppointmentType.CONSULT)
    w.date = TODAY
    w.walk_in = True
    state.appointments["A1"] = w
    state.actions["ACT1"] = ActionRecord(
        "ACT1", "waitlist_accept", "10:41", TODAY, changes=[{"x": 1}])
    r = out.day_outcomes(state, TODAY)["recovered"]
    assert r["walk_ins"] == 1
    assert r["walk_in_min"] == 15
    assert r["backfilled"] == 1


def test_an_undone_backfill_does_not_count(state):
    state.actions["ACT1"] = ActionRecord(
        "ACT1", "waitlist_accept", "10:41", TODAY, changes=[{"x": 1}],
        undone=True)
    assert out.day_outcomes(state, TODAY)["recovered"]["backfilled"] == 0


def test_losses_are_counted_against_what_was_booked(state):
    for i, st in enumerate((AppointmentStatus.NO_SHOW,
                            AppointmentStatus.NO_SHOW,
                            AppointmentStatus.CANCELLED,
                            AppointmentStatus.VISITED), start=1):
        a = Appointment(f"A{i}", f"P{i}", "D1", "09:00", "09:30",
                        AppointmentType.CONSULT, st)
        a.date = TODAY
        state.appointments[f"A{i}"] = a
    lo = out.day_outcomes(state, TODAY)["losses"]
    assert lo["no_shows"] == 2
    assert lo["cancelled"] == 1
    assert lo["no_show_pct"] == 50


# --------------------------------------------------------------------------- #
# Comparison against the clinic's own previous day
# --------------------------------------------------------------------------- #
def test_without_an_earlier_day_there_is_nothing_to_compare(state):
    _visit(state, "A1", "P1", "09:00", "09:20", "09:30")
    c = out.compare(state, TODAY)
    assert c["previous"] is None
    assert "no earlier day" in c["why"]


def test_the_previous_day_is_the_clinics_own_last_one(state):
    _visit(state, "A1", "P1", "09:00", "09:20", "09:30", day=YESTERDAY)
    _visit(state, "A2", "P2", "09:00", "09:20", "09:30", day="2026-10-01")
    assert out.previous_day_with_data(state, TODAY) == YESTERDAY


def test_a_shorter_wait_is_reported_as_better(state):
    for i, (arr, call) in enumerate(
            [("09:00", "09:30"), ("09:30", "10:00"), ("10:00", "10:30")], 1):
        _visit(state, f"Y{i}", f"P{i}", arr, call, day=YESTERDAY)   # 30 each
    for i, (arr, call) in enumerate(
            [("09:00", "09:10"), ("09:30", "09:40"), ("10:00", "10:10")], 1):
        _visit(state, f"T{i}", f"P{i}", arr, call, day=TODAY)       # 10 each

    d = {x["metric"]: x for x in out.compare(state, TODAY)["deltas"]}
    wait = d["waiting.median_min"]
    assert wait["now"] == 10 and wait["previous"] == 30
    assert wait["change"] == -20
    assert wait["better"] is True


def test_a_lower_utilisation_is_reported_as_worse(state):
    a = Appointment("Y1", "P1", "D1", "09:00", "13:00",
                    AppointmentType.CONSULT)
    a.date = YESTERDAY
    state.appointments["Y1"] = a
    b = Appointment("T1", "P2", "D1", "09:00", "10:00",
                    AppointmentType.CONSULT)
    b.date = TODAY
    state.appointments["T1"] = b

    d = {x["metric"]: x for x in out.compare(state, TODAY)["deltas"]}
    u = d["utilisation.pct"]
    assert u["change"] < 0
    assert u["better"] is False        # less used is not an improvement


def test_an_unmeasured_metric_says_so_rather_than_comparing(state):
    _visit(state, "Y1", "P1", "09:00", "09:30", day=YESTERDAY)
    _visit(state, "T1", "P2", "09:00", "09:10", day=TODAY)
    d = {x["metric"]: x for x in out.compare(state, TODAY)["deltas"]}
    wait = d["waiting.median_min"]
    assert wait["change"] is None
    assert wait["better"] is None
    assert "not measured" in wait["why"]


def test_a_doctor_sees_only_their_own_numbers(state):
    state.doctors["D2"] = Doctor("D2", "Dr Two", "oncology", 20)
    mine = Appointment("A1", "P1", "D1", "09:00", "09:30",
                       AppointmentType.CONSULT)
    mine.date = TODAY
    theirs = Appointment("A2", "P2", "D2", "09:00", "09:30",
                         AppointmentType.CONSULT)
    theirs.date = TODAY
    state.appointments.update({"A1": mine, "A2": theirs})
    assert out.day_outcomes(state, TODAY, "D1")["appointments"] == 1
    assert out.day_outcomes(state, TODAY)["appointments"] == 2
