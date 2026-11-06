"""FastAPI application for the cancer care department system.

Wires: Excel store + pure engine + auth + WebSocket broadcast + watchdog.

Run:  uvicorn api.main:app --reload --port 8000
"""

from __future__ import annotations

import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import (
    FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException,
    Request, Query, UploadFile, File,
)
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
    analyze, build_queue,
    to_min, to_hhmm,
)
from engine import (visits, waitlist as wl, investigations as inv,
                    arrivals as arr, risk as rk, actions as acts,
                    clinic_control as ctl, sessions as sess,
                    privacy as priv, context as ctx,
                    outcomes as out, coordination as coord,
                    capacity as cap, patient_view as pview,
                    ask as askq, guide as gde, propose as prop)
from engine import SessionBlock, CaseMixRule
from storage.excel_store import Store
from services.security import (
    verify_token, require_role, make_token, check_password, upgrade_password,
    decode_token, now as clock_now, today as clock_today,
    settings as sec_settings, login_throttled, login_failed, login_succeeded,
    revoke_token, bump_token_version,
)
from services.ws import ConnectionManager
from services.watchdog import Watchdog
from services.observability import AUDIT, METRICS
from services.messaging import Dispatcher, record_reply
from fastapi.responses import Response
from services import interop, sarvam
from services.security import appointment_token, appointment_for_token
from api import schemas

#: Hands queued patient messages to a provider. With no CARE_SMS_WEBHOOK
#: configured this logs them and marks them delivered, so the flow is real
#: without credentials.
DISPATCHER = Dispatcher()

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("api")

# --------------------------------------------------------------------------- #
# Globals (single process; Excel store is the only shared mutable state)
# --------------------------------------------------------------------------- #
STORE = Store()
manager = ConnectionManager()
watchdog = Watchdog(interval=5.0, no_show_min=15, clock_fn=clock_now)


def _alloc():
    return AppointmentAllocator(STORE.state, SlotRegistry(STORE.state))


def _sync_day() -> str:
    """Pin the engine's working day to the current department day.

    Called on every read/mutation path so day-scoped queries (capacity,
    availability, insights, triggers) always operate on the day the clock is
    running on. Cheap: only writes the string when it actually changed.
    """
    day = clock_today()
    if STORE.state.active_day != day:
        STORE.state.active_day = day
    return day


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
    """Persist state + push a real-time event to all connected dashboards.

    Called from *inside* an ``async_mutation`` block (mutation lock held), so
    the blocking openpyxl write is pushed to the thread pool — this keeps the
    event loop responsive for other requests and the watchdog while the file is
    written, and the lock is still held so no other mutation interleaves."""
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, STORE._persist)
    # Hand any queued patient messages to the provider before telling the UI.
    # This talks to the network, so it goes to the thread pool for the same
    # reason the Excel write above does: with a real driver configured it can
    # take seconds per message, and on the event loop that would stall every
    # other request and the watchdog with it.
    await loop.run_in_executor(None, DISPATCHER.flush, STORE.state,
                               clock_now())
    await manager.broadcast({"type": broadcast_type, **(payload or {})})
    await manager.broadcast({"type": "state_refresh"})


# Single event-loop mutex that serialises ALL state mutation: API requests
# (via ``async_mutation``) and the watchdog (via ``store_lock`` from its worker
# thread, using run_coroutine_threadsafe). Holding it means "I am the only
# thing touching SystemState right now". The lock is only ever acquired/released
# on the event loop (acquire is a coroutine; the watchdog schedules its
# acquire/release onto the loop), so it is always consistent.
_MUTATION_LOCK: asyncio.Lock | None = None
_MAIN_LOOP: asyncio.AbstractEventLoop | None = None


def _loop() -> asyncio.AbstractEventLoop:
    return asyncio.get_running_loop()


async def _get_lock() -> asyncio.Lock:
    global _MUTATION_LOCK
    if _MUTATION_LOCK is None:
        _MUTATION_LOCK = asyncio.Lock()
    return _MUTATION_LOCK


@asynccontextmanager
async def async_mutation():
    """Serialise a state-mutating request. The engine mutation is cheap and
    runs on the loop; the caller's ``_commit`` pushes the blocking openpyxl
    save to the thread pool while still holding this lock."""
    lock = await _get_lock()
    await lock.acquire()
    try:
        yield
    finally:
        lock.release()


def store_lock() -> "_MutationGuard":
    """Cross-thread guard for the watchdog (runs in a worker thread). Blocks
    until the event loop grants the mutation lock, then yields. Must be used as
    a context manager inside the worker thread."""
    return _MutationGuard()


class _MutationGuard:
    def __init__(self) -> None:
        self._acq_future = None
        self._rel_future = None

    def _submit(self, coro):
        if _MAIN_LOOP is None:
            raise RuntimeError("event loop not captured yet")
        return asyncio.run_coroutine_threadsafe(coro, _MAIN_LOOP)

    def __enter__(self):
        self._acq_future = self._submit(self._acquire())
        self._acq_future.result(timeout=30)  # block the worker thread until granted
        return self

    def __exit__(self, *exc):
        self._rel_future = self._submit(self._release())
        self._rel_future.result(timeout=30)
        return False

    @staticmethod
    async def _acquire():
        await (await _get_lock()).acquire()

    @staticmethod
    async def _release():
        (await _get_lock()).release()


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


def _own_day_or_403(claims: dict, appt_id: str = "",
                    doctor_id: str = "") -> None:
    """A doctor may rearrange their own list and nobody else's.

    Admin and nurse run the floor and are not restricted here; the engine
    still refuses anything that would break a constraint.
    """
    if claims.get("role") != "doctor":
        return
    mine = claims.get("doctor_id", "")
    if appt_id:
        a = STORE.state.appointment(appt_id)
        if a is None:
            raise HTTPException(404, "appointment not found")
        if a.doctor_id != mine:
            raise HTTPException(403, "that patient is not on your list")
    if doctor_id and doctor_id != mine:
        raise HTTPException(403, "you can only manage your own list")


def _waitlist_row(entry) -> dict:
    """A waitlist entry with the names the UI needs to render it."""
    p = STORE.state.patient(entry.patient_id)
    d = STORE.state.doctor(entry.doctor_id) if entry.doctor_id else None
    return {**entry.to_dict(),
            "patient_name": p.name if p else entry.patient_id,
            "doctor_name": d.name if d else "Any doctor"}


def _consult_window(slot_start: str, slot_end: Optional[str],
                    visit_type: Optional[str],
                    duration_min: Optional[int]) -> tuple[str, str, str]:
    """Resolve a consult's (start, end, visit_type).

    Precedence: an explicit ``slot_end`` wins, then an explicit
    ``duration_min``, then the visit type's own length. Callers that send
    neither keep the historical 30-minute behaviour.
    """
    vtype = visit_type if visits.is_visit_type(visit_type or "") else ""
    if slot_end:
        return slot_start, slot_end, vtype
    if duration_min:
        mins = visits.clamp_duration(duration_min)
    elif vtype:
        mins = visits.default_duration(vtype)
    else:
        mins = 30
    return slot_start, to_hhmm(to_min(slot_start) + mins), vtype


def _insights_payload() -> dict:
    """Current proactive insights (bottlenecks, capacity, waits, spare cap)."""
    _sync_day()
    now = clock_now()
    items = analyze(STORE.state, now)
    return {"now": now, "date": STORE.state.active_day,
            "insights": [i.to_dict() for i in items]}


