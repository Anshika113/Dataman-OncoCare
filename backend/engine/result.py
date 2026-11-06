"""Result types returned by engine operations."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class Action(str, Enum):
    BOOKED = "booked"
    INFO = "info"
    RESCHEDULED = "rescheduled"
    RESCHEDULE_OFFERED = "reschedule_offered"   # needs human / patient choice
    EMERGENCY_ASSIGNED = "emergency_assigned"
    EMERGENCY_WAITING = "emergency_waiting"
    SLOT_RELEASED = "slot_released"
    ROOM_FLAGGED = "room_flaged"
    OVERRUN_LOGGED = "overrun_logged"
    NEXT_PUSHED = "next_pushed"
    NO_SHOW = "no_show"
    REASSIGNED = "reassigned"
    CANCELLED = "cancelled"
    ROOM_RESTORED = "room_restored"
    EMERGENCY_COMPLETED = "emergency_completed"
    EMERGENCY_ASSIGNED_MANUAL = "emergency_assigned_manual"


class SeverityCode(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class EngineResult:
    """Uniform return value for every engine operation.

    ``success`` is True when the requested action completed without needing a
    human. ``actions`` records every discrete change the engine made (used for
    audit + real-time events). ``messages`` are human-readable lines for the UI.
    ``data`` carries extra structured payload (e.g. candidate slots to offer).
    """

    success: bool
    action: Action
    message: str
    severity: SeverityCode = SeverityCode.INFO
    actions: list[str] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)

    @property
    def messages(self) -> list[str]:
        return [self.message] + self.actions
