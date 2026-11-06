"""Tests for the real-time WebSocket endpoint (auth + snapshot on connect).

Run:  pytest -q tests/test_ws.py
"""

from __future__ import annotations

import os
import tempfile

# The store opens its datastore at import time; never touch the real one.
os.environ["CARE_DATA_PATH"] = os.path.join(tempfile.mkdtemp(), "care.xlsx")

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from api.main import app, manager
from services.security import make_token


@pytest.fixture()
def client():
    return TestClient(app)


def _token() -> str:
    token, _jti = make_token("admin", "admin")
    return token


def test_token_as_first_message_gets_snapshot(client):
    with client.websocket_connect("/ws") as ws:
        ws.send_text(_token())
        msg = ws.receive_json()
        assert msg["type"] == "snapshot"
        assert "state" in msg


def test_token_as_query_param_gets_snapshot(client):
    with client.websocket_connect(f"/ws?token={_token()}") as ws:
        assert ws.receive_json()["type"] == "snapshot"


def test_client_is_registered_then_removed_on_disconnect(client):
    before = manager.count
    with client.websocket_connect(f"/ws?token={_token()}") as ws:
        ws.receive_json()
        assert manager.count == before + 1
        ws.send_text("ping")
        assert ws.receive_json() == {"type": "pong"}
    assert manager.count == before


def test_invalid_token_is_closed_unauthorized(client):
    with client.websocket_connect("/ws") as ws:
        ws.send_text("not-a-jwt")
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
    assert exc.value.code == 1008
