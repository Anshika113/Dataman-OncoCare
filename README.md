# Dataman OncoCare — Patient Scheduling & Operations System

A full-stack system for a cancer/oncology department that schedules doctors and
chemo rooms, manages a live patient queue, handles emergencies by priority, and
automatically recovers from real-world disruptions (sick leave, overruns,
equipment breakdown, no-shows).

**Stack:** React + TypeScript + Tailwind (frontend) · FastAPI (backend) · **Excel as the datastore** (no database) · WebSocket for real-time.

---

## Why Excel as the datastore

Per the project requirement, all data lives in a single Excel workbook
(`backend/data/care.xlsx`). The backend:

- **loads** the whole workbook into memory on startup,
- runs the **pure scheduling engine** against that in-memory state,
- **saves** atomically (temp-file + rename) after each mutation, serialised by a
  lock so concurrent requests never corrupt the file.

This keeps the engine 100% pure and unit-testable while giving you a
human-readable, portable datastore you can open in Excel/LibreOffice.

> ⚠️ Excel is not a concurrent-transactional database. For a real multi-user
> production deployment you would swap `storage/excel_store.py` for a proper
> DB without touching the engine or API (they depend only on the `Store`
> interface). The whole reason the engine is isolated is that this swap is
> trivial.

---

## Architecture

```
frontend (React)                     backend (FastAPI)
┌──────────────────────┐   REST/WS  ┌───────────────────────────────┐
│ Login                │ ─────────► │ api/main.py (routes + auth)    │
│ Dashboard            │            │  ├─ services/security.py (JWT) │
│  ├ Schedule (Gantt)  │            │  ├─ services/ws.py (broadcast) │
│  ├ Live Queue        │ ◄───────── │  ├─ services/watchdog.py (clock)│
│  ├ Ops Console       │  WS push   │  └─ storage/excel_store.py     │
│  └ Activity / Audit  │            │        └─ engine/  (PURE)       │
└──────────────────────┘            │             ├─ state.py         │
                                     │             ├─ slots.py         │
                                     │             ├─ conflict.py      │
                                     │             ├─ allocator.py     │
                                     │             ├─ emergency.py     │
                                     │             └─ handlers.py      │
                                     └───────────────────────────────┘
                                                        │
                                                        ▼
                                              data/care.xlsx
```

The **engine is pure** — no I/O, no clock, no DB. It takes a `SystemState` + a
request, mutates it, and returns an `EngineResult`. This is what makes every
edge case unit-testable and the datastore swappable.

---

## The 6 edge cases — how they're handled

| # | Scenario | Engine handler | Behaviour |
|---|----------|----------------|-----------|
| A | **Doctor sick leave mid-day** | `handle_doctor_sick_leave` | Marks doctor `on_leave`, finds future appointments, auto-reschedules each to a **backup doctor** (same/compatible specialty, free slot, under daily cap). If no perfect slot → offers choices. **Notifies every affected patient.** |
| B | **Chemo session overrun** | `handle_chemo_overrun` | Compares `now` vs planned end + per-drug **grace period**. Once exceeded: flags `OVERRUN`, **logs the overrun**, and **auto-pushes the next patient** in the room later (cascade). |
| C | **Two emergencies at once** | `handle_emergency_pair` | Tries to assign to **different doctors** (parallel). If only one is free, breaks the tie by **priority sub-score** (severity, wait time, patient tier) and queues the other; re-evaluated as resources free. |
| D | **Room equipment breakdown** | `handle_room_breakdown` | Flags room `unavailable` until a time, then **reassigns affected sessions** to a compatible room (respecting equipment + drug time-window). Notifies patients. |
| E | **Patient no-show** | `handle_no_show` | After X minutes without check-in: records `NO_SHOW`, **releases the slot**, and **notifies the next patient in queue** ("you're up"). |
| F | **Drug time-of-day window** | conflict detector + allocator | Each drug carries a hard `time_window`; the room/slot search **filters out** any slot outside it before scoring. |

Two primitives back everything: `reschedule_affected` (a constraint changed) and
`advance_clock` (time advanced). The watchdog calls `advance_clock` every 5 s to
auto-fire no-show and overrun triggers, then pushes the result over WebSocket.

---

## Getting started

### 1. Backend

```bash
cd backend
pip install -r requirements.txt
python -m storage.seed          # (re)create data/care.xlsx with sample data
uvicorn api.main:app --reload --port 8000
```

### 2. Frontend

