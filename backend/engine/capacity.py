"""Capacity over days, not just this afternoon.

Every other module in this engine reasons about today. The brief, though,
describes a pressure that builds: *"as patient volumes increase, balancing
clinic capacity with patient demand becomes increasingly challenging"*. That
is a question about next week, and nothing here could answer it.

This looks forward across a horizon of days and says, per day and per doctor,
how much of the clinic is already committed, where the pressure is, and where
there is room to move work to.

Pure module: no I/O, no clock.
"""

from __future__ import annotations

from datetime import date as _date, timedelta
from typing import Optional

from .state import SystemState, AppointmentStatus
from .timeutils import to_min
from . import sessions as sess

#: Above this a day is effectively full; above FULL it is over-committed.
TIGHT_PCT = 85
FULL_PCT = 100

DAY_START = "08:00"
DAY_END = "18:00"

_COMMITTED = (AppointmentStatus.BOOKED, AppointmentStatus.RESCHEDULED,
              AppointmentStatus.ACTIVE, AppointmentStatus.OVERRUN)


def _days_from(start: str, n: int) -> list[str]:
    try:
        y, m, d = (int(x) for x in start.split("-"))
        first = _date(y, m, d)
    except (ValueError, TypeError):
        return [start]
    return [(first + timedelta(days=i)).isoformat() for i in range(max(1, n))]


def _available_min(state: SystemState, doctor, day: str) -> int:
    """Minutes this doctor can actually see patients in, on that day."""
    if doctor is None or doctor.on_leave:
        return 0
    windows = sess.bookable_windows(doctor, day, DAY_START, DAY_END)
    mins = sum(to_min(e) - to_min(s) for s, e in windows)
    for ls, le in doctor.unavailable_windows_for(day):
        mins -= max(0, to_min(le) - to_min(ls))
    return max(0, mins)


def _committed_min(state: SystemState, doctor_id: str, day: str) -> int:
    return sum(
        max(0, to_min(a.slot_end) - to_min(a.slot_start))
        for a in state.appointments.values()
        if a.doctor_id == doctor_id and a.eff_date == day
        and a.status in _COMMITTED
    )


def _pct(part: int, whole: int) -> Optional[int]:
    if whole <= 0:
        return None
    return int(round(100.0 * part / whole))


def _tone(pct: Optional[int]) -> str:
    if pct is None:
        return "closed"
    if pct > FULL_PCT:
        return "over"
    if pct >= TIGHT_PCT:
        return "tight"
    return "ok"


def day_capacity(state: SystemState, day: str, doctor_id: str = "") -> dict:
    """One day's committed vs available minutes, per doctor and in total."""
    docs = ([state.doctor(doctor_id)] if doctor_id
            else sorted(state.doctors.values(), key=lambda d: d.name))
    per_doctor = []
    total_av = total_com = 0
    for doc in docs:
        if doc is None:
            continue
        av = _available_min(state, doc, day)
        com = _committed_min(state, doc.id, day)
        total_av += av
        total_com += com
        per_doctor.append({
            "doctor_id": doc.id,
            "doctor_name": doc.name,
            "available_min": av,
            "committed_min": com,
            "free_min": max(0, av - com),
            "pct": _pct(com, av),
            "tone": _tone(_pct(com, av)),
            "closed": av == 0,
        })

    booked = len([
        a for a in state.appointments.values()
        if a.eff_date == day and a.status in _COMMITTED
        and (not doctor_id or a.doctor_id == doctor_id)
    ])
    pct = _pct(total_com, total_av)
    return {
        "date": day,
        "weekday": sess.weekday(day),
        "available_min": total_av,
        "committed_min": total_com,
        "free_min": max(0, total_av - total_com),
        "pct": pct,
        "tone": _tone(pct),
        "appointments": booked,
        "doctors": per_doctor,
    }


def horizon(state: SystemState, start: Optional[str] = None, days: int = 7,
            doctor_id: str = "") -> dict:
    """The next ``days`` days, and where the pressure is.

    ``advice`` names the move a human would make — shift work from the
    tightest day to the emptiest one — rather than leaving two numbers side
    by side and hoping.
    """
    first = start or state.day()
    rows = [day_capacity(state, d, doctor_id) for d in _days_from(first, days)]
    open_days = [r for r in rows if r["pct"] is not None]

    advice: list[str] = []
    over = [r for r in open_days if r["tone"] == "over"]
    tight = [r for r in open_days if r["tone"] == "tight"]
    roomy = sorted([r for r in open_days if r["tone"] == "ok"],
                   key=lambda r: r["pct"])

    for r in over:
        where = (f"; {roomy[0]['date']} is at {roomy[0]['pct']}%"
                 if roomy else "; no day in this window has room")
        advice.append(
            f"{r['date']} is over-committed at {r['pct']}%{where}")
    for r in tight:
        advice.append(f"{r['date']} is nearly full at {r['pct']}%")
    if not advice and open_days:
        busiest = max(open_days, key=lambda r: r["pct"])
        advice.append(
            f"No day in this window is tight — busiest is {busiest['date']} "
            f"at {busiest['pct']}%")

    closed = [r["date"] for r in rows if r["pct"] is None]
    if closed:
        advice.append("No clinic on " + ", ".join(closed))

    return {
        "start": first,
        "days": len(rows),
        "doctor_id": doctor_id,
        "rows": rows,
        "advice": advice,
        "busiest": (max(open_days, key=lambda r: r["pct"])["date"]
                    if open_days else ""),
        "emptiest": (roomy[0]["date"] if roomy else ""),
    }
