"""The assistant's local matcher: what it answers, and what it will not.

Three properties matter more than the answers themselves.

* **It cannot write.** The catalogue is the permission list, so there is no
  tool for booking or cancelling and a request to do either comes back saying
  so rather than being half-attempted.
* **It refuses clinical questions before it matches a view.** "Who is most
  urgent" is answered from the severity staff recorded. "Who is sickest" asks
  it to judge, so it is refused.
* **It never guesses a patient.** Two people called Fatima means a question,
  not a coin toss.

The matcher here is the local one, which runs with no model and no network.
That is not a fallback bolted on for offline use — it is how the feature
behaves when nobody has configured a model, so it has to work on its own.
"""

from __future__ import annotations

import pytest

from engine import ask

NAMES = {
    "P1": "Meera Nair",
    "P2": "Deepa Menon",
    "P3": "Fatima Noor",
    "P4": "Fatima Sayed",
    "P5": "Usman Tariq",
}


# --------------------------------------------------------------------------- #
# The questions a shift actually asks
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("question,view", [
    ("who is waiting longest", "waiting"),
    ("kaun sabse zyada wait kar raha hai", "waiting"),
    ("who hasn't been called yet", "not_called"),
    ("anyone in the waiting room", "not_called"),
    ("whose results are we waiting for", "held"),
    ("any chairs free", "free_rooms"),
    ("koi chair khaali hai", "free_rooms"),
    ("am I running late", "running_late"),
    ("how many left on my list", "my_day"),
    ("kitne bache hain meri list me", "my_day"),
    ("anything I should look at", "attention"),
    ("who needs chasing, follow up", "follow_ups"),
])
def test_it_finds_the_right_view(question, view):
    a = ask.resolve(question, NAMES)
    assert a.kind == "view"
    assert a.view == view


def test_a_named_patient_resolves_to_that_patient():
    a = ask.resolve("Meera ka kya chal raha hai", NAMES)
    assert a.kind == "view"
    assert a.view == "patient"
    assert a.patient_query == "P1"


def test_a_full_name_works_too():
    assert ask.resolve("how is Usman Tariq doing", NAMES).patient_query == "P5"


# --------------------------------------------------------------------------- #
# The clinical line
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("question", [
    "which patient is the sickest",
    "sabse bimar kaun hai",
    "सबसे ज्यादा बीमार कौन है",
    "is he well enough for chemo",
    "chemo de sakte hain kya",
    "कीमो दे सकते हैं क्या",
    "रिपोर्ट का मतलब क्या है",
    "are her counts safe to treat",
    "are her counts ok",
    "is he fit to proceed",
    "should we skip this cycle",
    "what does her report mean",
    "how ill is she",
    "what is his prognosis",
])
def test_clinical_questions_are_refused(question):
    a = ask.resolve(question, NAMES)
    assert a.kind == "refused"
    assert "doctor's call" in a.reason


def test_a_clinical_question_wearing_an_operational_coat_is_still_refused():
    """"Sickest person waiting" names a view and asks for a judgement."""
    a = ask.resolve("who is the sickest person waiting", NAMES)
    assert a.kind == "refused"


@pytest.mark.parametrize("question", [
    "who is most urgent",
    "who is the most urgent person waiting",
    "who should we prioritise",
    "emergency queue dikhao",
])
def test_urgency_comes_from_the_severity_staff_recorded(question):
    a = ask.resolve(question, NAMES)
    assert a.kind == "view"
    assert a.view == "emergency_queue"


def test_a_note_that_mentions_a_result_is_not_a_clinical_question():
    assert ask.clinical_reason("meera ko dr ben ko de do, counts 11 baje aaye the") is None


# --------------------------------------------------------------------------- #
# It cannot write
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("question,verb", [
    ("book Usman for 11:10", "book"),
    ("cancel Rahim's chemo today", "cancel"),
    ("move my 11:30 to the afternoon", "move"),
    ("hand off Meera to Dr Ben", "hand over"),
    ("clear the flag on her bloods", "clear a flag"),
    ("close my list at one", "close a list"),
])
def test_it_says_it_cannot_change_anything(question, verb):
    a = ask.resolve(question, NAMES)
    assert a.kind == "cannot_write"
    assert verb in a.reason


def test_no_view_in_the_catalogue_writes():
    """The catalogue is the permission list, so this is the whole guarantee."""
    writes = ("book", "cancel", "reschedul", "move", "hand", "clear",
              "close", "delete", "create", "update")
    for v in ask.VIEWS:
        blob = (v.id + " " + v.purpose).lower()
        assert not any(w in blob for w in writes), v.id


# --------------------------------------------------------------------------- #
# It does not guess
# --------------------------------------------------------------------------- #
def test_two_patients_of_the_same_name_is_a_question_not_a_coin_toss():
    a = ask.resolve("Fatima ka kya haal hai", NAMES)
    assert a.kind == "unclear"
    assert "more than one" in a.reason.lower()


def test_nonsense_is_unclear_and_offers_a_way_back():
    a = ask.resolve("asdf qwerty", NAMES)
    assert a.kind == "unclear"
    assert a.suggestions


def test_an_empty_question_asks_for_one():
    assert ask.resolve("   ", NAMES).kind == "unclear"


def test_a_short_name_cannot_match_inside_another_word():
    """A patient called "Ara" must not be found inside "are you free"."""
    assert ask.find_patient("are you free", {"P9": "Ara"}) == []


def test_a_first_name_inside_a_longer_word_is_not_a_match():
    assert ask.find_patient("the meeting is at noon", {"P1": "Meera Nair"}) == []


# --------------------------------------------------------------------------- #
# What a model is allowed to come back with
# --------------------------------------------------------------------------- #
def test_the_catalogue_is_the_entire_surface_offered_to_a_model():
    ids = {c["id"] for c in ask.catalogue()}
    assert ids == {v.id for v in ask.VIEWS}
    for c in ask.catalogue():
        assert set(c) == {"id", "purpose"}        # no endpoints, no params


def test_a_model_inventing_a_view_is_discarded():
    a = ask.from_model({"view": "cancel_appointment"}, NAMES)
    assert a.kind == "unclear"


def test_a_model_returning_junk_is_discarded():
    for junk in (None, "waiting", [], {"nope": 1}):
        assert ask.from_model(junk, NAMES).kind == "unclear"


def test_a_model_choosing_a_real_view_is_accepted_and_marked():
    a = ask.from_model({"view": "waiting"}, NAMES)
    assert a.kind == "view"
    assert a.view == "waiting"
    assert a.via == "model"


def test_a_model_must_still_name_one_patient_unambiguously():
    assert ask.from_model({"view": "patient", "patient": "Fatima"},
                          NAMES).kind == "unclear"
    assert ask.from_model({"view": "patient", "patient": "Meera Nair"},
                          NAMES).patient_query == "P1"
