"""Background watchdog: advances the department clock and runs the engine's
time-based triggers (auto no-show, auto overrun) on a fixed interval, then
broadcasts the resulting events over WebSocket so the dashboard updates live.

A single-threaded loop (asyncio task) serialises clock advancement, which keeps
the Excel store safe (one writer at a time) and guarantees triggers fire in a
deterministic order.
"""

from __future__ import annotations

import asyncio
import logging

log = logging.getLogger("watchdog")


class Watchdog:
    def __init__(self, interval: float = 5.0,
                 no_show_min: int = 15, clock_fn=None) -> None:
        self.interval = interval
        self.no_show_min = no_show_min
        self.clock_fn = clock_fn  # callable() -> "HH:MM"
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def start(self, store, broadcast) -> None:
        self._store = store
        self._broadcast = broadcast
        self._stop.clear()
        self._task = asyncio.create_task(self._run())
        log.info("watchdog started (interval=%.1fs)", self.interval)

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run(self) -> None:
        from engine import advance_clock
        while not self._stop.is_set():
            try:
                now = self.clock_fn() if self.clock_fn else None
                if now is None:
                    from services.security import now as _now
                    now = _now()
                # run the pure engine op off the event loop
                summary = await asyncio.to_thread(
                    self._advance, now)
                if summary["no_shows"] or summary["overruns"] or summary["expired_leaves"]:
                    await self._broadcast({
                        "type": "clock",
                        "now": now,
                        "no_shows": summary["no_shows"],
                        "overruns": summary["overruns"],
                        "expired_leaves": summary["expired_leaves"],
                    })
                    await self._broadcast({"type": "state_refresh"})
            except Exception:  # noqa: BLE001 - watchdog must never die
                log.exception("watchdog tick failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.interval)
            except asyncio.TimeoutError:
                pass

    def _advance(self, now: str) -> dict:
        from engine import advance_clock, expire_leaves
        from services.security import today as _today
        # Take the shared mutation lock (via the event loop) so we never
        # interleave with an API request mutating SystemState. Runs in a worker
        # thread (asyncio.to_thread); the guard blocks this thread until the
        # loop grants the lock, then we mutate+save synchronously.
        from api.main import store_lock
        with store_lock():
            s = self._store.state
            # pin the engine's working day to the current department day so
            # day-scoped triggers (no-show/overrun/leave expiry) fire on the
            # correct day, even after a calendar rollover.
            s.active_day = _today()
            out = advance_clock(s, now, no_show_min=self.no_show_min)
            # auto-expire doctor leaves whose window has ended
            expired = expire_leaves(s, now)
            out["expired_leaves"] = expired
            if out["no_shows"] or out["overruns"] or expired:
                self._store._persist()
        return out
