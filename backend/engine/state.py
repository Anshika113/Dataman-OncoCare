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
    PENDING = "pending"      # queued, not handed to a provider yet
    SENT = "sent"            # accepted by the provider
    DELIVERED = "delivered"  # provider confirmed it reached the handset
    FAILED = "failed"
    BLOCKED = "blocked"      # the patient did not agree to be messaged


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


def _split_list(raw: Any) -> list[str]:
    """Parse a packed list cell.

    The seed writes these semicolon-separated while ``to_dict`` joins with
    commas, so a workbook could hold either. Accepting both keeps old files
    working — and the mismatch is why cross-specialty cover silently never
    matched.
    """
    if not raw:
        return []
    if isinstance(raw, (list, tuple)):
        return [str(x).strip() for x in raw if str(x).strip()]
    out: list[str] = []
    for chunk in str(raw).replace(";", ",").split(","):
        chunk = chunk.strip()
        if chunk:
            out.append(chunk)
    return out


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


#: Weekday keys used by a session template. "*" means every working day.
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


@dataclass
class SessionBlock:
    """A recurring part of a doctor's working week.

    A consultant's week is not ten blank hours a day. It is clinic on Monday
    and Wednesday morning, a ward round on Tuesday, teaching on Thursday
    afternoon, and lunch every day. Until the scheduler knows that, it will
    keep producing days nobody would accept.

    ``kind`` ``clinic`` is *bookable*: once a doctor has any clinic session on
    a weekday, that day is bookable only inside those windows. Every other
    kind is a block — the slot search treats it like a leave window.
    """

    id: str
    days: list[str] = field(default_factory=list)   # [] or ["*"] -> every day
    start: str = "09:00"
    end: str = "13:00"
    kind: str = "clinic"        # clinic | ward_round | teaching | lunch | admin
    label: str = ""

    @property
    def bookable(self) -> bool:
        return self.kind == "clinic"

    def covers_day(self, weekday: str) -> bool:
        if not self.days or "*" in self.days:
            return True
        return weekday in self.days

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "days": list(self.days), "start": self.start,
                "end": self.end, "kind": self.kind, "label": self.label}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SessionBlock":
        raw_days = d.get("days")
        days = (_split_list(raw_days) if not isinstance(raw_days, list)
                else [str(x).strip().lower() for x in raw_days if str(x).strip()])
        return cls(
            id=d.get("id") or new_id("SES"),
            days=[x for x in days if x in WEEKDAYS or x == "*"],
            start=d.get("start", "09:00") or "09:00",
            end=d.get("end", "13:00") or "13:00",
            kind=d.get("kind", "clinic") or "clinic",
            label=d.get("label", "") or "",
        )


