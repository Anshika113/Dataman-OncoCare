"""What a patient is allowed to see about their own visit.

The brief asks for improvements to "patient experience" and the app had no
patient-facing surface at all: someone sitting in the waiting room could be
told by SMS that their time moved, but could not look up where they were in
the queue.

This builds that view, and it is defined by what it leaves out. A patient
sees their own position and nothing that identifies anybody else, and the
treatment is named only if they consented to it being named — the same rule
the outgoing messages follow.

The guidance line comes out twice: as English prose in ``advice``, which is
what a message would carry, and as ``advice_key`` plus ``advice_vars``, so
the page can say the same thing in the patient's own language without this
module knowing any of them. Translating here would mean every new language
touching the engine.

Pure module: no I/O, no clock.
"""

from __future__ import annotations

from typing import Optional

from .state import SystemState, Appointment, AppointmentStatus
from .timeutils import to_min
from . import arrivals, privacy

#: How long a visit is assumed to take when estimating a wait, if the people
#: ahead have no measured history to go on.
FALLBACK_VISIT_MIN = 15

_STAGE_TEXT = {
    "not_arrived": "Not checked in yet",
    "ready": "Checked in — waiting to be called",
    "in_labs": "Waiting for your test results",
    "with_doctor": "With the doctor now",
    "done": "Visit complete",
}


def _ahead_of(state: SystemState, appt: Appointment, now: str) -> list[dict]:
    """Patients with the same doctor who will be seen before this one."""
    board = arrivals.board(state, now, appt.eff_date)
    mine = next((r for r in board if r["appointment_id"] == appt.id), None)
    if mine is None or mine["stage"] in ("with_doctor", "done"):
        return []
    out = []
    for r in board:
        if r["doctor_id"] != appt.doctor_id or r["appointment_id"] == appt.id:
            continue
        if r["stage"] == "ready" and r["waiting_min"] >= mine["waiting_min"]:
            out.append(r)
        elif r["stage"] == "with_doctor":
            out.append(r)
    return out


def _estimated_wait(state: SystemState, appt: Appointment, ahead: int) -> int:
    """A rough wait, from this doctor's own median visit length."""
    from . import visits
    learned = visits.learned_duration(state, appt.doctor_id,
                                      appt.eff_visit_type)
    each = (learned["suggested_min"] if learned
            else max(FALLBACK_VISIT_MIN, appt.planned_min))
    return ahead * each


def status_for(state: SystemState, appt: Appointment, now: str) -> dict:
    """The patient's own view of their own visit.

    Deliberately excluded: any other patient's name, the doctor's specialty,
    the diagnosis, the drug, and the room where that would give the treatment
    away. The consent flag decides whether the treatment may be named at all.
    """
    patient = state.patient(appt.patient_id)
    doctor = state.doctor(appt.doctor_id)
    board = arrivals.board(state, now, appt.eff_date)
    mine = next((r for r in board if r["appointment_id"] == appt.id), None)
    stage = mine["stage"] if mine else "not_arrived"

    ahead = _ahead_of(state, appt, now)
    may_name = patient is not None and patient.consent_name_treatment

    out = {
        "token": mine["token"] if mine else "",
        "stage": stage,
        "stage_text": _STAGE_TEXT.get(stage, "Booked"),
        "date": appt.eff_date,
        "booked_for": appt.slot_start,
        "arrived_at": appt.checked_in_at,
        "waiting_min": mine["waiting_min"] if mine else 0,
        "people_ahead": len(ahead),
        "estimated_wait_min": (_estimated_wait(state, appt, len(ahead))
                               if stage == "ready" else 0),
        "doctor_name": doctor.name if doctor else "",
        # named only with consent, and never the specialty
        "treatment": (state.drug(appt.drug_id).name
                      if may_name and appt.drug_id
                      and state.drug(appt.drug_id) else ""),
        "awaiting_results": appt.awaiting_results,
        "can_confirm": appt.status in (AppointmentStatus.BOOKED,
                                       AppointmentStatus.RESCHEDULED),
        "confirmed": appt.confirmed,
        # the language this patient reads, so the page opens in it rather than
        # making them find a toggle first
        "language": (patient.language or "en") if patient else "en",
        # whether the relative who came with them may be shown this too. It is
        # the patient's own consent flag, about their own visit.
        "attendant_ok": bool(patient.consent_attendant) if patient else False,
    }

    # one line of guidance, in the patient's terms — as a key the page can
    # translate, and as English prose for anything that cannot
    out["advice_vars"] = {"ahead": out["people_ahead"],
                          "minutes": out["estimated_wait_min"]}
    if stage == "not_arrived":
        out["advice_key"] = "check_in"
        out["advice"] = "Please check in at the desk when you arrive."
    elif stage == "in_labs":
        out["advice_key"] = "in_labs"
        out["advice"] = ("Your results are being processed. You have not lost "
                         "your place.")
    elif stage == "ready" and out["people_ahead"]:
        out["advice_key"] = "ahead"
        out["advice"] = (f"{out['people_ahead']} patient(s) ahead of you — "
                         f"roughly {out['estimated_wait_min']} minutes.")
    elif stage == "ready":
        out["advice_key"] = "next"
        out["advice"] = "You are next."
    elif stage == "with_doctor":
        out["advice_key"] = ""
        out["advice"] = ""
    else:
        out["advice_key"] = "done"
        out["advice"] = "Nothing further today."
    return out


def safe_to_show(state: SystemState, appt: Appointment) -> bool:
    """A patient may always see their own visit; a cancelled one shows a
    neutral message instead of the detail."""
    return appt.status != AppointmentStatus.CANCELLED
