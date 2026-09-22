"""FastAPI application for the cancer care department system.

Wires: Excel store + pure engine + auth + WebSocket broadcast + watchdog.

Run:  uvicorn api.main:app --reload --port 8000
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from engine import (
    SystemState, AppointmentStatus, Severity, Emergency, new_id, Patient,
    AppointmentAllocator, SlotRegistry, DoctorStatus, EngineResult,
    Action, SeverityCode,
    handle_doctor_sick_leave, handle_chemo_overrun, handle_room_breakdown,
    handle_no_show, handle_emergency_pair, advance_clock, resolve_emergencies,
    handle_doctor_take_leave, handle_doctor_cancel_leave,
    handle_doctor_mark_available, expire_leaves,
    handle_cancel_appointment, handle_room_restore,
    handle_emergency_assign, handle_emergency_complete,
    analyze,
    to_min, to_hhmm,
)
from storage.excel_store import Store
from services.security import (
    verify_token, require_role, make_token, check_password, now as clock_now,
)
from services.ws import ConnectionManager
from services.watchdog import Watchdog
from api import schemas

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("api")

# --------------------------------------------------------------------------- #
# Globals (single process; Excel store is the only shared mutable state)
# --------------------------------------------------------------------------- #
STORE = Store()
manager = ConnectionManager()
watchdog = Watchdog(interval=5.0, no_show_min=15, clock_fn=clock_now)


def _alloc():
    return AppointmentAllocator(STORE.state, SlotRegistry(STORE.state))


def _result(r) -> dict:
    return {
        "success": r.success,
        "action": r.action.value if hasattr(r.action, "value") else str(r.action),
        "message": r.message,
        "severity": r.severity.value,
        "actions": r.actions,
        "data": r.data,
    }


async def _commit(broadcast_type: str, payload: dict | None = None) -> None:
    """Persist state + push a real-time event to all connected dashboards."""
    STORE.save()
    await manager.broadcast({"type": broadcast_type, **(payload or {})})
    await manager.broadcast({"type": "state_refresh"})


def _self_or_staff():
    """Dependency: admin/nurse may act on any doctor; a doctor may act only on
    themselves (matched by the doctor_id in their JWT). The route's ``doctor_id``
    path parameter is injected into ``target`` by FastAPI."""
    def dep(doctor_id: str, user: dict = Depends(verify_token)) -> dict:
        role = user.get("role")
        if role in ("admin", "nurse"):
            return user
        if role == "doctor" and user.get("doctor_id") == doctor_id:
            return user
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "you can only manage your own availability")
    return dep


def _insights_payload() -> dict:
    """Current proactive insights (bottlenecks, capacity, waits, spare cap)."""
    now = clock_now()
    items = analyze(STORE.state, now)
    return {"now": now, "insights": [i.to_dict() for i in items]}


def _state_payload() -> dict:
    s = STORE.state
    now = clock_now()
    return {
        "doctors": [d.to_dict() for d in s.doctors.values()],
        "rooms": [r.to_dict() for r in s.rooms.values()],
        "drugs": [g.to_dict() for g in s.drugs.values()],
        "patients": [p.to_dict() for p in s.patients.values()],
        "appointments": [a.to_dict() for a in s.appointments.values()],
        "emergencies": [e.to_dict() for e in s.emergencies.values()],
        "insights": [i.to_dict() for i in analyze(s, now)],
        "insights_now": now,
        "logs": [l.to_dict() for l in s.logs[-200:]],
        "notifications": [n.to_dict() for n in s.notifications[-200:]],
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    await watchdog.start(STORE, manager.broadcast)
    log.info("care backend ready; %d appointments loaded",
             len(STORE.state.appointments))
    yield
    await watchdog.stop()


app = FastAPI(title="Dataman OncoCare API", version="1.0",
              lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #
@app.post("/api/login", response_model=schemas.LoginOut)
async def login(body: schemas.LoginIn):
    for u in STORE.users():
        if u.get("username") == body.username:
            if check_password(str(u.get("password_hash", "")), body.password):
                doctor_id = str(u.get("doctor_id") or "")
                return schemas.LoginOut(
                    token=make_token(u["username"], u.get("role", "nurse"), doctor_id),
                    role=u.get("role", "nurse"),
                    name=u.get("name", u["username"]),
                    doctor_id=doctor_id,
                )
    raise HTTPException(401, "invalid credentials")


# --------------------------------------------------------------------------- #
# Read endpoints
# --------------------------------------------------------------------------- #
@app.get("/api/state")
async def get_state(_=Depends(require_role("admin", "nurse", "doctor"))):
    return _state_payload()


@app.get("/api/doctors")
async def get_doctors(_=Depends(require_role("admin", "nurse", "doctor"))):
    return [d.to_dict() for d in STORE.state.doctors.values()]


@app.get("/api/appointments")
async def get_appointments(_=Depends(require_role("admin", "nurse", "doctor"))):
    return [a.to_dict() for a in STORE.state.appointments.values()]


# --------------------------------------------------------------------------- #
# Patients (registration + list with derived status + history)
# --------------------------------------------------------------------------- #
def _patient_status(state, patient_id: str) -> dict:
    """Derive a patient's current status from their appointments."""
    appts = [a for a in state.appointments.values() if a.patient_id == patient_id]
    active = [a for a in appts if a.status in (AppointmentStatus.ACTIVE,)]
    booked = [a for a in appts if a.status in (AppointmentStatus.BOOKED,
                                               AppointmentStatus.RESCHEDULED)]
    visited = [a for a in appts if a.status in (AppointmentStatus.VISITED,
                                                AppointmentStatus.COMPLETED)]
    has_emg = any(e.patient_id == patient_id and e.status in ("waiting", "assigned")
                  for e in state.emergencies.values())
    visits = sum(a.visit_count for a in appts)

    if has_emg:
        status, label = "emergency", "In Emergency"
    elif active:
        status, label = "active", "In Visit"
    elif booked:
        status, label = "scheduled", "Scheduled"
    elif visits > 0:
        status, label = "revisit", "Revisit / Follow-up"
    else:
        status, label = "new", "New Patient"
    return {"status": status, "label": label,
            "upcoming": len(booked), "visits": visits}


