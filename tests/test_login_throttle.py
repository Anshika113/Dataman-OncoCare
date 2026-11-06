"""The login budget counts failed attempts, not people signing in.

This is pinned because the first version counted every attempt, and the bug
only showed up in use: signing into the nine demo accounts one after another
— exactly what an evaluator does with the buttons on the login page — spent
the whole budget and locked the tenth out with "too many login attempts".

Rate limiting a login exists to make password guessing expensive. A
successful sign-in is not guessing, so charging for it buys nothing and
costs the people who typed the password correctly.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from services import security as sec


@pytest.fixture(autouse=True)
def clean_counters():
    sec._attempts.clear()
    yield
    sec._attempts.clear()


IP = "203.0.113.7"


def _fail(n, ip=IP):
    for _ in range(n):
        sec.login_throttled(ip)
        sec.login_failed(ip)


# --------------------------------------------------------------------------- #
# What the limiter is for
# --------------------------------------------------------------------------- #
def test_repeated_failures_are_eventually_refused():
    _fail(sec.settings.login_max_attempts)
    with pytest.raises(HTTPException) as e:
        sec.login_throttled(IP)
    assert e.value.status_code == 429


def test_one_short_of_the_budget_is_still_allowed():
    _fail(sec.settings.login_max_attempts - 1)
    sec.login_throttled(IP)          # must not raise


# --------------------------------------------------------------------------- #
# What it must not do
# --------------------------------------------------------------------------- #
def test_signing_in_does_not_spend_the_budget():
    """Nine demo accounts in a row, then a tenth. The original bug."""
    for _ in range(9):
        sec.login_throttled(IP)
        sec.login_succeeded(IP)
    sec.login_throttled(IP)          # the tenth must still get through


def test_a_success_clears_earlier_failures():
    _fail(sec.settings.login_max_attempts - 1)
    sec.login_succeeded(IP)
    assert IP not in sec._attempts
    _fail(sec.settings.login_max_attempts - 1)
    sec.login_throttled(IP)          # budget started over, so still allowed


def test_checking_the_budget_does_not_charge_for_it():
    for _ in range(sec.settings.login_max_attempts * 2):
        sec.login_throttled(IP)
    assert sec._attempts.get(IP) in (None, )


# --------------------------------------------------------------------------- #
# Scope and housekeeping
# --------------------------------------------------------------------------- #
def test_one_network_being_blocked_does_not_block_another():
    _fail(sec.settings.login_max_attempts)
    with pytest.raises(HTTPException):
        sec.login_throttled(IP)
    sec.login_throttled("198.51.100.4")      # a different IP is unaffected


def test_failures_age_out_of_the_window(monkeypatch):
    clock = [1_000_000.0]
    monkeypatch.setattr(sec.time, "time", lambda: clock[0])
    _fail(sec.settings.login_max_attempts)
    with pytest.raises(HTTPException):
        sec.login_throttled(IP)
    clock[0] += sec.settings.login_window_sec + 1
    sec.login_throttled(IP)                  # the window has moved on


def test_an_ip_that_stops_failing_is_forgotten(monkeypatch):
    """Otherwise the process accumulates one empty deque per IP, forever."""
    clock = [1_000_000.0]
    monkeypatch.setattr(sec.time, "time", lambda: clock[0])
    _fail(1)
    assert IP in sec._attempts
    clock[0] += sec.settings.login_window_sec + 1
    sec.login_throttled(IP)
    assert IP not in sec._attempts
