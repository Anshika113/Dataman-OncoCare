"""Unit + integration tests for the pure scheduling engine.

Run:  pytest -q
"""

from __future__ import annotations

import pytest

from engine import (
    SystemState, Doctor, ChemRoom, Drug, Patient, Appointment,
    AppointmentType, AppointmentStatus, RoomType, DoctorStatus, Severity,
    SlotRegistry, ConflictDetector, AppointmentAllocator, TimeWindow,
    handle_doctor_sick_leave, handle_chemo_overrun, handle_room_breakdown,
    handle_no_show, handle_emergency_pair, advance_clock,
    resolve_emergencies, Emergency, to_min, add_min,
)


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture
def state() -> SystemState:
    s = SystemState()
    s.doctors = {
        "D1": Doctor("D1", "Dr One", "hematology", 20, DoctorStatus.AVAILABLE,
                     ["hematology", "oncology"]),
        "D2": Doctor("D2", "Dr Two", "oncology", 20, DoctorStatus.AVAILABLE,
                     ["oncology", "hematology"]),
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
    s.patients = {
        "P1": Patient("P1", "Alice", "+1", 1),
        "P2": Patient("P2", "Bob", "+2", 3),
    }
    return s


def _alloc(s):
    reg = SlotRegistry(s)
    return AppointmentAllocator(s, reg)


# --------------------------------------------------------------------------- #
# Phase 1: slot / conflict / chemo allocation
# --------------------------------------------------------------------------- #
def test_slot_generation(state):
    reg = SlotRegistry(state, "08:00", "09:00", 30)
    slots = reg.generate_day("08:00", "09:00", 30)
    assert slots == [("08:00", "08:30"), ("08:30", "09:00")]


def test_doctor_slot_becomes_busy(state):
    a = Appointment("A1", "P1", "D1", "09:00", "09:30")
    state.appointments["A1"] = a
    reg = SlotRegistry(state)
    assert not reg.is_doctor_slot_free("D1", "09:00", "09:30")
    assert reg.is_doctor_slot_free("D1", "09:30", "10:00")


def test_buffer_blocks_adjacent_booking(state):
    a = Appointment("A1", "P1", "D1", "09:00", "09:30",
                    buffer_before=15, buffer_after=15)
    state.appointments["A1"] = a
    reg = SlotRegistry(state)
    # well before the pre-buffer -> free
    assert reg.is_doctor_slot_free("D1", "08:00", "08:30")
    # 08:45-09:00 starts inside the pre-buffer zone -> blocked
    assert not reg.is_doctor_slot_free("D1", "08:45", "09:00")
    # 09:30-09:45 sits inside the post-buffer zone -> blocked
    assert not reg.is_doctor_slot_free("D1", "09:30", "09:45")
    # 09:45-10:00 is clear of the buffer -> free
    assert reg.is_doctor_slot_free("D1", "09:45", "10:00")
    # 10:00-10:30 well after -> free
    assert reg.is_doctor_slot_free("D1", "10:00", "10:30")


def test_drug_time_window_enforced(state):
    det = ConflictDetector(state, SlotRegistry(state))
    # MorningDrug only 08:00-12:00; 13:00 is outside
    v = det.check("D1", "R1", "G1", "13:00", "13:30", AppointmentType.CHEMO)
    assert not v.ok
    assert any("only allowed" in r for r in v.reasons)
    # 10:00 is inside the window
    v2 = det.check("D1", "R1", "G1", "10:00", "10:30", AppointmentType.CHEMO)
    assert v2.ok


def test_room_equipment_required(state):
    # G1 requires pump+monitor; a room missing them must be rejected
    state.rooms["R0"] = ChemRoom("R0", "Bare", RoomType.INFUSION_CHAIR, [])
    det = ConflictDetector(state, SlotRegistry(state))
    v = det.check("D1", "R0", "G1", "10:00", "10:30", AppointmentType.CHEMO)
    assert not v.ok
    assert any("lacks required equipment" in r for r in v.reasons)


def test_book_chemo_picks_valid_room(state):
    alloc = _alloc(state)
    r = alloc.book_chemo("P1", "D1", "G1", "09:00", at="08:00")
    assert r.success, r.message
    # the chosen room must have the equipment and the slot must be inside window
    appt = [a for a in state.appointments.values()
            if a.doctor_id == "D1" and a.drug_id == "G1"][0]
    assert state.room(appt.room_id) is not None
    assert state.drug("G1").time_window.contains(appt.slot_start)


def test_no_double_booking_same_slot(state):
    alloc = _alloc(state)
    r1 = alloc.book_consult("P1", "D1", "09:00", "09:30", at="08:00")
    r2 = alloc.book_consult("P2", "D1", "09:00", "09:30", at="08:00")
    assert r1.success
    assert not r2.success


# --------------------------------------------------------------------------- #
# Phase 2: emergency priority + two-at-once
# --------------------------------------------------------------------------- #
def test_priority_queue_orders_by_severity_then_subscore(state):
    from engine import build_queue
    state.emergencies = {
        "E1": Emergency("E1", "P1", Severity.LOW, "09:00"),
        "E2": Emergency("E2", "P2", Severity.CRITICAL, "09:00"),
    }
    order = [e.id for e in build_queue(state, "09:00")]
    assert order[0] == "E2"


def test_two_emergencies_different_doctors(state):
    e1 = Emergency("E1", "P1", Severity.HIGH, "09:00")
    e2 = Emergency("E2", "P2", Severity.HIGH, "09:00")
    state.emergencies["E1"] = e1
    state.emergencies["E2"] = e2
    r = handle_emergency_pair(state, "E1", "E2", "09:00")
    assert r.success
    assert r.data["different_doctors"] is True
    # distinct doctors assigned
    assert e1.assigned_doctor_id != e2.assigned_doctor_id


def test_two_emergencies_one_doctor_resolves_by_subscore(state):
    # only one doctor available
    state.doctors = {"D1": Doctor("D1", "Dr One", "hematology", 20,
                                  DoctorStatus.AVAILABLE, [])}
    e1 = Emergency("E1", "P1", Severity.CRITICAL, "09:00")
    e2 = Emergency("E2", "P2", Severity.HIGH, "09:00")
    state.emergencies["E1"] = e1
    state.emergencies["E2"] = e2
    r = handle_emergency_pair(state, "E1", "E2", "09:00")
    assert r.success
    assert r.data["different_doctors"] is False
    # critical gets the doctor, high waits
    assert e1.status == "assigned"
    assert e2.status == "waiting"


def test_emergency_resolution_assigns_free_doctor(state):
    state.emergencies["E1"] = Emergency("E1", "P1", Severity.URGENT, "09:00")
    r = resolve_emergencies(state, "09:00")
    assert r.success
    assert state.emergencies["E1"].status == "assigned"


# --------------------------------------------------------------------------- #
# Phase 3: edge cases
# --------------------------------------------------------------------------- #
def test_sick_leave_moves_future_appointments(state):
    # D1 has a future appointment
    a = Appointment("A1", "P1", "D1", "11:00", "11:30")
    state.appointments["A1"] = a
    r = handle_doctor_sick_leave(state, "D1", "10:00")
    assert r.success
    appt = state.appointment("A1")
    # must have been moved to a different doctor (D2 is backup-compatible)
    assert appt.doctor_id == "D2"
    assert appt.status == AppointmentStatus.RESCHEDULED
    assert state.doctor("D1").status == DoctorStatus.ON_LEAVE
    # patient notified
    assert any(n.patient_id == "P1" for n in state.notifications)


def test_sick_leave_past_appointments_untouched(state):
    a = Appointment("A1", "P1", "D1", "09:00", "09:30")
    state.appointments["A1"] = a
    handle_doctor_sick_leave(state, "D1", "10:00")
    # 09:00 is in the past relative to now=10:00 -> unchanged
    assert state.appointment("A1").doctor_id == "D1"


def test_overrun_within_grace_no_action(state):
    a = Appointment("A1", "P1", "D1", "09:00", "09:30", AppointmentType.CHEMO,
                    AppointmentStatus.ACTIVE, "R1", "G1")
    state.appointments["A1"] = a
    # only 5 min past end, grace is 15 -> no overrun yet
    r = handle_chemo_overrun(state, "A1", "09:35")
    assert r.action.value == "info"


def test_overrun_logs_and_cascades(state):
    a1 = Appointment("A1", "P1", "D1", "09:00", "09:30", AppointmentType.CHEMO,
                     AppointmentStatus.ACTIVE, "R1", "G1")
    a2 = Appointment("A2", "P2", "D1", "09:30", "10:00", AppointmentType.CHEMO,
                     AppointmentStatus.BOOKED, "R1", "G2")
    state.appointments["A1"] = a1
    state.appointments["A2"] = a2
    # 30 min past end, grace 15 -> overrun of 15 min
    r = handle_chemo_overrun(state, "A1", "10:00")
    assert r.action == "overrun_logged"
    assert state.appointment("A1").status == AppointmentStatus.OVERRUN
    # next appointment in R1 pushed to start after the overrun session ends
    # (A1 still running at 10:00 -> A2 cannot occupy R1 before then)
    assert to_min(state.appointment("A2").slot_start) >= to_min("10:00")
    assert r.data["next_pushed"] is True
    # overrun logged
    assert any(lg.kind == "overrun" for lg in state.logs)


def test_room_breakdown_reassigns_sessions(state):
    a1 = Appointment("A1", "P1", "D1", "10:00", "10:30", AppointmentType.CHEMO,
                     AppointmentStatus.BOOKED, "R1", "G2")
    state.appointments["A1"] = a1
    r = handle_room_breakdown(state, "R1", "09:00", "23:59")
    assert r.success
    assert state.room("R1").status.value == "unavailable"
    appt = state.appointment("A1")
    # reassigned to the other room
    assert appt.room_id == "R2"
    assert any(lg.kind == "breakdown" for lg in state.logs)


def test_no_show_releases_and_notifies_next(state):
    a1 = Appointment("A1", "P1", "D1", "09:00", "09:30")
    a2 = Appointment("A2", "P2", "D1", "09:30", "10:00")
    state.appointments["A1"] = a1
    state.appointments["A2"] = a2
    r = handle_no_show(state, "A1", "09:20", no_show_min=15)
    assert r.action == "slot_released"
    assert state.appointment("A1").status == AppointmentStatus.NO_SHOW
    # next patient (P2) notified they're up
    assert any(n.patient_id == "P2" and "You're up" in n.body
               for n in state.notifications)


def test_no_show_within_threshold_no_action(state):
    a1 = Appointment("A1", "P1", "D1", "09:00", "09:30")
    state.appointments["A1"] = a1
    r = handle_no_show(state, "A1", "09:10", no_show_min=15)
    assert r.action.value == "info"


def test_advance_clock_triggers_no_show_and_overrun(state):
    a1 = Appointment("A1", "P1", "D1", "08:30", "09:00")
    a2 = Appointment("A2", "P2", "D1", "09:00", "09:30", AppointmentType.CHEMO,
                     AppointmentStatus.ACTIVE, "R1", "G1")
    state.appointments["A1"] = a1
    state.appointments["A2"] = a2
    out = advance_clock(state, "09:20", no_show_min=15)
    assert "A1" in out["no_shows"]
    # at 09:20 A2 (chemo, ends 09:30) is not yet over -> no overrun
    assert "A2" not in out["overruns"]
    # at 10:00 A2 is 30 min past its 09:30 end (grace 15) -> overrun fires
    out2 = advance_clock(state, "10:00", no_show_min=15)
    assert "A2" in out2["overruns"]


# --------------------------------------------------------------------------- #
# G. Doctor availability / time-bounded leave
# --------------------------------------------------------------------------- #
def test_time_bounded_leave_blocks_only_that_window(state):
    from engine import handle_doctor_take_leave
    r = handle_doctor_take_leave(state, "D1", "08:00",
                                 start="10:00", end="12:00", reason="lunch")
    assert r.success
    doc = state.doctor("D1")
    assert doc.status.value == "partially_unavailable"
    reg = SlotRegistry(state)
    # 10:00-10:30 is inside the leave -> blocked
    assert not reg.is_doctor_slot_free("D1", "10:00", "10:30")
    # 12:30-13:00 is after the leave -> free
    assert reg.is_doctor_slot_free("D1", "12:30", "13:00")
    # 09:00-09:30 is before the leave -> free
    assert reg.is_doctor_slot_free("D1", "09:00", "09:30")


def test_cancel_leave_makes_doctor_available_again(state):
    from engine import handle_doctor_take_leave, handle_doctor_cancel_leave
    r1 = handle_doctor_take_leave(state, "D1", "08:00",
                                  start="10:00", end="12:00", reason="lunch")
    leave_id = state.doctor("D1").leaves[0].id
    r2 = handle_doctor_cancel_leave(state, "D1", "08:00", leave_id=leave_id)
    assert r2.success
    doc = state.doctor("D1")
    assert doc.status.value == "available"
    reg = SlotRegistry(state)
    assert reg.is_doctor_slot_free("D1", "10:00", "10:30")


def test_leave_auto_expires(state):
    from engine import handle_doctor_take_leave, expire_leaves
    handle_doctor_take_leave(state, "D1", "08:00",
                             start="10:00", end="12:00", reason="lunch")
    assert state.doctor("D1").status.value == "partially_unavailable"
    # at 13:00 the 10:00-12:00 leave has ended -> should expire
    changed = expire_leaves(state, "13:00")
    assert "D1" in changed
    assert state.doctor("D1").status.value == "available"


def test_full_day_leave_blocks_entire_day(state):
    from engine import handle_doctor_take_leave
    handle_doctor_take_leave(state, "D1", "08:00",
                             start="08:00", end="18:00", reason="sick",
                             full_day=True)
    doc = state.doctor("D1")
    assert doc.on_leave
    assert doc.status.value == "on_leave"
    reg = SlotRegistry(state)
    assert not reg.is_doctor_slot_free("D1", "09:00", "09:30")
    assert not reg.is_doctor_slot_free("D1", "15:00", "15:30")


def test_leave_reschedules_future_appointments(state):
    from engine import handle_doctor_take_leave
    a = Appointment("A1", "P1", "D1", "10:00", "10:30")
    state.appointments["A1"] = a
    state.patients["P1"] = Patient("P1", "Alice", "+1", 1)
    r = handle_doctor_take_leave(state, "D1", "09:00",
                                 start="10:00", end="12:00", reason="lunch")
    assert r.success
    # the 10:00 appointment falls in the window -> moved to backup doctor D2
    assert state.appointment("A1").doctor_id == "D2"
    assert state.doctor("D1").status.value == "partially_unavailable"


# --------------------------------------------------------------------------- #
# Persistence round-trip
# --------------------------------------------------------------------------- #
def test_excel_round_trip(tmp_path):
    from storage.excel_store import Store
    from storage.seed import build
    p = build(str(tmp_path / "care.xlsx"))
    s = Store(p)
    s.state.doctor("DOC-0001").daily_cap = 99
    # add a time-bounded leave and verify it survives the Excel round-trip
    from engine import handle_doctor_take_leave
    handle_doctor_take_leave(s.state, "DOC-0001", "08:00",
                             start="10:00", end="12:00", reason="lunch")
    s.save()
    s2 = Store(p)
    d2 = s2.state.doctor("DOC-0001")
    assert d2.daily_cap == 99
    assert len(d2.leaves) == 1
    assert d2.leaves[0].start == "10:00" and d2.leaves[0].end == "12:00"
    assert d2.status.value == "partially_unavailable"
    assert len(s2.state.appointments) == len(s.state.appointments)


# --------------------------------------------------------------------------- #
# H. Cancel appointment / restore room / emergency assign + complete
# --------------------------------------------------------------------------- #
def test_cancel_appointment_releases_slot(state):
    from engine import handle_cancel_appointment
    a = Appointment("A1", "P1", "D1", "10:00", "10:30")
    state.appointments["A1"] = a
    reg = SlotRegistry(state)
    assert not reg.is_doctor_slot_free("D1", "10:00", "10:30")
    r = handle_cancel_appointment(state, "A1", "09:00", reason="patient request")
    assert r.success and r.action.value == "cancelled"
    assert state.appointment("A1").status == AppointmentStatus.CANCELLED
    # slot freed again
    assert reg.is_doctor_slot_free("D1", "10:00", "10:30")


def test_cancel_rejects_active(state):
    from engine import handle_cancel_appointment
    a = Appointment("A1", "P1", "D1", "10:00", "10:30",
                    status=AppointmentStatus.ACTIVE)
    state.appointments["A1"] = a
    r = handle_cancel_appointment(state, "A1", "10:00")
    assert not r.success


def test_cancel_missing(state):
    from engine import handle_cancel_appointment
    r = handle_cancel_appointment(state, "NOPE", "09:00")
    assert not r.success


def test_room_restore(state):
    from engine import handle_room_breakdown, handle_room_restore
    handle_room_breakdown(state, "R1", "09:00", available_until="23:59")
    assert state.room("R1").status.value == "unavailable"
    r = handle_room_restore(state, "R1", "10:00", reason="fixed")
    assert r.success and r.action.value == "room_restored"
    assert state.room("R1").status.value == "available"
    assert state.room("R1").available_until == ""


def test_emergency_assign_and_complete(state):
    from engine import handle_emergency_assign, handle_emergency_complete
    em = Emergency("E1", "P1", Severity(4), "09:00")
    state.emergencies["E1"] = em
    r = handle_emergency_assign(state, "E1", "D2", "09:05")
    assert r.success and r.action.value == "emergency_assigned_manual"
    assert em.assigned_doctor_id == "D2" and em.status == "assigned"
    r2 = handle_emergency_complete(state, "E1", "09:30")
    assert r2.success and r2.action.value == "emergency_completed"
    assert em.status == "completed"
    # completing again is a no-op failure
    r3 = handle_emergency_complete(state, "E1", "09:40")
    assert not r3.success
