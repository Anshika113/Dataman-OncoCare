"""Getting data in and out.

The brief describes the problem as fragmentation — *"care teams often rely on
multiple systems"* — and the app answered that by having no way in or out at
all: the patient list came from a seed script and left only as rows in an
Excel file nobody else reads.

Three doors, deliberately small:

* **CSV in**, because that is what a hospital can actually produce from its
  existing HIS without a project. Validated and previewable first — an
  import that half-succeeds is worse than one that refuses.
* **CSV out**, for the people who will open it in Excel.
* **A FHIR-shaped bundle**, because the first question a health panel asks is
  "does it speak a standard?" This is a faithful resource *shape*, not a
  certified implementation, and it says so.
"""

from __future__ import annotations

import csv
import io
import re
from typing import Any, Optional

from engine.state import Patient, new_id

#: Columns an import may carry. Only `name` is required.
PATIENT_COLUMNS = (
    "name", "contact", "dob", "age", "gender", "blood_group", "mr_number",
    "diagnosis", "stage", "allergies", "insurance", "notes", "priority_tier",
    "consent_sms", "consent_name_treatment", "consent_attendant",
)

_TRUE = {"1", "true", "yes", "y", "on"}
_FALSE = {"0", "false", "no", "n", "off", ""}


def _as_bool(raw: Any, default: bool) -> bool:
    s = str(raw).strip().lower()
    if s in _TRUE:
        return True
    if s in _FALSE:
        return False
    return default


def _clean(row: dict) -> dict:
    return {str(k or "").strip().lower(): str(v or "").strip()
            for k, v in row.items()}


# --------------------------------------------------------------------------- #
# In
# --------------------------------------------------------------------------- #
def parse_patients(text: str) -> dict:
    """Read a CSV into candidate rows, with every problem named by line.

    Nothing is written. The caller shows this, and only then imports.
    """
    if not text or not text.strip():
        return {"rows": [], "errors": ["the file is empty"], "columns": []}

    reader = csv.DictReader(io.StringIO(text))
    cols = [c.strip().lower() for c in (reader.fieldnames or [])]
    if "name" not in cols:
        return {"rows": [], "columns": cols,
                "errors": ["a 'name' column is required"]}

    unknown = [c for c in cols if c not in PATIENT_COLUMNS]
    errors: list[str] = []
    if unknown:
        errors.append("ignored unknown column(s): " + ", ".join(unknown))

    rows: list[dict] = []
    seen_mr: set[str] = set()
    for i, raw in enumerate(reader, start=2):   # line 1 is the header
        d = _clean(raw)
        name = d.get("name", "")
        if not name:
            errors.append(f"line {i}: no name — skipped")
            continue
        mr = d.get("mr_number", "")
        if mr and mr in seen_mr:
            errors.append(f"line {i}: duplicate mr_number {mr} in this file — skipped")
            continue
        if mr:
            seen_mr.add(mr)

        tier = d.get("priority_tier", "1")
        try:
            tier_i = min(5, max(1, int(tier or 1)))
        except ValueError:
            errors.append(f"line {i}: priority_tier {tier!r} is not a number — used 1")
            tier_i = 1

        contact = d.get("contact", "")
        if contact and not re.fullmatch(r"[0-9+\-() ]{6,20}", contact):
            errors.append(f"line {i}: contact {contact!r} does not look like a number")

        rows.append({
            "line": i,
            "name": name,
            "contact": contact,
            "dob": d.get("dob", ""),
            "age": d.get("age", ""),
            "gender": d.get("gender", ""),
            "blood_group": d.get("blood_group", ""),
            "mr_number": mr,
            "diagnosis": d.get("diagnosis", ""),
            "stage": d.get("stage", ""),
            "allergies": d.get("allergies", ""),
            "insurance": d.get("insurance", ""),
            "notes": d.get("notes", ""),
            "priority_tier": tier_i,
            # consent defaults match the app's own: naming the treatment is off
            "consent_sms": _as_bool(d.get("consent_sms", "1"), True),
            "consent_name_treatment": _as_bool(
                d.get("consent_name_treatment", "0"), False),
            "consent_attendant": _as_bool(d.get("consent_attendant", "1"), True),
        })

    return {"rows": rows, "errors": errors, "columns": cols}


def preview(state, parsed: dict) -> dict:
    """Say what an import would do before it does it."""
    by_mr = {p.mr_number: p for p in state.patients.values() if p.mr_number}
    by_name = {p.name.lower(): p for p in state.patients.values()}
    creates, updates = [], []
    for r in parsed["rows"]:
        existing = (by_mr.get(r["mr_number"]) if r["mr_number"]
                    else by_name.get(r["name"].lower()))
        (updates if existing else creates).append(
            {**r, "existing_id": existing.id if existing else ""})
    return {"create": creates, "update": updates,
            "errors": parsed["errors"], "columns": parsed["columns"]}


