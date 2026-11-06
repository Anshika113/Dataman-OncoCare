"""Cross-day / day-boundary tests for the date-aware scheduling model.

These verify the one change that matters most: that every day-scoped query
(capacity, availability, no-show, overrun, leave expiry, proactive insights)
operates on the *correct* day, so a booking on Monday is validated against
Monday's load — not today's — and time math is right across midnight.

Run:  pytest -q
"""

from __future__ import annotations

import pytest

from engine import (
    SystemState, Doctor, ChemRoom, Drug, Patient, Appointment,
    AppointmentType, AppointmentStatus, RoomType, DoctorStatus, Severity,
    SlotRegistry, ConflictDetector, AppointmentAllocator, TimeWindow,
    handle_doctor_sick_leave, advance_clock,
)
from engine.timeutils import dt_key, add_days, overlaps_dt, norm_date, to_min
from engine.handlers import handle_no_show, expire_leaves
from engine.proactive import analyze
from engine.state import LeaveEntry


DAY0 = "2026-10-29"
DAY1 = "2026-10-30"
DAY2 = "2026-10-31"


@pytest.fixture
def state() -> SystemState:
    s = SystemState()
    s.active_day = DAY0
    s.doctors = {
        "D1": Doctor("D1", "Dr One", "hematology", 2, DoctorStatus.AVAILABLE,
                     ["hematology", "oncology"]),
        "D2": Doctor("D2", "Dr Two", "oncology", 2, DoctorStatus.AVAILABLE,
                     ["oncology", "hematology"]),
    }
    s.rooms = {
        "R1": ChemRoom("R1", "Infusion 1", RoomType.INFUSION_CHAIR,
                       ["pump", "monitor", "iv"]),
    }
    s.drugs = {
        "G1": Drug("G1", "AnytimeDrug", TimeWindow("08:00", "18:00"), 10,
                   ["pump"]),
    }
    s.patients = {
        "P1": Patient("P1", "Alice", "+1", 1),
        "P2": Patient("P2", "Bob", "+2", 3),
        "P3": Patient("P3", "Cid", "+3", 3),
    }
    return s


def _alloc(s):
    return AppointmentAllocator(s, SlotRegistry(s))


# --------------------------------------------------------------------------- #
# timeutils: date-aware primitives
# --------------------------------------------------------------------------- #
def test_dt_key_orders_across_days():
    # Monday 09:00 < Tuesday 08:00 < Tuesday 09:30
    assert dt_key(DAY0, "09:00") < dt_key(DAY1, "08:00") < dt_key(DAY1, "09:30")


def test_add_days_and_norm():
    assert add_days(DAY0, 1) == DAY1
    assert add_days(DAY0, 2) == DAY2
    assert norm_date(DAY0) == DAY0


def test_overlaps_dt_rejects_cross_day_same_time():
    # Same wall-clock slot on two different days never overlaps.
    assert not overlaps_dt(DAY0, "09:00", "09:30", DAY1, "09:00", "09:30")
    # Same day, same time, does overlap.
    assert overlaps_dt(DAY0, "09:00", "09:30", DAY0, "09:00", "09:30")


# --------------------------------------------------------------------------- #
# Capacity is per-day
# --------------------------------------------------------------------------- #
def test_daily_cap_is_per_day(state):
    alloc = _alloc(state)
    # Two back-to-back consults on DAY0 fill D1's cap of 2.
    r1 = alloc.book_consult("P1", "D1", "09:00", "09:30", at="08:50", date=DAY0)
    r2 = alloc.book_consult("P2", "D1", "09:30", "10:00", at="08:50", date=DAY0)
    assert r1.success and r2.success
    # A third on DAY0 hits the cap...
    r3 = alloc.book_consult("P3", "D1", "10:00", "10:30", at="08:50", date=DAY0)
    assert not r3.success
    # ...but the SAME doctor can take a new patient on the NEXT day.
    r4 = alloc.book_consult("P3", "D1", "09:00", "09:30", at="08:50", date=DAY1)
    assert r4.success


def test_active_appointments_day_scoped(state):
    state.appointments["A1"] = Appointment("A1", "P1", "D1", "09:00", "09:30",
                                           date=DAY0)
    state.appointments["A2"] = Appointment("A2", "P2", "D1", "09:00", "09:30",
                                           date=DAY1)
    assert len(state.active_appointments("D1", day=DAY0)) == 1
    assert len(state.active_appointments("D1", day=DAY1)) == 1
    assert state.doctor_appointment_count("D1", day=DAY0) == 1
    assert state.doctor_appointment_count("D1", day=DAY1) == 1


# --------------------------------------------------------------------------- #
# Conflict check is validated against the target day
# --------------------------------------------------------------------------- #
def test_conflict_check_uses_target_day(state):
    # D1 is full on DAY0 (cap 2).
    alloc = _alloc(state)
    alloc.book_consult("P1", "D1", "09:00", "09:30", at="08:50", date=DAY0)
    alloc.book_consult("P2", "D1", "09:30", "10:00", at="08:50", date=DAY0)
    reg = SlotRegistry(state)
    det = ConflictDetector(state, reg)
    # A new slot on DAY1 is fine (that day is empty)...
    ok = det.check("D1", None, None, "09:00", "09:30",
                   AppointmentType.CONSULT, date=DAY1)
    assert ok.ok
    # ...but on DAY0 it's at cap.
    bad = det.check("D1", None, None, "11:00", "11:30",
                    AppointmentType.CONSULT, date=DAY0)
    assert not bad.ok


