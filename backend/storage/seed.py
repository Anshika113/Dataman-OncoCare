"""Generate a seed Excel workbook with realistic department data.

Run:  python -m storage.seed
Creates data/care.xlsx with sheets: doctors, rooms, drugs, patients,
appointments, actions, emergencies, logs, notifications, users.

The appointment rows cover five days, and they do different jobs:

``day-2``
    The clinic as it ran before any of this. Chairs held empty through lab
    waits, four patients sitting in the waiting room marked no-show because
    their slot passed, two cancellations nobody refilled.
``day-1``
    The same list, managed. The four treatments waiting on bloods are gated,
    so the chairs go back to the pool and the patients are treated later the
    same day instead of being written off. Both cancellations are backfilled
    off the waitlist, and one walk-in is placed.
``day 0``
    Today, played out to 11:30, so the app opens on a clinic in motion:
    visits done, patients in chairs, one waiting to be called, one treatment
    held for results, and an afternoon still to run.
``+1, +2``
    Booked only, so the multi-day and capacity views have something to show.

Day-2 and day-1 carry the *same* patients in the *same* slots. That is what
makes them comparable: the only thing that differs is whether the clinic was
managed. No outcome figure is stored here — engine/outcomes.py computes every
one of them from these timestamp columns, so the comparison is measured
rather than asserted.
"""

from __future__ import annotations

import json
import os

from openpyxl import Workbook

from engine.timeutils import today as _today, add_days, to_min, to_hhmm
from engine.sessions import weekday as _weekday

BASE = os.path.join(os.path.dirname(__file__), "..", "data")
XLSX = os.path.join(BASE, "care.xlsx")

#: Each doctor runs one clinic, Monday to Saturday. This is the denominator
#: every utilisation figure is measured against, so it has to be real: a
#: doctor with no session template counts as available all day, which would
#: make a full clinic look two-thirds empty.
CLINIC_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat"]
CLINIC_START = "08:30"
CLINIC_END = "14:00"

#: Eight appointments per doctor per day — four consults and four treatments,
#: alternating. Doctors are staggered ten minutes apart so that five clinics
#: running at once never want the same chair at the same moment.
SLOTS_PER_DOCTOR = 8
STAGGER_MIN = 10

DOCTOR_IDS = ["DOC-0001", "DOC-0002", "DOC-0003", "DOC-0004", "DOC-0005"]
#: One chair per clinic: with the stagger above this makes chair clashes
#: impossible by construction rather than by luck.
CHEMO_CHAIR = {
    "DOC-0001": "RM-0001",
    "DOC-0002": "RM-0002",
    "DOC-0003": "RM-0003",
    "DOC-0004": "RM-0007",
    "DOC-0005": "RM-0008",
}

#: Which treatments were waiting on bloods. The same (doctor, slot) pairs on
#: both past days: no-showed on day-2, gated and treated on day-1.
LAB_HELD = {(0, 1), (1, 3), (2, 5), (3, 1)}
#: Late cancellations. Dropped on day-2, backfilled on day-1.
CANCELLED = {(4, 7), (2, 3)}


def _ws(wb, name, headers):
    ws = wb.create_sheet(name)
    ws.append(headers)
    return ws


def _ladder(doctor_index: int) -> list[tuple[str, str, str]]:
    """One doctor's slots for a day: (start, end, type).

    Consults run 20 minutes, treatments 30, alternating, with a ten-minute
    gap after each so a single overrun does not topple the whole list.
    """
    out: list[tuple[str, str, str]] = []
    t = to_min(CLINIC_START) + doctor_index * STAGGER_MIN
    for i in range(SLOTS_PER_DOCTOR):
        chemo = i % 2 == 1
        length = 30 if chemo else 20
        out.append((to_hhmm(t), to_hhmm(t + length),
                    "chemo" if chemo else "consult"))
        t += length + 10
    return out


def _clinic_day(day: str, step: int) -> str:
    """Walk from ``day`` in ``step``-day hops to the next day a clinic runs.

    The session template is Monday to Saturday, so a seed that counted plain
    calendar days put a full forty-patient list on a Sunday — a day the same
    workbook says the clinic is shut. The appointments showed, and
    utilisation correctly refused to divide by a closed clinic, which is a
    contradiction a reader spots immediately.
    """
    d = add_days(day, step)
    while _weekday(d) not in CLINIC_DAYS:
        d = add_days(d, step)
    return d


