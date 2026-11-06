"""Pydantic request/response schemas for the API."""

from __future__ import annotations

import re
from typing import Optional, Any
from pydantic import BaseModel, Field, field_validator

_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _validate_hhmm(cls, v):
    """Validate an optional HH:MM wall-clock time string."""
    if v is None or v == "":
        return v
    if not isinstance(v, str) or not _HHMM.match(v.strip()):
        raise ValueError("must be a time in HH:MM 24h format, e.g. 09:30")
    return v.strip()


def _validate_date(cls, v):
    """Validate an optional YYYY-MM-DD date string (empty -> caller defaults)."""
    if v is None or v == "":
        return v
    if not isinstance(v, str) or not _DATE.match(v.strip()):
        raise ValueError("must be a date in YYYY-MM-DD format, e.g. 2026-10-29")
    return v.strip()


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class LoginOut(BaseModel):
    token: str
    role: str
    name: str
    doctor_id: str = ""


class BookConsultIn(BaseModel):
    patient_id: str
    doctor_id: str
    slot_start: str
    # Optional: when omitted the visit type's duration decides the end.
    slot_end: Optional[str] = None
    visit_type: Optional[str] = Field(
        None, pattern="^(follow_up|new_case|counselling|chemo_review)$")
    duration_min: Optional[int] = Field(None, ge=5, le=240)
    date: Optional[str] = None  # YYYY-MM-DD (empty/None -> active working day)

    @field_validator("slot_start", "slot_end")
    @classmethod
    def _v_time(cls, v):
        return _validate_hhmm(cls, v)

    @field_validator("date")
    @classmethod
    def _v_date(cls, v):
        return _validate_date(cls, v)


class BookChemoIn(BaseModel):
    patient_id: str
    doctor_id: str
    drug_id: str
    preferred_start: Optional[str] = None
    date: Optional[str] = None  # YYYY-MM-DD (empty/None -> active working day)

    @field_validator("preferred_start")
    @classmethod
    def _v_time(cls, v):
        return _validate_hhmm(cls, v)

    @field_validator("date")
    @classmethod
    def _v_date(cls, v):
        return _validate_date(cls, v)


class RescheduleIn(BaseModel):
    new_doctor_id: Optional[str] = None
    new_room_id: Optional[str] = None
    slot_start: str
    slot_end: str
    reason: str = "manual reschedule"
    date: Optional[str] = None  # YYYY-MM-DD (empty/None -> keep the appt's day)

    @field_validator("slot_start", "slot_end")
    @classmethod
    def _v_time(cls, v):
        return _validate_hhmm(cls, v)

    @field_validator("date")
    @classmethod
    def _v_date(cls, v):
        return _validate_date(cls, v)


class RescheduleAutoIn(BaseModel):
    reason: str = "manual auto-reschedule"
    allow_backup_doctor: bool = True


class EmergencyIn(BaseModel):
    patient_id: str
    severity: int = Field(ge=1, le=5, default=3)


class EmergencyPairIn(BaseModel):
    e1_id: str
    e2_id: str


class SickLeaveIn(BaseModel):
    reason: str = Field("sick leave", max_length=200)


class RoomBreakdownIn(BaseModel):
    available_until: str = "23:59"
    reason: str = Field("equipment breakdown", max_length=200)

    @field_validator("available_until")
    @classmethod
    def _v_time(cls, v):
        return _validate_hhmm(cls, v)


class NoShowIn(BaseModel):
    no_show_min: int = Field(15, ge=1, le=1440)


class OverrunIn(BaseModel):
    pass


class CancelIn(BaseModel):
    reason: str = Field("patient request", max_length=200)


class RoomRestoreIn(BaseModel):
    reason: str = Field("equipment repaired", max_length=200)


class EmergencyAssignIn(BaseModel):
    doctor_id: str


class EmergencyCompleteIn(BaseModel):
    pass


class MarkCheckedInIn(BaseModel):
    checked_in: bool = True


class ClockAdvanceIn(BaseModel):
    no_show_min: int = Field(15, ge=1, le=1440)


class LeaveIn(BaseModel):
    start: str = "08:00"
    end: str = "18:00"
    reason: str = Field("leave", max_length=200)
    full_day: bool = False
    date: str = ""  # YYYY-MM-DD (optional; empty = today)

    @field_validator("start", "end")
    @classmethod
    def _v_time(cls, v):
        return _validate_hhmm(cls, v)


