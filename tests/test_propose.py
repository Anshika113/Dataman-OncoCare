"""What a model is allowed to do with a sentence.

The model is untrusted by design. These tests hand ``read_choice`` what a
confused or inventive model might return and check that nothing gets further
than a card a person still has to confirm.
"""

from __future__ import annotations

import pytest

from engine import ask, propose
from engine.state import (Appointment, AppointmentStatus, Doctor, DoctorStatus,
                          Patient, SystemState)

DAY, NOW = "2026-11-03", "10:00"
NAMES = {"P1": "Meera Nair", "P2": "Fatima Noor", "P3": "Fatima Sayed"}


@pytest.fixture
def state():
    s = SystemState()
    s.active_day = DAY
    for did, name in (("D1", "Dr. Amina Khan"), ("D2", "Dr. Ben Ortiz")):
        s.doctors[did] = Doctor(did, name, "oncology", 20,
                                DoctorStatus.AVAILABLE, [])
    for pid, name in NAMES.items():
        s.patients[pid] = Patient(pid, name, "9820011101", 1)
    s.appointments["A1"] = Appointment(
        "A1", "P1", "D1", "09:45", "10:15", status=AppointmentStatus.ACTIVE,
        date=DAY, started_at="09:45")
    return s


def read(state, choice, mask=None, mine="", sentence=""):
    return propose.read_choice(choice, state, NOW, DAY, mask or {}, NAMES, mine,
                               sentence)


# --------------------------------------------------------------------------- #
# Names
# --------------------------------------------------------------------------- #
def test_a_patient_name_does_not_leave_as_a_name():
    masked, mask = propose.mask_names("Meera ko Dr Ben ko de do", NAMES)
    assert "Meera" not in masked and "PATIENT_1" in masked
    assert mask["PATIENT_1"] == ["P1"]
    assert "Ben" in masked


def test_a_full_name_is_masked_whole():
    masked, _ = propose.mask_names("hand Meera Nair over", NAMES)
    assert masked == "hand PATIENT_1 over"


def test_a_marathi_ending_does_not_hide_the_name():
    masked, mask = propose.mask_names("Meerala Dr. Ben yanchyakade dya", NAMES)
    assert masked == "PATIENT_1 Dr. Ben yanchyakade dya"
    assert mask["PATIENT_1"] == ["P1"]


def test_two_people_called_fatima_stay_ambiguous(state):
    masked, mask = propose.mask_names("Fatima ko 5 minute do", NAMES)
    assert sorted(mask["PATIENT_1"]) == ["P2", "P3"]
    a = read(state, {"choice": "extend", "patient": "PATIENT_1", "minutes": 5}, mask)
    assert a.kind == "unclear"
    assert "more than one" in a.reason.lower()


# --------------------------------------------------------------------------- #
# Inventions
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("junk", [
    None, "extend", [], {}, {"choice": "cancel_appointment"},
    {"choice": "clear_flag"}, {"choice": "none"},
])
def test_anything_outside_the_list_goes_back_to_the_local_matcher(state, junk):
    assert read(state, junk) is None


def test_the_model_can_decline_a_clinical_question(state):
    assert read(state, {"choice": "clinical"}).kind == "refused"


def test_no_action_on_the_list_is_clinical():
    blob = " ".join(a.id + " " + a.purpose for a in propose.ACTIONS).lower()
    for word in ("flag", "dose", "result", "lab", "cancel", "prescri"):
        assert word not in blob


# --------------------------------------------------------------------------- #
# Actions become cards
# --------------------------------------------------------------------------- #
def test_this_patient_means_the_visit_under_way(state):
    a = read(state, {"choice": "extend", "minutes": 10}, mine="D1")
    assert a.kind == "proposal" and a.via == "model"
    assert a.proposal["appointment_id"] == "A1"
    assert a.proposal["minutes"] == 10


@pytest.mark.parametrize("minutes", [None, 0, 500, "ten", True])
def test_minutes_must_be_a_sensible_number(state, minutes):
    a = read(state, {"choice": "extend", "minutes": minutes}, mine="D1")
    assert a.kind == "unclear"


def test_a_hand_off_carries_the_note_with_the_name_put_back(state):
    a = read(state, {"choice": "hand_off", "patient": "PATIENT_1",
                     "to_doctor": "D2", "note": "PATIENT_1 ke counts 11 baje aaye"},
             mask={"PATIENT_1": ["P1"]}, mine="D1")
    assert a.kind == "proposal"
    assert a.proposal["to_doctor_id"] == "D2"
    assert a.proposal["note"] == "Meera Nair ke counts 11 baje aaye"