def _state_payload() -> dict:
    _sync_day()
    s = STORE.state
    now = clock_now()
    return {
        "now": now,
        "active_day": s.active_day,
        "doctors": [d.to_dict() for d in s.doctors.values()],
        "rooms": [r.to_dict() for r in s.rooms.values()],
        "drugs": [g.to_dict() for g in s.drugs.values()],
        "patients": [p.to_dict() for p in s.patients.values()],
        "appointments": [a.to_dict() for a in s.appointments.values()],
        "emergencies": [e.to_dict() for e in s.emergencies.values()],
        "visit_types": visits.catalogue(),
        "waitlist": [_waitlist_row(w) for w in s.waitlist.values() if w.active],
        "investigations": [i.to_dict() for i in s.investigations.values()],
        "gated": inv.gated_appointments(s),
        "arrivals": arr.board(s, now),
        "running_late": arr.running_late(s, now),
        "insights": [i.to_dict() for i in analyze(s, now)],
        "insights_now": now,
        # How many people nobody is currently looking after. The assistant's
        # badge counts this plus the insights above — things the clinic has
        # already flagged, never a judgement of its own.
        "follow_ups_total": coord.follow_up_list(s, now).get("total", 0),
        "logs": [l.to_dict() for l in s.logs[-200:]],
        "notifications": [n.to_dict() for n in s.notifications[-200:]],
        "messaging_driver": DISPATCHER.driver_name,
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _MAIN_LOOP
    _MAIN_LOOP = asyncio.get_running_loop()
    await watchdog.start(STORE, manager.broadcast)
    log.info("care backend ready; %d appointments loaded",
             len(STORE.state.appointments))
    yield
    await watchdog.stop()


app = FastAPI(title="DataMan OncoCare API", version="1.0",
               lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=sec_settings.cors_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def _request_metrics(request: Request, call_next):
    """Time every request, count by method+path+status, update gauges."""
    import time as _time
    t0 = _time.perf_counter()
    METRICS.set_gauge("ws_clients", manager.count)
    response = await call_next(request)
    dur = _time.perf_counter() - t0
    METRICS.inc("http_requests_total", 1.0)
    METRICS.inc(f"http_duration_ms_total", dur * 1000.0)
    response.headers["X-Process-Ms"] = f"{dur * 1000:.1f}"
    return response


@app.get("/metrics")
async def metrics_endpoint():
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(METRICS.render(),
                             media_type="text/plain; version=0.0.4")

# The built frontend is mounted LAST (see _mount_frontend at the bottom of the
# file) so the API/WS routes registered above always take precedence.


@app.exception_handler(ValueError)
async def _value_error_handler(request: Request, exc: ValueError):
    """Engine/validation ValueErrors are client errors, not server errors."""
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(KeyError)
async def _key_error_handler(request: Request, exc: KeyError):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=404,
                        content={"detail": f"unknown id: {exc.args[0] if exc.args else '?'}"})


@app.get("/health")
async def health():
    """Liveness + readiness probe (no auth)."""
    return {"ok": True, "ws_clients": manager.count,
            "appointments": len(STORE.state.appointments)}


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #
@app.post("/api/login", response_model=schemas.LoginOut)
async def login(body: schemas.LoginIn, request: Request):
    login_throttled(request.client.host if request.client else "unknown")
    for u in STORE.users():
        if u.get("username") == body.username:
            stored = str(u.get("password_hash", ""))
            if check_password(stored, body.password):
                # transparently upgrade legacy plaintext/sha256 creds to bcrypt
                upgraded = upgrade_password(stored, body.password)
                if upgraded:
                    STORE.set_password_hash(body.username, upgraded)
                doctor_id = str(u.get("doctor_id") or "")
                token, _jti = make_token(u["username"], u.get("role", "nurse"),
                                         doctor_id)
                login_succeeded(request.client.host
                                if request.client else "unknown")
                AUDIT.record("login_success", actor=body.username,
                             role=u.get("role", "nurse"),
                             ip=request.client.host if request.client else "")
                return schemas.LoginOut(
                    token=token,
                    role=u.get("role", "nurse"),
                    name=u.get("name", u["username"]),
                    doctor_id=doctor_id,
                )
    login_failed(request.client.host if request.client else "unknown")
    AUDIT.record("login_failure", actor=body.username,
                 ip=request.client.host if request.client else "")
    raise HTTPException(401, "invalid credentials")


@app.post("/api/logout")
async def logout(user: dict = Depends(verify_token)):
    """Revoke the presenting token and invalidate all of the user's sessions
    (bumps the token version)."""
    if user.get("jti"):
        revoke_token(user["jti"])
    bump_token_version(user["username"])
    AUDIT.record("logout", actor=user["username"], role=user.get("role", ""))
    return {"ok": True}


def _ws_auth(token: str | None) -> dict:
    """Validate a JWT presented on the WebSocket. Raises HTTPException ->
    FastAPI closes the socket before it is accepted."""
    if not token:
        raise HTTPException(401, "missing token")
    return decode_token(token)


# --------------------------------------------------------------------------- #
# Read endpoints
# --------------------------------------------------------------------------- #
@app.get("/api/state")
async def get_state(_=Depends(require_role("admin", "nurse", "doctor", "coordinator"))):
    return _state_payload()


@app.get("/api/doctors")
async def get_doctors(_=Depends(require_role("admin", "nurse", "doctor", "coordinator"))):
    return [d.to_dict() for d in STORE.state.doctors.values()]


@app.get("/api/appointments")
async def get_appointments(_=Depends(require_role("admin", "nurse", "doctor", "coordinator"))):
    return [a.to_dict() for a in STORE.state.appointments.values()]


@app.get("/api/doctors/{doctor_id}/visit-durations")
async def get_visit_durations(doctor_id: str,
                              _=Depends(require_role("admin", "nurse", "doctor", "coordinator"))):
    """This doctor's visit types, each with the planned length and — once
    enough visits have actually been timed — the median they really run.

    The suggestion is returned, never applied: booking only changes length if
    someone picks it.
    """
    if STORE.state.doctor(doctor_id) is None:
        raise HTTPException(404, "doctor not found")
    return {"doctor_id": doctor_id,
            "visit_types": visits.catalogue(STORE.state, doctor_id)}


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
async def get_patients(_=Depends(require_role("admin", "nurse", "doctor", "coordinator"))):
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
    async with async_mutation():
        p = Patient(new_id("PAT"), body.name, body.contact, body.priority_tier,
                    dob=body.dob, age=body.age, gender=body.gender,
                    blood_group=body.blood_group, mr_number=body.mr_number,
                    diagnosis=body.diagnosis, stage=body.stage,
                    allergies=body.allergies, insurance=body.insurance,
                    notes=body.notes,
                    consent_sms=body.consent_sms,
                    consent_name_treatment=body.consent_name_treatment,
                    consent_attendant=body.consent_attendant)
        STORE.state.patients[p.id] = p
        STORE.state.add_log("patient_created", p.id, "", p.name, "new patient", clock_now())
        await _commit("patient", {"id": p.id, "name": p.name})
        return p.to_dict()


@app.put("/api/patients/{patient_id}")
async def update_patient(patient_id: str, body: schemas.PatientIn,
                         _=Depends(require_role("admin", "nurse"))):
    async with async_mutation():
        p = STORE.state.patient(patient_id)
        if not p:
            raise HTTPException(404, "patient not found")
        p.name, p.contact = body.name, body.contact
        p.dob, p.age, p.gender = body.dob, body.age, body.gender
        p.blood_group, p.mr_number = body.blood_group, body.mr_number
        p.diagnosis, p.stage = body.diagnosis, body.stage
        p.allergies, p.insurance, p.notes = body.allergies, body.insurance, body.notes
        p.priority_tier = body.priority_tier
        p.consent_sms = body.consent_sms
        p.consent_name_treatment = body.consent_name_treatment
        p.consent_attendant = body.consent_attendant
        await _commit("patient", {"id": patient_id, "name": p.name})
        return p.to_dict()


@app.delete("/api/patients/{patient_id}")
async def delete_patient(patient_id: str,
                         _=Depends(require_role("admin"))):
    async with async_mutation():
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
                          _=Depends(require_role("admin", "nurse", "doctor", "coordinator"))):
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
async def get_queue(_=Depends(require_role("admin", "nurse", "doctor", "coordinator"))):
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
async def get_notifications(_=Depends(require_role("admin", "nurse", "doctor", "coordinator"))):
    return [n.to_dict() for n in STORE.state.notifications[-200:]]


@app.get("/api/audit")
async def get_audit(limit: int = 200,
                    _=Depends(require_role("admin"))):
    """Security/audit trail: logins, logouts, failures (no PHI)."""
    return AUDIT.recent(min(max(limit, 1), 1000))


@app.get("/api/insights")
async def get_insights(_=Depends(require_role("admin", "nurse", "doctor", "coordinator"))):
    """Proactive bottleneck / capacity / wait-time analysis + recommendations.

    Pure read over the current state; also folded into ``/api/state`` so the
    live dashboard picks it up on every refresh without a separate call.
    """
    return _insights_payload()