class LeaveCancelIn(BaseModel):
    leave_id: Optional[str] = None


class BookWithRecsIn(BaseModel):
    patient_id: str
    doctor_id: str
    appt_type: str = Field("consult", pattern="^(consult|chemo)$")
    drug_id: Optional[str] = None
    preferred_start: Optional[str] = None
    slot_start: Optional[str] = None    # explicit slot (consult)
    slot_end: Optional[str] = None
    visit_type: Optional[str] = Field(
        None, pattern="^(follow_up|new_case|counselling|chemo_review)$")
    duration_min: Optional[int] = Field(None, ge=5, le=240)
    date: Optional[str] = None          # YYYY-MM-DD (empty/None -> active day)

    @field_validator("preferred_start", "slot_start", "slot_end")
    @classmethod
    def _v_time(cls, v):
        return _validate_hhmm(cls, v)

    @field_validator("date")
    @classmethod
    def _v_date(cls, v):
        return _validate_date(cls, v)


class SessionBlockIn(BaseModel):
    """One recurring part of a doctor's week."""
    id: str = ""
    days: list[str] = Field(default_factory=list, max_length=7)
    start: str = "09:00"
    end: str = "13:00"
    kind: str = Field("clinic",
                      pattern="^(clinic|ward_round|teaching|lunch|admin)$")
    label: str = Field("", max_length=60)

    @field_validator("start", "end")
    @classmethod
    def _v_time(cls, v):
        return _validate_hhmm(cls, v)

    @field_validator("days")
    @classmethod
    def _v_days(cls, v):
        allowed = {"mon", "tue", "wed", "thu", "fri", "sat", "sun", "*"}
        out = [str(x).strip().lower() for x in (v or [])]
        bad = [x for x in out if x not in allowed]
        if bad:
            raise ValueError(f"unknown day(s): {', '.join(bad)}")
        return out


class SessionsIn(BaseModel):
    """The whole template, replaced in one go."""
    sessions: list[SessionBlockIn] = Field(default_factory=list, max_length=40)


class CaseMixRuleIn(BaseModel):
    id: str = ""
    kind: str = Field("max_consecutive",
                      pattern="^(max_consecutive|not_after|not_before)$")
    visit_type: str = Field(
        "new_case", pattern="^(follow_up|new_case|counselling|chemo_review)$")
    value: str = Field("3", min_length=1, max_length=8)
    enabled: bool = True


class RulesIn(BaseModel):
    rules: list[CaseMixRuleIn] = Field(default_factory=list, max_length=20)


class ExtendIn(BaseModel):
    """Give the doctor more time with the patient in front of them."""
    minutes: int = Field(10, ge=1, le=120)


class SwapIn(BaseModel):
    other_appointment_id: str


class HandOffIn(BaseModel):
    to_doctor_id: str
    reason: str = Field("", max_length=200)
    # what the receiving doctor needs to know about the patient, as opposed to
    # why the list moved
    note: str = Field("", max_length=500)


class CloseListIn(BaseModel):
    """Stop taking patients after a time; dry run first by default."""
    from_time: str
    apply: bool = False

    @field_validator("from_time")
    @classmethod
    def _v_time(cls, v):
        return _validate_hhmm(cls, v)


class SafetyBookingIn(BaseModel):
    """A doctor's own switch for overbooking high-risk slots."""
    enabled: bool


class MessageReplyIn(BaseModel):
    """What the patient replied, as received from the channel."""
    text: str = Field(min_length=1, max_length=300)


class InvestigationIn(BaseModel):
    """Order a lab or imaging test, optionally gating a treatment."""
    patient_id: str
    kind: str = Field("CBC", min_length=1, max_length=40)
    appointment_id: str = ""
    eta: Optional[str] = None           # HH:MM the lab expects to report
    blocking: bool = True
    note: str = Field("", max_length=200)

    @field_validator("eta")
    @classmethod
    def _v_time(cls, v):
        return _validate_hhmm(cls, v)


class InvestigationResultIn(BaseModel):
    value: str = Field(min_length=1, max_length=120)
    flagged: bool = False               # outside protocol -> doctor decides
    note: str = Field("", max_length=200)


