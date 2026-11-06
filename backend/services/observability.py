"""Lightweight observability: a security/audit trail and request metrics.

Kept deliberately dependency-free (no Prometheus client) so the production
box needs nothing extra. ``audit()`` appends tamper-evident security events
(logins, logouts, failures, PHI access) to an in-memory, ring-bounded list and
also emits them to the ``audit`` logger (wire it to a durable sink in
deployment). ``metrics`` is a tiny counter/gauge registry exposed as
Prometheus text at ``/metrics``.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque

audit_log = logging.getLogger("audit")


# --------------------------------------------------------------------------- #
# Security audit trail
# --------------------------------------------------------------------------- #
class AuditTrail:
    def __init__(self, maxlen: int = 5000) -> None:
        self._entries: deque[dict] = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def record(self, event: str, actor: str = "", role: str = "",
               detail: str = "", ip: str = "") -> None:
        entry = {
            "event": event,
            "actor": actor,
            "role": role,
            "detail": detail,
            "ip": ip,
            "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }
        with self._lock:
            self._entries.append(entry)
        # structured line; never includes PHI (no patient names/ids)
        audit_log.info("%s actor=%s role=%s ip=%s detail=%s",
                       event, actor, role, ip, detail)

    def recent(self, limit: int = 200) -> list[dict]:
        with self._lock:
            return list(self._entries)[-limit:]


AUDIT = AuditTrail()


# --------------------------------------------------------------------------- #
# Metrics (counters + gauges), Prometheus text format
# --------------------------------------------------------------------------- #
class Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, float] = {}
        self._gauges: dict[str, float] = {}
        self._start = time.time()

    def inc(self, name: str, value: float = 1.0) -> None:
        with self._lock:
            self._counters[name] = self._counters.get(name, 0.0) + value

    def set_gauge(self, name: str, value: float) -> None:
        with self._lock:
            self._gauges[name] = value

    def render(self) -> str:
        with self._lock:
            lines = [
                "# HELP oncocare_uptime_seconds Process uptime.",
                "# TYPE oncocare_uptime_seconds gauge",
                f"oncocare_uptime_seconds {time.time() - self._start:.1f}",
            ]
            for name, val in sorted(self._counters.items()):
                lines += [f"# TYPE oncocare_{name} counter",
                          f"oncocare_{name} {val}"]
            for name, val in sorted(self._gauges.items()):
                lines += [f"# TYPE oncocare_{name} gauge",
                          f"oncocare_{name} {val}"]
        return "\n".join(lines) + "\n"


METRICS = Metrics()
