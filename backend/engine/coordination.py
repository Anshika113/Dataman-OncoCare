"""Who fell through the cracks.

The brief names four roles — doctors, nurses, front-desk teams and **care
coordinators** — and the first three all have a surface. A coordinator's job
is different from the desk's: the desk runs the room in front of them, the
coordinator follows the patients who are no longer in front of anybody.

Every signal needed for that already exists elsewhere in the engine. What was
missing was one list that answers *"who has nobody looking after them right
now?"* — ranked, with the reason, and with the one action that would clear it.

Pure module: no I/O, no clock.
"""

from __future__ import annotations

from typing import Optional

from .state import SystemState, Appointment, AppointmentStatus
from .timeutils import to_min, dt_key
from . import investigations as inv, risk as rk
from .replies import read_reply

#: A treatment held this long without a result needs chasing, not waiting.
STALE_GATE_MIN = 60
#: A waitlist entry older than this has effectively been forgotten.
STALE_WAITLIST_MIN = 120
#: How late a patient can be before "arrived but never called" is a problem.
STRANDED_MIN = 45

#: Lower sorts first.
_SEVERITY_RANK = {"critical": 0, "warning": 1, "info": 2}


def _row(kind: str, severity: str, who: str, patient_id: str, summary: str,
         why: str, action: str, ref: str = "", when: str = "") -> dict:
    return {"kind": kind, "severity": severity, "patient_name": who,
            "patient_id": patient_id, "summary": summary, "why": why,
            "action": action, "ref": ref, "when": when}


def _name(state: SystemState, patient_id: str) -> str:
    p = state.patient(patient_id)
    return p.name if p else patient_id


def _late_min(state: SystemState, now: str, day: str, hhmm: str) -> int:
    """Minutes between ``hhmm`` on ``day`` and ``now``, date-aware."""
    return dt_key(state.day(), now)[1] - dt_key(day, hhmm)[1]


# --------------------------------------------------------------------------- #
# The checks
# --------------------------------------------------------------------------- #
def _dropped_no_shows(state: SystemState, day: str) -> list[dict]:
    """Marked no-show and never rebooked. Nobody owns these by default."""
    out = []
    for a in state.appointments.values():
        if a.status != AppointmentStatus.NO_SHOW or a.eff_date != day:
            continue
        rebooked = any(
            b.patient_id == a.patient_id and b.id != a.id
            and b.status in (AppointmentStatus.BOOKED,
                             AppointmentStatus.RESCHEDULED)
            for b in state.appointments.values())
        if rebooked:
            continue
        out.append(_row(
            "no_show_unrebooked", "critical", _name(state, a.patient_id),
            a.patient_id,
            f"missed {a.slot_start} and has nothing booked since",
            "no future appointment exists for this patient",
            "Call and rebook", ref=a.id, when=a.slot_start))
    return out


def _stale_gates(state: SystemState, now: str, day: str) -> list[dict]:
    """Held for results, and the result has not come back."""
    out = []
    for g in inv.gated_appointments(state, day):
        waited = _late_min(state, now, day, g["slot_start"])
        if waited < STALE_GATE_MIN:
            continue
        rd = g["readiness"]
        severity = "critical" if rd["status"] == "blocked" else "warning"
        pending = ", ".join(i["kind"] for i in rd["pending"]) or "a result"
        out.append(_row(
            "gate_stale", severity, g["patient_name"], g["patient_id"],
            f"held for results since {g['slot_start']} ({waited} min)",
            (f"{pending} still outstanding" if rd["status"] == "waiting"
             else "a result is flagged and nobody has cleared it"),
            "Chase the lab" if rd["status"] == "waiting" else "Ask the doctor to review",
            ref=g["appointment_id"], when=g["slot_start"]))
    return out


def _stranded(state: SystemState, now: str, day: str) -> list[dict]:
    """Arrived, checked in, and still has not been called."""
    out = []
    for a in state.appointments.values():
        if a.eff_date != day or not a.checked_in_at or a.started_at:
            continue
        if a.status in (AppointmentStatus.VISITED, AppointmentStatus.COMPLETED,
                        AppointmentStatus.CANCELLED):
            continue
        waited = to_min(now) - to_min(a.checked_in_at)
        if waited < STRANDED_MIN:
            continue
        doc = state.doctor(a.doctor_id)
        out.append(_row(
            "stranded", "critical" if waited >= 2 * STRANDED_MIN else "warning",
            _name(state, a.patient_id), a.patient_id,
            f"waiting {waited} min since {a.checked_in_at}",
            f"arrived for {a.slot_start} with {doc.name if doc else 'a doctor'} "
            f"and has not been called",
            "Call them in or explain the delay",
            ref=a.id, when=a.checked_in_at))
    return out


