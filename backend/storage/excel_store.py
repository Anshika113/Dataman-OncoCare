"""Excel-backed storage layer.

A :class:`Store` loads the whole workbook into :class:`SystemState` and writes
it back atomically. Because Excel is not a concurrency-safe store, all writes
are serialised behind a process-wide :class:`threading.Lock`, and each save
writes to a temp file then renames (atomic on the same volume).

This keeps the engine pure (it never touches I/O) while giving the API a simple
load -> mutate -> save lifecycle.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from contextlib import contextmanager
from typing import Any, Optional

from openpyxl import load_workbook, Workbook

from engine.state import (
    SystemState, Doctor, ChemRoom, Drug, Patient, Appointment,
    Emergency, LogEntry, Notification, NotificationStatus, WaitlistEntry,
    Investigation, ActionRecord,
)
from storage.seed import XLSX as DEFAULT_XLSX, build as seed_build
from engine.timeutils import today as _today


def _with_json_lists(d: dict[str, Any],
                     keys: tuple[str, ...] = ("leaves", "sessions", "rules"),
                     ) -> dict[str, Any]:
    """Decode JSON-serialized list columns into real lists.

    A column a workbook predates simply decodes to an empty list, so an older
    file opens without migration.
    """
    for key in keys:
        raw = d.get(key)
        if isinstance(raw, str) and raw.strip():
            try:
                d[key] = json.loads(raw)
            except (ValueError, TypeError):
                d[key] = []
        elif not isinstance(raw, list):
            d[key] = []
    return d


def _row_dicts(ws) -> list[dict[str, Any]]:
    """Return worksheet rows as a list of dicts keyed by header (row 1)."""
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return []
    headers = [str(h) for h in rows[0]]
    out = []
    for r in rows[1:]:
        if r is None or all(c is None or c == "" for c in r):
            continue
        out.append({headers[i]: r[i] for i in range(len(headers))})
    return out


def _write_sheet(wb: Workbook, name: str, headers: list[str],
                 rows: list[dict[str, Any]]) -> None:
    if name in wb.sheetnames:
        del wb[name]
    ws = wb.create_sheet(name)
    ws.append(headers)
    for r in rows:
        ws.append([r.get(h, "") for h in headers])


def default_path() -> str:
    """Datastore location. Override with CARE_DATA_PATH (used by Docker volume)."""
    return os.environ.get("CARE_DATA_PATH", DEFAULT_XLSX)


#: Rebuild a demo workbook once the day it was built around has passed.
#: Off by default: in a real clinic this would delete the clinic's records.
#: docker-compose.yml turns it on, because a demo that silently rots into a
#: clinic with a 100% no-show rate is worse than no demo at all.
def demo_refresh_enabled() -> bool:
    return os.environ.get("CARE_DEMO_REFRESH", "").strip().lower() in (
        "1", "true", "yes", "on")


def _seeded_for(path: str) -> str:
    """The day this workbook was built around, or "" if it does not say."""
    wb = None
    try:
        # read_only keeps the file handle open until it is closed, and on
        # Windows that is enough to make the rebuild's os.replace fail
        wb = load_workbook(path, data_only=True, read_only=True)
        if "meta" not in wb.sheetnames:
            return ""
        for row in _row_dicts(wb["meta"]):
            if row.get("key") == "seeded_for":
                return str(row.get("value") or "")
    except Exception:          # noqa: BLE001 - an unreadable workbook is stale
        return ""
    finally:
        if wb is not None:
            try:
                wb.close()
            except Exception:  # noqa: BLE001
                pass
    return ""


class Store:
    def __init__(self, path: Optional[str] = None) -> None:
        self.path = path or default_path()
        self._lock = threading.RLock()
        self._users_cache: list[dict[str, Any]] = []
        if not os.path.exists(self.path):
            self.state = SystemState()
            seed_build(self.path)
            self._load()
        else:
            if demo_refresh_enabled() and _seeded_for(self.path) != _today():
                self.reseed()
                return
            self._load()

    # ------------------------------------------------------------------ #
    def reseed(self) -> str:
        """Rebuild the demo workbook from the seed and reload it.

        The previous file is kept beside it rather than deleted — this is
        still somebody's data until they say otherwise, and a demo reset
        that destroys the only copy is the wrong default even for a demo.
        """
        with self._lock:
            if os.path.exists(self.path):
                backup = self.path + ".replaced"
                try:
                    if os.path.exists(backup):
                        os.remove(backup)
                    os.replace(self.path, backup)
                except OSError:
                    pass       # read-only FS: seed_build overwrites in place
            seed_build(self.path)
            self._load()
        return self.path

    # ------------------------------------------------------------------ #
    def _load(self) -> None:
        wb = load_workbook(self.path, data_only=True)
        s = SystemState()

        for d in _row_dicts(wb["doctors"]):
            d = _with_json_lists(d)
            doc = Doctor.from_dict(d)
            s.doctors[doc.id] = doc
        for d in _row_dicts(wb["rooms"]):
            room = ChemRoom.from_dict(d)
            s.rooms[room.id] = room
        for d in _row_dicts(wb["drugs"]):
            drug = Drug.from_dict(d)
            s.drugs[drug.id] = drug
        for d in _row_dicts(wb["patients"]):
            p = Patient.from_dict(d)
            s.patients[p.id] = p
        for d in _row_dicts(wb["appointments"]):
            a = Appointment.from_dict(d)
            s.appointments[a.id] = a
        for d in _row_dicts(wb["emergencies"]):
            e = Emergency.from_dict(d)
            s.emergencies[e.id] = e
        # added later than the other sheets: an older workbook simply has none
        if "waitlist" in wb.sheetnames:
            for d in _row_dicts(wb["waitlist"]):
                w = WaitlistEntry.from_dict(d)
                s.waitlist[w.id] = w
        if "investigations" in wb.sheetnames:
            for d in _row_dicts(wb["investigations"]):
                inv = Investigation.from_dict(d)
                s.investigations[inv.id] = inv
        if "actions" in wb.sheetnames:
            for d in _row_dicts(wb["actions"]):
                a = ActionRecord.from_dict(d)
                s.actions[a.id] = a
        for d in _row_dicts(wb["logs"]):
            s.logs.append(LogEntry(**{k: d.get(k, "") for k in
                          ("id", "kind", "appointment_id", "before", "after",
                           "reason", "at")}))
        for d in _row_dicts(wb["notifications"]):
            s.notifications.append(Notification.from_dict(d))

        self.state = s

    # ------------------------------------------------------------------ #
    @contextmanager
    def state_change(self):
        """Serialise ALL access to :attr:`state` (read-mutate-write + save).

        The API handlers (event-loop thread) and the watchdog (worker thread)
        both mutate ``SystemState``; wrapping their whole operation in this
        lock guarantees one writer at a time and makes concurrent requests
        safe. Re-entrant, so ``save()`` inside an already-held change is fine.
        """
        with self._lock:
            yield

    def save(self) -> None:
        with self._lock:
            self._persist()

    def _persist(self) -> None:
        """Write the full workbook to disk atomically. Caller must ensure
        single-writer exclusivity (holds ``state_change`` or ``save``)."""
        s = self.state
        wb = Workbook()
        wb.remove(wb.active)

        _write_sheet(wb, "users",
                     ["id", "username", "password_hash", "role", "name",
                      "doctor_id"],
                     self._users())
        _write_sheet(wb, "doctors",
                     ["id", "name", "specialty", "daily_cap", "status",
                      "backup_compatible", "leave_reason",
                      "allow_safety_booking", "leaves", "sessions", "rules"],
                     [{**d.to_dict(),
                       "leaves": json.dumps(d.to_dict()["leaves"]),
                       "sessions": json.dumps(d.to_dict()["sessions"]),
                       "rules": json.dumps(d.to_dict()["rules"])}
                      for d in s.doctors.values()])
        _write_sheet(wb, "rooms",
                     ["id", "name", "type", "equipment", "status",
                      "available_until"],
                     [r.to_dict() for r in s.rooms.values()])
        _write_sheet(wb, "drugs",
                     ["id", "name", "tw_start", "tw_end", "grace_minutes",
                      "required_equipment"],
                     [g.to_dict() for g in s.drugs.values()])
        _write_sheet(wb, "patients",
                     ["id", "name", "contact", "priority_tier", "dob", "age",
                      "gender", "blood_group", "mr_number", "diagnosis",
                      "stage", "allergies", "insurance", "notes",
                      "language", "consent_sms", "consent_name_treatment",
                      "consent_attendant"],
                     [p.to_dict() for p in s.patients.values()])
        _write_sheet(wb, "appointments",
                      ["id", "patient_id", "doctor_id", "date", "slot_start",
                       "slot_end", "type", "status", "room_id", "drug_id",
                       "severity", "buffer_before", "buffer_after", "checked_in",
                       "reschedule_reason", "visit_count", "last_visited",
                       "visit_type", "walk_in", "reason", "awaiting_results",
                       "confirmed", "held_room_id", "checked_in_at",
                       "started_at", "completed_at", "chair_released_min",
                       "handoff_note", "handoff_from"],
                      [a.to_dict() for a in s.appointments.values()])
        _write_sheet(wb, "emergencies",
                     ["id", "patient_id", "severity", "created_at", "subscore",
                      "assigned_doctor_id", "status"],
                     [e.to_dict() for e in s.emergencies.values()])
        _write_sheet(wb, "waitlist",
                     ["id", "patient_id", "doctor_id", "visit_type", "reason",
                      "earliest", "latest", "travel_min", "in_building",
                      "status", "added_at", "added_on", "offered_slot", "note"],
                     [w.to_dict() for w in s.waitlist.values()])
        _write_sheet(wb, "investigations",
                     ["id", "patient_id", "appointment_id", "kind",
                      "ordered_at", "ordered_on", "eta", "status",
                      "resulted_at", "value", "blocking", "note"],
                     [i.to_dict() for i in s.investigations.values()])
        _write_sheet(wb, "actions",
                     ["id", "kind", "at", "on", "by", "doctor_id", "summary",
                      "why", "changes", "undone"],
                     [a.to_dict() for a in s.actions.values()])
        _write_sheet(wb, "logs",
                     ["id", "kind", "appointment_id", "before", "after",
                      "reason", "at"],
                     [lg.to_dict() for lg in s.logs])
        _write_sheet(wb, "notifications",
                     ["id", "patient_id", "channel", "body", "sent_at",
                      "status", "delivered_at", "reply", "replied_at",
                      "kind", "ref"],
                     [n.to_dict() for n in s.notifications])

        # atomic-ish write: temp file in same dir, then rename. On Windows
        # the target may briefly be locked (Excel/openpyxl handle), so we
        # retry and fall back to a direct overwrite.
        dirn = os.path.dirname(self.path) or "."
        fd, tmp = tempfile.mkstemp(suffix=".xlsx", dir=dirn)
        os.close(fd)
        try:
            wb.save(tmp)
            self._atomic_replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass

    def _atomic_replace(self, src: str, dst: str) -> None:
        for attempt in range(5):
            try:
                os.replace(src, dst)
                return
            except PermissionError:
                if attempt == 4:
                    # last resort: overwrite in place
                    with open(dst, "wb") as f:
                        with open(src, "rb") as s:
                            f.write(s.read())
                    return
                time.sleep(0.1 * (attempt + 1))

    # ------------------------------------------------------------------ #
    def _users(self) -> list[dict[str, Any]]:
        # users are seed-managed; kept in memory (loaded once) so that
        # password upgrades persist without re-reading the whole workbook
        if not self._users_cache:
            if os.path.exists(self.path):
                wb = load_workbook(self.path, data_only=True)
                if "users" in wb.sheetnames:
                    self._users_cache = _row_dicts(wb["users"])
        return self._users_cache

    def set_password_hash(self, username: str, new_hash: str) -> None:
        """Update a user's password hash in the in-memory users list. The
        change is persisted on the next save() (users are rewritten every time)."""
        for u in self._users_cache:
            if u.get("username") == username:
                u["password_hash"] = new_hash
                return

    # ------------------------------------------------------------------ #
    def users(self) -> list[dict[str, Any]]:
        return self._users()