@app.get("/api/patients")
async def get_patients(_=Depends(require_role("admin", "nurse", "doctor"))):
    s = STORE.state
    out = []
    for p in s.patients.values():
        d = p.to_dict()
        d["appointment_count"] = len([a for a in s.appointments.values()
                                      if a.patient_id == p.id])
        d.update(_patient_status(s, p.id))
        out.append(d)
    out.sort(key=lambda x: x["name"])
    return out


@app.post("/api/patients")
async def create_patient(body: schemas.PatientIn,
                         _=Depends(require_role("admin", "nurse"))):
    p = Patient(new_id("PAT"), body.name, body.contact, body.priority_tier,
                dob=body.dob, age=body.age, gender=body.gender,
                blood_group=body.blood_group, mr_number=body.mr_number,
                diagnosis=body.diagnosis, stage=body.stage,
                allergies=body.allergies, insurance=body.insurance,
                notes=body.notes)
    STORE.state.patients[p.id] = p
    STORE.state.add_log("patient_created", p.id, "", p.name, "new patient", clock_now())
    await _commit("patient", {"id": p.id, "name": p.name})
    return p.to_dict()


@app.put("/api/patients/{patient_id}")
async def update_patient(patient_id: str, body: schemas.PatientIn,
                         _=Depends(require_role("admin", "nurse"))):
    p = STORE.state.patient(patient_id)
    if not p:
        raise HTTPException(404, "patient not found")
    p.name, p.contact = body.name, body.contact
    p.dob, p.age, p.gender = body.dob, body.age, body.gender
    p.blood_group, p.mr_number = body.blood_group, body.mr_number
    p.diagnosis, p.stage = body.diagnosis, body.stage
    p.allergies, p.insurance, p.notes = body.allergies, body.insurance, body.notes
    p.priority_tier = body.priority_tier
    await _commit("patient", {"id": patient_id, "name": p.name})
    return p.to_dict()