@app.get("/api/dates")
async def get_dates(_=Depends(require_role("admin", "nurse", "doctor", "coordinator"))):
    """Days the schedule spans, so the UI can offer a day selector.

    Returns the distinct appointment dates (ascending) plus the active working
    day, so a client can default the selector to today and jump to future days.
    """
    _sync_day()
    s = STORE.state
    days = sorted({a.eff_date for a in s.appointments.values()})
    active = s.active_day
    if active not in days:
        days.append(active)
        days.sort()
    return {"active_day": active, "days": days}


# --------------------------------------------------------------------------- #
# Booking
# --------------------------------------------------------------------------- #
@app.post("/api/appointments/consult")
async def book_consult(body: schemas.BookConsultIn,
                       _=Depends(require_role("admin", "nurse"))):
    async with async_mutation():
        _sync_day()
        now = clock_now()
        start, end, vtype = _consult_window(
            body.slot_start, body.slot_end, body.visit_type, body.duration_min)
        r = _alloc().book_consult(body.patient_id, body.doctor_id,
                                  start, end,
                                  at=now, date=body.date or None,
                                  visit_type=vtype)
        if r.success:
            await _commit("booked", {"message": r.message})
        return _result(r)


@app.post("/api/appointments/chemo")
async def book_chemo(body: schemas.BookChemoIn,
                     _=Depends(require_role("admin", "nurse"))):
    async with async_mutation():
        _sync_day()
        now = clock_now()
        r = _alloc().book_chemo(body.patient_id, body.doctor_id, body.drug_id,
                                body.preferred_start, at=now,
                                date=body.date or None)
        if r.success:
            await _commit("booked", {"message": r.message})
        return _result(r)


@app.post("/api/appointments/book-with-recs")
async def book_with_recs(body: schemas.BookWithRecsIn,
                         _=Depends(require_role("admin", "nurse", "coordinator"))):
    """Try to book the requested slot; if it's unavailable, return the best
    recommended slots so the UI can offer them. This is the 'slot not available
    -> recommend' flow."""
    async with async_mutation():
        _sync_day()
        now = clock_now()
        alloc = _alloc()
        is_chemo = body.appt_type == "chemo"
        date = body.date or None

        # 1) attempt the booking at the preferred slot
        if is_chemo:
            r = alloc.book_chemo(body.patient_id, body.doctor_id, body.drug_id or "",
                                 body.preferred_start, at=now, date=date)
        else:
            s, e, vtype = _consult_window(
                body.slot_start or body.preferred_start or "09:00",
                body.slot_end, body.visit_type, body.duration_min)
            r = alloc.book_consult(body.patient_id, body.doctor_id, s, e, at=now,
                                   date=date, visit_type=vtype)

        if r.success:
            await _commit("booked", {"message": r.message})
            return {**_result(r), "recommended": []}

        # 2) slot unavailable -> build recommendations (same day)
        if is_chemo:
            recs = alloc.recommend_chemo_slots(body.doctor_id, body.drug_id or "",
                                               body.preferred_start, date=date)
        else:
            _s, _e, _vt = _consult_window(
                body.slot_start or body.preferred_start or "09:00",
                body.slot_end, body.visit_type, body.duration_min)
            recs = alloc.recommend_consult_slots(
                body.doctor_id, body.preferred_start, date=date,
                duration=to_min(_e) - to_min(_s))
        return {
            **_result(r),
            "recommended": recs,
            "reasons": r.data.get("candidates", []) if isinstance(r.data, dict) else [],
        }


@app.post("/api/appointments/{appt_id}/extend")
async def extend_visit(appt_id: str, body: schemas.ExtendIn,
                       claims=Depends(require_role("admin", "nurse", "doctor", "coordinator"))):
    """More time with this patient; only this doctor's own later list moves."""
    async with async_mutation():
        _sync_day()
        _own_day_or_403(claims, appt_id=appt_id)
        r = ctl.extend(STORE.state, appt_id, body.minutes, clock_now(),
                       by=claims.get("username", ""))
        if r.success:
            await _commit("extend", {"message": r.message})
        return _result(r)


@app.post("/api/doctors/{doctor_id}/pull-forward")
async def pull_forward(doctor_id: str,
                       claims=Depends(require_role("admin", "nurse", "doctor", "coordinator"))):
    """Bring this doctor's next patient into the gap that just opened."""
    async with async_mutation():
        _sync_day()
        _own_day_or_403(claims, doctor_id=doctor_id)
        r = ctl.pull_forward(STORE.state, doctor_id, clock_now(),
                             by=claims.get("username", ""))
        if r.success:
            await _commit("pull_forward", {"message": r.message})
        return _result(r)


@app.post("/api/appointments/{appt_id}/swap")
async def swap_appointments(appt_id: str, body: schemas.SwapIn,
                            claims=Depends(require_role("admin", "nurse", "doctor", "coordinator"))):
    async with async_mutation():
        _sync_day()
        _own_day_or_403(claims, appt_id=appt_id)
        r = ctl.swap(STORE.state, appt_id, body.other_appointment_id,
                     clock_now(), by=claims.get("username", ""))
        if r.success:
            await _commit("swap", {"message": r.message})
        return _result(r)


@app.post("/api/appointments/{appt_id}/hand-off")
async def hand_off_appointment(appt_id: str, body: schemas.HandOffIn,
                               claims=Depends(require_role("admin", "nurse", "doctor", "coordinator"))):
    """Give one patient to a named colleague, if they can take them."""
    async with async_mutation():
        _sync_day()
        _own_day_or_403(claims, appt_id=appt_id)
        r = ctl.hand_off(STORE.state, appt_id, body.to_doctor_id, clock_now(),
                         reason=body.reason, by=claims.get("username", ""),
                         note=body.note)
        if r.success:
            await _commit("hand_off", {"message": r.message})
        return _result(r)


@app.post("/api/doctors/{doctor_id}/close-list")
async def close_list(doctor_id: str, body: schemas.CloseListIn,
                     claims=Depends(require_role("admin", "nurse", "doctor", "coordinator"))):
    """Stop taking patients after a time. Returns the plan unless `apply`."""
    async with async_mutation():
        _sync_day()
        _own_day_or_403(claims, doctor_id=doctor_id)
        r = ctl.close_list(STORE.state, doctor_id, body.from_time, clock_now(),
                           _alloc(), dry_run=not body.apply,
                           by=claims.get("username", ""))
        if r.success and body.apply:
            await _commit("close_list", {"message": r.message})
        return _result(r)


@app.get("/api/actions")
async def get_actions(doctor_id: str = "", limit: int = 20,
                      claims=Depends(require_role("admin", "nurse", "doctor", "coordinator"))):
    """What moved on the schedule, why, and whether it can be put back."""
    _sync_day()
    if claims.get("role") == "doctor" and not doctor_id:
        doctor_id = claims.get("doctor_id", "")
    return {"actions": acts.recent(STORE.state, doctor_id,
                                   limit=min(max(limit, 1), 100))}


@app.post("/api/actions/{action_id}/undo")
async def undo_action(action_id: str,
                      claims=Depends(require_role("admin", "nurse", "doctor", "coordinator"))):
    """Put the schedule back the way it was before that change."""
    async with async_mutation():
        _sync_day()
        rec = STORE.state.action(action_id)
        if rec is None:
            raise HTTPException(404, "action not found")
        if claims.get("role") == "doctor":
            mine = claims.get("doctor_id", "")
            touched = {c.get("before", {}).get("doctor_id") for c in rec.changes}
            touched |= {c.get("after", {}).get("doctor_id") for c in rec.changes}
            if mine not in touched:
                raise HTTPException(403, "that change is not on your list")
        r = acts.undo(STORE.state, action_id, clock_now(),
                      by=claims.get("username", ""))
        if r.success:
            await _commit("undo", {"message": r.message})
        return _result(r)


@app.get("/api/doctors/{doctor_id}/day-context")
async def get_day_context(doctor_id: str, date: str = "",
                          claims=Depends(require_role("admin", "nurse", "doctor", "coordinator"))):
    """The doctor's list for a day, each row carrying its own context.

    Reads existing data — chemo history for the cycle, the drug for the
    regimen, investigations for the labs, the reply for the confirmation. It
    writes nothing and adds no clinical record.
    """
    _sync_day()
    if STORE.state.doctor(doctor_id) is None:
        raise HTTPException(404, "doctor not found")
    if claims.get("role") == "doctor" and claims.get("doctor_id") != doctor_id:
        raise HTTPException(403, "that is not your list")
    return {"doctor_id": doctor_id,
            "date": date or STORE.state.day(),
            "rows": ctx.day_context(STORE.state, doctor_id, date or None)}


