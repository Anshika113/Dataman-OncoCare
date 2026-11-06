"""Consent on outgoing messages, and context at the point of care.

Covers the two Bucket C items that were built. The promises under test: a
patient who did not agree is never messaged (and the message is visibly held,
not dropped), a message may not name the treatment unless they said it could,
and the context shown to a doctor is a reading of existing data — it never
invents a cycle for a visit that has none.
"""

from __future__ import annotations

import pytest

from engine import (
    SystemState, Doctor, ChemRoom, Drug, Patient, Appointment,
    AppointmentType, AppointmentStatus, RoomType, DoctorStatus, TimeWindow,
    NotificationStatus, privacy, context as ctx, investigations as iv,
)
from services.messaging import Dispatcher, LogDriver


class Recorder(LogDriver):
    def __init__(self):
        self.sent = []

    def send(self, to, channel, body):
        self.sent.append((to, channel, body))
        return True, "ok"


@pytest.fixture
def state() -> SystemState:
    s = SystemState()
    s.doctors = {"D1": Doctor("D1", "Dr Amina Khan", "hematology", 20,
                              DoctorStatus.AVAILABLE)}
    s.rooms = {"R1": ChemRoom("R1", "Infusion 2", RoomType.INFUSION_CHAIR,
                              ["pump", "monitor", "iv"])}
    s.drugs = {"G1": Drug("G1", "FOLFOX", TimeWindow("08:00", "18:00"), 10,
                          ["pump"])}
    s.patients = {
        "P1": Patient("P1", "Meera Pillai", "+91555001", 1,
                      diagnosis="colorectal carcinoma", stage="III"),
        "P2": Patient("P2", "Rahim Ullah", "+91555002", 1),
    }
    return s


# --------------------------------------------------------------------------- #
# Consent to be messaged at all
# --------------------------------------------------------------------------- #
def test_messaging_is_on_by_default(state):
    assert privacy.may_send(state.patient("P1")) is True


def test_a_patient_who_declined_is_never_messaged(state):
    state.patient("P1").consent_sms = False
    state.add_notification("P1", "sms", "Your appointment moved", "10:00")
    drv = Recorder()
    out = Dispatcher(drv).flush(state, "10:01")
    assert drv.sent == []
    assert out["blocked"] == 1
    assert out["sent"] == 0


def test_a_held_message_is_visible_not_dropped(state):
    state.patient("P1").consent_sms = False
    n = state.add_notification("P1", "sms", "Your appointment moved", "10:00")
    Dispatcher(Recorder()).flush(state, "10:01")
    assert state.notification(n.id).status == NotificationStatus.BLOCKED


def test_blocking_one_patient_does_not_block_another(state):
    state.patient("P1").consent_sms = False
    state.add_notification("P1", "sms", "a", "10:00")
    state.add_notification("P2", "sms", "b", "10:00")
    out = Dispatcher(Recorder()).flush(state, "10:01")
    assert out == {"sent": 1, "failed": 0, "blocked": 1, "scrubbed": 0,
                   "driver": "log"}


def test_the_desk_is_told_why(state):
    state.patient("P1").consent_sms = False
    why = privacy.blocked_reason(state.patient("P1"))
    assert "Meera Pillai" in why and "phone them" in why


# --------------------------------------------------------------------------- #
# Consent to name the treatment
# --------------------------------------------------------------------------- #
def test_naming_the_treatment_is_off_by_default(state):
    assert state.patient("P1").consent_name_treatment is False


def test_the_drug_name_is_removed(state):
    body = "Your FOLFOX session has moved to 15:30."
    out, changed = privacy.scrub(state, state.patient("P1"), body)
    assert changed is True
    assert "FOLFOX" not in out
    assert "15:30" in out


def test_the_diagnosis_is_removed(state):
    body = "Review for colorectal carcinoma at 11:00."
    out, _ = privacy.scrub(state, state.patient("P1"), body)
    assert "colorectal carcinoma" not in out


def test_the_word_chemotherapy_is_removed_whatever_the_drug(state):
    body = "Your chemotherapy with Dr Amina Khan has been rescheduled."
    out, _ = privacy.scrub(state, state.patient("P1"), body)
    assert "chemotherapy" not in out.lower()


def test_the_room_name_is_neutralised(state):
    body = "Please come to Infusion 2 at 10:00."
    out, _ = privacy.scrub(state, state.patient("P1"), body)
    assert "Infusion 2" not in out
    assert "day-care unit" in out


def test_consent_lets_the_message_through_unchanged(state):
    state.patient("P1").consent_name_treatment = True
    body = "Your FOLFOX session has moved to 15:30."
    out, changed = privacy.scrub(state, state.patient("P1"), body)
    assert out == body
    assert changed is False


def test_what_was_actually_sent_is_what_is_logged(state):
    n = state.add_notification("P1", "sms", "Your FOLFOX session moved", "10:00")
    drv = Recorder()
    Dispatcher(drv).flush(state, "10:01")
    assert "FOLFOX" not in drv.sent[0][2]
    # the stored message matches the one that left the building
    assert state.notification(n.id).body == drv.sent[0][2]


