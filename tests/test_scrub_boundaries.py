"""The scrubber must redact disclosures, not maul the sentence around them.

This exists because of a real one. Terms were substituted as plain
substrings, and a patient's cancer stage went into the term list on its own.
For a stage I patient, every letter "i" in an outgoing SMS became the word
"treatment":

    Please arrive on time.  ->  Please arrtreatmentve on ttreatmentme.

Six of the thirty seeded patients are stage I, and stage IV patients got
"arrtreatmente". The consent machinery was working exactly as designed; the
message it produced was unreadable.

Two rules came out of it, and these tests hold them: terms match whole words
only, and nothing shorter than MIN_TERM_LEN is a term at all.
"""

from __future__ import annotations

import pytest

from engine import (
    SystemState, Patient, Drug, TimeWindow, ChemRoom, RoomType,
    privacy,
)

PLAIN = "Please arrive on time. Your visit is at 10:30 with Dr. Khan."


@pytest.fixture
def state() -> SystemState:
    s = SystemState()
    s.drugs = {
        "G1": Drug("G1", "Cisplatin", TimeWindow("08:00", "12:00"), 10, []),
        "G2": Drug("G2", "Ara-C", TimeWindow("08:00", "18:00"), 10, []),
    }
    s.rooms = {
        "R1": ChemRoom("R1", "Infusion 2", RoomType.INFUSION_CHAIR, ["pump"]),
    }
    return s


def _p(stage="IV", diagnosis="Lung Cancer", consent=False):
    return Patient("P1", "Test Patient", "+91 98200 11101", 1,
                   diagnosis=diagnosis, stage=stage,
                   consent_name_treatment=consent)


# --------------------------------------------------------------------------- #
# The bug itself
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("stage", ["I", "II", "III", "IV", "0", "1A", "T2N0"])
def test_a_cancer_stage_never_rewrites_ordinary_words(state, stage):
    out, changed = privacy.scrub(state, _p(stage=stage), PLAIN)
    assert out == PLAIN
    assert changed is False


def test_the_exact_sentence_that_broke(state):
    msg = "Good news — a slot opened up at 12:00. Please arrive on time."
    assert privacy.scrub(state, _p(stage="IV"), msg)[0] == msg


def test_stage_one_does_not_eat_every_i(state):
    out = privacy.scrub(state, _p(stage="I"), PLAIN)[0]
    assert "treatment" not in out
    assert out.count("i") == PLAIN.count("i")


# --------------------------------------------------------------------------- #
# It still redacts what it is for
# --------------------------------------------------------------------------- #
def test_the_stage_as_a_phrase_is_still_a_disclosure(state):
    out, changed = privacy.scrub(state, _p(stage="IV"),
                                 "Your stage IV review is tomorrow.")
    assert out == "Your treatment review is tomorrow."
    assert changed is True


def test_a_drug_name_is_still_removed(state):
    out = privacy.scrub(state, _p(), "Your Cisplatin session is at 10:30.")[0]
    assert out == "Your treatment session is at 10:30."


def test_a_revealing_room_is_still_removed(state):
    out = privacy.scrub(state, _p(), "Report to Infusion 2 at 10:30.")[0]
    assert out == "Report to the day-care unit at 10:30."


def test_a_generic_term_is_still_removed(state):
    out = privacy.scrub(state, _p(), "Please arrive for your infusion.")[0]
    assert out == "Please arrive for your treatment."


def test_the_diagnosis_is_still_removed(state):
    out = privacy.scrub(state, _p(), "Your Lung Cancer follow-up is due.")[0]
    assert out == "Your treatment follow-up is due."


def test_consent_still_lets_the_message_through_untouched(state):
    msg = "Your Cisplatin session in Infusion 2 is at 10:30."
    out, changed = privacy.scrub(state, _p(consent=True), msg)
    assert out == msg
    assert changed is False


# --------------------------------------------------------------------------- #
# Word boundaries, in both directions
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("msg", [
    "The reception desk is on the ground floor.",   # contains "on"
    "We will scan you in first.",                   # contains "can" / "cancer"?
    "Bring a carer with you.",                      # "care" inside "carer"
    "Your radiator appointment is wrong.",          # "radiation" is not here
    "Please confirm by reply.",
])
def test_ordinary_sentences_pass_through_whole(state, msg):
    assert privacy.scrub(state, _p(), msg)[0] == msg


def test_a_term_inside_a_longer_word_is_left_alone(state):
    """"chemo" must not fire inside "chemotherapist" being a different word."""
    out = privacy.scrub(state, _p(), "Ask the chemoreceptor team.")[0]
    assert out == "Ask the chemoreceptor team."


def test_a_hyphenated_drug_name_is_matched(state):
    """Ara-C ends in a word character but contains punctuation."""
    out = privacy.scrub(state, _p(), "Your Ara-C dose is at 11:00.")[0]
    assert out == "Your treatment dose is at 11:00."


def test_matching_ignores_case_but_keeps_the_sentence_shape(state):
    out = privacy.scrub(state, _p(), "CHEMOTHERAPY has moved to 14:00.")[0]
    assert out == "Treatment has moved to 14:00."


def test_a_term_mid_sentence_is_not_capitalised(state):
    out = privacy.scrub(state, _p(), "Your Chemotherapy has moved.")[0]
    assert out == "Your treatment has moved."


# --------------------------------------------------------------------------- #
# The floor
# --------------------------------------------------------------------------- #
def test_the_minimum_term_length_is_the_documented_one():
    assert privacy.MIN_TERM_LEN == 3


def test_a_two_letter_drug_name_is_never_substituted(state):
    """A backstop: any future short term must not be able to do this again."""
    state.drugs["G3"] = Drug("G3", "AC", TimeWindow("08:00", "18:00"), 10, [])
    msg = "Please contact the clinic."           # contains "ac" twice
    assert privacy.scrub(state, _p(), msg)[0] == msg


def test_an_empty_stage_adds_no_term(state):
    assert privacy.scrub(state, _p(stage=""), PLAIN)[0] == PLAIN
