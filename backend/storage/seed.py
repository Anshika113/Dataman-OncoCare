"""Generate a seed Excel workbook with realistic department data.

Run:  python -m storage.seed
Creates data/care.xlsx with sheets: doctors, rooms, drugs, patients,
appointments, emergencies, logs, notifications, users.
"""

from __future__ import annotations

import os

from openpyxl import Workbook

BASE = os.path.join(os.path.dirname(__file__), "..", "data")
XLSX = os.path.join(BASE, "care.xlsx")


def _ws(wb, name, headers):
    ws = wb.create_sheet(name)
    ws.append(headers)
    return ws


def build(path: str = XLSX) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    wb = Workbook()
    wb.remove(wb.active)

    # ---- users (login) ----
    # doctor_id links a login to a specific doctor record (empty for admin/nurse)
    ws = _ws(wb, "users",
             ["id", "username", "password_hash", "role", "name", "doctor_id"])
    # NOTE: passwords are demo-only. In production store proper password hashes.
    users = [
        ("USR-0001", "admin", "admin123", "admin", "System Admin", ""),
        ("USR-0002", "nurse", "nurse123", "nurse", "Nurse Station", ""),
        ("USR-0003", "doctor", "doctor123", "doctor", "Dr On Call", "DOC-0001"),
        ("USR-0004", "amina", "doctor123", "doctor", "Dr. Amina Khan", "DOC-0001"),
        ("USR-0005", "ben", "doctor123", "doctor", "Dr. Ben Ortiz", "DOC-0002"),
        ("USR-0006", "chloe", "doctor123", "doctor", "Dr. Chloe Wu", "DOC-0003"),
        ("USR-0007", "dan", "doctor123", "doctor", "Dr. Dan Meyer", "DOC-0004"),
        ("USR-0008", "elena", "doctor123", "doctor", "Dr. Elena Ross", "DOC-0005"),
    ]
    for u in users:
        ws.append(list(u))

    # ---- doctors ----
    ws = _ws(wb, "doctors",
             ["id", "name", "specialty", "daily_cap", "status",
              "backup_compatible", "leave_reason", "leaves"])
    doctors = [
        ("DOC-0001", "Dr. Amina Khan", "hematology", 18, "available",
         "hematology;oncology", ""),
        ("DOC-0002", "Dr. Ben Ortiz", "oncology", 16, "available",
         "oncology;hematology;radiation", ""),
        ("DOC-0003", "Dr. Chloe Wu", "radiation", 14, "available",
         "radiation;oncology", ""),
        ("DOC-0004", "Dr. Dan Meyer", "hematology", 18, "available",
         "hematology;oncology", ""),
        ("DOC-0005", "Dr. Elena Ross", "oncology", 16, "available",
         "oncology;hematology;radiation", ""),
    ]
    for d in doctors:
        ws.append(list(d) + ["[]"])  # leaves column (JSON list, empty)

    # ---- rooms ----
    ws = _ws(wb, "rooms",
             ["id", "name", "type", "equipment", "status", "available_until"])
    rooms = [
        ("RM-0001", "Infusion 1", "infusion_chair", "pump;monitor;iv", "available", ""),
        ("RM-0002", "Infusion 2", "infusion_chair", "pump;monitor;iv;oxygen", "available", ""),
        ("RM-0003", "Infusion 3", "infusion_chair", "pump;monitor;iv", "available", ""),
        ("RM-0004", "Isolation A", "isolation", "pump;monitor;iv;isolation", "available", ""),
        ("RM-0005", "Exam 1", "exam", "exam_table", "available", ""),
        ("RM-0006", "Exam 2", "exam", "exam_table", "available", ""),
    ]
    for r in rooms:
        ws.append(list(r))

    # ---- drugs (with time-of-day windows + grace) ----
    ws = _ws(wb, "drugs",
             ["id", "name", "tw_start", "tw_end", "grace_minutes",
              "required_equipment"])
    drugs = [
        ("DRG-0001", "Cisplatin", "08:00", "12:00", 15, "pump;monitor"),
        ("DRG-0002", "Paclitaxel", "09:00", "16:00", 20, "pump;monitor"),
        ("DRG-0003", "Doxorubicin", "08:00", "18:00", 10, "pump;monitor;iv"),
        ("DRG-0004", "Rituximab", "10:00", "14:00", 15, "pump;monitor;iv"),
        ("DRG-0005", "Oxaliplatin", "08:00", "13:00", 10, "pump;monitor"),
    ]
    for d in drugs:
        ws.append(list(d))

    # ---- patients (full registration fields) ----
    ws = _ws(wb, "patients",
             ["id", "name", "contact", "priority_tier", "dob", "age", "gender",
              "blood_group", "mr_number", "diagnosis", "stage", "allergies",
              "insurance", "notes"])
    patients = [
        ("PAT-0001", "Rahim Ullah", "+92 300 1111111", 3, "1968-04-12", "58", "male",
         "B+", "MR-1001", "Breast Cancer", "II", "Penicillin", "SEHA", ""),
        ("PAT-0002", "Sara Ahmed", "+92 301 2222222", 1, "1985-09-23", "40", "female",
         "A+", "MR-1002", "Lymphoma", "III", "", "Cigna", ""),
        ("PAT-0003", "Bilal Hussain", "+92 302 3333333", 2, "1972-01-30", "54", "male",
         "O-", "MR-1003", "Leukemia", "I", "Sulfa drugs", "SEHA", ""),
        ("PAT-0004", "Fatima Noor", "+92 303 4444444", 5, "1990-07-05", "35", "female",
         "AB+", "MR-1004", "Melanoma", "II", "", "Bupa", "VIP patient"),
        ("PAT-0005", "Usman Tariq", "+92 304 5555555", 2, "1955-11-18", "70", "male",
         "A-", "MR-1005", "Lung Cancer", "IV", "Aspirin", "self", ""),
        ("PAT-0006", "Ayesha Malik", "+92 305 6666666", 1, "1988-03-14", "37", "female",
         "B-", "MR-1006", "Ovarian Cancer", "II", "", "Cigna", ""),
        ("PAT-0007", "Hassan Ali", "+92 306 7777777", 3, "1961-12-02", "64", "male",
         "O+", "MR-1007", "Colorectal Cancer", "III", "None", "SEHA", ""),
        ("PAT-0008", "Zara Shah", "+92 307 8888888", 4, "1995-06-21", "30", "female",
         "A+", "MR-1008", "Thyroid Cancer", "I", "", "Bupa", ""),
    ]
    for p in patients:
        ws.append(list(p))

    # ---- appointments (a morning of realistic schedule) ----
    ws = _ws(wb, "appointments",
             ["id", "patient_id", "doctor_id", "slot_start", "slot_end",
              "type", "status", "room_id", "drug_id", "severity",
              "buffer_before", "buffer_after", "checked_in", "reschedule_reason"])
    appts = [
        ("APT-0001", "PAT-0001", "DOC-0001", "08:30", "09:00", "consult", "booked",
         "", "", 1, 0, 0, 0, ""),
        ("APT-0002", "PAT-0002", "DOC-0001", "09:00", "09:30", "chemo", "booked",
         "RM-0001", "DRG-0001", 1, 10, 10, 0, ""),
        ("APT-0003", "PAT-0003", "DOC-0002", "09:30", "10:00", "chemo", "booked",
         "RM-0002", "DRG-0002", 1, 10, 10, 0, ""),
        ("APT-0004", "PAT-0004", "DOC-0003", "10:00", "10:30", "consult", "booked",
         "", "", 1, 0, 0, 0, ""),
        ("APT-0005", "PAT-0005", "DOC-0001", "10:30", "11:00", "chemo", "booked",
         "RM-0003", "DRG-0003", 1, 10, 10, 0, ""),
        ("APT-0006", "PAT-0006", "DOC-0002", "11:00", "11:30", "consult", "booked",
         "", "", 1, 0, 0, 0, ""),
        ("APT-0007", "PAT-0007", "DOC-0004", "11:30", "12:00", "chemo", "booked",
         "RM-0001", "DRG-0004", 1, 10, 10, 0, ""),
        ("APT-0008", "PAT-0008", "DOC-0005", "12:00", "12:30", "consult", "booked",
         "", "", 1, 0, 0, 0, ""),
        ("APT-0009", "PAT-0001", "DOC-0002", "13:00", "13:30", "chemo", "booked",
         "RM-0002", "DRG-0005", 1, 10, 10, 0, ""),
        ("APT-0010", "PAT-0003", "DOC-0001", "13:30", "14:00", "consult", "booked",
         "", "", 1, 0, 0, 0, ""),
    ]
    for a in appts:
        ws.append(list(a))

    # ---- emergencies (empty to start) ----
    _ws(wb, "emergencies",
        ["id", "patient_id", "severity", "created_at", "subscore",
         "assigned_doctor_id", "status"])

    # ---- logs / notifications (empty to start) ----
    _ws(wb, "logs",
        ["id", "kind", "appointment_id", "before", "after", "reason", "at"])
    _ws(wb, "notifications",
        ["id", "patient_id", "channel", "body", "sent_at", "status"])

    wb.save(path)
    return path


if __name__ == "__main__":
    p = build()
    print("seeded:", p)