@app.put("/api/patients/{patient_id}/consent")
async def set_consent(patient_id: str, body: schemas.ConsentIn,
                      claims=Depends(require_role("admin", "nurse"))):
    """Record what the patient agreed to at registration."""
    async with async_mutation():
        p = STORE.state.patient(patient_id)
        if p is None:
            raise HTTPException(404, "patient not found")
        p.consent_sms = body.consent_sms
        p.consent_name_treatment = body.consent_name_treatment
        p.consent_attendant = body.consent_attendant
        STORE.state.add_log("consent_set", "", patient_id,
                            f"sms={int(p.consent_sms)} "
                            f"name_treatment={int(p.consent_name_treatment)} "
                            f"attendant={int(p.consent_attendant)}",
                            f"set by {claims.get('username', '')}", clock_now())
        await _commit("consent", {"patient_id": patient_id})
        return {**_result(EngineResult(True, Action.INFO,
                                       f"consent saved for {p.name}")),
                "consent": priv.describe(p)}


@app.get("/api/doctors/{doctor_id}/week")
async def get_week(doctor_id: str,
                   _=Depends(require_role("admin", "nurse", "doctor", "coordinator"))):
    """A doctor's session template and house rules."""
    if STORE.state.doctor(doctor_id) is None:
        raise HTTPException(404, "doctor not found")
    return sess.week_plan(STORE.state, doctor_id)


@app.get("/api/doctors/{doctor_id}/day-plan")
async def get_day_plan(doctor_id: str, date: str = "",
                       _=Depends(require_role("admin", "nurse", "doctor", "coordinator"))):
    """What a given day looks like structurally: clinic windows and blocks."""
    _sync_day()
    if STORE.state.doctor(doctor_id) is None:
        raise HTTPException(404, "doctor not found")
    return sess.day_plan(STORE.state, doctor_id, date or STORE.state.day())


@app.put("/api/doctors/{doctor_id}/sessions")
async def set_sessions(doctor_id: str, body: schemas.SessionsIn,
                       claims=Depends(require_role("admin", "doctor"))):
    """Replace a doctor's working week. A doctor may only set their own."""
    async with async_mutation():
        doc = STORE.state.doctor(doctor_id)
        if doc is None:
            raise HTTPException(404, "doctor not found")
        if claims.get("role") == "doctor" and claims.get("doctor_id") != doctor_id:
            raise HTTPException(403, "you can only set your own working week")
        for b in body.sessions:
            if to_min(b.end) <= to_min(b.start):
                raise HTTPException(400, f"{b.label or b.kind}: end must be after start")
        doc.sessions = [SessionBlock.from_dict(b.model_dump())
                        for b in body.sessions]
        STORE.state.add_log("sessions_set", "", doctor_id,
                            f"{len(doc.sessions)} block(s)",
                            f"set by {claims.get('username', '')}", clock_now())
        await _commit("sessions", {"doctor_id": doctor_id})
        return {**_result(EngineResult(
            True, Action.INFO,
            f"working week saved — {len(doc.sessions)} block(s)")),
            "week": sess.week_plan(STORE.state, doctor_id)}


@app.put("/api/doctors/{doctor_id}/rules")
async def set_rules(doctor_id: str, body: schemas.RulesIn,
                    claims=Depends(require_role("admin", "doctor"))):
    """Replace a doctor's case-mix rules. A doctor may only set their own."""
    async with async_mutation():
        doc = STORE.state.doctor(doctor_id)
        if doc is None:
            raise HTTPException(404, "doctor not found")
        if claims.get("role") == "doctor" and claims.get("doctor_id") != doctor_id:
            raise HTTPException(403, "you can only set your own rules")
        doc.rules = [CaseMixRule.from_dict(r.model_dump()) for r in body.rules]
        STORE.state.add_log("rules_set", "", doctor_id,
                            f"{len(doc.rules)} rule(s)",
                            f"set by {claims.get('username', '')}", clock_now())
        await _commit("rules", {"doctor_id": doctor_id})
        return {**_result(EngineResult(
            True, Action.INFO, f"rules saved — {len(doc.rules)} active")),
            "week": sess.week_plan(STORE.state, doctor_id)}


@app.get("/api/follow-ups")
async def get_follow_ups(date: str = "",
                         _=Depends(require_role("admin", "nurse", "coordinator"))):
    """Everyone nobody is currently looking after: dropped no-shows, stale
    lab gates, stranded arrivals, forgotten waitlist entries, unconfirmed
    high-risk patients and messages that could not be sent."""
    _sync_day()
    return coord.follow_up_list(STORE.state, clock_now(), date or None)


@app.get("/api/capacity")
async def get_capacity(start: str = "", days: int = 7, doctor_id: str = "",
                       claims=Depends(require_role("admin", "nurse", "doctor",
                                                   "coordinator"))):
    """Committed vs available minutes across the next days, and where the
    pressure is."""
    _sync_day()
    if claims.get("role") == "doctor":
        doctor_id = claims.get("doctor_id", "")
    return cap.horizon(STORE.state, start or None, min(max(days, 1), 31),
                       doctor_id)


# --------------------------------------------------------------------------- #
# Interop: a way in and a way out
# --------------------------------------------------------------------------- #
@app.post("/api/import/patients/preview")
async def preview_import(body: schemas.CsvIn,
                         _=Depends(require_role("admin"))):
    """Say what a patient CSV would do. Writes nothing."""
    return interop.preview(STORE.state, interop.parse_patients(body.csv))


@app.post("/api/import/patients")
async def do_import(body: schemas.CsvIn, _=Depends(require_role("admin"))):
    """Apply a patient CSV. Matches on mr_number first, then on name."""
    async with async_mutation():
        parsed = interop.parse_patients(body.csv)
        if not parsed["rows"]:
            raise HTTPException(400, "; ".join(parsed["errors"])
                                or "nothing importable in that file")
        out_ = interop.import_patients(STORE.state, parsed, clock_now())
        await _commit("patients_imported", {"created": out_["created"],
                                            "updated": out_["updated"]})
        return out_


@app.get("/api/export/patients.csv")
async def export_patients(_=Depends(require_role("admin", "nurse"))):
    return Response(content=interop.patients_csv(STORE.state),
                    media_type="text/csv",
                    headers={"Content-Disposition":
                             "attachment; filename=patients.csv"})


@app.get("/api/export/appointments.csv")
async def export_appointments(_=Depends(require_role("admin", "nurse"))):
    return Response(content=interop.appointments_csv(STORE.state),
                    media_type="text/csv",
                    headers={"Content-Disposition":
                             "attachment; filename=appointments.csv"})


@app.get("/api/export/fhir")
async def export_fhir(date: str = "",
                      _=Depends(require_role("admin", "nurse"))):
    """A FHIR-shaped Bundle. Resource shape, not a certified FHIR server —
    the bundle says so in its own meta tag."""
    return interop.fhir_bundle(STORE.state, date or None)


# --------------------------------------------------------------------------- #
# The patient's own view
# --------------------------------------------------------------------------- #
@app.get("/api/appointments/{appt_id}/patient-link")
async def get_patient_link(appt_id: str,
                           _=Depends(require_role("admin", "nurse",
                                                  "coordinator"))):
    """The link to give this patient. Derived from the signing secret, so it
    is stable and unguessable without being stored."""
    if STORE.state.appointment(appt_id) is None:
        raise HTTPException(404, "appointment not found")
    return {"appointment_id": appt_id, "token": appointment_token(appt_id),
            "path": f"/p/{appointment_token(appt_id)}"}


@app.get("/api/p/{token}")
async def patient_status(token: str):
    """Unauthenticated, by design: the token *is* the credential.

    Shows one visit and nothing about anybody else. Never names the
    diagnosis, the specialty or the room, and names the treatment only where
    the patient consented to that.
    """
    _sync_day()
    if not token or len(token) < 16:
        raise HTTPException(404, "not found")
    aid = appointment_for_token(token, list(STORE.state.appointments.keys()))
    if not aid:
        raise HTTPException(404, "not found")
    appt = STORE.state.appointment(aid)
    if not pview.safe_to_show(STORE.state, appt):
        return {"stage": "cancelled",
                "stage_text": "This appointment has been cancelled",
                "advice": "Please contact the clinic to rebook."}
    return pview.status_for(STORE.state, appt, clock_now())


