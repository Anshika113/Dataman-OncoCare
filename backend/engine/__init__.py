"""Pure, I/O-free scheduling engine for the cancer care department.

The engine operates on a single mutable :class:`SystemState` and returns
:class:`EngineResult` objects. It performs no I/O, no DB calls, and no time
reading (time is injected explicitly), which makes it fully deterministic and
unit-testable.
"""

from .state import (
    SystemState,
    Slot,
    Doctor,
    ChemRoom,
    Drug,
    Patient,
    Appointment,
    AppointmentType,
    AppointmentStatus,
    RoomType,
    DoctorStatus,
    RoomStatus,
    Emergency,
    Severity,
    LogEntry,
    Notification,
    NotificationStatus,
    TimeWindow,
    LeaveEntry,
    new_id,
)
from .result import EngineResult, Action, SeverityCode
from .timeutils import to_min, to_hhmm, add_min, overlaps
from .slots import SlotRegistry
from .conflict import ConflictDetector
from .allocator import RoomAllocator, AppointmentAllocator
from .emergency import PriorityQueue, resolve_emergencies, build_queue
from .proactive import (
    analyze,
    Insight,
    InsightKind,
    InsightSeverity,
    DEFAULT_HORIZON_MIN,
)
from .handlers import (
    handle_doctor_sick_leave,
    handle_chemo_overrun,
    handle_emergency_pair,
    handle_room_breakdown,
    handle_no_show,
    handle_doctor_take_leave,
    handle_doctor_cancel_leave,
    handle_doctor_mark_available,
    expire_leaves,
    advance_clock,
    handle_cancel_appointment,
    handle_room_restore,
    handle_emergency_assign,
    handle_emergency_complete,
)

__all__ = [
    "SystemState",
    "Slot",
    "Doctor",
    "ChemRoom",
    "Drug",
    "Patient",
    "Appointment",
    "AppointmentType",
    "AppointmentStatus",
    "RoomType",
    "DoctorStatus",
    "RoomStatus",
    "Emergency",
    "Severity",
    "LogEntry",
    "Notification",
    "NotificationStatus",
    "EngineResult",
    "Action",
    "SeverityCode",
    "TimeWindow",
    "LeaveEntry",
    "new_id",
    "SlotRegistry",
    "overlaps",
    "to_min",
    "to_hhmm",
    "add_min",
    "ConflictDetector",
    "RoomAllocator",
    "AppointmentAllocator",
    "PriorityQueue",
    "resolve_emergencies",
    "build_queue",
    "handle_doctor_sick_leave",
    "handle_chemo_overrun",
    "handle_emergency_pair",
    "handle_room_breakdown",
    "handle_no_show",
    "handle_doctor_take_leave",
    "handle_doctor_cancel_leave",
    "handle_doctor_mark_available",
    "expire_leaves",
    "advance_clock",
    "handle_cancel_appointment",
    "handle_room_restore",
    "handle_emergency_assign",
    "handle_emergency_complete",
    "analyze",
    "Insight",
    "InsightKind",
    "InsightSeverity",
    "DEFAULT_HORIZON_MIN",
]
