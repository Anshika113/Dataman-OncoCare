"""Slot model: per-resource availability as a set of time-bounded slots.

Availability is evaluated over *intervals* (arbitrary [start,end) ranges), not
only a fixed grid. :meth:`is_doctor_slot_free` therefore answers "can I book
this doctor from X to Y?" for any X,Y, which is what rescheduling / cascades
need. :meth:`doctor_free_slots` still yields the standard grid for search.

All availability is **day-scoped**: the registry operates over the state's
active working day, so an appointment on Monday never blocks Tuesday and a
doctor's ``daily_cap`` is applied per day.
"""

from __future__ import annotations

from typing import Optional

from .state import SystemState
from . import sessions as _sess
from .timeutils import to_min, to_hhmm, overlaps_m


class SlotRegistry:
    """Per-resource (doctor / room) interval availability derived from state."""

    def __init__(self, state: SystemState, day_start: str = "08:00",
                 day_end: str = "18:00", slot_len: int = 30,
                 day: Optional[str] = None) -> None:
        self.state = state
        self.day_start = day_start
        self.day_end = day_end
        self.slot_len = slot_len
        # Explicit day wins; otherwise track the state's active working day.
        self._fixed_day = day

    def day(self) -> str:
        return self._fixed_day or self.state.day()

    # -- grid --------------------------------------------------------------- #
    def generate_day(self, start: str, end: str, length: int) -> list[tuple[str, str]]:
        out = []
        cur, stop = to_min(start), to_min(end)
        while cur < stop:
            s, e = cur, min(cur + length, stop)
            out.append((to_hhmm(s), to_hhmm(e)))
            cur = e
        return out

    # -- doctor ------------------------------------------------------------- #
    def doctor_busy_intervals(self, doctor_id: str) -> list[tuple[str, str]]:
        return [
            (a.slot_start, a.slot_end)
            for a in self.state.active_appointments(doctor_id, day=self.day())
            if a.doctor_id == doctor_id
        ]

    def is_doctor_available_at(self, doctor_id: str, s: str, e: str) -> bool:
        """True if the doctor is not on leave / unavailable across [s,e) today."""
        doc = self.state.doctor(doctor_id)
        if doc is None:
            return False
        # A full-day on_leave blocks the whole working day.
        if doc.on_leave:
            return False
        s_m, e_m = to_min(s), to_min(e)
        for ls, le in doc.unavailable_windows_for(self.day()):
            if overlaps_m(s_m, e_m, to_min(ls), to_min(le)):
                return False
        return True

    def is_doctor_slot_free(self, doctor_id: str, s: str, e: str) -> bool:
        s_m, e_m = to_min(s), to_min(e)
        # must lie within the working day
        if s_m < to_min(self.day_start) or e_m > to_min(self.day_end):
            return False
        # must not fall inside a leave / unavailable window (today's leaves)
        if not self.is_doctor_available_at(doctor_id, s, e):
            return False
        # must sit inside a clinic session and clear of ward rounds, teaching
        # and lunch. A doctor with no session template is unconstrained.
        if not _sess.is_bookable(self.state.doctor(doctor_id), self.day(), s, e):
            return False
        for bs, be in self.doctor_busy_intervals(doctor_id):
            if overlaps_m(s_m, e_m, to_min(bs), to_min(be)):
                return False
        if self._buffer_violates(doctor_id, s, e):
            return False
        return True

    def doctor_free_slots(self, doctor_id: str) -> list[tuple[str, str]]:
        return [
            (s, e) for s, e in self.generate_day(self.day_start, self.day_end,
                                                 self.slot_len)
            if self.is_doctor_slot_free(doctor_id, s, e)
        ]

    def doctor_candidate_slots(self, doctor_id: str, duration: int,
                               step: int = 15) -> list[tuple[str, str]]:
        """Every free ``duration``-minute window for a doctor, on a ``step`` grid.

        Unlike :meth:`doctor_free_slots` this is not tied to the fixed 30-minute
        grid, so a 10-minute follow-up can sit in a gap a 30-minute slot could
        never use. Each candidate is validated by the same rules (working day,
        leave windows, existing appointments, buffers).
        """
        duration = max(1, int(duration))
        step = max(1, int(step))
        out: list[tuple[str, str]] = []
        cur, stop = to_min(self.day_start), to_min(self.day_end)
        while cur + duration <= stop:
            s, e = to_hhmm(cur), to_hhmm(cur + duration)
            if self.is_doctor_slot_free(doctor_id, s, e):
                out.append((s, e))
            cur += step
        return out

    def doctor_free_gaps(self, doctor_id: str) -> list[tuple[str, str]]:
        """Merged free intervals across the working day.

        Used to answer "is there room for a walk-in today, and how big is the
        gap?" without scanning a grid.
        """
        busy: list[tuple[int, int]] = []
        for a in self.state.active_appointments(doctor_id, day=self.day()):
            if a.doctor_id != doctor_id:
                continue
            busy.append((to_min(a.slot_start) - a.buffer_before,
                         to_min(a.slot_end) + a.buffer_after))
        doc = self.state.doctor(doctor_id)
        if doc is not None:
            if doc.on_leave:
                return []
            for ls, le in doc.unavailable_windows_for(self.day()):
                busy.append((to_min(ls), to_min(le)))
        busy.sort()

        gaps: list[tuple[str, str]] = []
        cur, stop = to_min(self.day_start), to_min(self.day_end)
        for bs, be in busy:
            if bs > cur:
                gaps.append((to_hhmm(cur), to_hhmm(min(bs, stop))))
            cur = max(cur, be)
            if cur >= stop:
                break
        if cur < stop:
            gaps.append((to_hhmm(cur), to_hhmm(stop)))
        return [(s, e) for s, e in gaps if to_min(e) > to_min(s)]

    def _buffer_violates(self, doctor_id: str, s: str, e: str) -> bool:
        """A reservation must not enter a neighbour's pre/post buffer zone.

        Back-to-back contact (ending exactly at a start, or starting exactly at
        an end) is allowed; only *entering* the gap is a violation.
        """
        s_m, e_m = to_min(s), to_min(e)
        for a in self.state.active_appointments(doctor_id, day=self.day()):
            if a.doctor_id != doctor_id:
                continue
            a_s, a_e = to_min(a.slot_start), to_min(a.slot_end)
            # Reserved zones: pre-buffer [a_s - buffer_before, a_s) and
            # post-buffer (a_e, a_e + buffer_after]. A candidate slot is
            # rejected if it *enters* either reserved zone.
            if overlaps_m(s_m, e_m, a_s - a.buffer_before, a_s):
                return True
            if overlaps_m(s_m, e_m, a_e, a_e + a.buffer_after):
                return True
        return False

    # -- room --------------------------------------------------------------- #
    def room_busy_intervals(self, room_id: str) -> list[tuple[str, str]]:
        return [
            (a.slot_start, a.slot_end)
            for a in self.state.active_appointments(day=self.day())
            if a.room_id == room_id
        ]

    def is_room_slot_free(self, room_id: str, s: str, e: str) -> bool:
        room = self.state.room(room_id)
        if room is None or room.status.value != "available":
            return False
        s_m, e_m = to_min(s), to_min(e)
        if s_m < to_min(self.day_start) or e_m > to_min(self.day_end):
            return False
        if room.available_until and e_m > to_min(room.available_until):
            return False
        for bs, be in self.room_busy_intervals(room_id):
            if overlaps_m(s_m, e_m, to_min(bs), to_min(be)):
                return False
        return True

    def room_free_slots(self, room_id: str) -> list[tuple[str, str]]:
        room = self.state.room(room_id)
        if room is None or room.status.value != "available":
            return []
        day_end = room.available_until if room.available_until else self.day_end
        return [
            (s, e) for s, e in self.generate_day(self.day_start, day_end,
                                                 self.slot_len)
            if self.is_room_slot_free(room_id, s, e)
        ]