def _drug_for(slot_start: str) -> str:
    """A drug whose time window actually contains this slot.

    Cisplatin closes at 12:00 and Rituximab opens at 10:00, so picking by the
    clock keeps every seeded treatment inside its own window — which is what
    the allocator would enforce anyway.
    """
    m = to_min(slot_start)
    if m >= to_min("12:00"):
        return "DRG-0003"        # Doxorubicin, 08:00-18:00
    if m >= to_min("10:00"):
        return "DRG-0004"        # Rituximab, 10:00-14:00
    return "DRG-0001"            # Cisplatin, 08:00-12:00


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
        ("USR-0009", "coord", "coord123", "coordinator", "Care Coordinator", ""),
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
              "backup_compatible", "leave_reason", "allow_safety_booking",
              "leaves", "sessions", "rules"])
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
    for n, d in enumerate(doctors, start=1):
        sessions = [{
            "id": f"SES-{n:04d}",
            "days": CLINIC_DAYS,
            "start": CLINIC_START,
            "end": CLINIC_END,
            "kind": "clinic",
            "label": "OPD clinic",
        }]
        ws.append(list(d) + [0, "[]", json.dumps(sessions), "[]"])

    # ---- rooms ----
    # Five infusion chairs — one per clinic — plus an isolation room kept free
    # for the neutropenic cases, and two exam rooms.
    ws = _ws(wb, "rooms",
             ["id", "name", "type", "equipment", "status", "available_until"])
    rooms = [
        ("RM-0001", "Infusion 1", "infusion_chair", "pump;monitor;iv", "available", ""),
        ("RM-0002", "Infusion 2", "infusion_chair", "pump;monitor;iv;oxygen", "available", ""),
        ("RM-0003", "Infusion 3", "infusion_chair", "pump;monitor;iv", "available", ""),
        ("RM-0007", "Infusion 4", "infusion_chair", "pump;monitor;iv", "available", ""),
        ("RM-0008", "Infusion 5", "infusion_chair", "pump;monitor;iv;oxygen", "available", ""),
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

    # ---- patients ----
    # Thirty, because forty appointments a day shared between eight people
    # would make every risk score and every learned duration meaningless.
    # consent_sms is on for most; naming the treatment in a message is off by
    # default and has to be asked for, which is what the scrubber then proves.
    ws = _ws(wb, "patients",
             ["id", "name", "contact", "priority_tier", "dob", "age", "gender",
              "blood_group", "mr_number", "diagnosis", "stage", "allergies",
              "insurance", "notes", "language", "consent_sms",
              "consent_name_treatment", "consent_attendant"])
    patients = [
        ("Rahim Ullah", "+91 98200 11101", 3, "1968-04-12", "58", "male", "B+",
         "Breast Cancer", "II", "Penicillin", "Ayushman Bharat", "", 1, 0, 1),
        ("Sara Ahmed", "+91 98200 11102", 1, "1985-09-23", "40", "female", "A+",
         "Lymphoma", "III", "", "Star Health", "", 1, 1, 0),
        ("Bilal Hussain", "+91 98200 11103", 2, "1972-01-30", "54", "male", "O-",
         "Leukemia", "I", "Sulfa drugs", "Ayushman Bharat", "", 1, 0, 1),
        ("Fatima Noor", "+91 98200 11104", 5, "1990-07-05", "35", "female", "AB+",
         "Melanoma", "II", "", "HDFC Ergo", "Prefers morning slots", 1, 0, 0),
        ("Usman Tariq", "+91 98200 11105", 2, "1955-11-18", "70", "male", "A-",
         "Lung Cancer", "IV", "Aspirin", "self", "Travels 60 km", 1, 0, 1),
        ("Ayesha Malik", "+91 98200 11106", 1, "1988-03-14", "37", "female", "B-",
         "Ovarian Cancer", "II", "", "Star Health", "", 1, 1, 1),
        ("Hassan Ali", "+91 98200 11107", 3, "1961-12-02", "64", "male", "O+",
         "Colorectal Cancer", "III", "None", "Ayushman Bharat", "", 1, 0, 0),
        ("Zara Shah", "+91 98200 11108", 4, "1995-06-21", "30", "female", "A+",
         "Thyroid Cancer", "I", "", "HDFC Ergo", "", 1, 0, 0),
        ("Meera Nair", "+91 98200 11109", 2, "1976-02-09", "50", "female", "B+",
         "Breast Cancer", "III", "", "Star Health", "", 1, 0, 1),
        ("Arjun Pillai", "+91 98200 11110", 3, "1964-08-27", "62", "male", "O+",
         "Prostate Cancer", "II", "Iodine", "Ayushman Bharat", "", 1, 0, 0),
        ("Lakshmi Iyer", "+91 98200 11111", 1, "1992-05-15", "34", "female", "AB-",
         "Cervical Cancer", "II", "", "self", "", 0, 0, 1),
        ("Imran Qureshi", "+91 98200 11112", 2, "1958-10-03", "68", "male", "A+",
         "Gastric Cancer", "III", "", "HDFC Ergo", "", 1, 0, 1),
        ("Deepa Menon", "+91 98200 11113", 4, "1983-01-22", "43", "female", "B+",
         "Lymphoma", "I", "Latex", "Star Health", "", 1, 1, 0),
        ("Vikram Rao", "+91 98200 11114", 3, "1970-07-11", "56", "male", "O-",
         "Pancreatic Cancer", "IV", "", "Ayushman Bharat", "Needs a wheelchair",
         1, 0, 1),
        ("Nadia Sheikh", "+91 98200 11115", 1, "1996-03-30", "30", "female", "A-",
         "Sarcoma", "II", "", "self", "", 1, 0, 0),
        ("Rohit Verma", "+91 98200 11116", 2, "1979-09-08", "47", "male", "B-",
         "Testicular Cancer", "I", "", "HDFC Ergo", "", 1, 0, 0),
        ("Shabana Khan", "+91 98200 11117", 3, "1966-12-19", "59", "female", "AB+",
         "Breast Cancer", "IV", "Penicillin", "Ayushman Bharat", "", 1, 0, 1),
        ("Kabir Das", "+91 98200 11118", 2, "1987-04-05", "39", "male", "O+",
         "Leukemia", "II", "", "Star Health", "", 1, 0, 0),
        ("Priya Sundaram", "+91 98200 11119", 1, "1991-11-28", "34", "female", "A+",
         "Ovarian Cancer", "III", "", "self", "", 0, 0, 1),
        ("Farhan Siddiqui", "+91 98200 11120", 4, "1954-06-16", "72", "male", "B+",
         "Bladder Cancer", "II", "Contrast dye", "Ayushman Bharat", "", 1, 0, 1),
        ("Anita Joshi", "+91 98200 11121", 2, "1974-02-24", "52", "female", "O-",
         "Colorectal Cancer", "III", "", "HDFC Ergo", "", 1, 1, 0),
        ("Tanvir Alam", "+91 98200 11122", 3, "1960-08-07", "66", "male", "A-",
         "Oesophageal Cancer", "IV", "", "self", "Interpreter sometimes needed",
         1, 0, 1),
        ("Kavya Reddy", "+91 98200 11123", 1, "1993-10-12", "33", "female", "B+",
         "Thyroid Cancer", "I", "", "Star Health", "", 1, 0, 0),
        ("Zaid Ansari", "+91 98200 11124", 2, "1981-05-29", "45", "male", "AB+",
         "Lymphoma", "II", "Sulfa drugs", "Ayushman Bharat", "", 1, 0, 0),
        ("Sunita Bhosale", "+91 98200 11125", 3, "1969-01-17", "57", "female", "O+",
         "Breast Cancer", "II", "", "HDFC Ergo", "", 1, 0, 1),
        ("Naveen Kumar", "+91 98200 11126", 2, "1977-07-03", "49", "male", "A+",
         "Renal Cancer", "III", "", "self", "", 1, 0, 0),
        ("Rukhsana Begum", "+91 98200 11127", 4, "1951-09-21", "75", "female", "B-",
         "Lung Cancer", "IV", "Morphine", "Ayushman Bharat", "Comes with her son",
         1, 0, 1),
        ("Aditya Ghosh", "+91 98200 11128", 1, "1989-12-08", "36", "male", "O+",
         "Leukemia", "I", "", "Star Health", "", 1, 0, 0),
        ("Fatima Sayed", "+91 98200 11129", 3, "1972-06-25", "54", "female", "A+",
         "Cervical Cancer", "III", "", "self", "", 1, 1, 1),
        ("Gaurav Chauhan", "+91 98200 11130", 2, "1984-03-11", "42", "male", "AB-",
         "Sarcoma", "II", "", "HDFC Ergo", "", 1, 0, 0),
    ]
    patient_ids: list[str] = []
    for n, p in enumerate(patients, start=1):
        pid = f"PAT-{n:04d}"
        patient_ids.append(pid)
        (name, contact, tier, dob, age, gender, blood, diagnosis, stage,
         allergies, insurance, notes, c_sms, c_name, c_att) = p
        # The reading language, mixed the way a Mumbai day-care unit's list
        # actually is. The console stays English; this only decides what the
        # patient's own page and their reminders open in.
        lang = "en" if n % 4 == 0 else "mr" if n % 7 == 0 else "hi"
        ws.append([pid, name, contact, tier, dob, age, gender, blood,
                   f"MR-{1000 + n}", diagnosis, stage, allergies, insurance,
                   notes, lang, c_sms, c_name, c_att])

    # ---- appointments ------------------------------------------------------ #
    ws = _ws(wb, "appointments",
             ["id", "patient_id", "doctor_id", "date", "slot_start", "slot_end",
              "type", "status", "room_id", "drug_id", "severity",
              "buffer_before", "buffer_after", "checked_in", "reschedule_reason",
              "walk_in", "awaiting_results", "held_room_id", "checked_in_at",
              "started_at", "completed_at", "chair_released_min", "confirmed"])

    day0 = _today()
    # the two most recent days the clinic actually ran, not merely the two
    # previous dates
    managed_day = _clinic_day(day0, -1)
    baseline_day = _clinic_day(managed_day, -1)

    counter = [0]

    def add(day, pat, doc, start, end, typ, room, drug, status,
            cin="", began="", done="", chair=0, walk_in=0, gated=0, held="",
            confirmed=""):
        counter[0] += 1
        buf = 10 if typ == "chemo" else 0
        ws.append([
            f"APT-{counter[0]:04d}", pat, doc, day, start, end, typ, status,
            room, drug, 1, buf, buf, 1 if cin else 0, "", walk_in, gated,
            held, cin, began, done, chair, confirmed,
        ])

    def emit_day(day, mode):
        """One day's forty appointments.

        ``mode`` picks the story: how long people waited, and which rows
        become a no-show, a gate, a cancellation or a backfill.
        """
        for d, doc in enumerate(DOCTOR_IDS):
            for i, (st, en, typ) in enumerate(_ladder(d)):
                # the same patients in the same slots on both past days, so
                # that the two days can be compared at all
                rot = 0 if mode in ("baseline", "managed") else 7
                pat = patient_ids[(d * SLOTS_PER_DOCTOR + i + rot)
                                  % len(patient_ids)]
                room = CHEMO_CHAIR[doc] if typ == "chemo" else ""
                drug = _drug_for(st) if typ == "chemo" else ""
                key = (d, i)
                arrive = to_hhmm(max(0, to_min(st) - 8))
                length = to_min(en) - to_min(st)

                if mode == "future":
                    add(day, pat, doc, st, en, typ, room, drug, "booked")
                    continue

                if key in CANCELLED:
                    add(day, pat, doc, st, en, typ, room, drug, "cancelled")
                    if mode == "managed":
                        # the chair went to someone who was already waiting
                        alt = patient_ids[(d * 3 + i + 19) % len(patient_ids)]
                        add(day, alt, doc, st, en, typ, room, drug,
                            "completed", arrive,
                            to_hhmm(to_min(arrive) + 15),
                            to_hhmm(to_min(arrive) + 15 + length),
                            confirmed="yes")
                    continue

                if mode == "baseline":
                    if key in LAB_HELD:
                        # present, bloods late, chair held, slot passed
                        add(day, pat, doc, st, en, typ, room, drug,
                            "no_show", arrive)
                        continue
                    wait = 22 + ((d * 7 + i * 5) % 30)
                    began = to_hhmm(to_min(arrive) + wait)
                    add(day, pat, doc, st, en, typ, room, drug, "completed",
                        arrive, began, to_hhmm(to_min(began) + length))
                    continue

                if mode == "managed":
                    if key in LAB_HELD:
                        # gated: chair handed back, treated once results landed
                        began = to_hhmm(to_min(st) + 120)
                        add(day, pat, doc, st, en, typ, room, drug,
                            "completed", arrive, began,
                            to_hhmm(to_min(began) + length), chair=length,
                            confirmed="yes")
                        continue
                    wait = 9 + ((d * 7 + i * 5) % 20)
                    began = to_hhmm(to_min(arrive) + wait)
                    add(day, pat, doc, st, en, typ, room, drug, "completed",
                        arrive, began, to_hhmm(to_min(began) + length),
                        confirmed="yes")
                    continue

                # mode == "today": played out to 11:30
                if key == (0, 1):
                    # held for results right now: the chair is already back in
                    # the pool, the patient is still in the building
                    add(day, pat, doc, st, en, typ, room, drug, "booked",
                        arrive, chair=length, gated=1, held=room)
                elif key == (1, 5):
                    # arrived and not yet called — what the arrivals board and
                    # the coordinator's list are for
                    add(day, pat, doc, st, en, typ, room, drug, "booked",
                        arrive, confirmed="yes")
                elif key == (3, 0):
                    add(day, pat, doc, st, en, typ, room, drug, "no_show")
                elif to_min(en) <= to_min("11:20"):
                    wait = 9 + ((d * 3 + i * 4) % 18)
                    began = to_hhmm(to_min(arrive) + wait)
                    add(day, pat, doc, st, en, typ, room, drug, "completed",
                        arrive, began, to_hhmm(to_min(began) + length),
                        confirmed="yes")
                elif to_min(st) <= to_min("11:30"):
                    wait = 10 + ((d * 3 + i * 4) % 11)
                    began = to_hhmm(to_min(arrive) + wait)
                    add(day, pat, doc, st, en, typ, room, drug, "active",
                        arrive, began, confirmed="yes")
                else:
                    add(day, pat, doc, st, en, typ, room, drug, "booked",
                        confirmed="yes" if i % 3 else "")

    emit_day(baseline_day, "baseline")
    emit_day(managed_day, "managed")
    # one walk-in placed into the managed day's spare capacity
    add(managed_day, patient_ids[11], "DOC-0005", "13:30", "13:50", "consult",
        "", "", "completed", "13:22", "13:32", "13:52", walk_in=1)
    # Today only gets a list if the clinic is open today. On a closed day the
    # honest demo is a quiet one, and the headline comparison still works
    # because it runs on the last two days the clinic ran.
    if _weekday(day0) in CLINIC_DAYS:
        emit_day(day0, "today")
    ahead1 = _clinic_day(day0, 1)
    emit_day(ahead1, "future")
    emit_day(_clinic_day(ahead1, 1), "future")

    # ---- actions ----
    # engine/outcomes.py counts a backfilled slot from a waitlist_accept
    # action, so the managed day carries the records its own engine would have
    # written when those two chairs were re-offered.
    ws = _ws(wb, "actions",
             ["id", "kind", "at", "on", "by", "doctor_id", "summary", "why",
              "changes", "undone"])
    backfills = [
        ("ACT-0001", "11:05", "DOC-0003",
         "Priya Sundaram took the freed chair",
         "slot freed by a late cancellation; she was already in the building"),
        ("ACT-0002", "12:40", "DOC-0005",
         "Kabir Das took the freed chair",
         "slot freed by a late cancellation; shortest journey of those waiting"),
    ]
    for aid, at, doc, summary, why in backfills:
        ws.append([aid, "waitlist_accept", at, managed_day, "coord", doc,
                   summary, why, "[]", 0])

    # ---- meta ----
    # The day every other date in this workbook is relative to. Without it
    # there is no way to tell a fresh demo from one built a week ago, and a
    # week-old demo is not stale in an obvious way — it is a clinic where
    # every patient was marked absent, because the watchdog did its job on
    # days that were seeded as "booked" and never checked in.
    ws = _ws(wb, "meta", ["key", "value"])
    ws.append(["seeded_for", day0])
    ws.append(["schema", "1"])

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