@app.delete("/api/patients/{patient_id}")
async def delete_patient(patient_id: str,
                         _=Depends(require_role("admin"))):
    p = STORE.state.patient(patient_id)
    if not p:
        raise HTTPException(404, "patient not found")
    # block deletion only if the patient still has *live* appointments
    live = {AppointmentStatus.BOOKED, AppointmentStatus.ACTIVE,
            AppointmentStatus.RESCHEDULED}
    has_live = any(a.patient_id == patient_id and a.status in live
                   for a in STORE.state.appointments.values())
    has_emg = any(e.patient_id == patient_id and e.status in ("waiting", "assigned")
                  for e in STORE.state.emergencies.values())
    if has_live or has_emg:
        raise HTTPException(400, "patient has live appointments or an active emergency; cancel them first")
    del STORE.state.patients[patient_id]
    STORE.state.add_log("patient_deleted", patient_id, p.name, "", "removed", clock_now())
    await _commit("patient", {"id": patient_id})
    return {"deleted": patient_id}


@app.get("/api/patients/{patient_id}/history")
async def patient_history(patient_id: str,
                          _=Depends(require_role("admin", "nurse", "doctor"))):
    s = STORE.state
    appts = [a.to_dict() for a in s.appointments.values()
             if a.patient_id == patient_id]
    appts.sort(key=lambda a: a["slot_start"])
    doctor = {d.id: d.name for d in s.doctors.values()}
    for a in appts:
        a["doctor_name"] = doctor.get(a["doctor_id"], "")
        a["is_revisit"] = a["visit_count"] >= 1
    ems = [e.to_dict() for e in s.emergencies.values()
           if e.patient_id == patient_id]
    return {"patient": s.patient(patient_id).to_dict(),
            "status": _patient_status(s, patient_id),
            "appointments": appts, "emergencies": ems}


@app.get("/api/queue")
async def get_queue(_=Depends(require_role("admin", "nurse", "doctor"))):
    """Live priority queue (emergencies first, then booked by time)."""
    s = STORE.state
    now = clock_now()
    ems = [e.to_dict() for e in s.emergencies.values() if e.status == "waiting"]
    for e in ems:
        em = s.emergencies[e["id"]]
        e["subscore"] = em.subscore
    booked = [
        a.to_dict() for a in s.appointments.values()
        if a.status == AppointmentStatus.BOOKED and to_min(a.slot_start) >= to_min(now)
    ]
    booked.sort(key=lambda a: a["slot_start"])
    return {"emergencies": ems, "up_next": booked}


@app.get("/api/logs")
async def get_logs(_=Depends(require_role("admin", "nurse"))):
    return [l.to_dict() for l in STORE.state.logs[-200:]]


@app.get("/api/notifications")
async def get_notifications(_=Depends(require_role("admin", "nurse"))):
    return [n.to_dict() for n in STORE.state.notifications[-200:]]


@app.get("/api/insights")
async def get_insights(_=Depends(require_role("admin", "nurse", "doctor"))):
    """Proactive bottleneck / capacity / wait-time analysis + recommendations.

    Pure read over the current state; also folded into ``/api/state`` so the
    live dashboard picks it up on every refresh without a separate call.
    """
    return _insights_payload()


# --------------------------------------------------------------------------- #
# Booking
# --------------------------------------------------------------------------- #
@app.post("/api/appointments/consult")
async def book_consult(body: schemas.BookConsultIn,
                       _=Depends(require_role("admin", "nurse"))):
    now = clock_now()
    r = _alloc().book_consult(body.patient_id, body.doctor_id,
                              body.slot_start, body.slot_end, at=now)
    if r.success:
        await _commit("booked", {"message": r.message})
    return _result(r)


