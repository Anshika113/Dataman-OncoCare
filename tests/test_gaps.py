"""The four gaps the brief left open: coordinator, interop, capacity, patient.

Each of these exists because the problem statement names something the app
could not do. The tests pin the part that makes each one trustworthy rather
than merely present: the coordinator list only surfaces people genuinely
unattended, an import refuses rather than half-applies, capacity counts the
hours the clinic really has, and the patient page leaks nothing.
"""

from __future__ import annotations

import pytest

from engine import (
    SystemState, Doctor, ChemRoom, Drug, Patient, Appointment,
    AppointmentType, AppointmentStatus, RoomType, DoctorStatus, TimeWindow,
    SessionBlock, WaitlistEntry, NotificationStatus,
    coordination as coord, capacity as cap, patient_view as pview,
    investigations as iv,
)
from services import interop

TODAY = "2026-11-02"      # a Monday
TOMORROW = "2026-11-03"


@pytest.fixture
def state() -> SystemState:
    s = SystemState()
    s.doctors = {
        "D1": Doctor("D1", "Dr One", "oncology", 20, DoctorStatus.AVAILABLE),
        "D2": Doctor("D2", "Dr Two", "oncology", 20, DoctorStatus.AVAILABLE),
    }
    s.rooms = {"R1": ChemRoom("R1", "Infusion 1", RoomType.INFUSION_CHAIR,
                              ["pump", "monitor", "iv"])}
    s.drugs = {"G1": Drug("G1", "FOLFOX", TimeWindow("08:00", "18:00"), 10,
                          ["pump"])}
    s.patients = {f"P{i}": Patient(f"P{i}", f"Patient {i}", f"+9155500{i}", 1)
                  for i in range(1, 6)}
    s.active_day = TODAY
    return s


def _appt(s, aid, pid, did="D1", start="10:00", end="10:30", day=TODAY, **kw):
    a = Appointment(aid, pid, did, start, end, AppointmentType.CONSULT)
    a.date = day
    for k, v in kw.items():
        setattr(a, k, v)
    s.appointments[aid] = a
    return a


# --------------------------------------------------------------------------- #
# 1. Care coordinator
# --------------------------------------------------------------------------- #
def test_a_quiet_clinic_produces_an_empty_list(state):
    _appt(state, "A1", "P1")
    assert coord.follow_up_list(state, "10:05")["rows"] == []


def test_a_missed_visit_with_nothing_rebooked_is_surfaced(state):
    _appt(state, "A1", "P1", status=AppointmentStatus.NO_SHOW)
    rows = coord.follow_up_list(state, "11:00")["rows"]
    assert [r["kind"] for r in rows] == ["no_show_unrebooked"]
    assert rows[0]["severity"] == "critical"
    assert rows[0]["action"] == "Call and rebook"


def test_a_missed_visit_already_rebooked_is_not(state):
    _appt(state, "A1", "P1", status=AppointmentStatus.NO_SHOW)
    _appt(state, "A2", "P1", start="15:00", end="15:30")
    assert coord.follow_up_list(state, "11:00")["rows"] == []


def test_an_arrival_nobody_called_is_surfaced(state):
    _appt(state, "A1", "P1", checked_in=True, checked_in_at="09:30")
    rows = coord.follow_up_list(state, "10:30")["rows"]   # 60 min waiting
    assert any(r["kind"] == "stranded" for r in rows)


def test_someone_waiting_ten_minutes_is_not(state):
    _appt(state, "A1", "P1", checked_in=True, checked_in_at="10:00")
    assert coord.follow_up_list(state, "10:10")["rows"] == []


def test_a_lab_gate_nobody_chased_is_surfaced(state):
    a = _appt(state, "A1", "P1", start="09:00", end="10:30")
    iv.order(state, "P1", "CBC", now="08:40", day=TODAY, appointment_id="A1")
    iv.gate(state, "A1", now="09:00")
    rows = coord.follow_up_list(state, "10:30")["rows"]
    gate = next(r for r in rows if r["kind"] == "gate_stale")
    assert "CBC" in gate["why"]
    assert gate["action"] == "Chase the lab"


