"""WebSocket connection registry for real-time dashboard pushes.

Every client is authenticated (JWT) before it is admitted. Broadcasts send
to all clients concurrently with a per-client send timeout so one slow or
dead client can never stall the others.
"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import WebSocket

log = logging.getLogger("ws")

SEND_TIMEOUT = 3.0  # seconds; a client that can't drain its buffer is dropped


class ConnectionManager:
    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()

    def connect(self, ws: WebSocket) -> None:
        """Register an already-accepted socket. The endpoint accepts it first
        because the JWT can arrive as the first message."""
        self._clients.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self._clients.discard(ws)

    async def broadcast(self, message: dict) -> None:
        if not self._clients:
            return
        data = json.dumps(message)
        dead = []

        async def _send(ws: WebSocket) -> None:
            try:
                await asyncio.wait_for(ws.send_text(data), timeout=SEND_TIMEOUT)
            except Exception:  # noqa: BLE001
                dead.append(ws)

        await asyncio.gather(*(_send(ws) for ws in list(self._clients)),
                             return_exceptions=True)
        for ws in dead:
            self._clients.discard(ws)
        if dead:
            log.info("dropped %d dead websocket client(s)", len(dead))

    @property
    def count(self) -> int:
        return len(self._clients)
