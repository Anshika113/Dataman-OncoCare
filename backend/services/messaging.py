"""Actually sending the messages the engine writes.

Until now every notification sat in the datastore as ``pending`` forever, so
the system claimed a coordination it never performed. This module hands
queued messages to a driver and records what the driver said.

Three drivers ship, and which one runs is decided only by the environment:

``LogDriver``
    The default. Writes the message to the application log and marks it
    delivered. No credentials, no network — the demo works out of the box on
    a train, and the state transitions are real.

``WebhookDriver``
    Posts to whatever URL ``CARE_SMS_WEBHOOK`` names (a provider, a gateway,
    an internal relay). Enabled only when that variable is set, so nothing
    leaves the machine unless someone asked for it.

``WhatsAppDriver``
    The WhatsApp Cloud API, because that is the channel this clinic's
    patients already read. Needs ``CARE_WHATSAPP_TOKEN`` and
    ``CARE_WHATSAPP_PHONE_ID``; without both it is not constructed at all.

Replies come back through the API, not from here.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Optional

from engine.state import NotificationStatus
from engine import privacy
from engine.replies import read_reply

log = logging.getLogger("messaging")

#: Don't let a slow provider stall a request.
TIMEOUT_S = 4


class LogDriver:
    """Delivers to the application log. Always succeeds."""

    name = "log"

    def send(self, to: str, channel: str, body: str) -> tuple[bool, str]:
        log.info("[%s -> %s] %s", channel, to, body)
        return True, "delivered to the application log"


class WebhookDriver:
    """Posts each message to an external endpoint as JSON."""

    name = "webhook"

    def __init__(self, url: str, token: str = "") -> None:
        self.url = url
        self.token = token

    def send(self, to: str, channel: str, body: str) -> tuple[bool, str]:
        payload = json.dumps({"to": to, "channel": channel,
                              "body": body}).encode()
        req = urllib.request.Request(
            self.url, data=payload,
            headers={"Content-Type": "application/json",
                     **({"Authorization": f"Bearer {self.token}"}
                        if self.token else {})})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
                ok = 200 <= r.status < 300
                return ok, f"provider responded {r.status}"
        except (urllib.error.URLError, OSError, ValueError) as e:
            return False, f"provider unreachable: {e}"


#: WhatsApp Cloud API version. Pinned rather than floating: a message that
#: silently stops sending because Meta moved on is the worst failure mode here.
WHATSAPP_API = "v21.0"


def to_e164(raw: str, default_cc: str = "91") -> str:
    """A phone number in the shape WhatsApp will accept, or "" if it cannot.

    The datastore holds numbers the way a clerk typed them — "+91 98200
    11101", "098200 11101", "9820011101". WhatsApp wants digits only, with
    the country code and no plus. Guessing a country code is a real decision,
    so it is a named default rather than a silent assumption, and anything
    that still does not look like a number comes back empty for the caller to
    refuse rather than being sent somewhere wrong.
    """
    digits = "".join(ch for ch in (raw or "") if ch.isdigit())
    if not digits:
        return ""
    if raw.strip().startswith("+"):
        return digits
    # a local number written with a trunk zero
    if digits.startswith("0"):
        digits = digits.lstrip("0")
    if len(digits) == 10:                 # a bare subscriber number
        return default_cc + digits
    if len(digits) < 10:                  # too short to be a mobile
        return ""
    return digits


class WhatsAppDriver:
    """Sends through the WhatsApp Cloud API.

    ``transport`` exists so the payload can be tested without a network and
    without credentials; in production it is left alone.
    """

    name = "whatsapp"

    def __init__(self, token: str, phone_id: str, default_cc: str = "91",
                 transport=None) -> None:
        self.token = token
        self.phone_id = phone_id
        self.default_cc = default_cc
        self._transport = transport

    def endpoint(self) -> str:
        return f"https://graph.facebook.com/{WHATSAPP_API}/{self.phone_id}/messages"

    def payload(self, to: str, body: str) -> dict:
        return {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "text": {"preview_url": False, "body": body},
        }

    def send(self, to: str, channel: str, body: str) -> tuple[bool, str]:
        number = to_e164(to, self.default_cc)
        if not number:
            # better a visibly failed message than one sent to a wrong number
            return False, f"not a usable mobile number: {to!r}"
        data = json.dumps(self.payload(number, body)).encode()
        headers = {"Content-Type": "application/json",
                   "Authorization": f"Bearer {self.token}"}
        if self._transport is not None:
            return self._transport(self.endpoint(), data, headers)
        req = urllib.request.Request(self.endpoint(), data=data,
                                     headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
                raw = r.read().decode() or "{}"
                mid = ""
                try:
                    mid = (json.loads(raw).get("messages") or [{}])[0].get("id", "")
                except (ValueError, IndexError, AttributeError):
                    pass
                ok = 200 <= r.status < 300
                return ok, (f"whatsapp accepted it ({mid})" if mid
                            else f"whatsapp responded {r.status}")
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = (json.loads(e.read().decode() or "{}")
                          .get("error", {}).get("message", ""))
            except (ValueError, AttributeError, OSError):
                pass
            return False, f"whatsapp refused it ({e.code}){': ' + detail if detail else ''}"
        except (urllib.error.URLError, OSError, ValueError) as e:
            return False, f"whatsapp unreachable: {e}"


def build_driver():
    """Pick a driver from the environment.

    WhatsApp first, because it is the channel patients actually read; then a
    generic webhook for whatever gateway a hospital already pays for; then the
    log, so a machine with no credentials still runs the whole flow.
    """
    token = os.environ.get("CARE_WHATSAPP_TOKEN", "").strip()
    phone_id = os.environ.get("CARE_WHATSAPP_PHONE_ID", "").strip()
    if token and phone_id:
        return WhatsAppDriver(
            token, phone_id,
            os.environ.get("CARE_DEFAULT_COUNTRY_CODE", "91").strip() or "91")
    url = os.environ.get("CARE_SMS_WEBHOOK", "").strip()
    if url:
        return WebhookDriver(url, os.environ.get("CARE_SMS_TOKEN", "").strip())
    return LogDriver()


class Dispatcher:
    """Flushes queued notifications through a driver."""

    def __init__(self, driver=None) -> None:
        self.driver = driver or build_driver()

    @property
    def driver_name(self) -> str:
        return getattr(self.driver, "name", "unknown")

    def flush(self, state, now: str, limit: int = 50) -> dict:
        """Send every PENDING notification. Returns what happened.

        Consent is applied here, at the last possible moment, so it holds no
        matter which part of the engine wrote the message. Failures are
        recorded as FAILED rather than retried forever — a message the clinic
        thinks went out but did not is worse than one visibly marked failed.
        """
        sent, failed, blocked, scrubbed = 0, 0, 0, 0
        for n in state.notifications:
            if n.status != NotificationStatus.PENDING:
                continue
            if sent + failed + blocked >= limit:
                break
            patient = state.patient(n.patient_id)

            if not privacy.may_send(patient):
                n.status = NotificationStatus.BLOCKED
                blocked += 1
                log.info("message %s held back: no consent to message %s",
                         n.id, n.patient_id)
                continue

            body, changed = privacy.scrub(state, patient, n.body)
            if changed:
                # the message itself is rewritten, so the log shows what was
                # really sent rather than what the engine first composed
                n.body = body
                scrubbed += 1

            to = (patient.contact if patient and patient.contact
                  else n.patient_id)
            # the channel the message actually went out on, not the one the
            # engine guessed when it wrote it
            channel = (self.driver_name if self.driver_name == "whatsapp"
                       else n.channel or "sms")
            n.channel = channel
            ok, detail = self.driver.send(to, channel, body)
            if ok:
                n.status = NotificationStatus.DELIVERED
                n.delivered_at = now
                sent += 1
            else:
                n.status = NotificationStatus.FAILED
                failed += 1
                log.warning("message %s to %s failed: %s", n.id, to, detail)
        return {"sent": sent, "failed": failed, "blocked": blocked,
                "scrubbed": scrubbed, "driver": self.driver_name}


def record_reply(state, notification_id: str, text: str, now: str) -> dict:
    """Store a patient's answer and say what it means.

    Returns ``intent``: "yes", "no" or "unclear". Acting on it is the
    caller's job — this module never books or cancels anything.
    """
    n = state.notification(notification_id)
    if n is None:
        return {"ok": False, "error": "notification not found"}
    n.reply = text
    n.replied_at = now
    intent = read_reply(text)
    state.add_log("message_reply", n.ref, n.kind or "message",
                  f"{intent}: {text[:60]}", "patient replied", now)
    return {"ok": True, "intent": intent, "notification": n.to_dict()}