def test_a_message_that_could_not_be_sent_is_surfaced(state):
    n = state.add_notification("P1", "sms", "Your appointment moved", "10:00")
    n.status = NotificationStatus.BLOCKED
    rows = coord.follow_up_list(state, "10:05")["rows"]
    assert any(r["kind"] == "message_blocked" for r in rows)
    assert any(r["action"] == "Phone them instead" for r in rows)


def test_a_forgotten_waitlist_entry_is_surfaced(state):
    state.waitlist["W1"] = WaitlistEntry(
        "W1", "P2", "D1", added_at="08:00", added_on=TODAY)
    rows = coord.follow_up_list(state, "11:00")["rows"]
    assert any(r["kind"] == "waitlist_stale" for r in rows)


def test_the_worst_things_sort_first(state):
    state.waitlist["W1"] = WaitlistEntry("W1", "P2", "D1", added_at="08:00")
    _appt(state, "A1", "P1", status=AppointmentStatus.NO_SHOW)
    rows = coord.follow_up_list(state, "11:00")["rows"]
    assert rows[0]["severity"] == "critical"


# --------------------------------------------------------------------------- #
# 2. Interop
# --------------------------------------------------------------------------- #
def test_a_csv_without_a_name_column_is_refused():
    out = interop.parse_patients("contact,dob\n+91,2000-01-01\n")
    assert out["rows"] == []
    assert "'name' column is required" in out["errors"][0]


def test_rows_without_a_name_are_skipped_by_line():
    out = interop.parse_patients(
        "name,contact\nAsha,+911234567\n,+911234568\n")
    assert len(out["rows"]) == 1
    assert any("line 3" in e and "no name" in e for e in out["errors"])


def test_a_contact_that_is_not_a_number_is_flagged_but_kept():
    out = interop.parse_patients("name,contact\nAsha,not-a-phone\n")
    assert len(out["rows"]) == 1          # a bad phone is not a lost patient
    assert any("does not look like a number" in e for e in out["errors"])


def test_a_duplicate_mrn_inside_one_file_is_skipped():
    out = interop.parse_patients(
        "name,mr_number\nAsha,MR1\nAsha Again,MR1\n")
    assert len(out["rows"]) == 1
    assert any("duplicate mr_number" in e for e in out["errors"])


def test_naming_the_treatment_defaults_to_off_on_import():
    out = interop.parse_patients("name\nAsha\n")
    assert out["rows"][0]["consent_sms"] is True
    assert out["rows"][0]["consent_name_treatment"] is False


def test_preview_writes_nothing(state):
    before = len(state.patients)
    parsed = interop.parse_patients("name\nBrand New\n")
    plan = interop.preview(state, parsed)
    assert len(plan["create"]) == 1
    assert len(state.patients) == before


def test_import_matches_on_mrn_before_name(state):
    state.patient("P1").mr_number = "MR9"
    parsed = interop.parse_patients(
        "name,mr_number,contact\nRenamed Person,MR9,+99\n")
    out = interop.import_patients(state, parsed, "10:00")
    assert out["updated"] == 1 and out["created"] == 0
    assert state.patient("P1").contact == "+99"


def test_import_creates_what_it_cannot_match(state):
    parsed = interop.parse_patients("name,contact\nBrand New,+91\n")
    out = interop.import_patients(state, parsed, "10:00")
    assert out["created"] == 1
    assert any(p.name == "Brand New" for p in state.patients.values())


def test_the_csv_export_round_trips(state):
    text = interop.patients_csv(state)
    again = interop.parse_patients(text)
    assert len(again["rows"]) == len(state.patients)


def test_the_fhir_bundle_is_shaped_and_says_what_it_is(state):
    _appt(state, "A1", "P1")
    b = interop.fhir_bundle(state)
    assert b["resourceType"] == "Bundle" and b["type"] == "searchset"
    kinds = {e["resource"]["resourceType"] for e in b["entry"]}
    assert kinds == {"Patient", "Appointment"}
    assert b["meta"]["tag"][0]["code"] == "fhir-shaped"


