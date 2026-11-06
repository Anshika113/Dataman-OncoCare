"""Tests for the pure proactive operations engine (``analyze``).

Run:  pytest -q tests/test_proactive.py
"""

from __future__ import annotations

import pytest

from engine import (
    SystemState, Doctor, ChemRoom, Drug, Patient, Appointment,
    AppointmentType, AppointmentStatus, RoomType, DoctorStatus, Severity,
    TimeWindow, Emergency,
    analyze, InsightKind, InsightSeverity,
)


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #
def _base_state(d1_cap: int = 20, d2_cap: int = 20) -> SystemState:
    s = SystemState()
    s.doctors = {
        "D1": Doctor("D1", "Dr One", "hematology", d1_cap,
                     DoctorStatus.AVAILABLE, ["hematology", "oncology"]),
        "D2": Doctor("D2", "Dr Two", "oncology", d2_cap,
                     DoctorStatus.AVAILABLE, ["oncology", "hematology"]),
    }
    s.rooms = {
        "R1": ChemRoom("R1", "Infusion 1", RoomType.INFUSION_CHAIR,
                       ["pump", "monitor", "iv"]),
        "R2": ChemRoom("R2", "Infusion 2", RoomType.INFUSION_CHAIR,
                       ["pump", "monitor", "iv", "oxygen"]),
    }
    s.drugs = {
        "G1": Drug("G1", "MorningDrug", TimeWindow("08:00", "12:00"), 15,
                   ["pump", "monitor"]),
        "G2": Drug("G2", "AnytimeDrug", TimeWindow("08:00", "18:00"), 10,
                   ["pump"]),
    }
    for i in range(1, 6):
        s.patients[f"P{i}"] = Patient(f"P{i}", f"Pat{i}", f"+{i}", 1)
    return s


def _by_kind(insights, kind: InsightKind):
    return [i for i in insights if i.kind == kind]


def _rank(sev: InsightSeverity) -> int:
    return {InsightSeverity.CRITICAL: 0, InsightSeverity.WARNING: 1,
            InsightSeverity.INFO: 2}[sev]


# --------------------------------------------------------------------------- #
# Calm state / shape
# --------------------------------------------------------------------------- #
def test_empty_state_no_insights():
    assert analyze(SystemState(), "09:00") == []


def test_calm_state_only_info():
    s = _base_state()
    s.appointments["A1"] = Appointment("A1", "P1", "D1", "11:00", "11:30")
    ins = analyze(s, "09:00")
    # plenty of capacity, nothing packed, nothing late -> no warnings/alerts
    assert all(i.severity == InsightSeverity.INFO for i in ins)
    assert not _by_kind(ins, InsightKind.QUEUE_OVERFLOW)
    assert not _by_kind(ins, InsightKind.DOCTOR_CAP)
    assert not _by_kind(ins, InsightKind.WAIT_TIME)


def test_insight_to_dict_shape():
    s = _base_state()
    s.appointments["A1"] = Appointment("A1", "P1", "D1", "09:00", "09:30")
    ins = analyze(s, "09:20")
    assert ins  # at least a wait_time
    d = ins[0].to_dict()
    for key in ("kind", "severity", "title", "detail", "action",
                "resource_id", "resource_name", "affected", "metric",
                "horizon_min"):
        assert key in d


def test_analyze_is_pure():
    s = _base_state()
    s.appointments["A1"] = Appointment("A1", "P1", "D1", "09:00", "09:30")
    before = {a.id: (a.status, a.slot_start, a.slot_end, a.doctor_id)
              for a in s.appointments.values()}
    analyze(s, "09:20")
    after = {a.id: (a.status, a.slot_start, a.slot_end, a.doctor_id)
             for a in s.appointments.values()}
    assert before == after
    assert len(s.notifications) == 0  # analysis never notifies


# --------------------------------------------------------------------------- #
# WAIT_TIME
# --------------------------------------------------------------------------- #
def test_wait_time_late_booked_warning():
    s = _base_state()
    s.appointments["A1"] = Appointment("A1", "P1", "D1", "09:00", "09:30")
    ins = _by_kind(analyze(s, "09:20"), InsightKind.WAIT_TIME)
    assert len(ins) == 1
    assert ins[0].severity == InsightSeverity.WARNING
    assert ins[0].metric["late_min"] == 20
    assert ins[0].resource_id == "D1"


def test_wait_time_late_booked_critical():
    s = _base_state()
    s.appointments["A1"] = Appointment("A1", "P1", "D1", "09:00", "09:30")
    ins = _by_kind(analyze(s, "09:40"), InsightKind.WAIT_TIME)
    assert ins[0].severity == InsightSeverity.CRITICAL
    assert ins[0].metric["late_min"] == 40


def test_wait_time_checked_in_suppressed():
    s = _base_state()
    s.appointments["A1"] = Appointment("A1", "P1", "D1", "09:00", "09:30",
                                       checked_in=True)
    assert not _by_kind(analyze(s, "09:40"), InsightKind.WAIT_TIME)