@app.post("/api/appointments/chemo")
async def book_chemo(body: schemas.BookChemoIn,
                     _=Depends(require_role("admin", "nurse"))):
    now = clock_now()
    r = _alloc().book_chemo(body.patient_id, body.doctor_id, body.drug_id,
                            body.preferred_start, at=now)
    if r.success:
        await _commit("booked", {"message": r.message})
    return _result(r)


@app.post("/api/appointments/book-with-recs")
async def book_with_recs(body: schemas.BookWithRecsIn,
                         _=Depends(require_role("admin", "nurse"))):
    """Try to book the requested slot; if it's unavailable, return the best
    recommended slots so the UI can offer them. This is the 'slot not available
    -> recommend' flow."""
    now = clock_now()
    alloc = _alloc()
    is_chemo = body.appt_type == "chemo"

    # 1) attempt the booking at the preferred slot
    if is_chemo:
        r = alloc.book_chemo(body.patient_id, body.doctor_id, body.drug_id or "",
                             body.preferred_start, at=now)
    else:
        s = body.slot_start or body.preferred_start or "09:00"
        e = body.slot_end or to_hhmm(to_min(s) + 30)
        r = alloc.book_consult(body.patient_id, body.doctor_id, s, e, at=now)

    if r.success:
        await _commit("booked", {"message": r.message})
        return {**_result(r), "recommended": []}

    # 2) slot unavailable -> build recommendations
    if is_chemo:
        recs = alloc.recommend_chemo_slots(body.doctor_id, body.drug_id or "",
                                           body.preferred_start)
    else:
        recs = alloc.recommend_consult_slots(body.doctor_id, body.preferred_start)
    return {
        **_result(r),
        "recommended": recs,
        "reasons": r.data.get("candidates", []) if isinstance(r.data, dict) else [],
    }


@app.post("/api/appointments/{appt_id}/complete-visit")
async def complete_visit(appt_id: str,
                         _=Depends(require_role("admin", "nurse", "doctor"))):
    """Mark a visit as done. Increments the patient's visit count so the next
    booking is recognised as a revisit."""
    a = STORE.state.appointment(appt_id)
    if not a:
        raise HTTPException(404, "appointment not found")
    if a.status not in (AppointmentStatus.ACTIVE, AppointmentStatus.BOOKED,
                        AppointmentStatus.RESCHEDULED, AppointmentStatus.OVERRUN):
        return _result(EngineResult(False, Action.INFO,
                                    f"cannot complete: status is {a.status.value}",
                                    SeverityCode.WARNING))
    a.status = AppointmentStatus.VISITED
    a.visit_count += 1
    a.last_visited = clock_now()
    STORE.state.add_log("visit_completed", appt_id,
                        a.slot_start, f"visited@{clock_now()}",
                        f"visit #{a.visit_count}", clock_now())
    await _commit("visit", {"appt_id": appt_id, "visit_count": a.visit_count})
    return _result(EngineResult(True, Action.INFO,
                                f"visit completed (#{a.visit_count})",
                                SeverityCode.INFO,
                                data={"visit_count": a.visit_count}))


@app.post("/api/appointments/{appt_id}/reschedule")
async def reschedule(appt_id: str, body: schemas.RescheduleIn,
                     _=Depends(require_role("admin", "nurse"))):
    now = clock_now()
    r = _alloc().reschedule(appt_id, body.new_doctor_id, body.new_room_id,
                            body.slot_start, body.slot_end, at=now,
                            reason=body.reason)
    if r.success:
        await _commit("rescheduled", {"message": r.message})
    return _result(r)


@app.post("/api/appointments/{appt_id}/reschedule-auto")
async def reschedule_auto(appt_id: str, body: schemas.RescheduleAutoIn,
                          _=Depends(require_role("admin", "nurse"))):
    now = clock_now()
    r = _alloc().reschedule_auto(appt_id, at=now, reason=body.reason,
                                 only_doctor=not body.allow_backup_doctor)
    if r.success:
        await _commit("rescheduled", {"message": r.message})
    return _result(r)