def test_fhir_status_uses_the_value_set(state):
    _appt(state, "A1", "P1", status=AppointmentStatus.NO_SHOW)
    appt = next(e["resource"] for e in interop.fhir_bundle(state)["entry"]
                if e["resource"]["resourceType"] == "Appointment")
    assert appt["status"] == "noshow"


# --------------------------------------------------------------------------- #
# 3. Multi-day capacity
# --------------------------------------------------------------------------- #
def test_capacity_counts_the_whole_working_day_by_default(state):
    _appt(state, "A1", "P1", start="09:00", end="11:00")
    d = cap.day_capacity(state, TODAY)
    assert d["available_min"] == 1200          # two doctors × 600
    assert d["committed_min"] == 120
    assert d["pct"] == 10


def test_a_session_template_shrinks_what_is_available(state):
    state.doctor("D1").sessions = [
        SessionBlock("S1", ["mon"], "09:00", "13:00", "clinic", "OPD")]
    d = cap.day_capacity(state, TODAY, "D1")
    assert d["available_min"] == 240


def test_a_closed_day_is_not_zero_per_cent(state):
    state.doctor("D1").sessions = [
        SessionBlock("S1", ["tue"], "09:00", "13:00", "clinic", "OPD")]
    d = cap.day_capacity(state, TODAY, "D1")       # Monday: no clinic
    assert d["available_min"] == 0
    assert d["pct"] is None
    assert d["tone"] == "closed"


def test_an_over_committed_day_is_called_out(state):
    state.doctor("D1").sessions = [
        SessionBlock("S1", ["*"], "09:00", "10:00", "clinic", "OPD")]
    _appt(state, "A1", "P1", start="09:00", end="11:00")   # 120 of 60
    d = cap.day_capacity(state, TODAY, "D1")
    assert d["pct"] == 200
    assert d["tone"] == "over"


def test_the_horizon_names_the_move_to_make(state):
    state.doctor("D1").sessions = [
        SessionBlock("S1", ["*"], "09:00", "10:00", "clinic", "OPD")]
    _appt(state, "A1", "P1", start="09:00", end="11:00")
    h = cap.horizon(state, TODAY, 3, "D1")
    assert h["busiest"] == TODAY
    assert any("over-committed" in a for a in h["advice"])


def test_a_quiet_week_says_so_rather_than_inventing_a_problem(state):
    h = cap.horizon(state, TODAY, 3)
    assert any("No day in this window is tight" in a for a in h["advice"])


def test_a_doctor_on_leave_contributes_nothing(state):
    state.doctor("D1").status = DoctorStatus.ON_LEAVE
    d = cap.day_capacity(state, TODAY, "D1")
    assert d["available_min"] == 0


# --------------------------------------------------------------------------- #
# 4. The patient's own view
# --------------------------------------------------------------------------- #
def test_the_page_never_names_the_treatment_without_consent(state):
    a = _appt(state, "A1", "P1", start="10:00", end="11:30")
    a.type = AppointmentType.CHEMO
    a.drug_id = "G1"
    assert state.patient("P1").consent_name_treatment is False
    assert pview.status_for(state, a, "09:50")["treatment"] == ""

    state.patient("P1").consent_name_treatment = True
    assert pview.status_for(state, a, "09:50")["treatment"] == "FOLFOX"


def test_the_page_carries_no_other_patient(state):
    _appt(state, "A1", "P1", checked_in=True, checked_in_at="09:30")
    mine = _appt(state, "A2", "P2", start="10:30", end="11:00",
                 checked_in=True, checked_in_at="09:45")
    blob = str(pview.status_for(state, mine, "10:00"))
    assert "Patient 1" not in blob


def test_a_waiting_patient_is_told_how_many_are_ahead(state):
    _appt(state, "A1", "P1", checked_in=True, checked_in_at="09:00")
    mine = _appt(state, "A2", "P2", start="10:30", end="11:00",
                 checked_in=True, checked_in_at="09:45")
    out = pview.status_for(state, mine, "10:00")
    assert out["stage"] == "ready"
    assert out["people_ahead"] == 1
    assert "ahead of you" in out["advice"]


