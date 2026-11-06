"""The assistant through the API, against the seeded workbook.

Sarvam is replaced here, so this proves the wiring around the model and says
nothing about how well the model reads a sentence. That is what
``scripts/eval_ask.py`` is for.
"""

from __future__ import annotations

import os
import tempfile

# The store opens its datastore at import time; never touch the real one.
os.environ.setdefault("CARE_DATA_PATH",
                      os.path.join(tempfile.mkdtemp(), "care.xlsx"))

import httpx
import pytest
from fastapi.testclient import TestClient

from api.main import STORE, app
from engine.state import AppointmentStatus
from services import sarvam
from services.security import make_token


@pytest.fixture()
def client():
    return TestClient(app)


def _headers(username="admin", role="admin", doctor_id=""):
    token, _ = make_token(username, role, doctor_id=doctor_id)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def model(monkeypatch):
    """A stand-in for Sarvam that records exactly what it was sent."""
    sent = []
    answer = {"value": {"choice": "none"}}

    def choose(sentence, doctors, catalogue, choices):
        sent.append({"sentence": sentence, "doctors": doctors,
                     "catalogue": catalogue})
        if isinstance(answer["value"], Exception):
            raise answer["value"]
        return answer["value"]

    monkeypatch.setenv("CARE_SARVAM_KEY", "test")
    monkeypatch.setattr(sarvam, "choose", choose)
    return sent, answer


def _ask(client, question, **who):
    r = client.post("/api/ask", json={"question": question}, headers=_headers(**who))
    assert r.status_code == 200
    return r.json()


def _a_live_visit():
    """A booked visit for someone with only one visit today."""
    day = STORE.state.day()
    live = [a for a in STORE.state.appointments.values()
            if a.eff_date == day and a.status in (AppointmentStatus.BOOKED,
                                                  AppointmentStatus.RESCHEDULED)]
    today = [a.patient_id for a in STORE.state.appointments.values()
             if a.eff_date == day]
    return next(a for a in live if today.count(a.patient_id) == 1)


# --------------------------------------------------------------------------- #
# Off by default
# --------------------------------------------------------------------------- #
def test_with_no_key_nothing_is_sent_and_the_matcher_answers(client, monkeypatch):
    monkeypatch.delenv("CARE_SARVAM_KEY", raising=False)
    monkeypatch.setattr(sarvam, "choose",
                        lambda *a: pytest.fail("must not call the model"))
    a = _ask(client, "who is waiting longest")
    assert a["kind"] == "view" and a["via"] == "local"
    caps = client.get("/api/ask/capabilities", headers=_headers()).json()
    assert caps == {"model": False}


def test_voice_is_refused_with_no_key(client, monkeypatch):
    monkeypatch.delenv("CARE_SARVAM_KEY", raising=False)
    r = client.post("/api/ask/voice", headers=_headers(),
                    files={"file": ("clip.wav", b"RIFF", "audio/wav")})
    assert r.status_code == 503


# --------------------------------------------------------------------------- #
# What leaves the building
# --------------------------------------------------------------------------- #
def test_a_clinical_question_never_reaches_the_model(client, model):
    sent, _ = model
    a = _ask(client, "sabse bimar kaun hai")
    assert a["kind"] == "refused"
    assert sent == []


def test_interface_help_never_reaches_the_model(client, model):
    sent, _ = model
    assert _ask(client, "how do I hold a treatment")["kind"] == "help"
    assert sent == []


def test_the_model_gets_the_sentence_with_the_name_masked(client, model):
    sent, _ = model
    _ask(client, "Meera ko 5 minute aur do")
    assert sent[0]["sentence"] == "PATIENT_1 ko 5 minute aur do"


def test_the_model_is_never_given_a_patient_record(client, model):
    sent, _ = model
    _ask(client, "any chairs free")
    blob = str(sent[0]["doctors"]) + str(sent[0]["catalogue"])
    for p in STORE.state.patients.values():
        assert p.name not in blob


# --------------------------------------------------------------------------- #
# When Sarvam fails
# --------------------------------------------------------------------------- #
def test_a_failed_call_falls_back_to_the_matcher(client, model):
    _, answer = model
    answer["value"] = sarvam.SarvamError("down")
    a = _ask(client, "who is waiting longest")
    assert a["kind"] == "view" and a["view"] == "waiting" and a["via"] == "local"


def test_a_real_timeout_becomes_the_fallback_error(monkeypatch):
    monkeypatch.setenv("CARE_SARVAM_KEY", "test")

    def boom(*a, **k):
        raise httpx.ConnectTimeout("slow")

    monkeypatch.setattr(httpx, "post", boom)
    with pytest.raises(sarvam.SarvamError):
        sarvam.choose("x", [], [], ["none"])
    with pytest.raises(sarvam.SarvamError):
        sarvam.transcribe(b"RIFF")


@pytest.mark.parametrize("content,expected", [
    ('{"choice": "extend", "minutes": 10}', {"choice": "extend", "minutes": 10}),
    ('```json\n{"choice": "none"}\n```', {"choice": "none"}),
])
def test_the_reply_is_parsed(monkeypatch, content, expected):
    class R:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": content}}]}

    monkeypatch.setenv("CARE_SARVAM_KEY", "test")
    monkeypatch.setattr(httpx, "post", lambda *a, **k: R())
    assert sarvam.choose("x", [], [], ["none"]) == expected


@pytest.mark.parametrize("content", [None, "", "not json", "[1]"])
def test_a_reply_that_is_not_an_answer_is_a_failure(monkeypatch, content):
    class R:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": content}}]}

    monkeypatch.setenv("CARE_SARVAM_KEY", "test")
    monkeypatch.setattr(httpx, "post", lambda *a, **k: R())
    with pytest.raises(sarvam.SarvamError):
        sarvam.choose("x", [], [], ["none"])


# --------------------------------------------------------------------------- #
# A proposal changes nothing until the ordinary endpoint is called
# --------------------------------------------------------------------------- #
def test_proposing_changes_nothing_and_confirming_can_be_undone(client, model):
    _, answer = model
    visit = _a_live_visit()
    name = STORE.state.patient(visit.patient_id).name
    start, end = visit.slot_start, visit.slot_end
    answer["value"] = {"choice": "extend", "patient": name, "minutes": 7}

    a = _ask(client, f"give {name} 7 more minutes")
    assert a["kind"] == "proposal"
    assert a["proposal"]["appointment_id"] == visit.id
    assert (visit.slot_start, visit.slot_end) == (start, end)

    done = client.post(f"/api/appointments/{visit.id}/extend",
                       json={"minutes": 7}, headers=_headers()).json()
    assert done["success"]
    assert visit.slot_end != end

    undone = client.post(f"/api/actions/{done['data']['action_id']}/undo",
                         headers=_headers()).json()
    assert undone["success"]
    assert (visit.slot_start, visit.slot_end) == (start, end)


def test_urgency_is_answered_from_the_recorded_queue(client):
    a = _ask(client, "who is most urgent")
    assert a["view"] == "emergency_queue"
    assert a["source"] == "GET /api/queue"