def test_wait_time_within_threshold_no_insight():
    s = _base_state()
    s.appointments["A1"] = Appointment("A1", "P1", "D1", "09:00", "09:30")
    assert not _by_kind(analyze(s, "09:10"), InsightKind.WAIT_TIME)


def test_emergency_waiting_warning():
    s = _base_state()
    s.emergencies["E1"] = Emergency("E1", "P1", Severity.HIGH, "09:00")
    ins = _by_kind(analyze(s, "09:15"), InsightKind.WAIT_TIME)
    assert len(ins) == 1
    assert ins[0].severity == InsightSeverity.WARNING
    assert ins[0].metric["waited_min"] == 15


def test_emergency_waiting_critical_by_severity():
    s = _base_state()
    s.emergencies["E1"] = Emergency("E1", "P1", Severity.CRITICAL, "09:00")
    # only 12 min waited (< 20) but severity 5 -> critical
    ins = _by_kind(analyze(s, "09:12"), InsightKind.WAIT_TIME)
    assert ins[0].severity == InsightSeverity.CRITICAL


# --------------------------------------------------------------------------- #
# QUEUE_OVERFLOW (no slack)
# --------------------------------------------------------------------------- #
def test_queue_overflow_no_slack():
    s = _base_state()
    s.appointments["A1"] = Appointment("A1", "P1", "D1", "09:00", "09:30")
    s.appointments["A2"] = Appointment("A2", "P2", "D1", "09:30", "10:00")
    ins = _by_kind(analyze(s, "09:00", horizon_min=60),
                   InsightKind.QUEUE_OVERFLOW)
    # D1 is packed (no free gap); D2 is not
    assert [i.resource_id for i in ins] == ["D1"]
    assert ins[0].severity == InsightSeverity.WARNING
    assert ins[0].metric["sessions"] == 2


def test_queue_overflow_critical_when_overrun_feeds():
    s = _base_state()
    s.appointments["A1"] = Appointment("A1", "P1", "D1", "09:00", "09:30",
                                       status=AppointmentStatus.OVERRUN)
    s.appointments["A2"] = Appointment("A2", "P2", "D1", "09:30", "10:00")
    ins = _by_kind(analyze(s, "09:00", horizon_min=60),
                   InsightKind.QUEUE_OVERFLOW)
    assert ins[0].severity == InsightSeverity.CRITICAL
    assert ins[0].metric["overrun_feeding"] is True


def test_queue_overflow_room_packed():
    s = _base_state()
    s.appointments["A1"] = Appointment("A1", "P1", "D1", "09:00", "09:30",
                                       AppointmentType.CHEMO,
                                       AppointmentStatus.BOOKED, "R1", "G2")
    s.appointments["A2"] = Appointment("A2", "P2", "D2", "09:30", "10:00",
                                       AppointmentType.CHEMO,
                                       AppointmentStatus.BOOKED, "R1", "G2")
    ins = _by_kind(analyze(s, "09:00", horizon_min=60),
                   InsightKind.QUEUE_OVERFLOW)
    room_ins = [i for i in ins if i.resource_id == "R1"]
    assert room_ins and room_ins[0].severity == InsightSeverity.WARNING


def test_queue_overflow_not_triggered_with_slack():
    # a single session leaves plenty of slack -> no bottleneck
    s = _base_state()
    s.appointments["A1"] = Appointment("A1", "P1", "D1", "09:00", "09:30")
    assert not _by_kind(analyze(s, "09:00", horizon_min=60),
                        InsightKind.QUEUE_OVERFLOW)


# --------------------------------------------------------------------------- #
# DOCTOR_CAP
# --------------------------------------------------------------------------- #
def test_doctor_capacity_at_cap():
    s = _base_state(d1_cap=3)
    for i, (a, b) in enumerate([("09:00", "09:30"), ("09:30", "10:00"),
                                ("10:00", "10:30")]):
        s.appointments[f"A{i}"] = Appointment(f"A{i}", f"P{i+1}", "D1", a, b)
    ins = _by_kind(analyze(s, "08:00"), InsightKind.DOCTOR_CAP)
    d1 = [i for i in ins if i.resource_id == "D1"]
    assert d1 and d1[0].severity == InsightSeverity.CRITICAL
    assert d1[0].metric["remaining"] == 0


def test_doctor_capacity_nearing_with_projection():
    s = _base_state(d1_cap=3)
    s.appointments["A1"] = Appointment("A1", "P1", "D1", "09:00", "09:30")
    s.appointments["A2"] = Appointment("A2", "P2", "D1", "09:30", "10:00")
    ins = [i for i in _by_kind(analyze(s, "08:00"), InsightKind.DOCTOR_CAP)
           if i.resource_id == "D1"]
    assert ins and ins[0].severity == InsightSeverity.WARNING
    assert ins[0].metric["remaining"] == 1
    assert ins[0].metric["full_by"] == "09:30"