@app.post("/api/appointments/{appt_id}/checkin")
async def checkin(appt_id: str, body: schemas.MarkCheckedInIn,
                  _=Depends(require_role("admin", "nurse", "doctor"))):
    a = STORE.state.appointment(appt_id)
    if not a:
        raise HTTPException(404, "appointment not found")
    a.checked_in = body.checked_in
    if body.checked_in and a.status == AppointmentStatus.BOOKED:
        a.status = AppointmentStatus.ACTIVE
    await _commit("checkin", {"appt_id": appt_id})
    return _result(EngineResult(True, Action.INFO, "checked in",
                                SeverityCode.INFO))


@app.post("/api/appointments/{appt_id}/cancel")
async def cancel_appt(appt_id: str, body: schemas.CancelIn,
                      _=Depends(require_role("admin", "nurse"))):
    """Manually cancel a booked appointment, releasing the slot and notifying
    the next patient in the queue."""
    r = handle_cancel_appointment(STORE.state, appt_id, clock_now(), body.reason)
    if r.success:
        await _commit("cancel", _result(r))
    return _result(r)


# --------------------------------------------------------------------------- #
# Edge cases
# --------------------------------------------------------------------------- #
@app.post("/api/doctors/{doctor_id}/sick-leave")
async def sick_leave(doctor_id: str, body: schemas.SickLeaveIn,
                     _=Depends(require_role("admin", "nurse"))):
    r = handle_doctor_sick_leave(STORE.state, doctor_id, clock_now(),
                                 body.reason)
    await _commit("sick_leave", _result(r))
    return _result(r)


# --------------------------------------------------------------------------- #
# Doctor availability / leave management (time-bounded)
# --------------------------------------------------------------------------- #
@app.post("/api/doctors/{doctor_id}/leave")
async def take_leave(doctor_id: str, body: schemas.LeaveIn,
                      _=Depends(_self_or_staff())):
    r = handle_doctor_take_leave(STORE.state, doctor_id, clock_now(),
                                  body.start, body.end, body.reason, body.full_day,
                                  date=body.date)
    await _commit("leave", _result(r))
    return _result(r)


@app.post("/api/doctors/{doctor_id}/leave/cancel")
async def cancel_leave(doctor_id: str, body: schemas.LeaveCancelIn,
                        _=Depends(_self_or_staff())):
    r = handle_doctor_cancel_leave(STORE.state, doctor_id, clock_now(),
                                    body.leave_id)
    await _commit("leave", _result(r))
    return _result(r)


@app.post("/api/doctors/{doctor_id}/available")
async def mark_available(doctor_id: str,
                          _=Depends(_self_or_staff())):
    r = handle_doctor_mark_available(STORE.state, doctor_id, clock_now())
    await _commit("leave", _result(r))
    return _result(r)


@app.post("/api/doctors/expire-leaves")
async def expire_leaves_endpoint(_=Depends(require_role("admin", "nurse"))):
    changed = expire_leaves(STORE.state, clock_now())
    await _commit("leave", {"changed": changed})
    return _result(EngineResult(
        True, Action.INFO,
        f"expired leaves; {len(changed)} doctor(s) became available" if changed
        else "no leaves to expire", SeverityCode.INFO, data={"changed": changed}))


@app.post("/api/appointments/{appt_id}/overrun")
async def overrun(appt_id: str, body: schemas.OverrunIn,
                  _=Depends(require_role("admin", "nurse"))):
    r = handle_chemo_overrun(STORE.state, appt_id, clock_now())
    await _commit("overrun", _result(r))
    return _result(r)


@app.post("/api/rooms/{room_id}/breakdown")
async def breakdown(room_id: str, body: schemas.RoomBreakdownIn,
                    _=Depends(require_role("admin", "nurse"))):
    r = handle_room_breakdown(STORE.state, room_id, clock_now(),
                               body.available_until, body.reason)
    await _commit("breakdown", _result(r))
    return _result(r)