def import_patients(state, parsed: dict, now: str) -> dict:
    """Apply an import. Matches on `mr_number` first, then on name."""
    plan = preview(state, parsed)
    created, updated = [], []

    for r in plan["create"]:
        p = Patient(
            new_id("PAT"), r["name"], r["contact"], r["priority_tier"],
            dob=r["dob"], age=r["age"], gender=r["gender"],
            blood_group=r["blood_group"], mr_number=r["mr_number"],
            diagnosis=r["diagnosis"], stage=r["stage"],
            allergies=r["allergies"], insurance=r["insurance"],
            notes=r["notes"], consent_sms=r["consent_sms"],
            consent_name_treatment=r["consent_name_treatment"],
            consent_attendant=r["consent_attendant"])
        state.patients[p.id] = p
        created.append(p.id)

    for r in plan["update"]:
        p = state.patient(r["existing_id"])
        if p is None:
            continue
        for field in ("contact", "dob", "age", "gender", "blood_group",
                      "mr_number", "diagnosis", "stage", "allergies",
                      "insurance", "notes"):
            if r[field]:
                setattr(p, field, r[field])
        p.priority_tier = r["priority_tier"]
        updated.append(p.id)

    state.add_log("patients_imported", "", "",
                  f"{len(created)} created, {len(updated)} updated",
                  "CSV import", now)
    return {"created": len(created), "updated": len(updated),
            "errors": plan["errors"],
            "created_ids": created, "updated_ids": updated}


# --------------------------------------------------------------------------- #
# Out
# --------------------------------------------------------------------------- #
def patients_csv(state) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=["id", *PATIENT_COLUMNS],
                       lineterminator="\n")
    w.writeheader()
    for p in state.patients.values():
        d = p.to_dict()
        w.writerow({k: d.get(k, "") for k in ["id", *PATIENT_COLUMNS]})
    return buf.getvalue()


def appointments_csv(state) -> str:
    cols = ["id", "patient_id", "patient_name", "doctor_id", "doctor_name",
            "date", "slot_start", "slot_end", "type", "visit_type", "status",
            "room_id", "drug_id", "walk_in", "checked_in_at", "started_at",
            "completed_at"]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, lineterminator="\n")
    w.writeheader()
    for a in state.appointments.values():
        d = a.to_dict()
        p, doc = state.patient(a.patient_id), state.doctor(a.doctor_id)
        d["patient_name"] = p.name if p else ""
        d["doctor_name"] = doc.name if doc else ""
        w.writerow({k: d.get(k, "") for k in cols})
    return buf.getvalue()


#: Statuses mapped onto the FHIR Appointment value set.
_FHIR_STATUS = {
    "booked": "booked", "rescheduled": "booked", "active": "arrived",
    "overrun": "arrived", "visited": "fulfilled", "completed": "fulfilled",
    "cancelled": "cancelled", "no_show": "noshow",
    "emergency_waiting": "waitlist",
}


def fhir_bundle(state, day: Optional[str] = None) -> dict:
    """A FHIR-*shaped* searchset Bundle of Patients and Appointments.

    This is the resource shape, not a certified implementation: no profiles,
    no terminology binding beyond the status value set, no identifiers system
    URIs that mean anything outside this deployment. It exists so another
    system has something to read, and so the shape is honest about what it is.
    """
    entries: list[dict] = []

    for p in state.patients.values():
        ident = [{"system": "urn:oncocare:patient-id", "value": p.id}]
        if p.mr_number:
            ident.append({"system": "urn:oncocare:mrn", "value": p.mr_number})
        res: dict[str, Any] = {
            "resourceType": "Patient",
            "id": p.id,
            "identifier": ident,
            "name": [{"text": p.name}],
        }
        if p.gender:
            res["gender"] = p.gender.lower()
        if p.dob:
            res["birthDate"] = p.dob
        if p.contact:
            res["telecom"] = [{"system": "phone", "value": p.contact}]
        entries.append({"resource": res})

    for a in state.appointments.values():
        if day and a.eff_date != day:
            continue
        doc = state.doctor(a.doctor_id)
        entries.append({"resource": {
            "resourceType": "Appointment",
            "id": a.id,
            "status": _FHIR_STATUS.get(a.status.value, "booked"),
            "start": f"{a.eff_date}T{a.slot_start}:00",
            "end": f"{a.eff_date}T{a.slot_end}:00",
            "minutesDuration": a.planned_min,
            "participant": [
                {"actor": {"reference": f"Patient/{a.patient_id}"},
                 "status": "accepted"},
                {"actor": {"reference": f"Practitioner/{a.doctor_id}",
                           "display": doc.name if doc else ""},
                 "status": "accepted"},
            ],
        }})

    return {
        "resourceType": "Bundle",
        "type": "searchset",
        "total": len(entries),
        "entry": entries,
        "meta": {"tag": [{
            "system": "urn:oncocare:disclaimer",
            "code": "fhir-shaped",
            "display": "FHIR-shaped export, not a certified FHIR server",
        }]},
    }
