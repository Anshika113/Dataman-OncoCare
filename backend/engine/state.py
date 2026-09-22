"""Core domain model for the cancer care scheduling engine.

All entities are plain dataclasses with ``to_dict`` / ``from_dict`` so the
storage layer can (de)serialise them to/from Excel rows. Ids are strings.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Optional


def new_id(prefix: str) -> str:
    """Short unique id with a readable prefix, e.g. ``DOC-1a2b3c``."""
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


# --------------------------------------------------------------------------- #
# Enums
# --------------------------------------------------------------------------- #
class AppointmentType(str, Enum):
    CONSULT = "consult"
    CHEMO = "chemo"
    EMERGENCY = "emergency"


class AppointmentStatus(str, Enum):
    BOOKED = "booked"
    ACTIVE = "active"
    OVERRUN = "overrun"
    NO_SHOW = "no_show"
    RESCHEDULED = "rescheduled"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    VISITED = "visited"          # patient checked in and was seen (past visit)
    EMERGENCY_WAITING = "emergency_waiting"


class RoomType(str, Enum):
    INFUSION_CHAIR = "infusion_chair"
    ISOLATION = "isolation"
    EXAM = "exam"


class DoctorStatus(str, Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    ON_LEAVE = "on_leave"
    PARTIALLY_UNAVAILABLE = "partially_unavailable"  # has a time-bounded leave


class RoomStatus(str, Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class Severity(int, Enum):
    """5-level emergency priority. 5 = most critical."""

    CRITICAL = 5
    URGENT = 4
    HIGH = 3
    MODERATE = 2
    LOW = 1

    @classmethod
    def from_int(cls, v: int) -> "Severity":
        v = max(1, min(5, int(v)))
        return cls(v)


class NotificationStatus(str, Enum):
    PENDING = "pending"
    SENT = "sent"
    FAILED = "failed"


# --------------------------------------------------------------------------- #
# Time helpers
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class TimeWindow:
    """Inclusive [start, end] clock window as HH:MM strings, e.g. 09:00-15:00."""

    start: str = "00:00"
    end: str = "23:59"

    def __post_init__(self) -> None:
        object.__setattr__(self, "start", _norm(self.start))
        object.__setattr__(self, "end", _norm(self.end))

    def contains(self, hhmm: str) -> bool:
        t = _norm(hhmm)
        return self.start <= t <= self.end


def _norm(hhmm: str) -> str:
    parts = hhmm.split(":")
    h, m = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
    return f"{h:02d}:{m:02d}"


# --------------------------------------------------------------------------- #
# Entities
# --------------------------------------------------------------------------- #
@dataclass
class Slot:
    """A single atomic time unit for a resource (doctor or room)."""

    start: str  # "09:00"
    end: str    # "09:30"
    appointment_id: Optional[str] = None  # None == free

    @property
    def is_free(self) -> bool:
        return self.appointment_id is None


@dataclass
class LeaveEntry:
    """A time-bounded absence for a doctor.

    ``start``/``end`` are HH:MM on the working day. A doctor is *unavailable*
    during the union of their active leaves. When a leave's ``end`` passes
    (or it is cancelled), the doctor becomes available again.
    """

    id: str
    start: str = "08:00"
    end: str = "18:00"
    reason: str = "leave"
    date: str = ""              # YYYY-MM-DD (which day this leave applies to)
    created_at: str = ""
    cancelled: bool = False

    @property
    def active(self) -> bool:
        return not self.cancelled

    def covers(self, t: str) -> bool:
        if self.cancelled:
            return False
        return self.start <= _norm(t) <= self.end

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "start": self.start, "end": self.end,
            "reason": self.reason, "date": self.date,
            "created_at": self.created_at,
            "cancelled": int(self.cancelled),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "LeaveEntry":
        return cls(
            id=d["id"], start=d.get("start", "08:00"), end=d.get("end", "18:00"),
            reason=d.get("reason", "leave"), date=d.get("date", ""),
            created_at=d.get("created_at", ""),
            cancelled=bool(int(d.get("cancelled", 0))),
        )


@dataclass
class Doctor:
    id: str
    name: str
    specialty: str
    daily_cap: int = 20
    status: DoctorStatus = DoctorStatus.AVAILABLE
    backup_compatible: list[str] = field(default_factory=list)  # specialties
    leave_reason: str = ""
    leaves: list["LeaveEntry"] = field(default_factory=list)

    @property
    def active_leaves(self) -> list["LeaveEntry"]:
        return [l for l in self.leaves if l.active]

    @property
    def on_leave(self) -> bool:
        return self.status == DoctorStatus.ON_LEAVE

    def unavailable_windows(self) -> list[tuple[str, str]]:
        """[start,end) windows when this doctor cannot be booked.

        A full on_leave day returns the whole working day; otherwise returns
        the active time-bounded leaves.
        """
        if self.on_leave:
            return [("08:00", "18:00")]
        return [(l.start, l.end) for l in self.active_leaves]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "specialty": self.specialty,
            "daily_cap": self.daily_cap,
            "status": self.status.value,
            "backup_compatible": ",".join(self.backup_compatible),
            "leave_reason": self.leave_reason,
            "leaves": [l.to_dict() for l in self.leaves],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Doctor":
        return cls(
            id=d["id"],
            name=d["name"],
            specialty=d["specialty"],
            daily_cap=int(d.get("daily_cap", 20)),
            status=DoctorStatus(d.get("status", "available")),
            backup_compatible=[s for s in (d.get("backup_compatible") or "").split(",") if s],
            leave_reason=d.get("leave_reason", ""),
            leaves=[LeaveEntry.from_dict(l) for l in (d.get("leaves") or [])],
        )


@dataclass
class ChemRoom:
    id: str
    name: str
    type: RoomType = RoomType.INFUSION_CHAIR
    equipment: list[str] = field(default_factory=list)
    status: RoomStatus = RoomStatus.AVAILABLE
    available_until: str = ""  # HH:MM; "" == available all day

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type.value,
            "equipment": ",".join(self.equipment),
            "status": self.status.value,
            "available_until": self.available_until,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ChemRoom":
        return cls(
            id=d["id"],
            name=d["name"],
            type=RoomType(d.get("type", "infusion_chair")),
            equipment=[e for e in (d.get("equipment") or "").split(",") if e],
            status=RoomStatus(d.get("status", "available")),
            available_until=d.get("available_until", ""),
        )


@dataclass
class Drug:
    id: str
    name: str
    time_window: TimeWindow = field(default_factory=TimeWindow)
    grace_minutes: int = 10
    required_equipment: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "tw_start": self.time_window.start,
            "tw_end": self.time_window.end,
            "grace_minutes": self.grace_minutes,
            "required_equipment": ",".join(self.required_equipment),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Drug":
        return cls(
            id=d["id"],
            name=d["name"],
            time_window=TimeWindow(
                start=d.get("tw_start", "00:00"), end=d.get("tw_end", "23:59")
            ),
            grace_minutes=int(d.get("grace_minutes", 10)),
            required_equipment=[e for e in (d.get("required_equipment") or "").split(",") if e],
        )


@dataclass
class Patient:
    id: str
    name: str
    contact: str
    priority_tier: int = 1
    # registration / clinical details
    dob: str = ""            # YYYY-MM-DD
    age: str = ""
    gender: str = ""         # male / female / other
    blood_group: str = ""
    mr_number: str = ""
    diagnosis: str = ""
    stage: str = ""
    allergies: str = ""
    insurance: str = ""
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "contact": self.contact,
            "priority_tier": self.priority_tier,
            "dob": self.dob,
            "age": self.age,
            "gender": self.gender,
            "blood_group": self.blood_group,
            "mr_number": self.mr_number,
            "diagnosis": self.diagnosis,
            "stage": self.stage,
            "allergies": self.allergies,
            "insurance": self.insurance,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Patient":
        return cls(
            id=d["id"],
            name=d["name"],
            contact=d.get("contact", ""),
            priority_tier=int(d.get("priority_tier", 1)),
            dob=d.get("dob", ""),
            age=d.get("age", ""),
            gender=d.get("gender", ""),
            blood_group=d.get("blood_group", ""),
            mr_number=d.get("mr_number", ""),
            diagnosis=d.get("diagnosis", ""),
            stage=d.get("stage", ""),
            allergies=d.get("allergies", ""),
            insurance=d.get("insurance", ""),
            notes=d.get("notes", ""),
        )


@dataclass
class Appointment:
    id: str
    patient_id: str
    doctor_id: str
    slot_start: str
    slot_end: str
    type: AppointmentType = AppointmentType.CONSULT
    status: AppointmentStatus = AppointmentStatus.BOOKED
    room_id: Optional[str] = None
    drug_id: Optional[str] = None
    severity: Severity = Severity.LOW
    buffer_before: int = 0
    buffer_after: int = 0
    checked_in: bool = False
    reschedule_reason: str = ""
    visit_count: int = 0          # how many times the patient has been seen
    last_visited: str = ""        # HH:MM (or ISO date) of the most recent visit

    @property
    def is_chemo(self) -> bool:
        return self.type == AppointmentType.CHEMO

    @property
    def is_revisit(self) -> bool:
        return self.visit_count >= 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "patient_id": self.patient_id,
            "doctor_id": self.doctor_id,
            "slot_start": self.slot_start,
            "slot_end": self.slot_end,
            "type": self.type.value,
            "status": self.status.value,
            "room_id": self.room_id or "",
            "drug_id": self.drug_id or "",
            "severity": int(self.severity.value),
            "buffer_before": self.buffer_before,
            "buffer_after": self.buffer_after,
            "checked_in": int(self.checked_in),
            "reschedule_reason": self.reschedule_reason,
            "visit_count": self.visit_count,
            "last_visited": self.last_visited,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Appointment":
        return cls(
            id=d["id"],
            patient_id=d["patient_id"],
            doctor_id=d["doctor_id"],
            slot_start=d["slot_start"],
            slot_end=d["slot_end"],
            type=AppointmentType(d.get("type", "consult")),
            status=AppointmentStatus(d.get("status", "booked")),
            room_id=d.get("room_id") or None,
            drug_id=d.get("drug_id") or None,
            severity=Severity.from_int(int(d.get("severity", 1))),
            buffer_before=int(d.get("buffer_before", 0)),
            buffer_after=int(d.get("buffer_after", 0)),
            checked_in=bool(int(d.get("checked_in", 0))),
            reschedule_reason=d.get("reschedule_reason", ""),
            visit_count=int(d.get("visit_count", 0)),
            last_visited=d.get("last_visited", ""),
        )


@dataclass
class Emergency:
    id: str
    patient_id: str
    severity: Severity
    created_at: str
    subscore: int = 0
    assigned_doctor_id: Optional[str] = None
    status: str = "waiting"  # waiting | assigned | completed

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "patient_id": self.patient_id,
            "severity": int(self.severity.value),
            "created_at": self.created_at,
            "subscore": self.subscore,
            "assigned_doctor_id": self.assigned_doctor_id or "",
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Emergency":
        return cls(
            id=d["id"],
            patient_id=d["patient_id"],
            severity=Severity.from_int(int(d.get("severity", 1))),
            created_at=d.get("created_at", ""),
            subscore=int(d.get("subscore", 0)),
            assigned_doctor_id=d.get("assigned_doctor_id") or None,
            status=d.get("status", "waiting"),
        )


@dataclass
class LogEntry:
    id: str
    kind: str
    appointment_id: str
    before: str
    after: str
    reason: str
    at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Notification:
    id: str
    patient_id: str
    channel: str
    body: str
    sent_at: str
    status: NotificationStatus = NotificationStatus.PENDING

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d


# --------------------------------------------------------------------------- #
# Aggregate state
# --------------------------------------------------------------------------- #
@dataclass
class SystemState:
    """The full in-memory snapshot the engine reasons over."""

    doctors: dict[str, Doctor] = field(default_factory=dict)
    rooms: dict[str, ChemRoom] = field(default_factory=dict)
    drugs: dict[str, Drug] = field(default_factory=dict)
    patients: dict[str, Patient] = field(default_factory=dict)
    appointments: dict[str, Appointment] = field(default_factory=dict)
    emergencies: dict[str, Emergency] = field(default_factory=dict)
    logs: list[LogEntry] = field(default_factory=list)
    notifications: list[Notification] = field(default_factory=list)

    # --- lookup helpers ---------------------------------------------------- #
    def doctor(self, did: str) -> Optional[Doctor]:
        return self.doctors.get(did)

    def room(self, rid: str) -> Optional[ChemRoom]:
        return self.rooms.get(rid)

    def drug(self, gid: str) -> Optional[Drug]:
        return self.drugs.get(gid)

    def patient(self, pid: str) -> Optional[Patient]:
        return self.patients.get(pid)

    def appointment(self, aid: str) -> Optional[Appointment]:
        return self.appointments.get(aid)

    # --- mutation helpers -------------------------------------------------- #
    def add_log(self, kind: str, appointment_id: str, before: str, after: str,
                reason: str, at: str) -> None:
        self.logs.append(LogEntry(
            id=new_id("LOG"), kind=kind, appointment_id=appointment_id,
            before=before, after=after, reason=reason, at=at,
        ))

    def add_notification(self, patient_id: str, channel: str, body: str,
                         at: str) -> Notification:
        n = Notification(
            id=new_id("NTF"), patient_id=patient_id, channel=channel,
            body=body, sent_at=at, status=NotificationStatus.SENT,
        )
        self.notifications.append(n)
        return n

    def active_appointments(self, doctor_id: Optional[str] = None) -> list[Appointment]:
        out = [
            a for a in self.appointments.values()
            if a.status not in (AppointmentStatus.CANCELLED, AppointmentStatus.COMPLETED)
        ]
        if doctor_id:
            out = [a for a in out if a.doctor_id == doctor_id]
        return out

    def doctor_appointment_count(self, doctor_id: str) -> int:
        return len(self.active_appointments(doctor_id))
