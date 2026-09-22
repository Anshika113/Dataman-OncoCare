"""Slot model: per-resource availability as a set of time-bounded slots.

Availability is evaluated over *intervals* (arbitrary [start,end) ranges), not
only a fixed grid. :meth:`is_doctor_slot_free` therefore answers "can I book
this doctor from X to Y?" for any X,Y, which is what rescheduling / cascades
need. :meth:`doctor_free_slots` still yields the standard grid for search.
"""

from __future__ import annotations

from typing import Optional

from .state import SystemState
from .timeutils import to_min, to_hhmm, overlaps_m


class SlotRegistry:
    """Per-resource (doctor / room) interval availability derived from state."""

    def __init__(self, state: SystemState, day_start: str = "08:00",
                 day_end: str = "18:00", slot_len: int = 30) -> None:
        self.state = state
        self.day_start = day_start
        self.day_end = day_end
        self.slot_len = slot_len

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
            for a in self.state.active_appointments(doctor_id)
            if a.doctor_id == doctor_id
        ]

    def is_doctor_available_at(self, doctor_id: str, s: str, e: str) -> bool:
        """True if the doctor is not on leave / unavailable across [s,e)."""
        doc = self.state.doctor(doctor_id)
        if doc is None:
            return False
        if doc.on_leave:
            return False
        s_m, e_m = to_min(s), to_min(e)
        for ls, le in doc.unavailable_windows():
            if overlaps_m(s_m, e_m, to_min(ls), to_min(le)):
                return False
        return True

    def is_doctor_slot_free(self, doctor_id: str, s: str, e: str) -> bool:
        s_m, e_m = to_min(s), to_min(e)
        # must lie within the working day
        if s_m < to_min(self.day_start) or e_m > to_min(self.day_end):
            return False
        # must not fall inside a leave / unavailable window
        if not self.is_doctor_available_at(doctor_id, s, e):
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

    def _buffer_violates(self, doctor_id: str, s: str, e: str) -> bool:
        """A reservation must not enter a neighbour's pre/post buffer zone.

        Back-to-back contact (ending exactly at a start, or starting exactly at
        an end) is allowed; only *entering* the gap is a violation.
        """
        s_m, e_m = to_min(s), to_min(e)
        for a in self.state.active_appointments(doctor_id):
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
            for a in self.state.active_appointments()
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