```bash
cd frontend
npm install
npm run dev                     # http://localhost:5173
```

The Vite dev server proxies `/api` and `/ws` to the backend on port 8000.

### 3. Log in

| Role   | Username | Password   |
|--------|----------|------------|
| admin  | `admin`  | `admin123` |
| nurse  | `nurse`  | `nurse123` |
| doctor | `doctor` | `doctor123`|

**Role permissions** (enforced on the backend via `require_role`, mirrored in the UI):

| Capability | admin | nurse | doctor |
|------------|:-----:|:-----:|:------:|
| View dashboard, schedule, live queue | ✅ | ✅ | ✅ |
| Book / reschedule appointments | ✅ | ✅ | ❌ |
| Check patients in | ✅ | ✅ | ✅ |
| Register & resolve emergencies | ✅ | ✅ | ✅ |
| Trigger edge cases (sick leave, overrun, breakdown, no-show, clock) | ✅ | ✅ | ❌ |
| View Ops Console tab | ✅ | ✅ | ❌ |
| View audit log + notifications (Activity tab) | ✅ | ✅ | ❌ |

Doctors get a focused, mostly read-only console (they can still check patients in
and raise emergencies), which matches a real clinical workflow.

---

## Dashboard

- **Schedule** — doctor/room Gantt timeline, live summary stats, and a booking
  form (consult or chemo; chemo auto-picks the best compatible room respecting
  equipment + drug time-window).
- **Live Queue** — real-time emergency priority queue (severity + sub-score),
  assigned emergencies, next-in-line, and one-click emergency registration.
- **Ops Console** — one-click buttons for each edge case (sick leave, overrun,
  breakdown, no-show, clock tick) plus live doctor/room status.
- **Activity** — live event stream, the full **audit log**, and the
  **notification log** (every patient message sent).

Everything updates **live** over WebSocket — no refresh needed.

---

## Project layout

```
cancer_help/
├── backend/
│   ├── engine/            # PURE scheduling engine (no I/O)
│   │   ├── state.py       #   data model + SystemState
│   │   ├── slots.py       #   interval slot model + buffer rules
│   │   ├── conflict.py    #   hard-constraint validation
│   │   ├── allocator.py   #   score-based chemo room/slot + booking/reschedule
│   │   ├── emergency.py   #   priority queue + sub-score + resolution
│   │   ├── handlers.py    #   the 6 edge-case handlers + advance_clock
│   │   └── result.py      #   EngineResult / Action / Severity
│   ├── api/               # FastAPI app, schemas
│   ├── services/          # security (JWT), ws (broadcast), watchdog
│   ├── storage/           # Excel load/save + seed generator
│   └── data/care.xlsx     # the datastore
└── frontend/              # React + TS + Tailwind (Vite)
```

## Deployment

### Frontend — Cloudflare Pages

1. Push this repo to GitHub.
2. Go to [Cloudflare Pages](https://dash.cloudflare.com/) → **Create a project** → **Connect to Git**.
3. Select your repo and configure:
   - **Framework preset:** None
   - **Build command:** `cd frontend && npm install && npm run build`
   - **Build output directory:** `frontend/dist`
4. Add environment variable: `VITE_API_URL` = your backend URL (e.g. `https://your-backend.onrender.com`).
5. Deploy.

### Backend — Render / Railway / Any Python Host

1. Create a new **Web Service** on [Render](https://render.com) (or similar).
2. Set:
   - **Root directory:** `backend`
   - **Build command:** `pip install -r requirements.txt && python -m storage.seed`
   - **Start command:** `uvicorn api.main:app --host 0.0.0.0 --port $PORT`
3. Set environment variable `CORS_ORIGIN` to your Cloudflare Pages URL.

> The frontend Vite proxy (`/api → localhost:8000`) works only in dev mode. For production, the frontend reads `VITE_API_URL` to call the backend directly.

---

## Notes & production caveats

- **PHI / security:** demo auth uses the Excel `users` sheet with plain (or
  `sha256:`-prefixed) passwords. For production use real password hashing +
  an IdP, encryption at rest, and keep PHI out of logs. The audit log and
  RBAC (admin > nurse > doctor) are already in place.
- **Clock:** the "wall clock" is the server's current time. For deterministic
  testing/demo you can override it via the `CARE_*` env vars or the
  `clock/advance` endpoint.
- **Scale:** single-process by design (Excel store). Horizontal scaling needs
  the datastore swap described above.