def _forgotten_waitlist(state: SystemState, now: str) -> list[dict]:
    out = []
    for e in state.waitlist.values():
        if not e.active or not e.added_at:
            continue
        waited = to_min(now) - to_min(e.added_at)
        if waited < STALE_WAITLIST_MIN:
            continue
        out.append(_row(
            "waitlist_stale", "info", _name(state, e.patient_id), e.patient_id,
            f"on the waitlist {waited} min with no offer",
            e.reason or "no slot has come free",
            "Offer a slot or take them off", ref=e.id, when=e.added_at))
    return out


def _unanswered(state: SystemState, day: str) -> list[dict]:
    """High-risk patients who never replied — the cheapest thing to fix."""
    out = []
    for r in rk.day_risk(state, day):
        if r["level"] != "high" or "never confirmed" not in r["factors"]:
            continue
        out.append(_row(
            "unconfirmed_high_risk", "warning", r["patient_name"],
            r["patient_id"],
            f"{r['slot_start']} booked, never confirmed",
            " · ".join(r["factors"]),
            "Phone to confirm", ref=r["appointment_id"],
            when=r["slot_start"]))
    return out


def _blocked_messages(state: SystemState) -> list[dict]:
    """Messages held for consent. Somebody has to pick up the phone."""
    out = []
    for n in state.notifications[-200:]:
        if n.status.value != "blocked":
            continue
        out.append(_row(
            "message_blocked", "warning", _name(state, n.patient_id),
            n.patient_id,
            "could not be messaged — no consent on file",
            n.body[:80],
            "Phone them instead", ref=n.id, when=n.sent_at))
    return out


def _unclear_replies(state: SystemState, day: str) -> list[dict]:
    """A patient answered and the clinic could not read it."""
    out = []
    for n in state.notifications[-200:]:
        if not n.reply or read_reply(n.reply) != "unclear":
            continue
        appt = state.appointment(n.ref) if n.ref else None
        # Settled, or about a different day: nobody needs to phone about it.
        if appt is not None and (appt.eff_date != day
                                 or appt.confirmed in ("yes", "no")):
            continue
        entry = state.waitlist_entry(n.ref) if n.ref else None
        if entry is not None and entry.status != "offered":
            continue
        out.append(_row(
            "reply_unclear", "warning", _name(state, n.patient_id),
            n.patient_id, "replied, and it needs a person to read it",
            n.reply[:80], "Phone them", ref=n.id, when=n.replied_at))
    return out


# --------------------------------------------------------------------------- #
# The list
# --------------------------------------------------------------------------- #
#: Worst first, for collapsing several rows about one person.
_SEV_ORDER = {"critical": 0, "warning": 1, "info": 2}


def by_patient(rows: list[dict], max_reasons: int = 2) -> list[dict]:
    """One row per patient, worst reason first.

    The full list keeps a row per *reason* on purpose: a coordinator with two
    rows for one patient genuinely has two jobs, each with its own action, and
    merging them would hide one. But anywhere the list is summarised — a panel
    that shows the top few — the same name twice reads as a bug rather than as
    two jobs, so this folds them.

    Severity is the worst of the set, never an average: a critical reason
    stays critical however many quieter ones sit under it.
    """
    order: list[str] = []
    seen: dict[str, list[dict]] = {}
    for r in rows:
        key = r.get("patient_id") or r.get("patient_name") or ""
        if key not in seen:
            seen[key] = []
            order.append(key)
        seen[key].append(r)

    out: list[dict] = []
    for key in order:
        group = sorted(seen[key],
                       key=lambda r: _SEV_ORDER.get(r.get("severity"), 9))
        head = dict(group[0])
        if len(group) > 1:
            reasons = [r.get("summary", "") for r in group[:max_reasons]]
            head["summary"] = " · ".join(x for x in reasons if x)
            head["reasons"] = len(group)
        out.append(head)
    return out


def follow_up_list(state: SystemState, now: str,
                   day: Optional[str] = None) -> dict:
    """Everyone nobody is currently looking after, worst first."""
    d = day or state.day()
    rows: list[dict] = []
    rows += _dropped_no_shows(state, d)
    rows += _stale_gates(state, now, d)
    rows += _stranded(state, now, d)
    rows += _forgotten_waitlist(state, now)
    rows += _unanswered(state, d)
    rows += _blocked_messages(state)
    rows += _unclear_replies(state, d)

    rows.sort(key=lambda r: (_SEVERITY_RANK.get(r["severity"], 9), r["when"]))
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["severity"]] = counts.get(r["severity"], 0) + 1
    return {"date": d, "now": now, "counts": counts, "rows": rows,
            "total": len(rows)}
