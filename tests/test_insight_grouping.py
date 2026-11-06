"""Three identical warnings are one signal, not three.

Five clinics running without slack in the same hour produced five cards that
differed only in the doctor's name, each with the same recommendation. A wall
of those buries the one insight that is not like the others, which is the
opposite of what a proactive panel is for.

Collapsing them is only safe if nothing is lost, so that is what these tests
check: every affected appointment survives, the worst severity wins, the
resources are still named, and two genuinely different signals never merge.
"""

from __future__ import annotations

import pytest

from engine.proactive import (
    Insight, InsightKind, InsightSeverity, GROUP_FROM, _group, _names,
)


def _ins(name, key="k", sev=InsightSeverity.WARNING, affected=(),
         title_prefix="No slack with"):
    return Insight(
        kind=InsightKind.QUEUE_OVERFLOW,
        severity=sev,
        title=f"{title_prefix} {name}",
        detail=f"{name} is fully booked.",
        action="Open an extra slot.",
        resource_id=name.replace(" ", "").lower(),
        resource_name=name,
        affected=list(affected),
        metric={"window_min": 60},
        horizon_min=60,
        group_key=key,
        group_title="No slack in {n} clinics",
        group_detail="{names} are fully booked.",
    )


# --------------------------------------------------------------------------- #
# Naming the resources
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("names,expected", [
    ([], ""),
    (["A"], "A"),
    (["A", "B"], "A and B"),
    (["A", "B", "C"], "A, B and C"),
    (["A", "B", "C", "D"], "A, B, C and 1 others"),
    (["A", "B", "C", "D", "E"], "A, B, C and 2 others"),
])
def test_resources_are_named_until_naming_stops_helping(names, expected):
    assert _names(names) == expected


def test_blank_names_are_not_counted():
    assert _names(["A", "", "B"]) == "A and B"


# --------------------------------------------------------------------------- #
# When it groups, and when it leaves things alone
# --------------------------------------------------------------------------- #
def test_a_repeated_signal_collapses_to_one_card():
    out = _group([_ins("Dr A"), _ins("Dr B"), _ins("Dr C")])
    assert len(out) == 1
    assert out[0].title == "No slack in 3 clinics"
    assert out[0].detail == "Dr A, Dr B and Dr C are fully booked."
    assert out[0].action == "Open an extra slot."


def test_two_of_a_kind_are_clearer_named_than_counted():
    out = _group([_ins("Dr A"), _ins("Dr B")])
    assert len(out) == 2
    assert out[0].title == "No slack with Dr A"


def test_different_signals_never_merge():
    out = _group([
        _ins("Dr A", key="doctors"), _ins("Dr B", key="doctors"),
        _ins("Dr C", key="doctors"),
        _ins("Room 1", key="rooms"), _ins("Room 2", key="rooms"),
    ])
    assert len(out) == 3                       # one group + two ungrouped rooms
    assert out[0].title == "No slack in 3 clinics"


def test_an_insight_with_no_group_key_stands_alone():
    out = _group([_ins("Dr A", key=""), _ins("Dr B", key=""),
                  _ins("Dr C", key="")])
    assert len(out) == 3


def test_an_insight_with_no_group_phrasing_is_never_collapsed():
    """A group_key without a title would produce a card with no words."""
    items = [_ins(f"Dr {c}") for c in "ABC"]
    for i in items:
        i.group_title = ""
    assert len(_group(items)) == 3


# --------------------------------------------------------------------------- #
# Nothing may be lost
# --------------------------------------------------------------------------- #
def test_every_affected_appointment_survives():
    out = _group([
        _ins("Dr A", affected=["A1", "A2"]),
        _ins("Dr B", affected=["B1"]),
        _ins("Dr C", affected=["C1", "C2"]),
    ])
    assert out[0].affected == ["A1", "A2", "B1", "C1", "C2"]


def test_an_appointment_touching_two_resources_is_listed_once():
    out = _group([
        _ins("Dr A", affected=["SHARED", "A1"]),
        _ins("Dr B", affected=["SHARED"]),
        _ins("Dr C", affected=["C1"]),
    ])
    assert out[0].affected == ["SHARED", "A1", "C1"]


def test_the_worst_severity_wins():
    out = _group([
        _ins("Dr A", sev=InsightSeverity.WARNING),
        _ins("Dr B", sev=InsightSeverity.CRITICAL),
        _ins("Dr C", sev=InsightSeverity.WARNING),
    ])
    assert out[0].severity == InsightSeverity.CRITICAL


def test_the_group_says_how_many_it_speaks_for():
    out = _group([_ins("Dr A"), _ins("Dr B"), _ins("Dr C")])
    assert out[0].metric["grouped"] == 3
    assert out[0].metric["resources"] == ["Dr A", "Dr B", "Dr C"]
    assert out[0].metric["window_min"] == 60     # the original metric survives


def test_a_group_claims_no_single_resource():
    """resource_name drives a 'Resource: X' line, which would be a lie here."""
    out = _group([_ins("Dr A"), _ins("Dr B"), _ins("Dr C")])
    assert out[0].resource_id == ""
    assert out[0].resource_name == ""


def test_order_of_first_appearance_is_kept():
    out = _group([
        _ins("Room 1", key="rooms"),
        _ins("Dr A", key="doctors"), _ins("Dr B", key="doctors"),
        _ins("Dr C", key="doctors"),
    ])
    assert out[0].resource_name == "Room 1"
    assert out[1].title == "No slack in 3 clinics"


def test_the_threshold_is_the_documented_one():
    assert GROUP_FROM == 3
    assert len(_group([_ins(f"Dr {c}") for c in "AB"])) == 2
    assert len(_group([_ins(f"Dr {c}") for c in "ABC"])) == 1
