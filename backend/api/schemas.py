"""Pydantic request/response schemas for the API."""

from __future__ import annotations

from typing import Optional, Any
from pydantic import BaseModel, Field


class LoginIn(BaseModel):
    username: str
    password: str


class LoginOut(BaseModel):
    token: str
    role: str
    name: str
    doctor_id: str = ""


class BookConsultIn(BaseModel):
    patient_id: str
    doctor_id: str
    slot_start: str
    slot_end: str


class BookChemoIn(BaseModel):
    patient_id: str
    doctor_id: str
    drug_id: str
    preferred_start: Optional[str] = None


class RescheduleIn(BaseModel):
    new_doctor_id: Optional[str] = None
    new_room_id: Optional[str] = None
    slot_start: str
    slot_end: str
    reason: str = "manual reschedule"


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
    reason: str = "sick leave"


class RoomBreakdownIn(BaseModel):
    available_until: str = "23:59"
    reason: str = "equipment breakdown"


class NoShowIn(BaseModel):
    no_show_min: int = 15


class OverrunIn(BaseModel):
    pass


class CancelIn(BaseModel):
    reason: str = "patient request"


class RoomRestoreIn(BaseModel):
    reason: str = "equipment repaired"


class EmergencyAssignIn(BaseModel):
    doctor_id: str


class EmergencyCompleteIn(BaseModel):
    pass


class MarkCheckedInIn(BaseModel):
    checked_in: bool = True


class ClockAdvanceIn(BaseModel):
    no_show_min: int = 15


class LeaveIn(BaseModel):
    start: str = "08:00"
    end: str = "18:00"
    reason: str = "leave"
    full_day: bool = False
    date: str = ""


class LeaveCancelIn(BaseModel):
    leave_id: Optional[str] = None


class BookWithRecsIn(BaseModel):
    patient_id: str
    doctor_id: str
    appt_type: str = "consult"          # consult | chemo
    drug_id: Optional[str] = None
    preferred_start: Optional[str] = None
    slot_start: Optional[str] = None    # explicit slot (consult)
    slot_end: Optional[str] = None


class PatientIn(BaseModel):
    name: str
    contact: str = ""
    dob: str = ""
    age: str = ""
    gender: str = ""
    blood_group: str = ""
    mr_number: str = ""
    diagnosis: str = ""
    stage: str = ""
    allergies: str = ""
    insurance: str = ""
    priority_tier: int = 1
    notes: str = ""


class EngineOut(BaseModel):
    success: bool
    action: str
    message: str
    severity: str
    actions: list[str] = []
    data: dict[str, Any] = {}
