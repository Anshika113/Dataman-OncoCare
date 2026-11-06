"""Help for somebody stuck in the interface, that knows who is asking.

The most common stuck-moment here is not "I cannot find the button" — it is
"the button is not there", and the answer is nearly always that this person's
role does not have it. A nurse hunting for *clear this flagged result* will
never find it: accepting an out-of-protocol lab value is a clinical decision
and the backend gives it to doctors and admins only.

So the thing worth testing is not the prose. It is that the help tells the
truth about permissions — the same truth `require_role` enforces — and that
it never hands somebody steps for a button they do not have.
"""

from __future__ import annotations

import re
import pathlib

import pytest

from engine import ask, guide

MAIN = pathlib.Path(__file__).resolve().parents[1] / "backend" / "api" / "main.py"


# --------------------------------------------------------------------------- #
# It answers as the person asking, not in general
# --------------------------------------------------------------------------- #
def test_a_doctor_is_told_how_to_clear_a_flag():
    t = guide.TOPIC_BY_ID["clear_flag"]
    a = guide.answer(t, "doctor")
    assert a["allowed"] is True
    assert a["steps"]


def test_a_nurse_is_told_who_to_ask_instead():
    a = guide.answer(guide.TOPIC_BY_ID["clear_flag"], "nurse")
    assert a["allowed"] is False
    assert a["steps"] == []
    assert "doctor" in a["who_can"]
    assert a["why_not"]


def test_somebody_who_cannot_do_it_never_gets_the_steps():
    """Steps for a button you do not have is worse than no answer."""
    for topic in guide.TOPICS:
        for role in guide.ALL:
            a = guide.answer(topic, role)
            if not a["allowed"]:
                assert a["steps"] == [], (topic.id, role)


def test_every_refusal_explains_itself():
    """"Ask a nurse" with no reason reads as a bug in the software."""
    for topic in guide.TOPICS:
        if set(topic.roles) != set(guide.ALL):
            assert topic.why_not, topic.id


def test_a_note_is_shown_to_everybody():
    """A caveat applies whether or not you have the button."""
    t = guide.TOPIC_BY_ID["gate"]
    assert guide.answer(t, "coordinator")["note"]
    assert guide.answer(t, "doctor")["note"]


@pytest.mark.parametrize("role,expected", [
    ("doctor", False), ("nurse", True), ("admin", True), ("coordinator", False),
])
def test_booking_belongs_to_the_desk(role, expected):
    assert guide.answer(guide.TOPIC_BY_ID["book"], role)["allowed"] is expected


def test_who_can_reads_as_a_sentence():
    assert guide.who_can(guide.TOPIC_BY_ID["import"]) == "an administrator"
    assert guide.who_can(guide.TOPIC_BY_ID["clear_flag"]) == \
        "an administrator or a doctor"
    assert "or" in guide.who_can(guide.TOPIC_BY_ID["waitlist"])


# --------------------------------------------------------------------------- #
# The roles here are the backend's, not a second opinion
# --------------------------------------------------------------------------- #
def _roles_for(path: str) -> set[str]:
    """The roles require_role() actually names on that route."""
    src = MAIN.read_text(encoding="utf-8")
    m = re.search(re.escape(f'"{path}"') + r"\)(.{0,700}?)require_role\(([^)]*)\)",
                  src, re.S)
    assert m, f"route not found: {path}"
    return set(re.findall(r'"(\w+)"', m.group(2)))


@pytest.mark.parametrize("topic_id,path", [
    ("clear_flag", "/api/investigations/{inv_id}/clear"),
    ("book", "/api/appointments/consult"),
    ("import", "/api/import/patients"),
    ("audit", "/api/audit"),
    ("consent", "/api/patients/{patient_id}/consent"),
    ("working_week", "/api/doctors/{doctor_id}/sessions"),
    ("walk_in", "/api/walk-ins"),
    ("follow_ups", "/api/follow-ups"),
    ("gate", "/api/appointments/{appt_id}/gate"),
    ("hand_off", "/api/appointments/{appt_id}/hand-off"),
    ("checkin", "/api/appointments/{appt_id}/checkin"),
])
def test_the_help_matches_what_the_backend_enforces(topic_id, path):
    """Where the two disagree the backend wins, so this has to track it."""
    assert set(guide.TOPIC_BY_ID[topic_id].roles) == _roles_for(path), topic_id


def test_every_topic_names_at_least_one_role():
    for t in guide.TOPICS:
        assert t.roles
        assert set(t.roles) <= set(guide.ALL), t.id


def test_every_topic_says_where_it_lives():
    tabs = {"Dashboard", "My Day", "Schedule", "Front Desk", "Follow-ups",
            "Live Queue", "Doctors & Patients", "Availability", "Activity",
            "Ops Console"}
    for t in guide.TOPICS:
        assert t.where in tabs, (t.id, t.where)


# --------------------------------------------------------------------------- #
# Telling a how-to from a what-is
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("question,topic", [
    ("how do I hold a treatment", "gate"),
    ("where do I check someone in", "checkin"),
    ("how do I check a patient in", "checkin"),
    ("kaise check in karte hain", "checkin"),
    ("why can't I clear this flag", "clear_flag"),
    ("clear flag kaise karein", "clear_flag"),
    ("how do I hand over a patient", "hand_off"),
    ("how do I undo that", "undo"),
    ("booking kaise kare", "book"),
    ("where is the waitlist", "waitlist"),
    ("why cant I find the audit trail", "audit"),
    ("import kaise karu", "import"),
])
def test_a_stuck_question_finds_its_topic(question, topic):
    assert ask.resolve(question, {}).topic == topic


def test_a_question_about_today_is_not_answered_with_a_how_to():
    """"Whose results are we waiting for" wants patients, not instructions."""
    a = ask.resolve("whose results are we waiting for", {})
    assert a.kind == "view"
    assert a.view == "held"


def test_asking_to_do_something_offers_the_how_to():
    """It cannot book, but it knows where you can."""
    a = ask.resolve("book Usman for 11:10", {})
    assert a.kind == "cannot_write"
    assert a.topic == "book"


def test_a_single_short_word_cannot_carry_a_match():
    assert guide.match_topic("is the csv in the folder") is None
    assert guide.match_topic("put it in") is None


def test_a_cue_matches_however_the_words_are_spaced():
    for q in ("check in", "check a patient in", "check someone in now"):
        assert guide.match_topic(q) is guide.TOPIC_BY_ID["checkin"]


def test_the_catalogue_offers_topics_and_nothing_else():
    for c in guide.catalogue():
        assert set(c) == {"id", "about"}
    assert {c["id"] for c in guide.catalogue()} == {t.id for t in guide.TOPICS}
