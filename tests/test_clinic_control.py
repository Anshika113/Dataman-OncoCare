"""The doctor's control strip, and the explain/undo trail behind it.

Covers Bucket B. The guarantees under test are the ones that make this
"help, don't replace": a doctor's action touches their own list only, every
change records what happened and why, and undo refuses rather than guessing
once the world has moved on.
"""

from __future__ import annotations

import pytest

from engine import (
    SystemState, Doctor, ChemRoom, Patient, Appointment, AppointmentType,
    AppointmentStatus, DoctorStatus, RoomType, SlotRegistry,
    AppointmentAllocator, actions as act, clinic_control as ctl,
)


@pytest.fixture
def state() -> SystemState:
    s = SystemState()
    s.doctors = {
        "D1": Doctor("D1", "Dr One", "oncology", 20, DoctorStatus.AVAILABLE,
                     ["oncology"]),
        "D2": Doctor("D2", "Dr Two", "oncology", 20, DoctorStatus.AVAILABLE,
                     ["oncology"]),
        "D3": Doctor("D3", "Dr Three", "radiology", 20, DoctorStatus.AVAILABLE,
                     ["radiology"]),
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


def _alloc(s):
    return AppointmentAllocator(s, SlotRegistry(s))


# --------------------------------------------------------------------------- #
# Extend
# --------------------------------------------------------------------------- #
def test_extend_pushes_only_this_doctors_later_patients(state):
    _appt(state, "A1", "P1", "D1", "10:00", "10:30")
    _appt(state, "A2", "P2", "D1", "10:30", "11:00")
    _appt(state, "A3", "P3", "D2", "10:30", "11:00")   # another doctor

    r = ctl.extend(state, "A1", 15, now="10:20", by="amina")
    assert r.success
    assert state.appointment("A1").slot_end == "10:45"
    assert state.appointment("A2").slot_start == "10:45"      # pushed
    assert state.appointment("A3").slot_start == "10:30"      # untouched


def test_extend_does_not_move_earlier_patients(state):
    _appt(state, "A0", "P3", "D1", "09:00", "09:30")
    _appt(state, "A1", "P1", "D1", "10:00", "10:30")
    ctl.extend(state, "A1", 15, now="10:20")
    assert state.appointment("A0").slot_start == "09:00"


def test_extend_warns_when_the_day_runs_over(state):
    _appt(state, "A1", "P1", "D1", "17:00", "17:30")
    _appt(state, "A2", "P2", "D1", "17:30", "18:00")
    r = ctl.extend(state, "A1", 30, now="17:10")
    assert r.success
    assert "after 18:00" in r.message
    assert r.data["past_day_end"]


def test_extend_rejects_a_silly_duration(state):
    _appt(state, "A1", "P1", "D1", "10:00", "10:30")
    assert not ctl.extend(state, "A1", 0, now="10:00").success
    assert not ctl.extend(state, "A1", 999, now="10:00").success


def test_extend_notifies_the_patients_who_were_pushed(state):
    _appt(state, "A1", "P1", "D1", "10:00", "10:30")
    _appt(state, "A2", "P2", "D1", "10:30", "11:00")
    before = len(state.notifications)
    ctl.extend(state, "A1", 15, now="10:20")
    assert len(state.notifications) == before + 1
    assert state.notifications[-1].patient_id == "P2"


# --------------------------------------------------------------------------- #
# Pull forward
# --------------------------------------------------------------------------- #
def test_pull_forward_prefers_a_patient_who_has_arrived(state):
    _appt(state, "A1", "P1", "D1", "11:00", "11:30")
    _appt(state, "A2", "P2", "D1", "11:30", "12:00",
          checked_in=True, checked_in_at="10:15")
    r = ctl.pull_forward(state, "D1", now="10:30")
    assert r.success
    assert state.appointment("A2").slot_start == "10:30"
    assert state.appointment("A1").slot_start == "11:00"


def test_pull_forward_says_so_when_nobody_has_arrived(state):
    _appt(state, "A1", "P1", "D1", "11:00", "11:30")
    r = ctl.pull_forward(state, "D1", now="10:30")
    assert r.success
    assert "not checked in" in r.message


def test_pull_forward_with_an_empty_list(state):
    r = ctl.pull_forward(state, "D1", now="10:30")
    assert not r.success
    assert "nobody left" in r.message


def test_pull_forward_refuses_when_there_is_no_earlier_gap(state):
    _appt(state, "A0", "P3", "D1", "10:30", "11:00")
    _appt(state, "A1", "P1", "D1", "11:00", "11:30", checked_in=True)
    r = ctl.pull_forward(state, "D1", now="10:30")
    assert not r.success
    assert "no earlier gap" in r.message


# --------------------------------------------------------------------------- #
# Swap
# --------------------------------------------------------------------------- #
def test_swap_exchanges_two_of_my_own_slots(state):
    _appt(state, "A1", "P1", "D1", "10:00", "10:30")
    _appt(state, "A2", "P2", "D1", "11:00", "11:30")
    assert ctl.swap(state, "A1", "A2", now="09:50").success
    assert state.appointment("A1").slot_start == "11:00"
    assert state.appointment("A2").slot_start == "10:00"


def test_swap_refuses_across_doctors(state):
    _appt(state, "A1", "P1", "D1", "10:00", "10:30")
    _appt(state, "A2", "P2", "D2", "11:00", "11:30")
    r = ctl.swap(state, "A1", "A2", now="09:50")
    assert not r.success
    assert "same doctor" in r.message


def test_swap_refuses_different_lengths(state):
    _appt(state, "A1", "P1", "D1", "10:00", "10:30")
    _appt(state, "A2", "P2", "D1", "11:00", "11:10")
    r = ctl.swap(state, "A1", "A2", now="09:50")
    assert not r.success
    assert "different lengths" in r.message


# --------------------------------------------------------------------------- #
# Hand off
# --------------------------------------------------------------------------- #
def test_hand_off_keeps_the_time_when_the_colleague_is_free(state):
    _appt(state, "A1", "P1", "D1", "10:00", "10:30")
    r = ctl.hand_off(state, "A1", "D2", now="09:50", reason="called away")
    assert r.success
    assert state.appointment("A1").doctor_id == "D2"
    assert state.appointment("A1").slot_start == "10:00"
    assert r.data["moved"] is False


def test_hand_off_moves_the_time_when_the_colleague_is_busy(state):
    _appt(state, "A1", "P1", "D1", "10:00", "10:30")
    _appt(state, "A2", "P2", "D2", "10:00", "10:30")
    r = ctl.hand_off(state, "A1", "D2", now="09:50")
    assert r.success
    assert state.appointment("A1").slot_start != "10:00"
    assert r.data["moved"] is True


def test_hand_off_refuses_an_incompatible_specialty(state):
    _appt(state, "A1", "P1", "D1", "10:00", "10:30")
    r = ctl.hand_off(state, "A1", "D3", now="09:50")
    assert not r.success
    assert "not a listed cover" in r.message


def test_hand_off_refuses_a_doctor_on_leave(state):
    state.doctors["D2"].status = DoctorStatus.ON_LEAVE
    _appt(state, "A1", "P1", "D1", "10:00", "10:30")
    r = ctl.hand_off(state, "A1", "D2", now="09:50")
    assert not r.success
    assert "on leave" in r.message


def test_hand_off_respects_the_daily_cap(state):
    state.doctors["D2"].daily_cap = 1
    _appt(state, "A0", "P3", "D2", "09:00", "09:30")
    _appt(state, "A1", "P1", "D1", "10:00", "10:30")
    r = ctl.hand_off(state, "A1", "D2", now="09:50")
    assert not r.success
    assert "daily cap" in r.message


# --------------------------------------------------------------------------- #
# Close list
# --------------------------------------------------------------------------- #
def test_close_list_plans_before_it_moves_anyone(state):
    _appt(state, "A1", "P1", "D1", "14:00", "14:30")
    r = ctl.close_list(state, "D1", "13:00", now="12:00", allocator=_alloc(state))
    assert r.success
    assert r.data["applied"] is False
    assert state.appointment("A1").doctor_id == "D1"      # nothing moved yet
    assert r.data["plan"][0]["to_doctor_name"] == "Dr Two"


def test_close_list_applies_and_rehomes(state):
    _appt(state, "A1", "P1", "D1", "14:00", "14:30")
    r = ctl.close_list(state, "D1", "13:00", now="12:00",
                       allocator=_alloc(state), dry_run=False)
    assert r.success
    assert state.appointment("A1").doctor_id == "D2"


def test_close_list_reports_who_it_could_not_cover(state):
    state.doctors["D2"].status = DoctorStatus.ON_LEAVE
    _appt(state, "A1", "P1", "D1", "14:00", "14:30")
    r = ctl.close_list(state, "D1", "13:00", now="12:00", allocator=_alloc(state))
    assert r.data["uncovered"]
    assert r.data["uncovered"][0]["patient_name"] == "Asha"


def test_close_list_leaves_the_morning_alone(state):
    _appt(state, "A1", "P1", "D1", "09:00", "09:30")
    r = ctl.close_list(state, "D1", "13:00", now="08:00", allocator=_alloc(state))
    assert r.success
    assert r.data["plan"] == []


# --------------------------------------------------------------------------- #
# Explain + undo
# --------------------------------------------------------------------------- #
def test_every_action_records_what_and_why(state):
    _appt(state, "A1", "P1", "D1", "10:00", "10:30")
    _appt(state, "A2", "P2", "D1", "10:30", "11:00")
    ctl.extend(state, "A1", 15, now="10:20", by="amina")
    rows = act.recent(state, "D1")
    assert len(rows) == 1
    assert rows[0]["by"] == "amina"
    assert "extended by 15 min" in rows[0]["summary"]
    assert rows[0]["why"]
    assert rows[0]["reversible"] is True


def test_undo_restores_everything_the_action_moved(state):
    _appt(state, "A1", "P1", "D1", "10:00", "10:30")
    _appt(state, "A2", "P2", "D1", "10:30", "11:00")
    r = ctl.extend(state, "A1", 15, now="10:20")
    assert act.undo(state, r.data["action_id"], now="10:25").success
    assert state.appointment("A1").slot_end == "10:30"
    assert state.appointment("A2").slot_start == "10:30"


def test_undo_is_refused_twice(state):
    _appt(state, "A1", "P1", "D1", "10:00", "10:30")
    _appt(state, "A2", "P2", "D1", "10:30", "11:00")
    r = ctl.extend(state, "A1", 15, now="10:20")
    act.undo(state, r.data["action_id"], now="10:25")
    assert not act.undo(state, r.data["action_id"], now="10:26").success


def test_undo_refused_once_the_patient_has_been_seen(state):
    _appt(state, "A1", "P1", "D1", "10:00", "10:30")
    _appt(state, "A2", "P2", "D1", "10:30", "11:00")
    r = ctl.extend(state, "A1", 15, now="10:20")
    state.appointment("A2").status = AppointmentStatus.VISITED
    out = act.undo(state, r.data["action_id"], now="11:30")
    assert not out.success
    assert "already been seen" in out.message


def test_undo_refused_when_a_later_change_overlaps(state):
    _appt(state, "A1", "P1", "D1", "10:00", "10:30")
    _appt(state, "A2", "P2", "D1", "10:30", "11:00")
    first = ctl.extend(state, "A1", 15, now="10:20")
    ctl.extend(state, "A1", 5, now="10:25")          # touches A1 and A2 again
    out = act.undo(state, first.data["action_id"], now="10:30")
    assert not out.success
    assert "happened afterwards" in out.message


def test_an_engine_reschedule_is_recorded_too(state):
    _appt(state, "A1", "P1", "D1", "10:00", "10:30")
    _alloc(state).reschedule("A1", None, None, "15:00", "15:30",
                             at="11:00", reason="doctor sick leave")
    rows = act.recent(state, "D1")
    assert rows
    assert rows[0]["kind"] == "reschedule"
    assert rows[0]["why"] == "doctor sick leave"
    assert rows[0]["by"] == "system"


def test_an_engine_reschedule_can_be_undone(state):
    _appt(state, "A1", "P1", "D1", "10:00", "10:30")
    _alloc(state).reschedule("A1", None, None, "15:00", "15:30",
                             at="11:00", reason="doctor sick leave")
    rows = act.recent(state, "D1")
    assert act.undo(state, rows[0]["id"], now="11:05").success
    assert state.appointment("A1").slot_start == "10:00"


def test_history_is_scoped_to_the_doctor_who_asks(state):
    _appt(state, "A1", "P1", "D1", "10:00", "10:30")
    _appt(state, "A2", "P2", "D2", "10:00", "10:30")
    ctl.extend(state, "A1", 10, now="09:50")
    ctl.extend(state, "A2", 10, now="09:51")
    assert len(act.recent(state, "D1")) == 1
    assert len(act.recent(state, "D2")) == 1
    assert len(act.recent(state)) == 2


# --------------------------------------------------------------------------- #
# The note that travels with the patient
# --------------------------------------------------------------------------- #
# A hand-off moves a name and a slot. Without this the receiving doctor has to
# telephone the colleague who handed over to learn anything about the patient,
# which is the manual coordination the brief is asking to remove.
def test_hand_off_carries_a_note_to_the_receiving_doctor(state):
    _appt(state, "A1", "P1", "D1", "10:00", "10:30")
    r = ctl.hand_off(state, "A1", "D2", now="09:50", reason="called away",
                     note="Counts back at 11:05, keen to go ahead today.")
    a = state.appointment("A1")
    assert r.success
    assert a.handoff_note == "Counts back at 11:05, keen to go ahead today."
    assert a.handoff_from == "Dr One"
    assert r.data["note"] == a.handoff_note


def test_the_note_is_separate_from_the_scheduling_reason(state):
    """They answer different questions and must not collapse into one field."""
    _appt(state, "A1", "P1", "D1", "10:00", "10:30")
    ctl.hand_off(state, "A1", "D2", now="09:50", reason="clinic overran",
                 note="Attendant is waiting outside.")
    a = state.appointment("A1")
    assert a.reschedule_reason == "clinic overran"
    assert a.handoff_note == "Attendant is waiting outside."


def test_a_hand_off_without_a_note_records_none(state):
    _appt(state, "A1", "P1", "D1", "10:00", "10:30")
    ctl.hand_off(state, "A1", "D2", now="09:50")
    a = state.appointment("A1")
    assert a.handoff_note == ""
    assert a.handoff_from == ""


def test_whitespace_is_not_a_note(state):
    _appt(state, "A1", "P1", "D1", "10:00", "10:30")
    ctl.hand_off(state, "A1", "D2", now="09:50", note="   \n  ")
    assert state.appointment("A1").handoff_note == ""


def test_a_very_long_note_is_cut_rather_than_refused(state):
    """Losing the tail of a note beats losing the hand-off."""
    _appt(state, "A1", "P1", "D1", "10:00", "10:30")
    r = ctl.hand_off(state, "A1", "D2", now="09:50", note="x" * 900)
    assert r.success
    assert len(state.appointment("A1").handoff_note) == 500


def test_a_failed_hand_off_leaves_no_note_behind(state):
    _appt(state, "A1", "P1", "D1", "10:00", "10:30")
    r = ctl.hand_off(state, "A1", "D9", now="09:50", note="should not persist")
    assert not r.success
    assert state.appointment("A1").handoff_note == ""


def test_the_note_reaches_the_doctors_own_day_list(state):
    from engine import context as ctx
    _appt(state, "A1", "P1", "D1", "10:00", "10:30")
    ctl.hand_off(state, "A1", "D2", now="09:50",
                 note="Bloods back at 11:05.")
    rows = ctx.day_context(state, "D2", state.active_day)
    row = next(r for r in rows if r["appointment_id"] == "A1")
    assert row["handoff_note"] == "Bloods back at 11:05."
    assert any("note from" in f["text"] for f in row["flags"])