class WaitlistAddIn(BaseModel):
    """Put a patient on the list for an earlier slot."""
    patient_id: str
    doctor_id: str = ""                 # "" -> any doctor
    visit_type: Optional[str] = Field(
        None, pattern="^(follow_up|new_case|counselling|chemo_review)$")
    reason: str = Field("", max_length=200)
    earliest: str = "08:00"
    latest: str = "18:00"
    travel_min: int = Field(30, ge=0, le=600)
    in_building: bool = False
    note: str = Field("", max_length=200)

    @field_validator("earliest", "latest")
    @classmethod
    def _v_time(cls, v):
        return _validate_hhmm(cls, v)


class WaitlistMatchIn(BaseModel):
    """Who could take this freed slot."""
    doctor_id: str
    slot_start: str
    slot_end: str
    limit: int = Field(5, ge=1, le=20)

    @field_validator("slot_start", "slot_end")
    @classmethod
    def _v_time(cls, v):
        return _validate_hhmm(cls, v)


class WaitlistOfferIn(BaseModel):
    entry_ids: list[str] = Field(min_length=1, max_length=20)
    doctor_id: str
    slot_start: str
    slot_end: str

    @field_validator("slot_start", "slot_end")
    @classmethod
    def _v_time(cls, v):
        return _validate_hhmm(cls, v)


class WaitlistAcceptIn(BaseModel):
    """Accept an offered slot. Empty fields fall back to what was offered."""
    doctor_id: str = ""
    slot_start: Optional[str] = None
    slot_end: Optional[str] = None

    @field_validator("slot_start", "slot_end")
    @classmethod
    def _v_time(cls, v):
        return _validate_hhmm(cls, v)


class WalkInOptionsIn(BaseModel):
    """Ask where a walk-in could be fitted today. Reads only."""
    doctor_id: Optional[str] = None     # None -> search every available doctor
    specialty: Optional[str] = Field(None, max_length=60)
    visit_type: Optional[str] = Field(
        None, pattern="^(follow_up|new_case|counselling|chemo_review)$")
    duration_min: Optional[int] = Field(None, ge=5, le=240)
    urgency: str = Field("routine", pattern="^(routine|soon|urgent)$")
    limit: int = Field(3, ge=1, le=10)


class WalkInBookIn(BaseModel):
    """Place a walk-in in one of the offered gaps."""
    patient_id: str
    doctor_id: str
    slot_start: str
    slot_end: Optional[str] = None
    visit_type: Optional[str] = Field(
        None, pattern="^(follow_up|new_case|counselling|chemo_review)$")
    duration_min: Optional[int] = Field(None, ge=5, le=240)
    reason: str = Field("", max_length=200)
    urgency: str = Field("routine", pattern="^(routine|soon|urgent)$")

    @field_validator("slot_start", "slot_end")
    @classmethod
    def _v_time(cls, v):
        return _validate_hhmm(cls, v)


class AskIn(BaseModel):
    """A question for the read-only assistant. It changes nothing."""
    question: str = Field("", max_length=300)


class CsvIn(BaseModel):
    """A pasted or uploaded CSV, as text."""
    csv: str = Field(min_length=1, max_length=2_000_000)


class PatientConfirmIn(BaseModel):
    coming: bool


class ConsentIn(BaseModel):
    """What this patient agreed we may send. Naming the treatment is off by
    default — a phone is often shared."""
    consent_sms: bool = True
    consent_name_treatment: bool = False
    consent_attendant: bool = True


class _ConsentFields(BaseModel):
    """Mixed into the patient record so consent is captured at registration."""
    consent_sms: bool = True
    consent_name_treatment: bool = False
    consent_attendant: bool = True


class PatientIn(_ConsentFields):
    name: str = Field(min_length=1, max_length=120)
    contact: str = Field("", max_length=40)
    dob: str = Field("", max_length=10)
    age: str = Field("", max_length=4)
    gender: str = Field("", max_length=20)
    blood_group: str = Field("", max_length=5)
    mr_number: str = Field("", max_length=40)
    diagnosis: str = Field("", max_length=300)
    stage: str = Field("", max_length=40)
    allergies: str = Field("", max_length=300)
    insurance: str = Field("", max_length=120)
    priority_tier: int = Field(1, ge=1, le=5)
    notes: str = Field("", max_length=2000)


class EngineOut(BaseModel):
    success: bool
    action: str
    message: str
    severity: str
    actions: list[str] = []
    data: dict[str, Any] = {}