# --------------------------------------------------------------------------- #
# No-show / overrun are correct across midnight
# --------------------------------------------------------------------------- #
def test_no_show_late_math_across_midnight(state):
    # A 17:00 booking on DAY0; the clock has rolled to 08:00 the next morning.
    state.active_day = DAY0
    a = Appointment("A1", "P1", "D1", "17:00", "17:30",
                    status=AppointmentStatus.BOOKED, date=DAY0)
    state.appointments["A1"] = a
    # 17:00 DAY0 -> 08:00 DAY1 is 15 hours = 900 min late (not a negative).
    # Absolute minutes = days*1440 + within-day minutes.
    def _abs(d, h):
        return dt_key(d, h)[0] * 1440 + dt_key(d, h)[1]
    late = _abs(DAY1, "08:00") - _abs(DAY0, "17:00")
    assert late == 900
    # advance_clock on DAY1 (the day the clock is running) fires the no-show.
    state.active_day = DAY1
    out = advance_clock(state, "08:00", no_show_min=15)
    assert "A1" in out["no_shows"]
    assert a.status == AppointmentStatus.NO_SHOW


def test_advance_clock_does_not_no_show_future_day(state):
    # A booking on TOMORROW must not be marked a no-show today.
    a = Appointment("A1", "P1", "D1", "09:00", "09:30",
                    status=AppointmentStatus.BOOKED, date=DAY1)
    state.appointments["A1"] = a
    state.active_day = DAY0
    # 09:00 "now" on DAY0 — the tomorrow 09:00 slot is in the future.
    out = advance_clock(state, "09:00", no_show_min=15)
    assert out["no_shows"] == []
    assert a.status == AppointmentStatus.BOOKED


# --------------------------------------------------------------------------- #
# Leave expiry is day-aware
# --------------------------------------------------------------------------- #
def test_leave_for_future_day_does_not_expire(state):
    # D1 takes a 10:00-12:00 leave for TOMORROW.
    l = LeaveEntry("LV1", start="10:00", end="12:00", reason="tomorrow",
                   date=DAY1, created_at="09:00")
    state.doctor("D1").leaves.append(l)
    state.doctor("D1").status = DoctorStatus.PARTIALLY_UNAVAILABLE
    # It is 13:00 today (DAY0). `now > end` (13:00 > 12:00) is true, but the
    # leave is for a future day so it must NOT expire.
    changed = expire_leaves(state, "13:00")
    assert "D1" not in changed
    assert not l.cancelled


def test_leave_same_day_expires_after_end(state):
    l = LeaveEntry("LV1", start="10:00", end="12:00", reason="lunch",
                   date=DAY0, created_at="09:00")
    state.doctor("D1").leaves.append(l)
    state.doctor("D1").status = DoctorStatus.PARTIALLY_UNAVAILABLE
    # 13:00 same day — past the leave end — it expires.
    changed = expire_leaves(state, "13:00")
    assert "D1" in changed
    assert l.cancelled
    assert state.doctor("D1").status == DoctorStatus.AVAILABLE


# --------------------------------------------------------------------------- #
# Sick leave only affects the active day's appointments
# --------------------------------------------------------------------------- #
def test_sick_leave_only_affects_active_day(state):
    # Two appointments for D1: one today (DAY0), one tomorrow (DAY1).
    state.appointments["A1"] = Appointment("A1", "P1", "D1", "14:00", "14:30",
                                           date=DAY0)
    state.appointments["A2"] = Appointment("A2", "P2", "D1", "14:00", "14:30",
                                           date=DAY1)
    # Doctor goes on sick leave now (13:00) on DAY0.
    r = handle_doctor_sick_leave(state, "D1", "13:00")
    assert r.success
    # Only today's appt was touched (moved or offered); tomorrow's is untouched.
    assert state.appointment("A2").slot_start == "14:00"
    assert state.appointment("A2").status == AppointmentStatus.BOOKED


# --------------------------------------------------------------------------- #
# Proactive insights are scoped to the active day
# --------------------------------------------------------------------------- #
def test_proactive_scoped_to_active_day(state):
    # Pack D1 on DAY1 (a future day). On DAY0 there is zero load.
    alloc = _alloc(state)
    alloc.book_consult("P1", "D1", "09:00", "09:30", at="08:50", date=DAY1)
    alloc.book_consult("P2", "D1", "09:30", "10:00", at="08:50", date=DAY1)

    # Looking at DAY0 (the active day): D1 should appear "free" (underutilised).
    state.active_day = DAY0
    insights0 = {i.resource_name for i in analyze(state, "08:45")}
    # ...and on DAY1 D1 is the busy one (near/at cap, not underutilised).
    state.active_day = DAY1
    insights1 = {i.resource_name for i in analyze(state, "08:45")}

    # The DAY0 analysis should flag Dr One as free; the DAY1 analysis should NOT
    # (he is near cap). This proves the analysers are day-scoped.
    free_insights = [i for i in analyze(state, "08:45")
                     if i.kind.value == "underutilised"]
    assert any(i.resource_name == "Dr One" for i in free_insights) is False  # DAY1: packed
    # Re-check on DAY0 explicitly:
    state.active_day = DAY0
    free0 = [i for i in analyze(state, "08:45")
             if i.kind.value == "underutilised" and i.resource_name == "Dr One"]
    assert len(free0) == 1