@dataclass
class CaseMixRule:
    """A limit on what kind of work may be stacked, and when.

    These are the house rules a consultant would state in one sentence —
    "no more than three new cases in a row", "counselling before noon". The
    engine can honour them; it just has to be told.
    """

    id: str
    kind: str = "max_consecutive"   # max_consecutive | not_after | not_before
    visit_type: str = "new_case"
    value: str = "3"                # a count, or HH:MM for the time rules
    enabled: bool = True

    @property
    def count(self) -> int:
        try:
            return max(1, int(self.value))
        except (TypeError, ValueError):
            return 1

    def describe(self) -> str:
        from .visits import label as _label
        vt = _label(self.visit_type)
        if self.kind == "max_consecutive":
            return f"no more than {self.count} {vt.lower()} visits in a row"
        if self.kind == "not_after":
            return f"{vt.lower()} visits before {self.value} only"
        if self.kind == "not_before":
            return f"{vt.lower()} visits after {self.value} only"
        return f"{self.kind} {self.visit_type} {self.value}"

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "kind": self.kind,
                "visit_type": self.visit_type, "value": self.value,
                "enabled": int(self.enabled), "describe": self.describe()}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CaseMixRule":
        return cls(
            id=d.get("id") or new_id("RUL"),
            kind=d.get("kind", "max_consecutive") or "max_consecutive",
            visit_type=d.get("visit_type", "new_case") or "new_case",
            value=str(d.get("value", "3")),
            enabled=bool(int(d.get("enabled", 1) or 0)),
        )


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
    date: str = ""              # YYYY-MM-DD (which day this leave applies to; "" -> today)
    created_at: str = ""
    cancelled: bool = False

    @property
    def active(self) -> bool:
        return not self.cancelled

    @property
    def eff_date(self) -> str:
        from .timeutils import today
        return self.date or today()

    def covers(self, t: str) -> bool:
        """Whether a given HH:MM (on this leave's day) falls inside the window."""
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
    #: Overbooking behind a high-risk slot is off unless this doctor says so.
    allow_safety_booking: bool = False
    #: The working week. Empty = available all day, as before.
    sessions: list["SessionBlock"] = field(default_factory=list)
    #: House rules on what may be stacked. Empty = no extra limits.
    rules: list["CaseMixRule"] = field(default_factory=list)

    @property
    def active_leaves(self) -> list["LeaveEntry"]:
        return [l for l in self.leaves if l.active]

    @property
    def on_leave(self) -> bool:
        return self.status == DoctorStatus.ON_LEAVE

    def unavailable_windows(self, day: Optional[str] = None) -> list[tuple[str, str]]:
        """[start,end) windows when this doctor cannot be booked on ``day``.

        A full on_leave day returns the whole working day; otherwise returns
        the active time-bounded leaves **for that day** (leaves on other days
        don't block today).
        """
        if self.on_leave:
            return [("08:00", "18:00")]
        leaves = self.active_leaves
        if day is not None:
            leaves = [l for l in leaves if l.eff_date == day]
        return [(l.start, l.end) for l in leaves]

    # Backwards-compatible alias used by older call sites.
    def unavailable_windows_for(self, day: str) -> list[tuple[str, str]]:
        return self.unavailable_windows(day)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "specialty": self.specialty,
            "daily_cap": self.daily_cap,
            "status": self.status.value,
            "backup_compatible": ",".join(self.backup_compatible),
            "leave_reason": self.leave_reason,
            "allow_safety_booking": int(self.allow_safety_booking),
            "leaves": [l.to_dict() for l in self.leaves],
            "sessions": [x.to_dict() for x in self.sessions],
            "rules": [r.to_dict() for r in self.rules],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Doctor":
        return cls(
            id=d["id"],
            name=d["name"],
            specialty=d["specialty"],
            daily_cap=int(d.get("daily_cap", 20)),
            status=DoctorStatus(d.get("status", "available")),
            backup_compatible=_split_list(d.get("backup_compatible")),
            leave_reason=d.get("leave_reason", ""),
            allow_safety_booking=bool(int(d.get("allow_safety_booking", 0) or 0)),
            leaves=[LeaveEntry.from_dict(l) for l in (d.get("leaves") or [])],
            sessions=[SessionBlock.from_dict(x) for x in (d.get("sessions") or [])],
            rules=[CaseMixRule.from_dict(r) for r in (d.get("rules") or [])],
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
            equipment=_split_list(d.get("equipment")),
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
            required_equipment=_split_list(d.get("required_equipment")),
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
    # --- what this patient agreed we may send ------------------------------ #
    #: Send appointment reminders and offers at all.
    consent_sms: bool = True
    #: A message may name the treatment, the drug or the specialty. OFF by
    #: default: a phone is often shared, and a cancer diagnosis in an SMS is
    #: not something to disclose by omission of a checkbox.
    consent_name_treatment: bool = False
    #: Whoever answers this number may be spoken to about the appointment.
    consent_attendant: bool = True
    #: The language this patient reads, as a two-letter code. Doctors work in
    #: English; patients and the relatives who bring them often do not, and
    #: the one screen a patient ever sees should not assume otherwise.
    language: str = "en"

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
            "language": self.language or "en",
            "consent_sms": int(self.consent_sms),
            "consent_name_treatment": int(self.consent_name_treatment),
            "consent_attendant": int(self.consent_attendant),
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
            consent_sms=bool(int(d.get("consent_sms", 1) or 0)),
            consent_name_treatment=bool(
                int(d.get("consent_name_treatment", 0) or 0)),
            consent_attendant=bool(int(d.get("consent_attendant", 1) or 0)),
            language=(d.get("language") or "en"),
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
    # NOTE: appended last so positional construction in tests / seed keeps working.
    date: str = ""                 # YYYY-MM-DD the appointment falls on ("" -> today on load)
    visit_type: str = ""           # follow_up | new_case | counselling | chemo_review
    walk_in: bool = False          # arrived without an appointment
    awaiting_results: bool = False # gated: an investigation must clear first
    confirmed: str = ""            # "" unanswered | "yes" coming | "no" cannot
    held_room_id: str = ""         # chair released while waiting, to re-grab
    reason: str = ""               # why the patient came (walk-ins especially)
    checked_in_at: str = ""        # HH:MM the patient actually arrived
    started_at: str = ""           # HH:MM the patient went in to the doctor
    completed_at: str = ""         # HH:MM the visit was marked done
    # Chair time handed back to the pool when this treatment was gated for
    # results. Written once, at the moment the chair was released, because
    # re-pencilling clears held_room_id and the fact would otherwise be lost.
    chair_released_min: int = 0
    # What the handing-over doctor wanted their colleague to know, and who
    # wrote it. The hand-off already moved the patient; without this the
    # receiving doctor inherits a name and a slot and has to telephone for
    # the rest.
    handoff_note: str = ""
    handoff_from: str = ""         # the doctor who handed the patient over

    @property
    def is_chemo(self) -> bool:
        return self.type == AppointmentType.CHEMO

    @property
    def is_revisit(self) -> bool:
        return self.visit_count >= 1

    @property
    def eff_date(self) -> str:
        """The appointment's day, or today if unset (legacy rows)."""
        from .timeutils import today
        return self.date or today()

    @property
    def eff_visit_type(self) -> str:
        """Visit type, defaulted for rows booked before types existed.

        Only consults carry one; chemo is paced by its drug and an emergency
        by its severity.
        """
        from .visits import DEFAULT_VISIT_TYPE
        if self.visit_type:
            return self.visit_type
        return DEFAULT_VISIT_TYPE if self.type == AppointmentType.CONSULT else ""

    @property
    def planned_min(self) -> int:
        """How long the slot was booked for."""
        from .timeutils import duration_min
        return duration_min(self.slot_start, self.slot_end)

    @property
    def actual_min(self) -> Optional[int]:
        """How long the visit really took, once it has started and finished."""
        from .timeutils import to_min
        if not self.started_at or not self.completed_at:
            return None
        return to_min(self.completed_at) - to_min(self.started_at)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "patient_id": self.patient_id,
            "doctor_id": self.doctor_id,
            "slot_start": self.slot_start,
            "slot_end": self.slot_end,
            "date": self.date,
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
            "visit_type": self.visit_type,
            "walk_in": int(self.walk_in),
            "awaiting_results": int(self.awaiting_results),
            "confirmed": self.confirmed,
            "held_room_id": self.held_room_id,
            "reason": self.reason,
            "checked_in_at": self.checked_in_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "chair_released_min": int(self.chair_released_min),
            "handoff_note": self.handoff_note,
            "handoff_from": self.handoff_from,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Appointment":
        return cls(
            id=d["id"],
            patient_id=d["patient_id"],
            doctor_id=d["doctor_id"],
            slot_start=d["slot_start"],
            slot_end=d["slot_end"],
            date=d.get("date", ""),
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
            visit_type=d.get("visit_type", "") or "",
            walk_in=bool(int(d.get("walk_in", 0) or 0)),
            awaiting_results=bool(int(d.get("awaiting_results", 0) or 0)),
            confirmed=d.get("confirmed", "") or "",
            held_room_id=d.get("held_room_id", "") or "",
            reason=d.get("reason", "") or "",
            checked_in_at=d.get("checked_in_at", "") or "",
            started_at=d.get("started_at", "") or "",
            completed_at=d.get("completed_at", "") or "",
            chair_released_min=int(d.get("chair_released_min", 0) or 0),
            handoff_note=d.get("handoff_note", "") or "",
            handoff_from=d.get("handoff_from", "") or "",
        )


@dataclass
class ActionRecord:
    """One reversible change to the schedule, with the reason for it.

    The engine moves patients for good reasons — a doctor went on leave, a
    session overran, a result came back. A doctor who finds their list
    rearranged deserves to know *what* moved, *why*, and to be able to put it
    back. ``changes`` holds a before/after snapshot per appointment, which is
    what makes undo exact rather than approximate.
    """

    id: str
    kind: str                      # extend | swap | hand_off | close_list | reschedule | ...
    at: str                        # HH:MM
    on: str                        # YYYY-MM-DD
    by: str = ""                   # username, or "system" for the watchdog
    doctor_id: str = ""            # whose day this concerns
    summary: str = ""              # what happened, in plain words
    why: str = ""                  # why the engine chose it
    changes: list[dict[str, Any]] = field(default_factory=list)
    undone: bool = False

    @property
    def reversible(self) -> bool:
        return bool(self.changes) and not self.undone

    def to_dict(self) -> dict[str, Any]:
        import json as _json
        return {
            "id": self.id, "kind": self.kind, "at": self.at, "on": self.on,
            "by": self.by, "doctor_id": self.doctor_id,
            "summary": self.summary, "why": self.why,
            "changes": _json.dumps(self.changes),
            "undone": int(self.undone),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ActionRecord":
        import json as _json
        raw = d.get("changes") or "[]"
        try:
            changes = _json.loads(raw) if isinstance(raw, str) else list(raw)
        except (ValueError, TypeError):
            changes = []
        return cls(
            id=d["id"], kind=d.get("kind", ""), at=d.get("at", ""),
            on=d.get("on", ""), by=d.get("by", "") or "",
            doctor_id=d.get("doctor_id", "") or "",
            summary=d.get("summary", "") or "", why=d.get("why", "") or "",
            changes=changes, undone=bool(int(d.get("undone", 0) or 0)),
        )


@dataclass
class Investigation:
    """A lab or imaging order that a treatment may depend on.

    In an oncology OPD this is the real bottleneck: the chair is held from
    10:00 while the counts are still in the lab. Modelling the order lets the
    schedule know *why* a patient is not ready, instead of marking them a
    no-show.
    """

    id: str
    patient_id: str
    appointment_id: str = ""       # the appointment this gates
    kind: str = "CBC"
    ordered_at: str = ""           # HH:MM
    ordered_on: str = ""           # YYYY-MM-DD
    eta: str = ""                  # HH:MM the lab expects to report
    status: str = "pending"        # pending | resulted | flagged | cancelled
    resulted_at: str = ""
    value: str = ""                # e.g. "ANC 0.9"
    blocking: bool = True          # must clear before treatment proceeds
    note: str = ""

    @property
    def open(self) -> bool:
        """Still stopping the treatment from going ahead."""
        return self.blocking and self.status in ("pending", "flagged")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "patient_id": self.patient_id,
            "appointment_id": self.appointment_id,
            "kind": self.kind,
            "ordered_at": self.ordered_at,
            "ordered_on": self.ordered_on,
            "eta": self.eta,
            "status": self.status,
            "resulted_at": self.resulted_at,
            "value": self.value,
            "blocking": int(self.blocking),
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Investigation":
        return cls(
            id=d["id"],
            patient_id=d["patient_id"],
            appointment_id=d.get("appointment_id", "") or "",
            kind=d.get("kind", "CBC") or "CBC",
            ordered_at=d.get("ordered_at", "") or "",
            ordered_on=d.get("ordered_on", "") or "",
            eta=d.get("eta", "") or "",
            status=d.get("status", "pending") or "pending",
            resulted_at=d.get("resulted_at", "") or "",
            value=d.get("value", "") or "",
            blocking=bool(int(d.get("blocking", 1) or 0)),
            note=d.get("note", "") or "",
        )


@dataclass
class WaitlistEntry:
    """A patient who would take an earlier slot if one frees up.

    This is what turns a cancellation from dead time into a filled slot. An
    entry says who, with whom, how long they need, when they could come and
    how long it takes them to get here — enough to rank honestly rather than
    ringing round in booking order.
    """

    id: str
    patient_id: str
    doctor_id: str = ""            # "" -> any doctor will do
    visit_type: str = ""
    reason: str = ""
    earliest: str = "08:00"        # will not come before this
    latest: str = "18:00"          # will not come after this
    travel_min: int = 30           # how long they need to reach the clinic
    in_building: bool = False      # already here (bloods, pharmacy, waiting)
    status: str = "waiting"        # waiting | offered | booked | removed
    added_at: str = ""             # HH:MM
    added_on: str = ""             # YYYY-MM-DD
    offered_slot: str = ""         # "HH:MM-HH:MM@DOC" currently offered
    note: str = ""

    @property
    def active(self) -> bool:
        return self.status in ("waiting", "offered")

    def accepts(self, doctor_id: str) -> bool:
        return not self.doctor_id or self.doctor_id == doctor_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "patient_id": self.patient_id,
            "doctor_id": self.doctor_id,
            "visit_type": self.visit_type,
            "reason": self.reason,
            "earliest": self.earliest,
            "latest": self.latest,
            "travel_min": self.travel_min,
            "in_building": int(self.in_building),
            "status": self.status,
            "added_at": self.added_at,
            "added_on": self.added_on,
            "offered_slot": self.offered_slot,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "WaitlistEntry":
        return cls(
            id=d["id"],
            patient_id=d["patient_id"],
            doctor_id=d.get("doctor_id", "") or "",
            visit_type=d.get("visit_type", "") or "",
            reason=d.get("reason", "") or "",
            earliest=d.get("earliest", "08:00") or "08:00",
            latest=d.get("latest", "18:00") or "18:00",
            travel_min=int(d.get("travel_min", 30) or 0),
            in_building=bool(int(d.get("in_building", 0) or 0)),
            status=d.get("status", "waiting") or "waiting",
            added_at=d.get("added_at", "") or "",
            added_on=d.get("added_on", "") or "",
            offered_slot=d.get("offered_slot", "") or "",
            note=d.get("note", "") or "",
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
    """A message to a patient, and whatever came back.

    Previously these were rows nobody ever sent. They now carry a delivery
    state a provider can confirm and a reply field, because a confirmed
    patient is a kept slot and a declined one frees the slot hours before a
    no-show would have.
    """

    id: str
    patient_id: str
    channel: str
    body: str
    sent_at: str
    status: NotificationStatus = NotificationStatus.PENDING
    delivered_at: str = ""
    reply: str = ""
    replied_at: str = ""
    kind: str = ""        # offer | reschedule | cancel | reminder | …
    ref: str = ""         # the appointment / waitlist entry it is about

    @property
    def answered(self) -> bool:
        return bool(self.reply)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "patient_id": self.patient_id,
            "channel": self.channel,
            "body": self.body,
            "sent_at": self.sent_at,
            "status": self.status.value,
            "delivered_at": self.delivered_at,
            "reply": self.reply,
            "replied_at": self.replied_at,
            "kind": self.kind,
            "ref": self.ref,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Notification":
        return cls(
            id=d["id"],
            patient_id=d.get("patient_id", ""),
            channel=d.get("channel", "sms"),
            body=d.get("body", ""),
            sent_at=d.get("sent_at", ""),
            status=NotificationStatus(d.get("status", "pending") or "pending"),
            delivered_at=d.get("delivered_at", "") or "",
            reply=d.get("reply", "") or "",
            replied_at=d.get("replied_at", "") or "",
            kind=d.get("kind", "") or "",
            ref=d.get("ref", "") or "",
        )


# --------------------------------------------------------------------------- #
# Aggregate state
# --------------------------------------------------------------------------- #
@dataclass
class SystemState:
    """The full in-memory snapshot the engine reasons over.

    ``active_day`` is the working day (YYYY-MM-DD) the slot grid and
    day-scoped logic operate over. It is set by the API layer from the clock
    each tick, and defaults to today for a fresh state.
    """

    doctors: dict[str, Doctor] = field(default_factory=dict)
    rooms: dict[str, ChemRoom] = field(default_factory=dict)
    drugs: dict[str, Drug] = field(default_factory=dict)
    patients: dict[str, Patient] = field(default_factory=dict)
    appointments: dict[str, Appointment] = field(default_factory=dict)
    emergencies: dict[str, Emergency] = field(default_factory=dict)
    waitlist: dict[str, WaitlistEntry] = field(default_factory=dict)
    investigations: dict[str, Investigation] = field(default_factory=dict)
    actions: dict[str, ActionRecord] = field(default_factory=dict)
    logs: list[LogEntry] = field(default_factory=list)
    notifications: list[Notification] = field(default_factory=list)
    active_day: str = field(default="", repr=False)

    def day(self) -> str:
        """The current working day (active_day, or today if unset)."""
        from .timeutils import today
        return self.active_day or today()

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

    def waitlist_entry(self, wid: str) -> Optional[WaitlistEntry]:
        return self.waitlist.get(wid)

    def investigation(self, iid: str) -> Optional[Investigation]:
        return self.investigations.get(iid)

    def action(self, aid: str) -> Optional[ActionRecord]:
        return self.actions.get(aid)

    def investigations_for(self, appointment_id: str) -> list[Investigation]:
        return [i for i in self.investigations.values()
                if i.appointment_id == appointment_id]

    # --- mutation helpers -------------------------------------------------- #
    def add_log(self, kind: str, appointment_id: str, before: str, after: str,
                reason: str, at: str) -> None:
        self.logs.append(LogEntry(
            id=new_id("LOG"), kind=kind, appointment_id=appointment_id,
            before=before, after=after, reason=reason, at=at,
        ))

    def add_notification(self, patient_id: str, channel: str, body: str,
                         at: str, kind: str = "", ref: str = "") -> Notification:
        """Queue a message. It is PENDING until a dispatcher hands it to a
        provider — the status now means something."""
        n = Notification(
            id=new_id("NTF"), patient_id=patient_id, channel=channel,
            body=body, sent_at=at, status=NotificationStatus.PENDING,
            kind=kind, ref=ref,
        )
        self.notifications.append(n)
        return n

    def notification(self, nid: str) -> Optional[Notification]:
        for n in self.notifications:
            if n.id == nid:
                return n
        return None

    def active_appointments(self, doctor_id: Optional[str] = None,
                            day: Optional[str] = None) -> list[Appointment]:
        """Live (not cancelled/completed) appointments, optionally scoped to a
        single working day. ``day`` defaults to the state's active day so the
        slot grid and capacity checks are always day-scoped."""
        out = [
            a for a in self.appointments.values()
            if a.status not in (AppointmentStatus.CANCELLED, AppointmentStatus.COMPLETED)
        ]
        if doctor_id:
            out = [a for a in out if a.doctor_id == doctor_id]
        if day is not None:
            d = day or self.day()
            out = [a for a in out if a.eff_date == d]
        return out

    def doctor_appointment_count(self, doctor_id: str,
                                 day: Optional[str] = None) -> int:
        """Appointments booked for this doctor **on a given day** (defaults to
        the active day) — this is what ``daily_cap`` constrains."""
        return len(self.active_appointments(doctor_id, day=day))
