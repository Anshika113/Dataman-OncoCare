"""Patient messaging: queue, delivery and replies.

Covers Bucket A / feature 4. Messages used to sit in the datastore marked
pending forever. They now move through real states via a driver, and a reply
means something — a YES on a waitlist offer is what fills the slot.
"""

from __future__ import annotations

import pytest

from engine import (
    SystemState, Doctor, Patient, NotificationStatus, SlotRegistry,
    AppointmentAllocator, waitlist as wl,
)
from services.messaging import Dispatcher, LogDriver, record_reply


class FailDriver:
    """A provider that is down."""
    name = "fail"

    def send(self, to, channel, body):
        return False, "provider unreachable"


class RecordingDriver(LogDriver):
    def __init__(self):
        self.sent = []

    def send(self, to, channel, body):
        self.sent.append((to, channel, body))
        return True, "ok"


@pytest.fixture
def state() -> SystemState:
    s = SystemState()
    s.doctors = {"D1": Doctor("D1", "Dr One", "oncology", 20)}
    s.patients = {
        "P1": Patient("P1", "Asha", "+91555001", 1),
        "P2": Patient("P2", "Bilal", "+91555002", 1),
    }
    return s


def _alloc(s):
    return AppointmentAllocator(s, SlotRegistry(s))


# --------------------------------------------------------------------------- #
# Queue and delivery
# --------------------------------------------------------------------------- #
def test_new_notification_starts_pending(state):
    n = state.add_notification("P1", "sms", "hello", "10:00")
    assert n.status == NotificationStatus.PENDING
    assert n.delivered_at == ""


def test_flush_delivers_and_timestamps(state):
    state.add_notification("P1", "sms", "hello", "10:00")
    out = Dispatcher(RecordingDriver()).flush(state, "10:01")
    assert out["sent"] == 1
    assert out["failed"] == 0
    assert out["driver"] == "log"
    n = state.notifications[-1]
    assert n.status == NotificationStatus.DELIVERED
    assert n.delivered_at == "10:01"


def test_flush_sends_to_the_patients_contact(state):
    drv = RecordingDriver()
    state.add_notification("P1", "whatsapp", "hello", "10:00")
    Dispatcher(drv).flush(state, "10:01")
    assert drv.sent == [("+91555001", "whatsapp", "hello")]


def test_a_failed_send_is_visible_not_silent(state):
    state.add_notification("P1", "sms", "hello", "10:00")
    out = Dispatcher(FailDriver()).flush(state, "10:01")
    assert out["failed"] == 1
    assert state.notifications[-1].status == NotificationStatus.FAILED


def test_flush_is_idempotent(state):
    state.add_notification("P1", "sms", "hello", "10:00")
    d = Dispatcher(RecordingDriver())
    d.flush(state, "10:01")
    assert d.flush(state, "10:02")["sent"] == 0


# --------------------------------------------------------------------------- #
# Replies
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("text,intent", [
    ("YES", "yes"), ("yes please", "yes"), ("haan", "yes"), ("ok", "yes"),
    ("no", "no"), ("Nahi", "no"), ("cannot make it", "no"),
    ("what time?", "unclear"), ("hmm", "unclear"),
])
def test_reply_intent(state, text, intent):
    n = state.add_notification("P1", "sms", "come at 11", "10:00")
    out = record_reply(state, n.id, text, "10:05")
    assert out["intent"] == intent


def test_reply_is_recorded_on_the_message(state):
    n = state.add_notification("P1", "sms", "come at 11", "10:00")
    record_reply(state, n.id, "YES", "10:05")
    assert state.notification(n.id).reply == "YES"
    assert state.notification(n.id).replied_at == "10:05"


def test_reply_to_an_unknown_message_is_an_error(state):
    assert record_reply(state, "nope", "YES", "10:05")["ok"] is False


def test_reply_is_logged(state):
    n = state.add_notification("P1", "sms", "come at 11", "10:00")
    record_reply(state, n.id, "YES", "10:05")
    assert "message_reply" in [lg.kind for lg in state.logs]


# --------------------------------------------------------------------------- #
# The loop that matters: an offer, a YES, a filled slot
# --------------------------------------------------------------------------- #
def test_waitlist_offer_is_tagged_so_a_yes_can_be_acted_on(state):
    r = wl.add(state, "P1", now="10:00", day=state.day(), doctor_id="D1")
    eid = r.data["entry"]["id"]
    wl.offer(state, [eid], "D1", "11:00", "11:30", now="10:00")
    n = state.notifications[-1]
    assert n.kind == "waitlist_offer"
    assert n.ref == eid


