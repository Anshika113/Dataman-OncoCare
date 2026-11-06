"""A yes books a waitlist slot, so a yes has to be earned.

Reading only the first word turned refusals into confirmations, and one of
those refusals mentioned a fever. These replies are the reason this file exists.
"""

from __future__ import annotations

import pytest

from engine import coordination as coord
from engine.replies import read_reply
from engine.state import Notification, Patient, SystemState


@pytest.mark.parametrize("text", [
    "ji nahi", "जी नहीं", "ho nahi payega", "aa nahi paunga",
    "ok but papa ko bukhar hai aa nahi payenge",
    "yes, I can't", "haan nahi aa paunga",
])
def test_a_refusal_anywhere_is_a_refusal(text):
    assert read_reply(text) == "no"


@pytest.mark.parametrize("text", [
    "yes", "YES.", "yes please", "ok sir", "haan", "ji", "हाँ", "होय",
    "haan aa raha hoon", "ok, no problem",
])
def test_a_plain_yes_is_still_a_yes(text):
    assert read_reply(text) == "yes"


@pytest.mark.parametrize("text", [
    "haan bukhar hai", "ok but my son will call", "kya time hai", "coming?",
    "", "   ",
])
def test_a_yes_with_something_else_in_it_goes_to_a_person(text):
    assert read_reply(text) == "unclear"


def _state():
    s = SystemState()
    s.patients["P1"] = Patient("P1", "Asha Rao", "9820011101", 1)
    return s


def test_an_unclear_reply_reaches_the_follow_up_list():
    s = _state()
    n = Notification("N1", "P1", "sms", "Are you coming?", "09:00")
    n.reply, n.replied_at = "haan bukhar hai", "09:30"
    s.notifications.append(n)
    rows = coord.follow_up_list(s, "10:00")["rows"]
    assert [r["kind"] for r in rows] == ["reply_unclear"]
    assert rows[0]["why"] == "haan bukhar hai"


def test_a_clear_reply_does_not():
    s = _state()
    n = Notification("N1", "P1", "sms", "Are you coming?", "09:00")
    n.reply, n.replied_at = "haan", "09:30"
    s.notifications.append(n)
    assert coord.follow_up_list(s, "10:00")["rows"] == []