def test_a_hand_off_with_the_doctor_in_the_other_field_still_works(state):
    a = read(state, {"choice": "hand_off", "patient": "PATIENT_1", "doctor": "D2"},
             mask={"PATIENT_1": ["P1"]}, mine="D1")
    assert a.proposal["to_doctor_id"] == "D2"


def test_the_receiving_doctor_is_not_taken_for_whose_list_it_is(state):
    """Staff saying "this patient" must not end up on the receiving doctor's list."""
    a = read(state, {"choice": "hand_off", "doctor": "D2"})
    assert a.kind == "unclear"
    assert "Which patient" in a.reason


@pytest.mark.parametrize("said", ["is patient", "this patient", "ya patient",
                                  "इस मरीज़", "या रुग्णाला"])
def test_this_patient_is_not_taken_for_a_name(state, said):
    a = read(state, {"choice": "extend", "patient": said, "minutes": 10}, mine="D1")
    assert a.kind == "proposal"
    assert a.proposal["appointment_id"] == "A1"


def test_a_name_with_patient_after_it_is_still_a_name(state):
    a = read(state, {"choice": "extend", "patient": "Vitram patient", "minutes": 5},
             mine="D1")
    assert a.kind == "unclear"


def test_a_misheard_name_never_becomes_the_patient_in_the_room(state):
    a = read(state, {"choice": "extend", "patient": "Vitram", "minutes": 5}, mine="D1")
    assert a.kind == "unclear"
    assert "Vitram" in a.reason


def test_a_hand_off_with_nobody_named_must_say_this_patient(state):
    """Saaras heard "Vitramla", the model left the patient empty, and the patient
    in the room was nearly handed over instead."""
    choice = {"choice": "hand_off", "to_doctor": "D2"}
    a = read(state, choice, mine="D1", sentence="Vitramla Dr. Ben yanchyakade dya")
    assert a.kind == "unclear"
    for said in ("pass this patient to Dr. Ben", "is patient ko Dr. Ben ko de do",
                 "ya patient la Dr. Ben kade dya", "इस मरीज़ को डॉक्टर बेन को दे दो",
                 "या रुग्णाला डॉक्टर बेन यांच्याकडे द्या"):
        assert read(state, choice, mine="D1", sentence=said).kind == "proposal", said


def test_an_invented_doctor_is_a_question(state):
    a = read(state, {"choice": "hand_off", "patient": "PATIENT_1",
                     "to_doctor": "D99"}, mask={"PATIENT_1": ["P1"]}, mine="D1")
    assert a.kind == "unclear"


def test_a_doctor_cannot_be_proposed_someone_elses_patient(state):
    a = read(state, {"choice": "extend", "patient": "PATIENT_1", "minutes": 5},
             mask={"PATIENT_1": ["P1"]}, mine="D2")
    assert a.kind == "unclear"
    assert "not on your list" in a.reason


def test_a_doctor_cannot_close_a_colleagues_list(state):
    a = read(state, {"choice": "close_list", "doctor": "D2", "from_time": "13:00"},
             mine="D1")
    assert a.proposal["doctor_id"] == "D1"


@pytest.mark.parametrize("at", ["", "1pm", "25:00", "13:99", None])
def test_a_bad_time_is_a_question(state, at):
    a = read(state, {"choice": "close_list", "from_time": at}, mine="D1")
    assert a.kind == "unclear"


def test_staff_with_no_list_of_their_own_must_name_the_doctor(state):
    assert read(state, {"choice": "pull_forward"}).kind == "unclear"
    assert read(state, {"choice": "pull_forward", "doctor": "D1"}).kind == "proposal"


# --------------------------------------------------------------------------- #
# Lookups
# --------------------------------------------------------------------------- #
def test_a_lookup_is_marked_as_coming_from_the_model(state):
    a = read(state, {"choice": "free_rooms"})
    assert a.kind == "view" and a.view == "free_rooms" and a.via == "model"


def test_every_view_and_action_is_offered_and_nothing_else():
    ids = {c["id"] for c in propose.catalogue()}
    assert ids == {v.id for v in ask.VIEWS} | {a.id for a in propose.ACTIONS}
    assert set(propose.choices()) == ids | {"clinical", "none"}