def test_the_result_reads_like_a_sentence(state):
    """Substitution must not leave "Your your treatment session"."""
    out, _ = privacy.scrub(state, state.patient("P1"),
                           "Your FOLFOX session has moved to 15:30.")
    assert out == "Your treatment session has moved to 15:30."


def test_sentence_case_is_preserved(state):
    out, _ = privacy.scrub(state, state.patient("P1"),
                           "Chemotherapy is scheduled for 10:00.")
    assert out.startswith("Treatment is scheduled")


def test_adjacent_terms_collapse_to_one(state):
    out, _ = privacy.scrub(state, state.patient("P1"),
                           "Your chemotherapy infusion is at 10:00.")
    assert "treatment treatment" not in out.lower()
    assert out == "Your treatment is at 10:00."


def test_a_time_and_a_place_the_patient_needs_survive(state):
    body = "Your chemotherapy appointment has moved to 15:30 today."
    out, _ = privacy.scrub(state, state.patient("P1"), body)
    assert "15:30" in out and "today" in out


# --------------------------------------------------------------------------- #
# Context at the point of care
# --------------------------------------------------------------------------- #
def _chemo(s, aid, start, end, status=AppointmentStatus.BOOKED, pid="P1"):
    a = Appointment(aid, pid, "D1", start, end, AppointmentType.CHEMO, status,
                    room_id="R1", drug_id="G1")
    a.date = s.day()
    s.appointments[aid] = a
    return a


def test_cycle_counts_the_ones_already_given(state):
    _chemo(state, "A1", "09:00", "10:30", AppointmentStatus.VISITED)
    _chemo(state, "A2", "09:00", "10:30", AppointmentStatus.VISITED)
    now = _chemo(state, "A3", "11:00", "12:30")
    assert ctx.cycle_number(state, now) == 3
    assert ctx.patient_context(state, now)["visit_label"] == "C3D1"


def test_a_consult_has_no_cycle(state):
    a = Appointment("A1", "P2", "D1", "11:00", "11:10",
                    AppointmentType.CONSULT)
    a.visit_type = "follow_up"
    state.appointments["A1"] = a
    assert ctx.cycle_number(state, a) is None
    assert ctx.patient_context(state, a)["visit_label"] == "Follow-up"


def test_a_cancelled_cycle_does_not_count(state):
    _chemo(state, "A1", "09:00", "10:30", AppointmentStatus.VISITED)
    _chemo(state, "A2", "09:00", "10:30", AppointmentStatus.CANCELLED)
    now = _chemo(state, "A3", "11:00", "12:30")
    assert ctx.cycle_number(state, now) == 2


def test_context_carries_the_regimen_and_room(state):
    a = _chemo(state, "A1", "11:00", "12:30")
    row = ctx.patient_context(state, a)
    assert row["regimen"] == "FOLFOX"
    assert row["room"] == "Infusion 2"
    assert row["patient_name"] == "Meera Pillai"


def test_lab_status_appears_as_chips(state):
    a = _chemo(state, "A1", "11:00", "12:30")
    o = iv.order(state, "P1", "CBC", now="09:20", day=state.day(),
                 appointment_id="A1", eta="11:30")
    row = ctx.patient_context(state, a)
    assert row["labs"]["status"] == "waiting"
    assert "CBC pending" in row["labs"]["chips"][0]["text"]

    iv.result(state, o.data["investigation"]["id"], "ANC 0.9", now="10:48",
              flagged=True)
    row = ctx.patient_context(state, a)
    assert row["labs"]["status"] == "blocked"
    assert row["labs"]["chips"][0]["tone"] == "alert"


def test_confirmation_shows_as_a_flag(state):
    a = _chemo(state, "A1", "11:00", "12:30")
    assert any(f["text"] == "never confirmed" for f in
               ctx.patient_context(state, a)["flags"])
    a.confirmed = "yes"
    assert any(f["text"] == "confirmed by reply" for f in
               ctx.patient_context(state, a)["flags"])


def test_first_visit_is_flagged(state):
    a = _chemo(state, "A1", "11:00", "12:30")
    assert any(f["text"] == "first visit here" for f in
               ctx.patient_context(state, a)["flags"])


def test_a_walk_in_reason_is_carried_through(state):
    a = Appointment("A1", "P2", "D1", "11:00", "11:10",
                    AppointmentType.CONSULT)
    a.walk_in = True
    a.reason = "mouth sores since C2"
    state.appointments["A1"] = a
    row = ctx.patient_context(state, a)
    assert "mouth sores since C2" in row["notes"]
    assert any(f["text"] == "walked in today" for f in row["flags"])


def test_day_context_is_in_clock_order(state):
    _chemo(state, "A2", "14:00", "15:30")
    _chemo(state, "A1", "09:00", "10:30")
    rows = ctx.day_context(state, "D1")
    assert [r["slot_start"] for r in rows] == ["09:00", "14:00"]


def test_day_context_skips_another_doctors_patients(state):
    state.doctors["D2"] = Doctor("D2", "Dr Two", "oncology", 20)
    a = _chemo(state, "A1", "09:00", "10:30")
    a.doctor_id = "D2"
    assert ctx.day_context(state, "D1") == []