def test_doctor_capacity_healthy_no_insight():
    s = _base_state(d1_cap=20)
    s.appointments["A1"] = Appointment("A1", "P1", "D1", "09:00", "09:30")
    assert not [i for i in _by_kind(analyze(s, "08:00"),
                                    InsightKind.DOCTOR_CAP)
                if i.resource_id == "D1"]


# --------------------------------------------------------------------------- #
# DRUG_WINDOW
# --------------------------------------------------------------------------- #
def test_drug_window_closing_warning():
    s = _base_state()
    s.appointments["A1"] = Appointment("A1", "P1", "D1", "11:00", "11:30",
                                       AppointmentType.CHEMO,
                                       AppointmentStatus.BOOKED, "R1", "G1")
    # MorningDrug window 08:00-12:00; horizon_end 12:00 -> at risk, still inside
    ins = _by_kind(analyze(s, "11:00", horizon_min=60),
                   InsightKind.DRUG_WINDOW)
    assert ins and ins[0].severity == InsightSeverity.WARNING
    assert ins[0].resource_name == "MorningDrug"


def test_drug_window_breached_critical():
    s = _base_state()
    s.appointments["A1"] = Appointment("A1", "P1", "D1", "13:00", "13:30",
                                       AppointmentType.CHEMO,
                                       AppointmentStatus.BOOKED, "R1", "G1")
    # 13:00 is outside the 08:00-12:00 window -> critical
    ins = _by_kind(analyze(s, "12:30", horizon_min=60),
                   InsightKind.DRUG_WINDOW)
    assert ins and ins[0].severity == InsightSeverity.CRITICAL


def test_drug_window_full_day_not_flagged():
    s = _base_state()
    s.appointments["A1"] = Appointment("A1", "P1", "D1", "11:00", "11:30",
                                       AppointmentType.CHEMO,
                                       AppointmentStatus.BOOKED, "R1", "G2")
    # AnytimeDrug window ends 18:00, well past the horizon -> no insight
    assert not _by_kind(analyze(s, "11:00", horizon_min=60),
                        InsightKind.DRUG_WINDOW)


# --------------------------------------------------------------------------- #
# LOAD_REBALANCE
# --------------------------------------------------------------------------- #
def test_load_rebalance_suggests_move():
    s = _base_state()
    # D1 fully packed the next hour; D2 idle and specialty-compatible
    s.appointments["A1"] = Appointment("A1", "P1", "D1", "09:00", "09:30")
    s.appointments["A2"] = Appointment("A2", "P2", "D1", "09:30", "10:00")
    ins = _by_kind(analyze(s, "09:00", horizon_min=60),
                   InsightKind.LOAD_REBALANCE)
    assert len(ins) == 1
    assert ins[0].metric["busy"] == "D1"
    assert ins[0].metric["idle"] == "D2"
    assert ins[0].metric["move_appt"] == "A1"
    # action is human-readable (names), metric carries the ids
    assert "Dr One" in ins[0].action and "Dr Two" in ins[0].action


def test_load_rebalance_not_when_no_idle():
    # both doctors packed -> no one to rebalance onto
    s = _base_state()
    for d, p in (("D1", "P1"), ("D2", "P2")):
        s.appointments[f"B{d}1"] = Appointment(f"B{d}1", p, d, "09:00", "09:30")
        s.appointments[f"B{d}2"] = Appointment(f"B{d}2", f"P{3}", d,
                                               "09:30", "10:00")
    assert not _by_kind(analyze(s, "09:00", horizon_min=60),
                        InsightKind.LOAD_REBALANCE)


# --------------------------------------------------------------------------- #
# UNDERUTILISED
# --------------------------------------------------------------------------- #
def test_underutilised_free_doctor_and_room():
    s = _base_state()
    ins = analyze(s, "09:00", horizon_min=60)
    under = _by_kind(ins, InsightKind.UNDERUTILISED)
    # everyone idle -> all doctors + chemo rooms flagged as spare capacity
    assert {i.resource_id for i in under} == {"D1", "D2", "R1", "R2"}
    assert all(i.severity == InsightSeverity.INFO for i in under)


# --------------------------------------------------------------------------- #
# Sorting
# --------------------------------------------------------------------------- #
def test_sorted_most_severe_first():
    s = _base_state(d1_cap=1, d2_cap=3)
    s.appointments["A1"] = Appointment("A1", "P1", "D1", "09:00", "09:30")   # D1 at cap -> critical
    s.appointments["A2"] = Appointment("A2", "P2", "D2", "09:00", "09:30")   # D2 nearing -> warning
    s.appointments["A3"] = Appointment("A3", "P3", "D2", "09:30", "10:00")
    ins = analyze(s, "08:00")
    ranks = [_rank(i.severity) for i in ins]
    assert ranks == sorted(ranks)          # non-decreasing rank (critical first)
    assert ins[0].severity == InsightSeverity.CRITICAL