@app.post("/api/rooms/{room_id}/restore")
async def restore_room(room_id: str, body: schemas.RoomRestoreIn,
                       _=Depends(require_role("admin", "nurse"))):
    """Return a broken-down room to available (inverse of breakdown)."""
    r = handle_room_restore(STORE.state, room_id, clock_now(), body.reason)
    await _commit("room_restore", _result(r))
    return _result(r)


@app.post("/api/appointments/{appt_id}/no-show")
async def no_show(appt_id: str, body: schemas.NoShowIn,
                  _=Depends(require_role("admin", "nurse"))):
    r = handle_no_show(STORE.state, appt_id, clock_now(), body.no_show_min)
    await _commit("no_show", _result(r))
    return _result(r)


@app.post("/api/clock/advance")
async def clock(body: schemas.ClockAdvanceIn,
                _=Depends(require_role("admin", "nurse"))):
    out = advance_clock(STORE.state, clock_now(), body.no_show_min)
    if out["no_shows"] or out["overruns"]:
        await _commit("clock", out)
    else:
        STORE.save()
        await manager.broadcast({"type": "state_refresh"})
    return _result(EngineResult(
        True, Action.INFO, f"clock advanced to {out['now']}", SeverityCode.INFO,
        actions=out["no_shows"] + out["overruns"], data=out))


# --------------------------------------------------------------------------- #
# Emergencies
# --------------------------------------------------------------------------- #
@app.post("/api/emergencies")
async def add_emergency(body: schemas.EmergencyIn,
                        _=Depends(require_role("admin", "nurse", "doctor"))):
    now = clock_now()
    em = Emergency(new_id("EMG"), body.patient_id, Severity.from_int(body.severity),
                   now)
    STORE.state.emergencies[em.id] = em
    r = resolve_emergencies(STORE.state, now)
    await _commit("emergency", _result(r))
    return _result(r)


@app.post("/api/emergencies/pair")
async def emergency_pair(body: schemas.EmergencyPairIn,
                         _=Depends(require_role("admin", "nurse"))):
    r = handle_emergency_pair(STORE.state, body.e1_id, body.e2_id, clock_now())
    await _commit("emergency", _result(r))
    return _result(r)


@app.post("/api/emergencies/resolve")
async def resolve_emer(_=Depends(require_role("admin", "nurse"))):
    r = resolve_emergencies(STORE.state, clock_now())
    await _commit("emergency", _result(r))
    return _result(r)


@app.post("/api/emergencies/{emergency_id}/assign")
async def assign_emergency(emergency_id: str, body: schemas.EmergencyAssignIn,
                           _=Depends(require_role("admin", "nurse"))):
    """Manually assign an emergency to a specific doctor (overrides auto-assign)."""
    r = handle_emergency_assign(STORE.state, emergency_id, body.doctor_id,
                                clock_now())
    if r.success:
        await _commit("emergency", _result(r))
    return _result(r)


@app.post("/api/emergencies/{emergency_id}/complete")
async def complete_emergency(emergency_id: str,
                             _=Depends(require_role("admin", "nurse"))):
    """Mark an emergency as finished / cleared from the live queue."""
    r = handle_emergency_complete(STORE.state, emergency_id, clock_now())
    if r.success:
        await _commit("emergency", _result(r))
    return _result(r)


# --------------------------------------------------------------------------- #
# WebSocket (real-time)
# --------------------------------------------------------------------------- #
@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await manager.connect(ws)
    try:
        # send the current snapshot on connect
        await ws.send_text(__import__("json").dumps(
            {"type": "snapshot", "state": _state_payload()}))
        while True:
            # we only push; ignore inbound pings/echo
            msg = await ws.receive_text()
            if msg == "ping":
                await ws.send_text(__import__("json").dumps({"type": "pong"}))
    except WebSocketDisconnect:
        manager.disconnect(ws)
    except Exception:  # noqa: BLE001
        manager.disconnect(ws)
