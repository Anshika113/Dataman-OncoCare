"""Session templates and case-mix rules.

Covers the last Bucket B item. Two promises are under test: a doctor with no
template behaves exactly as before (so nothing regressed), and once a template
exists the slot search and the booking path both honour it — refusing with the
rule's own words rather than a code.
"""

from __future__ import annotations

import pytest

from engine import (
    SystemState, Doctor, Patient, Appointment, AppointmentType,
    AppointmentStatus, DoctorStatus, SessionBlock, CaseMixRule,
    SlotRegistry, AppointmentAllocator, sessions as sess,
)

# 2026-11-02 is a Monday; 2026-11-03 a Tuesday.
MON = "2026-11-02"
TUE = "2026-11-03"


@pytest.fixture
def state() -> SystemState:
    s = SystemState()
    s.doctors = {"D1": Doctor("D1", "Dr One", "oncology", 20,
                              DoctorStatus.AVAILABLE, ["oncology"])}
    s.patients = {
        "P1": Patient("P1", "Asha", "+1", 1),
        "P2": Patient("P2", "Bilal", "+2", 1),
        "P3": Patient("P3", "Carol", "+3", 1),
        "P4": Patient("P4", "Dev", "+4", 1),
    }
    s.active_day = MON
    return s


def _alloc(s):
    return AppointmentAllocator(s, SlotRegistry(s, day=s.day()))


def _template(doc):
    doc.sessions = [
        SessionBlock("S1", ["mon", "wed"], "09:00", "13:00", "clinic", "OPD clinic"),
        SessionBlock("S2", ["tue"], "08:00", "18:00", "ward_round", "Ward round"),
        SessionBlock("S3", ["*"], "13:00", "13:30", "lunch", "Lunch"),
        SessionBlock("S4", ["thu"], "14:00", "16:00", "teaching", "Teaching"),
    ]


# --------------------------------------------------------------------------- #
# Weekdays
# --------------------------------------------------------------------------- #
def test_weekday_lookup():
    assert sess.weekday(MON) == "mon"
    assert sess.weekday(TUE) == "tue"
    assert sess.weekday("not-a-date") == ""


def test_a_star_block_covers_every_day():
    b = SessionBlock("S", ["*"], "13:00", "13:30", "lunch")
    assert b.covers_day("mon") and b.covers_day("sun")


# --------------------------------------------------------------------------- #
# No template = exactly the old behaviour
# --------------------------------------------------------------------------- #
def test_doctor_without_a_template_is_unconstrained(state):
    assert sess.session_conflict(state.doctor("D1"), MON, "09:00", "09:30") is None
    assert SlotRegistry(state, day=MON).is_doctor_slot_free("D1", "16:00", "16:30")


def test_day_plan_says_so(state):
    plan = sess.day_plan(state, "D1", MON)
    assert plan["unconstrained"] is True
    assert plan["clinic"] == [{"start": "08:00", "end": "18:00"}]


# --------------------------------------------------------------------------- #
# Session blocks
# --------------------------------------------------------------------------- #
def test_inside_clinic_hours_is_fine(state):
    _template(state.doctor("D1"))
    assert sess.session_conflict(state.doctor("D1"), MON, "09:30", "10:00") is None


def test_outside_clinic_hours_is_refused_with_the_hours(state):
    _template(state.doctor("D1"))
    why = sess.session_conflict(state.doctor("D1"), MON, "15:00", "15:30")
    assert why is not None
    assert "outside clinic hours" in why and "09:00–13:00" in why


def test_lunch_is_protected_every_day(state):
    _template(state.doctor("D1"))
    why = sess.session_conflict(state.doctor("D1"), MON, "13:00", "13:30")
    assert why is not None and "Lunch" in why


def test_a_day_with_no_clinic_session_is_closed(state):
    _template(state.doctor("D1"))
    why = sess.session_conflict(state.doctor("D1"), TUE, "10:00", "10:30")
    assert why is not None
    assert "Ward round" in why


def test_the_slot_grid_honours_the_template(state):
    _template(state.doctor("D1"))
    reg = SlotRegistry(state, day=MON)
    starts = [s for s, _ in reg.doctor_candidate_slots("D1", 30, step=30)]
    assert "09:00" in starts
    assert "12:30" in starts
    assert "13:00" not in starts     # lunch
    assert "15:00" not in starts     # after clinic


def test_booking_outside_the_template_is_refused(state):
    _template(state.doctor("D1"))
    r = _alloc(state).book_consult("P1", "D1", "15:00", "15:30", at="08:00",
                                   date=MON, visit_type="new_case")
    assert not r.success
    assert "outside clinic hours" in r.message


def test_booking_inside_the_template_succeeds(state):
    _template(state.doctor("D1"))
    r = _alloc(state).book_consult("P1", "D1", "09:30", "10:00", at="08:00",
                                   date=MON, visit_type="new_case")
    assert r.success


