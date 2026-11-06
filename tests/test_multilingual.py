"""The one screen a patient sees, and the replies they send back.

The organisers' guidance is explicit: design for the languages of the
doctors, patients and caregivers you serve, and treat caregivers as
first-class users — "not English-only by default if the care setting is not".

The console stays English on purpose; the doctors use it. These tests cover
the two places where that choice would otherwise cost a patient something:
the page they are sent a link to, and whatever they type back.
"""

from __future__ import annotations

import pytest

from engine import (
    SystemState, Doctor, Patient, Appointment, AppointmentType,
    AppointmentStatus, DoctorStatus, Drug, Notification, TimeWindow,
    patient_view as pv,
)
from services.messaging import record_reply

TODAY = "2026-11-02"
NOW = "10:00"


@pytest.fixture
def state() -> SystemState:
    s = SystemState()
    s.doctors = {"D1": Doctor("D1", "Dr Rao", "oncology", 20,
                              DoctorStatus.AVAILABLE)}
    s.drugs = {"G1": Drug("G1", "Cisplatin", TimeWindow("08:00", "12:00"),
                          15, ["pump", "monitor"])}
    s.active_day = TODAY
    return s


def _patient(s, pid="P1", **kw):
    p = Patient(pid, "Meera Nair", "+91 98200 11109", 1, **kw)
    s.patients[pid] = p
    return p


def _appt(s, aid="A1", pid="P1", start="10:30", end="11:00",
          status=AppointmentStatus.BOOKED, **kw):
    a = Appointment(aid, pid, "D1", start, end, AppointmentType.CONSULT,
                    status)
    a.date = TODAY
    for k, v in kw.items():
        setattr(a, k, v)
    s.appointments[aid] = a
    return a


# --------------------------------------------------------------------------- #
# The page opens in the patient's own language
# --------------------------------------------------------------------------- #
def test_the_view_carries_the_language_the_clinic_recorded(state):
    _patient(state, language="hi")
    a = _appt(state)
    assert pv.status_for(state, a, NOW)["language"] == "hi"


def test_a_patient_with_no_recorded_language_gets_english(state):
    _patient(state)
    a = _appt(state)
    assert pv.status_for(state, a, NOW)["language"] == "en"


def test_a_blank_language_does_not_become_a_blank_page(state):
    """An empty cell in the workbook must not reach the page as a language."""
    p = _patient(state)
    p.language = ""
    a = _appt(state)
    assert pv.status_for(state, a, NOW)["language"] == "en"


# --------------------------------------------------------------------------- #
# Guidance travels as a key, so the engine knows no languages
# --------------------------------------------------------------------------- #
def test_guidance_comes_out_as_a_key_as_well_as_prose(state):
    _patient(state)
    a = _appt(state)
    out = pv.status_for(state, a, NOW)
    assert out["advice_key"] == "check_in"
    assert out["advice"]                      # English, for a message
    assert "advice_vars" in out


def test_the_key_follows_the_stage(state):
    _patient(state)
    a = _appt(state, checked_in=True, checked_in_at="10:05",
              awaiting_results=True)
    out = pv.status_for(state, a, NOW)
    assert out["stage"] == "in_labs"
    assert out["advice_key"] == "in_labs"


def test_the_queue_numbers_travel_with_the_key(state):
    """So a translated string can interpolate them without re-deriving them."""
    _patient(state)
    _patient(state, "P2")
    a = _appt(state, checked_in=True, checked_in_at="09:30")
    _appt(state, "A2", "P2", "10:00", "10:30", checked_in=True,
          checked_in_at="09:00")
    out = pv.status_for(state, a, NOW)
    assert out["advice_vars"]["ahead"] == out["people_ahead"]
    assert out["advice_vars"]["minutes"] == out["estimated_wait_min"]


def test_a_patient_with_the_doctor_gets_no_guidance_line(state):
    _patient(state)
    a = _appt(state, status=AppointmentStatus.ACTIVE, checked_in=True,
              checked_in_at="10:05", started_at="10:20")
    out = pv.status_for(state, a, NOW)
    assert out["stage"] == "with_doctor"
    assert out["advice_key"] == ""
    assert out["advice"] == ""


# --------------------------------------------------------------------------- #
# The person who came with them
# --------------------------------------------------------------------------- #
def test_the_caregiver_block_follows_the_patients_own_consent(state):
    _patient(state, consent_attendant=True)
    a = _appt(state)
    assert pv.status_for(state, a, NOW)["attendant_ok"] is True


def test_no_caregiver_block_where_that_was_declined(state):
    _patient(state, consent_attendant=False)
    a = _appt(state)
    assert pv.status_for(state, a, NOW)["attendant_ok"] is False


def test_the_caregiver_block_does_not_unlock_the_treatment(state):
    """Two different consents. Letting a relative follow the queue is not
    permission to tell them what the drug is."""
    _patient(state, consent_attendant=True, consent_name_treatment=False)
    a = _appt(state, type=AppointmentType.CHEMO, drug_id="G1")
    out = pv.status_for(state, a, NOW)
    assert out["attendant_ok"] is True
    assert out["treatment"] == ""


# --------------------------------------------------------------------------- #
# Whatever they type back
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("text,intent", [
    # English
    ("yes", "yes"), ("Y", "yes"), ("ok", "yes"), ("no", "no"),
    ("cannot", "no"),
    # Hindi, romanised and in Devanagari
    ("haan", "yes"), ("ji", "yes"), ("हाँ", "yes"),
    ("हां", "yes"),
    ("nahi", "no"), ("नहीं", "no"),
    # Marathi
    ("ho", "yes"), ("hoy", "yes"), ("होय", "yes"),
    ("nako", "no"), ("नाही", "no"),
    # and the ones nobody should guess at
    ("maybe later", "unclear"), ("", "unclear"),
    ("call me", "unclear"),
])
def test_replies_are_read_in_the_language_they_were_sent_in(state, text,
                                                            intent):
    _patient(state)
    state.notifications.append(
        Notification("N1", "P1", "whatsapp", "Are you coming?", "09:00"))
    assert record_reply(state, "N1", text, NOW)["intent"] == intent


def test_an_unclear_reply_is_still_recorded(state):
    """It goes on the coordinator's list to phone, not into a guess."""
    _patient(state)
    state.notifications.append(
        Notification("N1", "P1", "whatsapp", "Are you coming?", "09:00"))
    r = record_reply(state, "N1", "my son will call you", NOW)
    assert r["intent"] == "unclear"
    assert r["notification"]["reply"] == "my son will call you"