@app.post("/api/p/{token}/confirm")
async def patient_confirm(token: str, body: schemas.PatientConfirmIn):
    """A patient confirming or declining their own visit."""
    async with async_mutation():
        aid = appointment_for_token(token, list(STORE.state.appointments.keys()))
        if not aid:
            raise HTTPException(404, "not found")
        appt = STORE.state.appointment(aid)
        appt.confirmed = "yes" if body.coming else "no"
        STORE.state.add_log("patient_confirmed", aid, "", appt.confirmed,
                            "from the patient page", clock_now())
        await _commit("patient_confirmed", {"appt_id": aid})
        return {"ok": True, "confirmed": appt.confirmed}


# --------------------------------------------------------------------------- #
# The assistant. It looks, and it proposes; only a person changes anything.
# --------------------------------------------------------------------------- #
def _ask_rows(view: str, claims: dict, patient_id: str = "") -> dict:
    """Fetch one view using the same engine calls the screens use.

    Nothing new is computed here and no new permission is invented: a doctor
    gets their own list because every view that is about "my" day is scoped
    to the doctor_id on their token, exactly as the console scopes it.
    """
    state = STORE.state
    now, day = clock_now(), _sync_day()
    mine = claims.get("doctor_id", "") or ""

    if view == "waiting":
        rows = [r for r in arr.board(state, now, day)
                if r["stage"] in ("ready", "in_labs")]
        rows.sort(key=lambda r: -r["waiting_min"])
        return {"rows": rows[:8], "source": "GET /api/arrivals"}

    if view == "not_called":
        rows = [r for r in arr.board(state, now, day) if r["stage"] == "ready"]
        rows.sort(key=lambda r: -r["waiting_min"])
        return {"rows": rows, "source": "GET /api/arrivals"}

    if view == "held":
        return {"rows": inv.gated_appointments(state, day),
                "source": "GET /api/investigations"}

    if view == "free_rooms":
        busy = {a.room_id for a in state.appointments.values()
                if a.eff_date == day and a.room_id
                and a.status in (AppointmentStatus.ACTIVE,
                                 AppointmentStatus.BOOKED,
                                 AppointmentStatus.RESCHEDULED)}
        rows = [{"room_id": r.id, "room_name": r.name,
                 "type": r.type.value, "status": r.status.value,
                 "idle": r.id not in busy}
                for r in state.rooms.values()]
        rows.sort(key=lambda r: (not r["idle"], r["room_name"]))
        return {"rows": rows, "source": "room status + today's bookings"}

    if view == "running_late":
        rows = arr.running_late(state, now, day)
        if mine:
            rows = [r for r in rows if r.get("doctor_id") == mine]
        return {"rows": rows, "source": "GET /api/arrivals (running_late)"}

    if view == "my_day":
        doctor_id = mine or (state.doctors and
                             sorted(state.doctors)[0] or "")
        rows = [r for r in ctx.day_context(state, doctor_id, day)
                if r["status"] in ("booked", "active", "rescheduled")]
        return {"rows": rows, "scoped_to": doctor_id,
                "source": "GET /api/doctors/{id}/day-context"}

    if view == "follow_ups":
        return {"rows": coord.follow_up_list(state, now, day).get("rows", []),
                "source": "GET /api/follow-ups"}

    if view == "attention":
        rows = [{"severity": i.severity.value, "title": i.title,
                 "detail": i.detail, "action": i.action}
                for i in analyze(state, now)]
        # One row per patient here. The full list keeps a row per reason,
        # because each is a separate job for the coordinator; in a summary
        # the same name twice just reads as a bug.
        folded = coord.by_patient(
            coord.follow_up_list(state, now, day).get("rows", []))
        for r in folded[:3]:
            rows.append({"severity": r["severity"], "title": r["patient_name"],
                         "detail": r["summary"], "action": r.get("action", ""),
                         "reasons": r.get("reasons", 1)})
        return {"rows": rows,
                "source": "GET /api/insights + GET /api/follow-ups"}

    if view == "emergency_queue":
        rows = [{"emergency_id": e.id, "patient_id": e.patient_id,
                 "patient_name": (state.patient(e.patient_id).name
                                  if state.patient(e.patient_id) else e.patient_id),
                 "severity": e.severity.name.lower(),
                 "since": e.created_at}
                for e in build_queue(state, now)]
        return {"rows": rows, "source": "GET /api/queue"}

    if view == "patient":
        row = next((r for r in arr.board(state, now, day)
                    if r["patient_id"] == patient_id), None)
        rows = [row] if row else []
        held = [h for h in inv.gated_appointments(state, day)
                if h["patient_id"] == patient_id]
        return {"rows": rows, "held": held,
                "source": "GET /api/arrivals + investigations"}

    return {"rows": [], "source": ""}


@app.post("/api/ask")
async def ask_the_clinic(body: schemas.AskIn,
                         claims=Depends(require_role("admin", "nurse",
                                                     "doctor", "coordinator"))):
    """Answer with one of the views this app has, or propose one of its actions.

    Read-only by construction: every branch above calls an engine function
    that returns rows, and a proposal is only a card. Confirming it calls the
    ordinary endpoint with its ordinary role check and undo.

    A clinical question is refused before anything else is considered, and
    before the sentence can leave the building. "How do I…" stays local too:
    help is about this interface, which the model knows nothing about.
    """
    day = _sync_day()
    state = STORE.state
    names = {p.id: p.name for p in state.patients.values()}
    question = body.question

    a = None
    if (sarvam.enabled() and question.strip()
            and not askq.clinical_reason(question)
            and not (gde.looks_like_help(question)
                     and gde.match_topic(question))):
        masked, mask = prop.mask_names(question, names)
        doctors = [{"id": d.id, "name": d.name} for d in state.doctors.values()]
        try:
            choice = await asyncio.to_thread(
                sarvam.choose, masked, doctors, prop.catalogue(), prop.choices())
            a = prop.read_choice(choice, state, clock_now(), day, mask, names,
                                 claims.get("doctor_id", "") or "", question)
        except sarvam.SarvamError:
            a = None
    if a is None:
        a = askq.resolve(question, names)
    out_ = a.to_dict()

    # Stuck in the interface. The answer depends on who is asking: the steps
    # if their role has it, who to ask and why if it does not.
    if a.topic:
        topic = gde.TOPIC_BY_ID.get(a.topic)
        if topic is not None:
            out_["help"] = gde.answer(topic, claims.get("role", ""))

    if a.kind != "view":
        return out_
    data = _ask_rows(a.view, claims, a.patient_query)
    if a.view == "patient" and a.patient_query:
        out_["patient_name"] = names.get(a.patient_query, "")
    return {**out_, **data}


@app.get("/api/ask/capabilities")
async def ask_capabilities(_=Depends(require_role("admin", "nurse", "doctor",
                                                  "coordinator"))):
    """Whether a model is configured, so the UI only offers what will work."""
    return {"model": sarvam.enabled()}


#: A 25-second 16 kHz mono WAV is under 1 MB.
MAX_CLIP_BYTES = 2 * 1024 * 1024


@app.post("/api/ask/voice")
async def ask_voice(file: UploadFile = File(...),
                    _=Depends(require_role("admin", "nurse", "doctor",
                                           "coordinator"))):
    """Turn a short clip into text. The text then goes through /api/ask like
    anything typed, so voice can do nothing that typing cannot."""
    if not sarvam.enabled():
        raise HTTPException(503, "voice is not switched on")
    audio = await file.read()
    if len(audio) > MAX_CLIP_BYTES:
        raise HTTPException(413, "that clip is too long")
    try:
        text = await asyncio.to_thread(sarvam.transcribe, audio)
    except sarvam.SarvamError:
        raise HTTPException(502, "I could not hear that. Please type it.")
    return {"transcript": text[:300]}


