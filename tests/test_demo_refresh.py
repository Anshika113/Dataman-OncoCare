"""The demo workbook has an anchor date, and it must not be allowed to rot.

Everything the seed builds — two finished days behind, a half-played today,
two booked days ahead — is relative to one date. Nothing recorded which date
that was, and the workbook persists in a Docker volume that is only seeded
when the file is missing.

Two days later the consequences were not subtle. The day seeded as "booked
only" had become today, nobody had checked in, and the watchdog had marked
every appointment absent: a 100% no-show rate on the doctor's home screen and
a headline metric of zero. The engine was right every step of the way; the
data had simply expired.

These tests pin the anchor, the staleness check, and the fact that it stays
off unless someone asks for it.
"""

from __future__ import annotations

import os

import pytest
from openpyxl import load_workbook

from engine.timeutils import today as _today, add_days
from storage import excel_store as store_mod
from storage.excel_store import Store, _seeded_for, demo_refresh_enabled
from storage.seed import build


@pytest.fixture
def book(tmp_path):
    return str(tmp_path / "care.xlsx")


@pytest.fixture(autouse=True)
def no_refresh(monkeypatch):
    """Default the flag off; each test opts in."""
    monkeypatch.delenv("CARE_DEMO_REFRESH", raising=False)
    yield


def _set_anchor(path, day):
    wb = load_workbook(path)
    ws = wb["meta"]
    for row in ws.iter_rows(min_row=2):
        if row[0].value == "seeded_for":
            row[1].value = day
    wb.save(path)


# --------------------------------------------------------------------------- #
# The anchor
# --------------------------------------------------------------------------- #
def test_the_seed_records_the_day_it_was_built_around(book):
    build(book)
    assert _seeded_for(book) == _today()


def test_a_workbook_with_no_meta_sheet_reads_as_stale(book, tmp_path):
    build(book)
    wb = load_workbook(book)
    del wb["meta"]
    wb.save(book)
    assert _seeded_for(book) == ""      # "" != today, so stale


def test_an_unreadable_workbook_reads_as_stale(tmp_path):
    broken = str(tmp_path / "broken.xlsx")
    with open(broken, "wb") as fh:
        fh.write(b"this is not a workbook")
    assert _seeded_for(broken) == ""


# --------------------------------------------------------------------------- #
# The flag is off unless asked for
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("value,expected", [
    ("true", True), ("True", True), ("1", True), ("yes", True), ("on", True),
    ("false", False), ("0", False), ("", False), ("no", False),
])
def test_the_flag_is_explicit(monkeypatch, value, expected):
    monkeypatch.setenv("CARE_DEMO_REFRESH", value)
    assert demo_refresh_enabled() is expected


def test_a_stale_workbook_is_left_alone_when_the_flag_is_off(book):
    build(book)
    _set_anchor(book, add_days(_today(), -5))
    Store(book)
    assert _seeded_for(book) != _today()     # untouched


# --------------------------------------------------------------------------- #
# What it does when it is on
# --------------------------------------------------------------------------- #
def test_a_stale_workbook_is_rebuilt(book, monkeypatch):
    monkeypatch.setenv("CARE_DEMO_REFRESH", "true")
    build(book)
    _set_anchor(book, add_days(_today(), -5))

    s = Store(book)

    assert _seeded_for(book) == _today()
    today_rows = [a for a in s.state.appointments.values()
                  if a.eff_date == _today()]
    assert today_rows, "today must have a list again"
    assert any(a.checked_in_at and a.started_at for a in today_rows), \
        "and it must be a day that has actually been played, not booked-only"


def test_a_fresh_workbook_is_not_rebuilt(book, monkeypatch):
    monkeypatch.setenv("CARE_DEMO_REFRESH", "true")
    build(book)
    before = os.path.getmtime(book)
    Store(book)
    assert os.path.getmtime(book) == before
    assert not os.path.exists(book + ".replaced")


def test_the_previous_workbook_is_kept_not_deleted(book, monkeypatch):
    """A reset that destroys the only copy is the wrong default."""
    monkeypatch.setenv("CARE_DEMO_REFRESH", "true")
    build(book)
    _set_anchor(book, add_days(_today(), -5))
    Store(book)
    assert os.path.exists(book + ".replaced")


def test_reseed_can_be_called_directly(book):
    build(book)
    _set_anchor(book, add_days(_today(), -5))
    s = Store(book)                      # flag off, so still stale
    assert _seeded_for(book) != _today()
    s.reseed()
    assert _seeded_for(book) == _today()


def test_a_rebuilt_workbook_can_still_prove_the_headline(book, monkeypatch):
    """The whole point of rebuilding: the two-day comparison works again."""
    from engine import outcomes
    monkeypatch.setenv("CARE_DEMO_REFRESH", "true")
    build(book)
    _set_anchor(book, add_days(_today(), -9))

    s = Store(book)
    # the clinic does not run every weekday, so ask the workbook which day
    # it last ran rather than assuming yesterday
    managed = outcomes.previous_day_with_data(s.state, _today())
    assert managed, "a rebuilt workbook must have a completed day behind it"
    r = outcomes.compare(s.state, managed)

    assert r["previous"] is not None
    chair = next(d for d in r["deltas"]
                 if d["metric"] == "gating.chair_min_released")
    assert chair["now"] > 0
    assert chair["better"] is True