def test_someone_waiting_on_labs_is_reassured_not_alarmed(state):
    a = _appt(state, "A1", "P1", checked_in=True, checked_in_at="09:30",
              awaiting_results=True)
    out = pview.status_for(state, a, "10:00")
    assert out["stage"] == "in_labs"
    assert "not lost your place" in out["advice"]


def test_a_cancelled_visit_shows_nothing(state):
    a = _appt(state, "A1", "P1", status=AppointmentStatus.CANCELLED)
    assert pview.safe_to_show(state, a) is False


def test_a_patient_can_still_answer_before_they_arrive(state):
    a = _appt(state, "A1", "P1")
    assert pview.status_for(state, a, "09:00")["can_confirm"] is True
    a.status = AppointmentStatus.VISITED
    assert pview.status_for(state, a, "12:00")["can_confirm"] is False


# --------------------------------------------------------------------------- #
# One row per reason, or one per patient — each in its right place
# --------------------------------------------------------------------------- #
# The coordinator's own list keeps a row per *reason*: two rows for one
# patient are two jobs with two actions, and folding them would hide one.
# Anywhere that list is summarised, the same name twice reads as a bug. These
# pin both halves of that, and that severity is the worst of the set rather
# than whichever reason happened to be first.
def test_two_reasons_for_one_patient_fold_into_one_row():
    from engine import coordination as coord
    rows = [
        {"patient_id": "P1", "patient_name": "Meera Nair",
         "severity": "warning", "summary": "held for results since 09:00"},
        {"patient_id": "P1", "patient_name": "Meera Nair",
         "severity": "critical", "summary": "waiting 158 min since 08:52"},
    ]
    out = coord.by_patient(rows)
    assert len(out) == 1
    assert out[0]["patient_name"] == "Meera Nair"
    assert out[0]["reasons"] == 2


def test_the_worst_reason_leads_and_sets_the_severity():
    from engine import coordination as coord
    rows = [
        {"patient_id": "P1", "patient_name": "A", "severity": "info",
         "summary": "quiet"},
        {"patient_id": "P1", "patient_name": "A", "severity": "critical",
         "summary": "urgent"},
        {"patient_id": "P1", "patient_name": "A", "severity": "warning",
         "summary": "middling"},
    ]
    out = coord.by_patient(rows)
    assert out[0]["severity"] == "critical"
    assert out[0]["summary"].startswith("urgent")


def test_different_patients_are_never_merged():
    from engine import coordination as coord
    rows = [
        {"patient_id": "P1", "patient_name": "A", "severity": "critical",
         "summary": "x"},
        {"patient_id": "P2", "patient_name": "B", "severity": "warning",
         "summary": "y"},
    ]
    assert len(coord.by_patient(rows)) == 2


def test_a_single_reason_is_left_exactly_as_it_was():
    from engine import coordination as coord
    row = {"patient_id": "P1", "patient_name": "A", "severity": "warning",
           "summary": "one thing", "action": "call"}
    out = coord.by_patient([row])
    assert out[0]["summary"] == "one thing"
    assert out[0]["action"] == "call"
    assert "reasons" not in out[0]


def test_the_order_patients_first_appeared_in_is_kept():
    from engine import coordination as coord
    rows = [
        {"patient_id": "P2", "patient_name": "B", "severity": "warning",
         "summary": "y"},
        {"patient_id": "P1", "patient_name": "A", "severity": "critical",
         "summary": "x"},
        {"patient_id": "P1", "patient_name": "A", "severity": "info",
         "summary": "z"},
    ]
    out = coord.by_patient(rows)
    assert [r["patient_name"] for r in out] == ["B", "A"]


def test_folding_never_invents_a_row():
    from engine import coordination as coord
    rows = [{"patient_id": f"P{i}", "patient_name": f"N{i}",
             "severity": "info", "summary": "s"} for i in range(5)]
    assert len(coord.by_patient(rows)) == 5
    assert coord.by_patient([]) == []