@app.get("/api/outcomes")
async def get_outcomes(date: str = "", against: str = "", doctor_id: str = "",
                       claims=Depends(require_role("admin", "nurse", "doctor", "coordinator"))):
    """Did any of it help? A day's waiting times, punctuality, utilisation,
    recovered time and losses, set against the clinic's own previous day.

    Blocks computed from too few timed visits report that instead of printing
    a figure — a median drawn from two visits is a number that lies.
    """
    _sync_day()
    if claims.get("role") == "doctor":
        # a doctor sees their own day; nobody else's
        doctor_id = claims.get("doctor_id", "")
    if doctor_id and STORE.state.doctor(doctor_id) is None:
        raise HTTPException(404, "doctor not found")
    return out.compare(STORE.state, date or None, against or None, doctor_id)


@app.get("/api/arrivals")
async def get_arrivals(_=Depends(require_role("admin", "nurse", "doctor", "coordinator"))):
    """The waiting-room board: who is here, for how long, and what next."""
    _sync_day()
    now = clock_now()
    return {"now": now,
            "board": arr.board(STORE.state, now),
            "next_up": arr.next_up(STORE.state, now),
            "running_late": arr.running_late(STORE.state, now)}


@app.post("/api/appointments/{appt_id}/call")
async def call_patient(appt_id: str,
                       _=Depends(require_role("admin", "nurse", "doctor", "coordinator"))):
    """Call a waiting patient in. This is what ends their wait and starts
    the visit — the two timestamps the clinic is actually measured on."""
    async with async_mutation():
        a = STORE.state.appointment(appt_id)
        if not a:
            raise HTTPException(404, "appointment not found")
        if not a.checked_in:
            return _result(EngineResult(False, Action.INFO,
                                        "patient has not arrived yet",
                                        SeverityCode.WARNING))
        now = clock_now()
        if not a.started_at:
            a.started_at = now
        if a.status in (AppointmentStatus.BOOKED,
                        AppointmentStatus.RESCHEDULED):
            a.status = AppointmentStatus.ACTIVE
        waited = (to_min(now) - to_min(a.checked_in_at)) if a.checked_in_at else 0
        STORE.state.add_log("called_in", appt_id, a.checked_in_at or "",
                            now, f"waited {waited} min", now)
        await _commit("called", {"appt_id": appt_id})
        return _result(EngineResult(True, Action.INFO,
                                    f"called in after {waited} min waiting",
                                    data={"waited_min": waited}))


@app.get("/api/risk")
async def get_risk(date: str = "", doctor_id: str = "",
                   _=Depends(require_role("admin", "nurse", "doctor", "coordinator"))):
    """No-show risk for a day, with what can be done about it.

    Safety bookings only appear for doctors who switched them on; for
    everyone else the suggestion is to ask the patient earlier.
    """
    _sync_day()
    return rk.suggestions(STORE.state, date or None, doctor_id)


@app.put("/api/doctors/{doctor_id}/safety-booking")
async def set_safety_booking(doctor_id: str, body: schemas.SafetyBookingIn,
                             claims=Depends(require_role("admin", "doctor"))):
    """A doctor decides whether their own clinic may be overbooked."""
    async with async_mutation():
        doc = STORE.state.doctor(doctor_id)
        if doc is None:
            raise HTTPException(404, "doctor not found")
        # a doctor may only set this for themselves
        if claims.get("role") == "doctor" and claims.get("doctor_id") != doctor_id:
            raise HTTPException(403, "you can only set this for yourself")
        doc.allow_safety_booking = body.enabled
        STORE.state.add_log("safety_booking", "", doctor_id,
                            "on" if body.enabled else "off",
                            f"set by {claims.get('username', '')}", clock_now())
        await _commit("safety_booking", {"doctor_id": doctor_id,
                                         "enabled": body.enabled})
        return _result(EngineResult(
            True, Action.INFO,
            f"safety bookings {'enabled' if body.enabled else 'disabled'} "
            f"for {doc.name}"))


@app.post("/api/notifications/{notification_id}/reply")
async def reply_notification(notification_id: str, body: schemas.MessageReplyIn,
                             _=Depends(require_role("admin", "nurse", "coordinator"))):
    """Record what a patient answered, and act on it where it is unambiguous.

    A YES to a waitlist offer books the slot (first reply wins). A reply about
    an appointment records whether they are coming — that is what lets the
    clinic know the list is real before anyone is due.
    """
    async with async_mutation():
        _sync_day()
        now = clock_now()
        out = record_reply(STORE.state, notification_id, body.text, now)
        if not out["ok"]:
            raise HTTPException(404, out["error"])
        n = STORE.state.notification(notification_id)
        acted = None

        if n.kind == "waitlist_offer" and out["intent"] == "yes":
            r = wl.accept(STORE.state, n.ref, _alloc(), now)
            acted = _result(r)
        elif n.kind == "waitlist_offer" and out["intent"] == "no":
            entry = STORE.state.waitlist_entry(n.ref)
            if entry and entry.status == "offered":
                entry.status = "waiting"
                entry.offered_slot = ""
            acted = {"success": True, "message": "declined; still on the list"}
        elif n.kind == "appointment" and out["intent"] in ("yes", "no"):
            appt = STORE.state.appointment(n.ref)
            if appt:
                appt.confirmed = out["intent"]
                acted = {"success": True,
                         "message": f"appointment marked {out['intent']}"}

        await _commit("message_reply", {"intent": out["intent"]})
        return {**out, "acted": acted}


@app.post("/api/notifications/flush")
async def flush_notifications(_=Depends(require_role("admin"))):
    """Force a send of anything still queued (useful after a driver outage)."""
    async with async_mutation():
        out = DISPATCHER.flush(STORE.state, clock_now())
        await _commit("messages_flushed", out)
        return out


@app.get("/api/investigations")
async def get_investigations(_=Depends(require_role("admin", "nurse", "doctor", "coordinator"))):
    return [i.to_dict() for i in STORE.state.investigations.values()]


@app.post("/api/investigations")
async def order_investigation(body: schemas.InvestigationIn,
                              _=Depends(require_role("admin", "nurse", "doctor", "coordinator"))):
    async with async_mutation():
        _sync_day()
        r = inv.order(STORE.state, body.patient_id, body.kind, clock_now(),
                      STORE.state.day(), appointment_id=body.appointment_id,
                      eta=body.eta or "", blocking=body.blocking,
                      note=body.note)
        if r.success:
            await _commit("investigation", {"message": r.message})
        return _result(r)


@app.post("/api/investigations/{inv_id}/result")
async def result_investigation(inv_id: str, body: schemas.InvestigationResultIn,
                               _=Depends(require_role("admin", "nurse", "doctor", "coordinator"))):
    """File a result. A flagged value keeps the treatment blocked — the
    system never decides to proceed, reduce or defer on its own."""
    async with async_mutation():
        r = inv.result(STORE.state, inv_id, body.value, clock_now(),
                       flagged=body.flagged, note=body.note)
        if r.success:
            await _commit("investigation_result", {"message": r.message})
        return _result(r)


@app.post("/api/investigations/{inv_id}/clear")
async def clear_investigation_flag(inv_id: str,
                                   claims=Depends(require_role("admin", "doctor"))):
    """A doctor accepts an out-of-protocol result so treatment can proceed.
    Only a doctor or admin can do this, and it is written to the audit log."""
    async with async_mutation():
        who = claims.get("username", "") if isinstance(claims, dict) else ""
        r = inv.clear_flag(STORE.state, inv_id, clock_now(), by=who)
        if r.success:
            await _commit("investigation_cleared", {"message": r.message})
        return _result(r)


@app.get("/api/appointments/{appt_id}/readiness")
async def get_readiness(appt_id: str,
                        _=Depends(require_role("admin", "nurse", "doctor", "coordinator"))):
    if STORE.state.appointment(appt_id) is None:
        raise HTTPException(404, "appointment not found")
    return inv.readiness(STORE.state, appt_id)


@app.post("/api/appointments/{appt_id}/gate")
async def gate_appointment(appt_id: str,
                           _=Depends(require_role("admin", "nurse", "doctor", "coordinator"))):
    """Hold a treatment for results: the patient keeps their place and is
    never no-showed, while the chair goes back to the pool."""
    async with async_mutation():
        _sync_day()
        r = inv.gate(STORE.state, appt_id, clock_now())
        if not r.success:
            return _result(r)
        await _commit("gated", {"message": r.message})
        # the chair is free now — who on the waitlist could use it?
        matches = []
        data = r.data if isinstance(r.data, dict) else {}
        appt = STORE.state.appointment(appt_id)
        if appt:
            matches = wl.candidates(STORE.state, appt.doctor_id,
                                    data.get("slot_start", appt.slot_start),
                                    data.get("slot_end", appt.slot_end),
                                    clock_now())
        return {**_result(r), "waitlist_matches": matches}