# --------------------------------------------------------------------------- #
# Case-mix rules
# --------------------------------------------------------------------------- #
def _booked(s, aid, pid, start, end, visit_type, day=MON):
    a = Appointment(aid, pid, "D1", start, end, AppointmentType.CONSULT,
                    AppointmentStatus.BOOKED)
    a.visit_type = visit_type
    a.date = day
    s.appointments[aid] = a
    return a


def test_max_consecutive_blocks_the_fourth_in_a_row(state):
    doc = state.doctor("D1")
    doc.rules = [CaseMixRule("R1", "max_consecutive", "new_case", "3")]
    _booked(state, "A1", "P1", "09:00", "09:30", "new_case")
    _booked(state, "A2", "P2", "09:30", "10:00", "new_case")
    _booked(state, "A3", "P3", "10:00", "10:30", "new_case")
    why = sess.case_mix_conflict(state, "D1", MON, "new_case", "10:30", "11:00")
    assert why == "no more than 3 new case visits in a row"


def test_a_different_visit_type_breaks_the_run(state):
    doc = state.doctor("D1")
    doc.rules = [CaseMixRule("R1", "max_consecutive", "new_case", "3")]
    _booked(state, "A1", "P1", "09:00", "09:30", "new_case")
    _booked(state, "A2", "P2", "09:30", "10:00", "new_case")
    _booked(state, "A3", "P3", "10:00", "10:10", "follow_up")
    assert sess.case_mix_conflict(state, "D1", MON, "new_case",
                                  "10:10", "10:40") is None


def test_run_is_counted_in_clock_order_not_booking_order(state):
    doc = state.doctor("D1")
    doc.rules = [CaseMixRule("R1", "max_consecutive", "new_case", "2")]
    _booked(state, "A1", "P1", "11:00", "11:30", "new_case")
    _booked(state, "A2", "P2", "09:00", "09:30", "new_case")
    # the new one lands between them, making three in a row
    why = sess.case_mix_conflict(state, "D1", MON, "new_case", "10:00", "10:30")
    assert why is not None


def test_not_after_rule(state):
    doc = state.doctor("D1")
    doc.rules = [CaseMixRule("R1", "not_after", "counselling", "12:00")]
    assert sess.case_mix_conflict(state, "D1", MON, "counselling",
                                  "11:00", "11:45") is None
    why = sess.case_mix_conflict(state, "D1", MON, "counselling",
                                 "14:00", "14:45")
    assert why == "counselling visits before 12:00 only"


def test_a_disabled_rule_does_nothing(state):
    doc = state.doctor("D1")
    doc.rules = [CaseMixRule("R1", "not_after", "counselling", "12:00",
                             enabled=False)]
    assert sess.case_mix_conflict(state, "D1", MON, "counselling",
                                  "14:00", "14:45") is None


def test_rules_only_apply_to_their_own_visit_type(state):
    doc = state.doctor("D1")
    doc.rules = [CaseMixRule("R1", "not_after", "counselling", "12:00")]
    assert sess.case_mix_conflict(state, "D1", MON, "follow_up",
                                  "14:00", "14:10") is None


def test_booking_refuses_with_the_rule_in_plain_words(state):
    doc = state.doctor("D1")
    doc.rules = [CaseMixRule("R1", "max_consecutive", "new_case", "2")]
    _booked(state, "A1", "P1", "09:00", "09:30", "new_case")
    _booked(state, "A2", "P2", "09:30", "10:00", "new_case")
    r = _alloc(state).book_consult("P3", "D1", "10:00", "10:30", at="08:00",
                                   date=MON, visit_type="new_case")
    assert not r.success
    assert "no more than 2 new case visits in a row" in r.message


def test_rescheduling_an_appointment_does_not_count_itself(state):
    doc = state.doctor("D1")
    doc.rules = [CaseMixRule("R1", "max_consecutive", "new_case", "1")]
    a = _booked(state, "A1", "P1", "09:00", "09:30", "new_case")
    # moving A1 elsewhere must not trip the rule against its own old slot
    assert sess.case_mix_conflict(state, "D1", MON, "new_case",
                                  "11:00", "11:30", exclude=a.id) is None


# --------------------------------------------------------------------------- #
# Round trip
# --------------------------------------------------------------------------- #
def test_template_and_rules_survive_a_round_trip(state):
    doc = state.doctor("D1")
    _template(doc)
    doc.rules = [CaseMixRule("R1", "max_consecutive", "new_case", "3")]
    again = Doctor.from_dict(doc.to_dict())
    assert len(again.sessions) == 4
    assert again.sessions[0].kind == "clinic"
    assert again.sessions[0].days == ["mon", "wed"]
    assert again.rules[0].describe() == "no more than 3 new case visits in a row"


def test_week_plan_groups_by_weekday(state):
    _template(state.doctor("D1"))
    week = sess.week_plan(state, "D1")
    assert [b["kind"] for b in week["days"]["mon"]] == ["clinic", "lunch"]
    assert [b["kind"] for b in week["days"]["tue"]] == ["ward_round", "lunch"]
    assert [b["kind"] for b in week["days"]["fri"]] == ["lunch"]