def test_yes_on_an_offer_fills_the_slot(state):
    a = wl.add(state, "P1", now="10:00", day=state.day(),
               doctor_id="D1").data["entry"]["id"]
    b = wl.add(state, "P2", now="10:00", day=state.day(),
               doctor_id="D1").data["entry"]["id"]
    wl.offer(state, [a, b], "D1", "11:00", "11:30", now="10:00")

    offer_to_a = next(n for n in state.notifications
                      if n.kind == "waitlist_offer" and n.ref == a)
    out = record_reply(state, offer_to_a.id, "YES", "10:03")
    assert out["intent"] == "yes"

    # the API layer acts on that intent; here we do the same call it makes
    assert wl.accept(state, a, _alloc(state), now="10:03").success
    assert state.waitlist_entry(a).status == "booked"
    assert state.waitlist_entry(b).status == "waiting"


# --------------------------------------------------------------------------- #
# WhatsApp: the channel the patients already read
# --------------------------------------------------------------------------- #
# The guide names WhatsApp twice as a low-cost channel to meet a clinic on.
# These tests pin the two things that would make it look done and not be: the
# number has to arrive in the shape the Cloud API accepts, and a number that
# cannot be fixed must fail visibly rather than be sent somewhere else.
import pytest

from services import messaging as msg


@pytest.mark.parametrize("raw,expected", [
    ("+91 98200 11101", "919820011101"),   # as a clerk types it
    ("+919820011101", "919820011101"),
    ("098200 11101", "919820011101"),      # local, with a trunk zero
    ("9820011101", "919820011101"),        # bare subscriber number
    ("+44 7700 900123", "447700900123"),   # already international
    ("", ""),
    ("not a phone", ""),
    ("12345", ""),                          # too short to be a mobile
])
def test_numbers_are_normalised_for_whatsapp(raw, expected):
    assert msg.to_e164(raw) == expected


def test_the_default_country_code_is_a_choice_not_an_assumption():
    assert msg.to_e164("9820011101", default_cc="44") == "449820011101"


def test_the_payload_is_the_shape_the_cloud_api_wants():
    import json

    sent = {}

    def transport(url, data, headers):
        sent["url"] = url
        sent["body"] = json.loads(data.decode())
        sent["auth"] = headers.get("Authorization")
        return True, "whatsapp accepted it (wamid.TEST)"

    d = msg.WhatsAppDriver("tok", "556677", transport=transport)
    ok, detail = d.send("+91 98200 11101", "whatsapp", "Your visit is at 10:30.")

    assert ok
    assert "wamid.TEST" in detail
    assert sent["url"].endswith("/556677/messages")
    assert sent["auth"] == "Bearer tok"
    assert sent["body"]["messaging_product"] == "whatsapp"
    assert sent["body"]["to"] == "919820011101"
    assert sent["body"]["text"]["body"] == "Your visit is at 10:30."


def test_an_unusable_number_fails_instead_of_being_sent():
    def transport(url, data, headers):      # pragma: no cover - must not run
        raise AssertionError("it tried to send to an unusable number")

    d = msg.WhatsAppDriver("tok", "556677", transport=transport)
    ok, detail = d.send("ask at reception", "whatsapp", "hello")

    assert ok is False
    assert "not a usable mobile number" in detail


def test_the_driver_is_chosen_by_the_environment(monkeypatch):
    for var in ("CARE_WHATSAPP_TOKEN", "CARE_WHATSAPP_PHONE_ID",
                "CARE_SMS_WEBHOOK"):
        monkeypatch.delenv(var, raising=False)
    assert msg.build_driver().name == "log"

    monkeypatch.setenv("CARE_SMS_WEBHOOK", "https://gateway.example/send")
    assert msg.build_driver().name == "webhook"

    monkeypatch.setenv("CARE_WHATSAPP_TOKEN", "tok")
    monkeypatch.setenv("CARE_WHATSAPP_PHONE_ID", "556677")
    assert msg.build_driver().name == "whatsapp"


def test_half_configured_whatsapp_does_not_take_over(monkeypatch):
    """A token with no phone id is a mistake, not a channel."""
    monkeypatch.delenv("CARE_SMS_WEBHOOK", raising=False)
    monkeypatch.setenv("CARE_WHATSAPP_TOKEN", "tok")
    monkeypatch.delenv("CARE_WHATSAPP_PHONE_ID", raising=False)
    assert msg.build_driver().name == "log"