@app.post("/api/appointments/{appt_id}/repencil")
async def repencil_appointment(appt_id: str,
                               _=Depends(require_role("admin", "nurse"))):
    """Results are in — put the treatment back on the board."""
    async with async_mutation():
        _sync_day()
        r = inv.repencil(STORE.state, appt_id, _alloc(), clock_now())
        if r.success:
            await _commit("repencilled", {"message": r.message})
        return _result(r)


@app.get("/api/waitlist")
async def get_waitlist(_=Depends(require_role("admin", "nurse", "doctor", "coordinator"))):
    return [_waitlist_row(w) for w in STORE.state.waitlist.values() if w.active]


@app.post("/api/waitlist")
async def add_waitlist(body: schemas.WaitlistAddIn,
                       _=Depends(require_role("admin", "nurse", "coordinator"))):
    async with async_mutation():
        _sync_day()
        r = wl.add(STORE.state, body.patient_id, clock_now(), STORE.state.day(),
                   doctor_id=body.doctor_id, visit_type=body.visit_type or "",
                   reason=body.reason, earliest=body.earliest,
                   latest=body.latest, travel_min=body.travel_min,
                   in_building=body.in_building, note=body.note)
        if r.success:
            await _commit("waitlist", {"message": r.message})
        return _result(r)


@app.delete("/api/waitlist/{entry_id}")
async def remove_waitlist(entry_id: str,
                          _=Depends(require_role("admin", "nurse", "coordinator"))):
    async with async_mutation():
        r = wl.remove(STORE.state, entry_id, clock_now())
        if r.success:
            await _commit("waitlist", {"message": r.message})
        return _result(r)


@app.post("/api/waitlist/match")
async def match_waitlist(body: schemas.WaitlistMatchIn,
                         _=Depends(require_role("admin", "nurse", "doctor", "coordinator"))):
    """Who could take a given free slot. Read-only."""
    _sync_day()
    return {"matches": wl.candidates(STORE.state, body.doctor_id,
                                     body.slot_start, body.slot_end,
                                     clock_now(), limit=body.limit)}


@app.post("/api/waitlist/offer")
async def offer_waitlist(body: schemas.WaitlistOfferIn,
                         _=Depends(require_role("admin", "nurse", "coordinator"))):
    """Offer one freed slot to several patients; the first accept wins."""
    async with async_mutation():
        _sync_day()
        r = wl.offer(STORE.state, body.entry_ids, body.doctor_id,
                     body.slot_start, body.slot_end, clock_now())
        if r.success:
            await _commit("waitlist_offer", {"message": r.message})
        return _result(r)


@app.post("/api/waitlist/{entry_id}/accept")
async def accept_waitlist(entry_id: str, body: schemas.WaitlistAcceptIn,
                          _=Depends(require_role("admin", "nurse", "coordinator"))):
    async with async_mutation():
        _sync_day()
        r = wl.accept(STORE.state, entry_id, _alloc(), clock_now(),
                      doctor_id=body.doctor_id,
                      slot_start=body.slot_start or "",
                      slot_end=body.slot_end or "")
        if r.success:
            await _commit("waitlist_accept", {"message": r.message})
        return _result(r)


@app.post("/api/walk-ins/options")
async def walk_in_options(body: schemas.WalkInOptionsIn,
                          _=Depends(require_role("admin", "nurse", "doctor", "coordinator"))):
    """Where a patient standing at the desk could be seen today.

    Read-only: it searches the gaps that already exist and never moves a
    booked patient. A doctor at their daily cap is reported, not squeezed.
    """
    _sync_day()
    mins = (visits.clamp_duration(body.duration_min)
            if body.duration_min
            else visits.default_duration(body.visit_type or visits.DEFAULT_VISIT_TYPE))
    out = _alloc().walk_in_options(
        duration=mins, now=clock_now(), doctor_id=body.doctor_id or None,
        urgency=body.urgency, specialty=body.specialty or None,
        limit=body.limit)
    out["duration_min"] = mins
    out["now"] = clock_now()
    return out


@app.post("/api/walk-ins")
async def book_walk_in(body: schemas.WalkInBookIn,
                       _=Depends(require_role("admin", "nurse", "coordinator"))):
    """Place the walk-in in one of the gaps that was offered."""
    async with async_mutation():
        _sync_day()
        now = clock_now()
        start, end, vtype = _consult_window(
            body.slot_start, body.slot_end, body.visit_type, body.duration_min)
        r = _alloc().book_walk_in(body.patient_id, body.doctor_id, start, end,
                                  at=now, reason=body.reason,
                                  visit_type=vtype)
        if r.success:
            await _commit("walk_in", {"message": r.message})
        return _result(r)


@app.post("/api/appointments/{appt_id}/complete-visit")
async def complete_visit(appt_id: str,
                         _=Depends(require_role("admin", "nurse", "doctor", "coordinator"))):
    """Mark a visit as done. Increments the patient's visit count so the next
    booking is recognised as a revisit."""
    async with async_mutation():
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
        a.completed_at = clock_now()
        if not a.started_at:
            # completed without being called in: fall back to arrival, then
            # to the booked slot, so a learned duration is never invented
            a.started_at = a.checked_in_at or a.slot_start
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
    async with async_mutation():
        _sync_day()
        now = clock_now()
        r = _alloc().reschedule(appt_id, body.new_doctor_id, body.new_room_id,
                                body.slot_start, body.slot_end, at=now,
                                reason=body.reason, date=body.date or None)
        if r.success:
            await _commit("rescheduled", {"message": r.message})
        return _result(r)


@app.post("/api/appointments/{appt_id}/reschedule-auto")
async def reschedule_auto(appt_id: str, body: schemas.RescheduleAutoIn,
                          _=Depends(require_role("admin", "nurse", "coordinator"))):
    async with async_mutation():
        _sync_day()
        now = clock_now()
        # operate on the appointment's own day so auto-reschedule never jumps days
        _appt = STORE.state.appointment(appt_id)
        r = _alloc().reschedule_auto(appt_id, at=now, reason=body.reason,
                                     only_doctor=not body.allow_backup_doctor,
                                     date=_appt.eff_date if _appt else None)
        if r.success:
            await _commit("rescheduled", {"message": r.message})
        return _result(r)


@app.post("/api/appointments/{appt_id}/checkin")
async def checkin(appt_id: str, body: schemas.MarkCheckedInIn,
                  _=Depends(require_role("admin", "nurse", "doctor", "coordinator"))):
    async with async_mutation():
        a = STORE.state.appointment(appt_id)
        if not a:
            raise HTTPException(404, "appointment not found")
        a.checked_in = body.checked_in
        if body.checked_in:
            # Arrival only. The visit starts when the patient is called in,
            # which is a separate event — that gap is the waiting time.
            if not a.checked_in_at:
                a.checked_in_at = clock_now()
            if a.status in (AppointmentStatus.BOOKED,
                            AppointmentStatus.RESCHEDULED):
                a.status = AppointmentStatus.ACTIVE
        await _commit("checkin", {"appt_id": appt_id})
        return _result(EngineResult(True, Action.INFO, "checked in",
                                    SeverityCode.INFO))


@app.post("/api/appointments/{appt_id}/cancel")
async def cancel_appt(appt_id: str, body: schemas.CancelIn,
                      _=Depends(require_role("admin", "nurse", "coordinator"))):
    """Manually cancel a booked appointment, releasing the slot and notifying
    the next patient in the queue."""
    async with async_mutation():
        appt = STORE.state.appointment(appt_id)
        freed = ({"doctor_id": appt.doctor_id, "slot_start": appt.slot_start,
                  "slot_end": appt.slot_end, "date": appt.eff_date}
                 if appt else None)
        r = handle_cancel_appointment(STORE.state, appt_id, clock_now(), body.reason)
        if not r.success:
            return _result(r)
        await _commit("cancel", _result(r))
        # the slot is free now — say who could actually take it, and let a
        # human decide. Nothing is offered or booked automatically.
        matches = []
        if freed:
            matches = wl.candidates(STORE.state, freed["doctor_id"],
                                    freed["slot_start"], freed["slot_end"],
                                    clock_now())
        return {**_result(r), "freed_slot": freed, "waitlist_matches": matches}


