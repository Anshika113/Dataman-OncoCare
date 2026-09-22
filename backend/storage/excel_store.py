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
from typing import Any

from openpyxl import load_workbook, Workbook

from engine.state import (
    SystemState, Doctor, ChemRoom, Drug, Patient, Appointment,
    Emergency, LogEntry, Notification, NotificationStatus,
)
from storage.seed import XLSX as DEFAULT_XLSX, build as seed_build


def _with_leaves(d: dict[str, Any]) -> dict[str, Any]:
    """Decode the JSON-serialized ``leaves`` column into a list of dicts."""
    raw = d.get("leaves")
    if isinstance(raw, str) and raw.strip():
        try:
            d["leaves"] = json.loads(raw)
        except (ValueError, TypeError):
            d["leaves"] = []
    elif not isinstance(raw, list):
        d["leaves"] = []
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


class Store:
    def __init__(self, path: str = DEFAULT_XLSX) -> None:
        self.path = path
        self._lock = threading.RLock()
        if not os.path.exists(path):
            self.state = SystemState()
            seed_build(path)
            self._load()
        else:
            self._load()

    # ------------------------------------------------------------------ #
    def _load(self) -> None:
        wb = load_workbook(self.path, data_only=True)
        s = SystemState()

        for d in _row_dicts(wb["doctors"]):
            d = _with_leaves(d)
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
        for d in _row_dicts(wb["logs"]):
            s.logs.append(LogEntry(**{k: d.get(k, "") for k in
                          ("id", "kind", "appointment_id", "before", "after",
                           "reason", "at")}))
        for d in _row_dicts(wb["notifications"]):
            s.notifications.append(Notification(**{
                "id": d.get("id", ""),
                "patient_id": d.get("patient_id", ""),
                "channel": d.get("channel", ""),
                "body": d.get("body", ""),
                "sent_at": d.get("sent_at", ""),
                "status": NotificationStatus(d.get("status", "sent")),
            }))

        self.state = s

    # ------------------------------------------------------------------ #
    def save(self) -> None:
        with self._lock:
            s = self.state
            wb = Workbook()
            wb.remove(wb.active)

            _write_sheet(wb, "users",
                         ["id", "username", "password_hash", "role", "name",
                          "doctor_id"],
                         self._users())
            _write_sheet(wb, "doctors",
                         ["id", "name", "specialty", "daily_cap", "status",
                          "backup_compatible", "leave_reason", "leaves"],
                         [{**d.to_dict(),
                           "leaves": json.dumps(d.to_dict()["leaves"])}
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
                          "stage", "allergies", "insurance", "notes"],
                         [p.to_dict() for p in s.patients.values()])
            _write_sheet(wb, "appointments",
                         ["id", "patient_id", "doctor_id", "slot_start", "slot_end",
                          "type", "status", "room_id", "drug_id", "severity",
                          "buffer_before", "buffer_after", "checked_in",
                          "reschedule_reason", "visit_count", "last_visited"],
                         [a.to_dict() for a in s.appointments.values()])
            _write_sheet(wb, "emergencies",
                         ["id", "patient_id", "severity", "created_at", "subscore",
                          "assigned_doctor_id", "status"],
                         [e.to_dict() for e in s.emergencies.values()])
            _write_sheet(wb, "logs",
                         ["id", "kind", "appointment_id", "before", "after",
                          "reason", "at"],
                         [lg.to_dict() for lg in s.logs])
            _write_sheet(wb, "notifications",
                         ["id", "patient_id", "channel", "body", "sent_at", "status"],
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
        # users are seed-managed; re-read from disk so credentials persist
        if os.path.exists(self.path):
            wb = load_workbook(self.path, data_only=True)
            if "users" in wb.sheetnames:
                return _row_dicts(wb["users"])
        return []

    # ------------------------------------------------------------------ #
    def users(self) -> list[dict[str, Any]]:
        return self._users()
