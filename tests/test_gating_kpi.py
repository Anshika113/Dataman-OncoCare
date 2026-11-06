"""The headline KPI: chair time recovered from lab waits.

This is the number the project asks to be judged on, so the tests here pin
the three things that could quietly make it a lie:

* it is recorded when the chair is actually released, not reconstructed
  afterwards (re-pencilling clears ``held_room_id``, so a later reconstruction
  would silently read zero);
* a gate that frees no chair recovers no minutes;
* the queue metrics leave gated patients out, because their clock keeps
  running while the lab works and counting it would punish the clinic for the
  one move that gave the chair back.
"""

from __future__ import annotations

import pytest

from engine import (
    SystemState, Doctor, Patient, ChemRoom, Appointment, AppointmentType,
    AppointmentStatus, DoctorStatus, RoomStatus, RoomType, Investigation,
    investigations as inv,
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
    s.rooms = {"R1": ChemRoom("R1", "Infusion 1", RoomType.INFUSION_CHAIR,
                          ["pump", "monitor", "iv"], RoomStatus.AVAILABLE)}
    s.active_day = TODAY
    return s


def _chemo(s, aid, pid, start, end, day=TODAY, room="R1"):
    a = Appointment(aid, pid, "D1", start, end, AppointmentType.CHEMO,
                    AppointmentStatus.BOOKED)
    a.date = day
    a.room_id = room
    s.appointments[aid] = a
    return a


def _visit(s, aid, pid, arrived, called, done, slot=None, day=TODAY,
           chair=0):
    a = Appointment(aid, pid, "D1", slot or called, done,
                    AppointmentType.CONSULT, AppointmentStatus.COMPLETED)
    a.date = day
    a.checked_in = True
    a.checked_in_at = arrived
    a.started_at = called
    a.completed_at = done
    a.chair_released_min = chair
    s.appointments[aid] = a
    return a


# --------------------------------------------------------------------------- #
# The measurement happens when the chair is released
# --------------------------------------------------------------------------- #
def test_gating_records_the_slot_length_it_freed(state):
    a = _chemo(state, "A1", "P1", "10:00", "10:45")
    state.investigations["I1"] = Investigation(
        id="I1", patient_id="P1", kind="FBC", appointment_id="A1",
        ordered_at="09:20", ordered_on=TODAY, blocking=True)

    r = inv.gate(state, "A1", "09:30")

    assert r.success
    assert a.chair_released_min == 45
    assert a.room_id is None
    assert a.held_room_id == "R1"


def test_repencilling_clears_the_room_but_not_the_measurement(state):
    """The reason this is a stored field rather than something derived."""
    a = _chemo(state, "A1", "P1", "10:00", "10:30")
    state.investigations["I1"] = Investigation(
        id="I1", patient_id="P1", kind="FBC", appointment_id="A1",
        ordered_at="09:20", ordered_on=TODAY, blocking=True)
    inv.gate(state, "A1", "09:30")
    assert a.chair_released_min == 30

    a.held_room_id = ""          # what repencil() does once results land
    a.awaiting_results = False

    assert a.chair_released_min == 30
    assert out.day_outcomes(state, TODAY)["gating"]["chair_min_released"] == 30


def test_a_gate_that_frees_no_chair_recovers_nothing(state):
    a = _chemo(state, "A1", "P1", "10:00", "10:30", room=None)
    a.room_id = None
    state.investigations["I1"] = Investigation(
        id="I1", patient_id="P1", kind="FBC", appointment_id="A1",
        ordered_at="09:20", ordered_on=TODAY, blocking=True)

    r = inv.gate(state, "A1", "09:30")

    assert r.success
    assert a.chair_released_min == 0
    assert out.day_outcomes(state, TODAY)["gating"]["chair_min_released"] == 0


def test_gating_block_counts_held_treatments_and_their_minutes(state):
    _visit(state, "A1", "P1", "09:00", "09:10", "09:30", chair=30)
    _visit(state, "A2", "P2", "09:30", "09:40", "10:00", chair=45)
    _visit(state, "A3", "P3", "10:00", "10:10", "10:30")

    g = out.day_outcomes(state, TODAY)["gating"]

    assert g["held"] == 2
    assert g["chair_min_released"] == 75


# --------------------------------------------------------------------------- #
# A lab wait is not a queue wait
# --------------------------------------------------------------------------- #
def test_waiting_leaves_out_patients_held_for_results(state):
    _visit(state, "A1", "P1", "09:00", "09:15", "09:35")            # 15
    _visit(state, "A2", "P2", "09:30", "09:45", "10:05")            # 15
    _visit(state, "A3", "P3", "10:00", "10:20", "10:40")            # 20
    # held two hours for bloods: real, and not the queue's doing
    _visit(state, "A4", "P4", "09:00", "11:00", "11:30", chair=30)  # 120

    w = out.day_outcomes(state, TODAY)["waiting"]

    assert w["enough"] is True
    assert w["measured"] == 3
    assert w["held_excluded"] == 1
    assert w["median_min"] == 15
    # the 120-minute lab wait would otherwise have doubled the mean
    assert w["mean_min"] < 20


def test_punctuality_leaves_out_patients_held_for_results(state):
    _visit(state, "A1", "P1", "09:00", "09:05", "09:25", slot="09:00")
    _visit(state, "A2", "P2", "09:30", "09:35", "09:55", slot="09:30")
    _visit(state, "A3", "P3", "10:00", "10:10", "10:30", slot="10:00")
    _visit(state, "A4", "P4", "09:00", "11:00", "11:30", slot="09:00",
           chair=30)

    p = out.day_outcomes(state, TODAY)["punctuality"]

    assert p["measured"] == 3
    assert p["held_excluded"] == 1
    assert p["on_time"] == 3
    assert p["on_time_pct"] == 100


def test_the_exclusion_is_reported_even_when_there_is_too_little_data(state):
    _visit(state, "A1", "P1", "09:00", "09:15", "09:35")
    _visit(state, "A2", "P2", "09:00", "11:00", "11:30", chair=30)

    w = out.day_outcomes(state, TODAY)["waiting"]

    assert w["enough"] is False
    assert w["measured"] == 1
    assert w["held_excluded"] == 1


# --------------------------------------------------------------------------- #
# The direction of the change
# --------------------------------------------------------------------------- #
def test_more_chair_time_recovered_is_better(state):
    # yesterday: nothing gated, so nothing recovered
    for n, pid in enumerate(("P1", "P2", "P3"), start=1):
        _visit(state, f"Y{n}", pid, "09:00", "09:30", "09:50",
               day=YESTERDAY)
    # today: two treatments held, two chairs back
    _visit(state, "A1", "P1", "09:00", "09:10", "09:30")
    _visit(state, "A2", "P2", "09:30", "09:40", "10:00")
    _visit(state, "A3", "P3", "10:00", "10:10", "10:30")
    _visit(state, "A4", "P4", "09:00", "11:00", "11:30", chair=30)
    _visit(state, "A5", "P5", "09:30", "12:00", "12:30", chair=45)

    r = out.compare(state, TODAY, YESTERDAY)
    d = next(x for x in r["deltas"]
             if x["metric"] == "gating.chair_min_released")

    assert d["now"] == 75
    assert d["previous"] == 0
    assert d["change"] == 75
    assert d["better"] is True


def test_the_comparison_names_the_chair_metric_first(state):
    """It is the headline, so it leads the list the dashboard renders."""
    for n, pid in enumerate(("P1", "P2", "P3"), start=1):
        _visit(state, f"Y{n}", pid, "09:00", "09:30", "09:50", day=YESTERDAY)
    for n, pid in enumerate(("P1", "P2", "P3"), start=1):
        _visit(state, f"A{n}", pid, "09:00", "09:15", "09:35")

    r = out.compare(state, TODAY, YESTERDAY)

    assert r["deltas"][0]["metric"] == "gating.chair_min_released"
    assert r["deltas"][0]["label"] == "Chair time recovered"