# --------------------------------------------------------------------------- #
# Edge cases
# --------------------------------------------------------------------------- #
@app.post("/api/doctors/{doctor_id}/sick-leave")
async def sick_leave(doctor_id: str, body: schemas.SickLeaveIn,
                     _=Depends(require_role("admin", "nurse"))):
    async with async_mutation():
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
    async with async_mutation():
        r = handle_doctor_take_leave(STORE.state, doctor_id, clock_now(),
                                      body.start, body.end, body.reason, body.full_day,
                                      date=body.date)
        await _commit("leave", _result(r))
        return _result(r)


@app.post("/api/doctors/{doctor_id}/leave/cancel")
async def cancel_leave(doctor_id: str, body: schemas.LeaveCancelIn,
                        _=Depends(_self_or_staff())):
    async with async_mutation():
        r = handle_doctor_cancel_leave(STORE.state, doctor_id, clock_now(),
                                        body.leave_id)
        await _commit("leave", _result(r))
        return _result(r)


@app.post("/api/doctors/{doctor_id}/available")
async def mark_available(doctor_id: str,
                          _=Depends(_self_or_staff())):
    async with async_mutation():
        r = handle_doctor_mark_available(STORE.state, doctor_id, clock_now())
        await _commit("leave", _result(r))
        return _result(r)


@app.post("/api/doctors/expire-leaves")
async def expire_leaves_endpoint(_=Depends(require_role("admin", "nurse"))):
    async with async_mutation():
        changed = expire_leaves(STORE.state, clock_now())
        await _commit("leave", {"changed": changed})
        return _result(EngineResult(
            True, Action.INFO,
            f"expired leaves; {len(changed)} doctor(s) became available" if changed
            else "no leaves to expire", SeverityCode.INFO, data={"changed": changed}))


@app.post("/api/appointments/{appt_id}/overrun")
async def overrun(appt_id: str, body: schemas.OverrunIn,
                  _=Depends(require_role("admin", "nurse"))):
    async with async_mutation():
        r = handle_chemo_overrun(STORE.state, appt_id, clock_now())
        await _commit("overrun", _result(r))
        return _result(r)


@app.post("/api/rooms/{room_id}/breakdown")
async def breakdown(room_id: str, body: schemas.RoomBreakdownIn,
                    _=Depends(require_role("admin", "nurse"))):
    async with async_mutation():
        r = handle_room_breakdown(STORE.state, room_id, clock_now(),
                                   body.available_until, body.reason)
        await _commit("breakdown", _result(r))
        return _result(r)


@app.post("/api/rooms/{room_id}/restore")
async def restore_room(room_id: str, body: schemas.RoomRestoreIn,
                       _=Depends(require_role("admin", "nurse"))):
    """Return a broken-down room to available (inverse of breakdown)."""
    async with async_mutation():
        r = handle_room_restore(STORE.state, room_id, clock_now(), body.reason)
        await _commit("room_restore", _result(r))
        return _result(r)


@app.post("/api/appointments/{appt_id}/no-show")
async def no_show(appt_id: str, body: schemas.NoShowIn,
                  _=Depends(require_role("admin", "nurse"))):
    async with async_mutation():
        r = handle_no_show(STORE.state, appt_id, clock_now(), body.no_show_min)
        await _commit("no_show", _result(r))
        return _result(r)


@app.post("/api/clock/advance")
async def clock(body: schemas.ClockAdvanceIn,
                _=Depends(require_role("admin", "nurse"))):
    async with async_mutation():
        out = advance_clock(STORE.state, clock_now(), body.no_show_min)
        if out["no_shows"] or out["overruns"]:
            await _commit("clock", out)
        else:
            STORE._persist()
            await manager.broadcast({"type": "state_refresh"})
        return _result(EngineResult(
            True, Action.INFO, f"clock advanced to {out['now']}", SeverityCode.INFO,
            actions=out["no_shows"] + out["overruns"], data=out))


# --------------------------------------------------------------------------- #
# Emergencies
# --------------------------------------------------------------------------- #
@app.post("/api/emergencies")
async def add_emergency(body: schemas.EmergencyIn,
                        _=Depends(require_role("admin", "nurse", "doctor", "coordinator"))):
    async with async_mutation():
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
    async with async_mutation():
        r = handle_emergency_pair(STORE.state, body.e1_id, body.e2_id, clock_now())
        await _commit("emergency", _result(r))
        return _result(r)


@app.post("/api/emergencies/resolve")
async def resolve_emer(_=Depends(require_role("admin", "nurse"))):
    async with async_mutation():
        r = resolve_emergencies(STORE.state, clock_now())
        await _commit("emergency", _result(r))
        return _result(r)


@app.post("/api/emergencies/{emergency_id}/assign")
async def assign_emergency(emergency_id: str, body: schemas.EmergencyAssignIn,
                           _=Depends(require_role("admin", "nurse"))):
    """Manually assign an emergency to a specific doctor (overrides auto-assign)."""
    async with async_mutation():
        r = handle_emergency_assign(STORE.state, emergency_id, body.doctor_id,
                                    clock_now())
        if r.success:
            await _commit("emergency", _result(r))
        return _result(r)


@app.post("/api/emergencies/{emergency_id}/complete")
async def complete_emergency(emergency_id: str,
                             _=Depends(require_role("admin", "nurse"))):
    """Mark an emergency as finished / cleared from the live queue."""
    async with async_mutation():
        r = handle_emergency_complete(STORE.state, emergency_id, clock_now())
        if r.success:
            await _commit("emergency", _result(r))
        return _result(r)


# --------------------------------------------------------------------------- #
# WebSocket (real-time)
# --------------------------------------------------------------------------- #
@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket,
                      token: str | None = Query(default=None)):
    import json as _json
    await ws.accept()
    # Authenticate: the token may arrive as a query param or as the first
    # text message (clients that can't set query strings).
    if not token:
        try:
            first = await ws.receive_text()
        except WebSocketDisconnect:
            return
        token = first.strip() if first else None
    try:
        user = _ws_auth(token)
    except HTTPException:
        await ws.close(code=1008, reason="unauthorized")
        return
    manager.connect(ws)
    try:
        # send the current snapshot on connect
        await ws.send_text(_json.dumps(
            {"type": "snapshot", "state": _state_payload()}))
        while True:
            # we only push; ignore inbound pings/echo
            msg = await ws.receive_text()
            if msg == "ping":
                await ws.send_text(_json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        manager.disconnect(ws)
    except Exception:  # noqa: BLE001
        manager.disconnect(ws)


# --------------------------------------------------------------------------- #
# Static frontend (mounted last so /api/* and /ws always win)
# --------------------------------------------------------------------------- #
_FRONTEND_DIST = os.path.normpath(os.path.join(
    os.path.dirname(__file__), "..", "..", "frontend", "dist"))
if os.path.isdir(_FRONTEND_DIST):
    from fastapi.staticfiles import StaticFiles
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import FileResponse
    from starlette.routing import Mount

    class _SpaFallback(BaseHTTPMiddleware):
        """Serve the built SPA. Existing files (JS/CSS/index.html) are served
        directly; any other non-API, non-WS GET (e.g. /login, /schedule) returns
        index.html so the client-side router can take over."""
        async def dispatch(self, request, call_next):
            path = request.url.path
            if path.startswith(("/api/", "/ws", "/metrics", "/health", "/docs", "/openapi.json", "/redoc")):
                return await call_next(request)
            if request.method != "GET" and request.method != "HEAD":
                return await call_next(request)
            candidate = os.path.join(_FRONTEND_DIST, path.lstrip("/"))
            if path != "/" and os.path.isfile(candidate):
                return FileResponse(candidate)
            return FileResponse(os.path.join(_FRONTEND_DIST, "index.html"))

    app.add_middleware(_SpaFallback)
    app.router.routes.append(
        Mount("/", StaticFiles(directory=_FRONTEND_DIST, html=True),
              name="frontend"))
