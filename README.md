# DataMan OncoCare — Patient Scheduling & Operations System

A full-stack system for a cancer/oncology department that schedules doctors and
chemo rooms, manages a live patient queue, handles emergencies by priority, and
automatically recovers from real-world disruptions (sick leave, overruns,
equipment breakdown, no-shows).

It also covers the parts of a real OPD day that sit *before* a disruption:
walk-ins, lab results that treatment waits on, filling slots a cancellation
freed, messages patients can actually reply to, an arrivals board for the front
desk, visit-length that reflects how long visits really take, and a no-show
risk score. Those are described under
[Clinic flow](#clinic-flow--beyond-the-edge-cases).

And it gives the **doctor** the controls they already use verbally — more time
with this patient, send the next one in, swap two, hand one to a colleague,
close my list at one — each recorded with its reason and reversible, inside a
working week the scheduler is finally aware of. See
[The doctor's own controls](#the-doctors-own-controls).

Two further pieces sit deliberately outside the brief — consent on outgoing
messages, and clinical context on the doctor's day list. See
[Beyond the brief](#beyond-the-brief).

The last four pieces close the remaining phrases in the brief — the care
coordinator role, a way data gets in and out, capacity across days — plus a
patient-facing view. See [The last four gaps](#the-last-four-gaps).

A doctor or nurse can also say or type those controls. The assistant understands
English, Hindi, Marathi and a mix of them through Sarvam AI, and shows a card for
staff to confirm before anything changes. See [Ask the clinic](#ask-the-clinic).

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

Sheets: `users`, `doctors`, `rooms`, `drugs`, `patients`, `appointments`,
`emergencies`, `waitlist`, `investigations`, `actions`, `logs`,
`notifications`. `patients` carries the three consent columns, and `doctors`
the working week and case-mix rules as JSON. Some columns may be newer than a workbook you already have —
every loader reads with defaults and a missing sheet decodes to empty, so an
older file opens without migration.

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
│  ├ Front Desk        │ ◄───────── │  ├─ services/watchdog.py (clock)│
│  ├ Live Queue        │  WS push   │  ├─ services/messaging.py      │
│  ├ Ops Console       │            │  └─ storage/excel_store.py     │
│  └ Activity / Audit  │            │        └─ engine/  (PURE)       │
└──────────────────────┘            │             ├─ state.py         │
                                     │             ├─ slots.py         │
                                     │             ├─ conflict.py      │
                                     │             ├─ allocator.py     │
                                     │             ├─ emergency.py     │
                                     │             ├─ handlers.py      │
                                     │             ├─ visits.py        │
                                     │             ├─ waitlist.py      │
                                     │             ├─ investigations.py│
                                     │             ├─ arrivals.py      │
                                     │             ├─ risk.py          │
                                     │             ├─ actions.py       │
                                     │             ├─ clinic_control.py│
                                     │             ├─ sessions.py      │
                                     │             ├─ privacy.py       │
                                     │             ├─ context.py       │
                                     │             ├─ outcomes.py      │
                                     │             ├─ coordination.py  │
                                     │             ├─ capacity.py      │
                                     │             ├─ patient_view.py  │
                                     │             ├─ ask.py + guide.py│
                                     │             ├─ propose.py       │
                                     │             └─ replies.py       │
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
| C | **Two emergencies at once** | `handle_emergency_pair` | Tries to assign to **different doctors** (parallel). If only one is free, breaks the tie by **priority sub-score** (severity recorded by staff, then wait time) and queues the other; re-evaluated as resources free. |
| D | **Room equipment breakdown** | `handle_room_breakdown` | Flags room `unavailable` until a time, then **reassigns affected sessions** to a compatible room (respecting equipment + drug time-window). Notifies patients. |
| E | **Patient no-show** | `handle_no_show` | After X minutes without check-in: records `NO_SHOW`, **releases the slot**, and **notifies the next patient in queue** ("you're up"). |
| F | **Drug time-of-day window** | conflict detector + allocator | Each drug carries a hard `time_window`; the room/slot search **filters out** any slot outside it before scoring. |

Two primitives back everything: `reschedule_affected` (a constraint changed) and
`advance_clock` (time advanced). The watchdog calls `advance_clock` every 5 s to
auto-fire no-show and overrun triggers, then pushes the result over WebSocket.
It skips any appointment held for lab results, so a patient waiting on their
counts is never recorded as absent.

---

## Clinic flow — beyond the edge cases

The six handlers above all answer "something broke, now fix the schedule".
These seven cover the ordinary day, and each one is a pure engine module with
its own test suite.

| # | Feature | Module | What it does |
|---|---------|--------|--------------|
| 1 | **Walk-in intake** | `allocator.walk_in_options` / `book_walk_in` | Finds where a patient at the desk can be seen **today, in gaps that are already free**. Never moves a booked patient. A doctor at their `daily_cap` is reported, not squeezed. Urgency narrows the search: `urgent` 1 h, `soon` 3 h, `routine` the rest of the day. |
| 2 | **Investigation gate** | `investigations.py` | Models the lab order a treatment waits on. Gating holds the patient's place — they are **never marked no-show** — while releasing the chair back to the pool. An out-of-protocol result **blocks**; only a doctor can clear it, and re-pencilling still respects the drug's time window. |
| 3 | **Waitlist + backfill** | `waitlist.py` | A cancellation now asks *who could actually take this?* Candidates are ranked by whether they can physically get here (in the building → reachable → longest wait), one slot can be offered to several patients, and the **first acceptance wins** while the rest are told it is gone. |
| 4 | **Patient messaging** | `services/messaging.py` | Notifications move through real states (`pending → delivered / failed`) via a pluggable driver, and replies are parsed to an intent. A `YES` to a waitlist offer books the slot; a reply about an appointment records whether the patient is coming, which feeds the risk score. |
| 5 | **Arrivals board** | `arrivals.py` | The waiting room as a board: tokens issued in arrival order, real waiting time (arrival → called in), and a stage per patient (not arrived / ready / in labs / with doctor). Also reports which doctors are **running late**, measured only against patients who actually turned up. |
| 6 | **Smarter slots** | `visits.py` | Visit types carry their own length (follow-up 10, new case 30, counselling 45, chemo review 15) and the slot search runs on a 15-minute grid, so a short visit can use a gap a 30-minute slot could not. Once a doctor has enough timed visits, the **median they really run** is offered as a suggestion — never applied. |
| 7 | **No-show risk** | `risk.py` | Scores a day's list from attendance history, whether the patient replied, first visit and slot time — only factors the datastore actually holds, each one named in the output. Overbooking is **off** unless a doctor switches it on for their own clinic. |

Three rules hold across all of them:

- **Nothing clinical is decided automatically.** A flagged lab result blocks
  and waits for a doctor; the system never proceeds, defers or reduces a dose.
- **Overbooking needs the doctor's own switch.** `Doctor.allow_safety_booking`
  defaults to `false`; high-risk slots sit in `needs_doctor_opt_in` until then.
- **Suggestions say why.** Every ranked row carries its reasons, so a human can
  disagree with the ordering instead of trusting a number.

### Endpoints these add

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/walk-ins/options` | Where a walk-in could be fitted today (read-only) |
| `POST` | `/api/walk-ins` | Place the walk-in in one of those gaps |
| `GET`  | `/api/doctors/{id}/visit-durations` | Planned vs learned length per visit type |
| `GET`  | `/api/waitlist` · `POST` · `DELETE /{id}` | Manage the waitlist |
| `POST` | `/api/waitlist/match` | Who could take a given free slot |
| `POST` | `/api/waitlist/offer` · `/{id}/accept` | Offer a slot, then book the first acceptance |
| `GET`  | `/api/investigations` · `POST` | List / order investigations |
| `POST` | `/api/investigations/{id}/result` · `/clear` | File a result; a doctor accepts a flagged one |
| `GET`  | `/api/appointments/{id}/readiness` | Is this treatment clear to proceed? |
| `POST` | `/api/appointments/{id}/gate` · `/repencil` | Hold for results; put it back on the board |
| `POST` | `/api/notifications/{id}/reply` · `/flush` | Record a patient reply; force a send |
| `GET`  | `/api/arrivals` | Arrivals board, next up, who is running late |
| `POST` | `/api/appointments/{id}/call` | Call a waiting patient in (ends their wait) |
| `GET`  | `/api/risk` | No-show risk for a day, with suggestions |
| `PUT`  | `/api/doctors/{id}/safety-booking` | A doctor's own overbooking switch |

`/api/state` also gained `visit_types`, `waitlist`, `investigations`, `gated`,
`arrivals`, `running_late` and `messaging_driver`, so the UI stays live over
the WebSocket without extra polling.

---

## The doctor's own controls

The clinic-flow features above make the department run better. These make the
*doctor* an operator of the scheduler rather than a subject of it — each one is
a sentence a consultant already says out loud, and which the schedule
currently finds out about late, if at all.

| Control | Module | What it does |
|---------|--------|--------------|
| **Running the room** | `clinic_control.extend` / `.swap` | "+5 / +10 / +15 min" with this patient. Only *this doctor's* own later patients shift; a colleague's list is never touched. If the cascade would run past 18:00 it says so and names who. Swapping refuses when the two visits are different lengths, because that would quietly resize someone's appointment. |
| **Send the next patient in** | `clinic_control.pull_forward` | Moves the next patient into the gap that just opened, on a 5-minute grid. Prefers someone who has actually arrived; if nobody has, it still offers the next patient and says plainly they may not be in the building. |
| **Hand over to a colleague** | `clinic_control.hand_off` | Checks specialty cover, leave and the colleague's daily cap *before* moving anyone, keeps the same time when they are free and finds their nearest equal-length slot when they are not. Refusals name the constraint. |
| **Close my list** | `clinic_control.close_list` | Stop taking patients after a time without being marked sick for the whole day. Returns the **plan first** — who is affected, who can cover them, who cannot — and moves nobody until it is applied. |
| **What changed, and undo** | `actions.py` | Every reversible change records a before/after snapshot per appointment plus its reason, and shows up on the doctor's own screen. `allocator.reschedule` records too, so sick-leave cascades, overruns, auto-reschedule and backfill are all explainable and reversible — not just manual actions. |
| **Working week** | `sessions.py` | Clinic sessions, ward rounds, teaching and lunch. A `clinic` block is where booking is *allowed*; every other kind is treated like a leave window. A doctor with no template is unconstrained, exactly as before. |
| **Case-mix rules** | `sessions.py` | "No more than 3 new cases in a row", "counselling before 12:00 only". Checked at booking time, because they depend on what else is already on the list. |

Two properties are worth calling out, because they are what make this help
rather than replacement:

- **Refusals speak the doctor's language.** A booking blocked by the week
  comes back as `Teaching (16:00–16:30)` or
  `outside clinic hours (09:00–17:00)`, and one blocked by a rule as
  `no more than 2 follow-up visits in a row` — never as a slot-conflict code.
- **The rules live in the conflict detector, not the booking form.** Walk-ins,
  waitlist backfill, auto-reschedule and re-pencilling therefore inherit the
  working week and the case-mix rules for free: one place to write them, five
  places they take effect.

**Undo is deliberately conservative.** It refuses — rather than
half-applying — once a patient on that change has been seen, or once a later
change has touched the same appointments. A wrong undo is worse than none.

### Who may do what

A doctor acts on **their own list only**, and the API enforces it rather than
the UI alone. `POST /api/appointments/{id}/extend` on someone else's patient
returns `403 "that patient is not on your list"`; undoing a change that is not
on your list returns `403 "that change is not on your list"`. Admin and nurse
run the floor and are not scoped — the engine still refuses anything that
would break a constraint.

The UI mirrors this with a **scope**, which is a different question from
capability: a doctor opens the schedule and the waiting room on their own
list, with a *Whole department* toggle one click away, because handing a
patient over needs a colleague's day visible.

### Endpoints for these controls

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/appointments/{id}/extend` | More time with this patient; cascades your own list |
| `POST` | `/api/doctors/{id}/pull-forward` | Send the next patient in |
| `POST` | `/api/appointments/{id}/swap` | Exchange two of your own slots |
| `POST` | `/api/appointments/{id}/hand-off` | Give one patient to a named colleague |
| `POST` | `/api/doctors/{id}/close-list` | Plan (default) or apply closing your list |
| `GET`  | `/api/actions` | What changed, why, and whether it can be undone |
| `POST` | `/api/actions/{id}/undo` | Put the schedule back |
| `GET`  | `/api/doctors/{id}/week` | The session template and case-mix rules |
| `GET`  | `/api/doctors/{id}/day-plan` | Clinic windows and blocks for one day |
| `PUT`  | `/api/doctors/{id}/sessions` | Replace the working week (a doctor: own only) |
| `PUT`  | `/api/doctors/{id}/rules` | Replace the case-mix rules (a doctor: own only) |

---

## Beyond the brief

Two things the problem statement never asks for. They are here on purpose,
and for opposite reasons.

### Consent on outgoing messages

The app can send real SMS or WhatsApp once a provider is configured. None is
configured in the demo, so nothing is actually sent there. A phone in an OPD is often shared — an attendant, a
neighbour, a son who came along — so a message reading *"Your chemotherapy
with Dr. Amina Khan has been rescheduled"* discloses a cancer diagnosis to
whoever picks it up. Nobody agreed to that.

Three flags are captured at registration, and one of them is **off by
default**:

| Flag | Default | Effect |
|------|:-------:|--------|
| `consent_sms` | on | Off and the patient is never messaged. The message is marked **`blocked`**, not dropped, so the desk can see it and phone instead. |
| `consent_name_treatment` | **off** | Off and drug names, the patient's own diagnosis, the chemo room and words like *chemotherapy* are replaced with neutral wording. |
| `consent_attendant` | on | Whether whoever answers that number may be spoken to. |

Enforcement lives in `engine/privacy.py` and runs **at dispatch**, the moment
a message is handed to the provider — so it holds no matter which part of the
engine composed it, rather than depending on every call site remembering.

The terms being removed are read from the datastore — the actual drug names,
this patient's own diagnosis and stage, the real chemo room names — never
guessed from a word list alone:

```
consent to name the treatment: OFF
  CHANGED  Your treatment session has moved to 15:30.
  CHANGED  Your treatment with Dr. Amina Khan has been rescheduled.
  CHANGED  Please come to the day-care unit at 10:00.
  as-is    Your appointment at 16:00 has been cancelled.
```

The stored message is rewritten too, so the log shows what actually left the
building rather than what the engine first composed.

> **Not done:** consent governs what *leaves* the building. Inside it, the
> activity log and the change history still carry patient names. Both are
> role-gated, but neither has been reduced to identifiers.

### Context at the point of care

The doctor's day list was four columns — time, name, room, status — so to
know which cycle a patient is on, whether their counts are back, or whether
they confirmed they were coming, the doctor had to open another record or ask
them.

`engine/context.py` reads what the system already holds and puts it on the
row: the chemo history gives the cycle, the drug gives the regimen, the
investigations give the lab status, the reply gives the confirmation.

```
16:35  Bilal Hussain   Follow-up
       never confirmed · first visit here
       allergies: Sulfa drugs
```

Two deliberate limits:

- **It invents nothing.** A consult has no cycle, so `cycle_number()` returns
  `None` rather than a number — and a cancelled cycle does not count towards
  the next one.
- **It is a reading, not a record.** Nothing here is written; this is an
  operations tool surfacing its own data, not a chart.

### Endpoints for these two

| Method | Path | Purpose |
|--------|------|---------|
| `PUT` | `/api/patients/{id}/consent` | Record what the patient agreed to |
| `GET` | `/api/doctors/{id}/day-context` | The day's list with its context (a doctor: own only) |

Consent also travels with `POST`/`PUT /api/patients`, so registration captures
it in one step.

---

## The last four gaps

Three of these are phrases in the brief the app could not answer; the fourth
is implied by one word in it.

### The fourth role: care coordinator

The brief names four roles — doctors, nurses, front-desk teams and **care
coordinators** — and only three had a surface. A coordinator's job is not the
desk's: the desk runs the room in front of them, the coordinator follows the
patients who are no longer in front of anybody.

`engine/coordination.py` joins six signals that already existed separately
into one ranked list, each row carrying its reason and the single action that
would clear it:

| Surfaced when | Action offered |
|---------------|----------------|
| A missed visit has **nothing rebooked** | Call and rebook |
| A lab gate is 60+ minutes old | Chase the lab, or ask the doctor to review a flag |
| Someone arrived and was not called for 45+ minutes | Call them in |
| A waitlist entry has sat 2 hours with no offer | Offer a slot or remove them |
| A high-risk patient never replied | Phone to confirm |
| A message was **blocked for consent** | Phone them instead |

A no-show that *has* already been rebooked never appears — otherwise the list
becomes noise and stops being read.

The role is scoped to that job: it may rebook, cancel, offer waitlist slots,
place walk-ins and record replies. It may not trigger edge cases, open the Ops
Console, read the security audit, or make the clinical calls (`sick-leave`
and `/api/audit` both return `403`).

### A way in and a way out

The brief describes fragmentation — *"care teams often rely on multiple
systems"* — and the app answered it with no door at all: the patient list came
from a seed script. `services/interop.py` opens three, deliberately small:

- **CSV in**, because that is what a hospital can produce from its existing
  HIS without a project. **Previewed first** — every problem named by line,
  nothing written:
  ```
  preview -> create: 2  update: 0
    error: line 3: no name — skipped
    error: line 4: contact 'bad-phone' does not look like a number
  ```
  Matching is on `mr_number` first, then on name. An import cannot turn
  consent on by accident: naming the treatment still defaults to off.
- **CSV out**, for the people who will open it in Excel.
- **A FHIR-shaped Bundle** of Patients and Appointments. It is the resource
  *shape*, not a certified FHIR server, and the bundle says so in its own
  `meta.tag`: `fhir-shaped`. Claiming more would be the easiest thing in this
  repo to get caught doing.

### Capacity across days

Every other module reasons about today; the brief describes a pressure that
builds — *"as patient volumes increase, balancing clinic capacity with patient
demand"*. `engine/capacity.py` looks across a horizon of days and names the
move rather than leaving two numbers side by side:

```
2026-11-01 sun  10%  ok   10 booked
2026-11-02 mon  10%  ok   10 booked
· No day in this window is tight — busiest is 2026-11-01 at 10%
```

The denominator is the hours the clinic **actually has**: session templates
and leave both come off it, and a day with no clinic reports `null` rather
than 0%.

### The patient's own view

`/p/<token>` is unauthenticated by design — the link is the credential. It
shows one visit: the token number, the stage, how many people are ahead, and
one line of guidance. A patient can confirm or decline from it, which is what
frees a slot hours before a no-show would have.

It is defined by what it leaves out: no other patient's name, no diagnosis, no
specialty, no room name that would give the treatment away — and the treatment
itself only where that consent was given. The token is an HMAC of the
appointment id under the signing secret, so it is stable and unguessable
without being stored, and an unknown token returns `404`.

### Endpoints for the last four

| Method | Path | Purpose |
|--------|------|---------|
| `GET`  | `/api/follow-ups` | Everyone nobody is currently looking after |
| `GET`  | `/api/capacity` | Committed vs available across a horizon of days |
| `POST` | `/api/import/patients/preview` | What a CSV would do; writes nothing |
| `POST` | `/api/import/patients` | Apply it (admin only) |
| `GET`  | `/api/export/patients.csv` · `/appointments.csv` | CSV out |
| `GET`  | `/api/export/fhir` | A FHIR-shaped Bundle |
| `GET`  | `/api/appointments/{id}/patient-link` | The link to give this patient |
| `GET`  | `/api/p/{token}` | The patient's own view (no session) |
| `POST` | `/api/p/{token}/confirm` | The patient answering for themselves |


---

## The number this asks to be judged on

Every other section describes something the app *does*. This one is the only
claim about whether any of it helped, and it is deliberately a single
operational metric rather than a dashboard of them.

**Chair-minutes recovered from lab waits.** When a treatment is waiting on
bloods, gating hands its chair back to the pool instead of holding it empty
until the slot passes. The minutes handed back are recorded at the moment of
release — `engine/investigations.gate` writes `chair_released_min` onto the
appointment — and summed per day by `engine/outcomes._gating`.

It is a stored field rather than something derived later, and that is not an
implementation detail: `repencil()` clears `held_room_id` when the results
land, so anything reconstructing this afterwards would quietly read zero.
`test_gating_kpi.py` pins exactly that.

### Two complete days, same list

The seeded workbook builds two full past days that differ in one respect
only — whether the clinic was managed. Same forty patients, same doctors,
same slots:

| | Unmanaged (day-2) | Managed (day-1) |
|---|---|---|
| Chair-minutes recovered | 0 | **120** |
| Median queue wait | 36 min | **19 min** |
| Seen within 15 min of their slot | 9% | **76%** |
| No-show rate | 10% | **0%** |
| Visits seen | 34 | **41** |
| Utilisation | 50% | **62%** |

Measured from 37 timed visits, computed by `engine/outcomes.compare()` from
the check-in and call-in timestamps on the rows. No figure in that table is
stored anywhere.

On the unmanaged day the four treatments waiting on bloods are marked
**no-show while the patient is sitting in the waiting room** — their chair was
held, the slot passed, and the clinic recorded them as absent. On the managed
day those same four are gated and treated later the same day. That is where
six of the seven extra visits come from.

### Two deliberate refusals

- **A lab wait is not a queue wait.** Waiting and punctuality leave out
  patients held for results: their clock keeps running while the lab works,
  and counting it would penalise the clinic for the one move that freed the
  chair. The number excluded is reported next to the figure, so the omission
  is visible rather than silent.
- **The dashboard compares the last two *complete* days.** Not today against
  yesterday: a half-played day makes every count look like a collapse at
  11:00 and a triumph at 18:00, which says something about the clock and
  nothing about the clinic. Today is still shown, as a running total, labelled
  as partial.

The figures above come from a seeded workbook, not a clinic. What they
demonstrate is that the instrument works.

[`docs/PILOT.md`](docs/PILOT.md) is the plan for getting a real one: a paper
baseline week (Mon 30 Nov 2026), three phases to a read-out on Fri 5 Mar 2027,
the sample-size arithmetic, and six stopping rules — including the two honest
ones, that under 30 recovered chair-minutes a day is not worth a clinic's
training time, and that recovering chair time while patients wait *longer* is
not the trade being claimed.

The site and the clinical lead are named by role rather than by name — a
pilot site is a relationship, not a line in a document, and the names go in
once the partner unit has agreed. One piece of engineering stands between the
current code and day 0: **log redaction**, below.

---

## Closing the last gaps

### A note that travels with the patient

A hand-off moved a name and a slot; the receiving doctor inherited no context
and had to telephone the colleague who handed over. `hand_off()` now carries a
`note` — kept separate from `reason`, because "clinic overran" and "counts
back at 11:05, keen to go ahead today" answer different questions and
collapsing them would bury the second one in an audit summary.

It appears in full on the receiving doctor's own list, with who wrote it, plus
a flag on the row so it is visible before they call the patient in. A failed
hand-off leaves no note behind, and whitespace is not a note.

### WhatsApp, pointed somewhere

The dispatcher, the consent gate, the scrubber and the reply parser were all
real; what had never happened was a message leaving the machine.
`WhatsAppDriver` sends through the Cloud API, and `build_driver()` chooses by
environment alone: WhatsApp if `CARE_WHATSAPP_TOKEN` **and**
`CARE_WHATSAPP_PHONE_ID` are both set, else a generic webhook, else the log.

A token with no phone id is a mistake rather than a channel, so it falls
through to the log instead of half-working. Numbers are normalised to the
shape the API accepts — the workbook holds `+91 98200 11101`, `098200 11101`
and `9820011101`, all of which have to become `919820011101` — and a number
that cannot be made sense of **fails visibly** rather than being sent
somewhere wrong. The country code for locally-typed numbers is a named
default (`CARE_DEFAULT_COUNTRY_CODE`), not a silent assumption.

With nothing configured, messages go to the application log and the entire
flow still runs. That is the default on purpose.

### हिंदी, and the person who came along

The console stays English: the doctors, nurses and coordinators who use it
work in English, and translating four hundred strings nobody asked for would
be effort spent on the wrong screen. The one surface a *patient* ever sees is
the one that must not be English-only, so that is the one translated —
English, Hindi and Marathi, in `frontend/src/lib/i18n.ts`, with no library.

Three details that make it more than a toggle:

- **It opens in the language the clinic recorded** (`Patient.language`). A
  toggle nobody finds is not multilingual. The toggle is still there, because
  the person holding the phone is often a son or a daughter.
- **The engine knows no languages.** `patient_view.status_for()` returns the
  guidance as `advice_key` plus `advice_vars` as well as English prose, so a
  new language touches one dictionary and never the engine.
- **Replies are read in the language they were sent in.** `haan`, `ji`, `हाँ`,
  `ho`, `होय`, `nahi`, `नाही`, `nako` all parse. A reply the clinic cannot read
  is a patient who answered and was treated as though they had not. Anything
  genuinely ambiguous stays `unclear` and goes on the coordinator's list to
  phone — it is never guessed at. Any refusal in a reply wins, and a yes only
  counts when nothing else was said, so "ji nahi" can never book a slot.

The caregiver block appears only where the patient already agreed that
whoever came with them may be spoken to about the appointment. It is a
separate consent from naming the treatment, and it does not unlock it.


---

## Ask the clinic

The console can answer "who has been waiting longest" today — it just makes
you assemble it: open Front Desk, read eighteen rows, sort them by eye, then
open Follow-ups to learn the longest wait is a patient *held for results*
rather than one who was forgotten. At a desk with somebody standing in front
of you, that assembly is the expensive part.

A floating button at the bottom right, or <kbd>Ctrl</kbd>+<kbd>K</kbd>. Same
panel either way: the button is how it gets found, the shortcut is how it gets
used on the fortieth lookup of a shift. English, हिंदी and मराठी in the same
box, because the desk already works that way.

### It looks and proposes. It never acts alone

Looking something up changes nothing, so there is nothing to confirm. Changing
the schedule always takes a person: the assistant can only propose one of four
actions, as a card.

| Action | Example | What the card does on Confirm |
|---|---|---|
| Extend | "is patient ko 10 minute aur do" | `POST /api/appointments/{id}/extend` |
| Send next patient | "agle patient ko bhej do" | `POST /api/doctors/{id}/pull-forward` |
| Hand off with a note | "Vikram ko Dr. Ben ko de do, counts 11 baje aaye the" | `POST /api/appointments/{id}/hand-off` |
| Close a list | "meri list ek baje band kar do" | `POST /api/doctors/{id}/close-list` |

Confirm calls the same endpoint as the button, with the same role check, the
same refusals and the same Undo. Voice adds nothing to this: Saaras turns a short
clip into text, and that text goes through the same path as anything typed.

`engine/ask.py` and `engine/propose.py` decide **which existing view or action**
a sentence wants. They do not fetch rows, count anything or phrase an answer. The
API calls the same engine function the screen calls, and the UI draws the rows as
any other panel does.

That split is the safety argument: **nothing in the answer path can invent a
number.** "Meera Nair · 158 min" came from `GET /api/arrivals`. The worst a wrong
guess can do is show the wrong table or offer a wrong card, and both say what they
are before anyone acts on them. Every answer carries its own `from GET /api/…` line.

### The catalogue is the permission list

Ten read-only views and four actions. Adding to those lists is the only way to
widen what the assistant can do. `test_ask.py` asserts that no view's id or
purpose contains a writing verb. `propose.read_choice` throws away anything the
model returns that is not on the list, so a model inventing `cancel_appointment`
gets the same answer as one returning nonsense.

### Questions that look alike

| Asked | Answer |
|---|---|
| "Who is waiting longest?" | The arrivals board, sorted by a clock |
| "Who is most urgent?" | The emergency queue, in the order of the severity staff recorded |
| "Who is sickest?" | Refused: nobody recorded that, and the assistant does not work it out |
| "Whose results are back?" | Investigations with a status; a flagged one says a doctor must review it |
| "Are her counts safe to treat?" | Refused: it does not read values, and clearing a flag stays the doctor's button |
| "Give Usman more time" with a misheard name | It asks which patient. It never falls back to whoever is in the room |

Clinical questions are refused **locally, before the model runs**, so the sentence
never leaves the machine. It also never guesses a patient. Two people called
Fatima is a question, not a coin toss.

### What Sarvam sees

| Goes to Sarvam | Does not go to Sarvam |
|---|---|
| The sentence staff typed, including any note in it | Patient records, lab values and diagnoses held in the app |
| The list of doctor names, views and actions | Clinical questions, which are refused first |
| A voice clip, as recorded | "How do I…" help questions, which are answered locally |

Latin-script patient names in typed text are replaced with `PATIENT_1` and so on
before sending. **Names typed in Devanagari are not masked, and a voice clip
carries any name spoken in it.** That is acceptable on synthetic data and has to
be settled in the data-handling note before any real patient is entered.

With no `CARE_SARVAM_KEY`, or when Sarvam fails or times out, the local phrase
matcher answers instead. The mic only appears when a key is set. Microphones need
HTTPS or localhost.

### How well it reads

Scored by `scripts/eval_ask.py` on `docs/eval/commands_dev.csv`: synthetic commands
in English, Hindi, Hinglish, Marathi and Latin-script Marathi.

| 149 commands, 3 Nov 2026 | Phrase matcher | Sarvam |
|---|---:|---:|
| Right view, action or refusal | 34.2% | 98.7% |
| Actions with every detail right | 0 of 72 | 69 of 72 |
| Clinical questions refused | 20 of 25 | 25 of 25 |
| Cards for the wrong action | 0 | 1 |
| Operational questions wrongly refused | 0 | 1 |
| Median time per command | | 0.66 s |

**These are tuning results and they flatter the model.** The prompt was adjusted
while reading failures on these same sentences, and they were not written by clinic
staff. They show the path works. The figure to quote will come from one run on a
held-out set written by someone who has not seen this sheet or the prompt, with no
tuning afterwards. Voice has only had a small test with generated speech, not real
voices or a clinic's background noise.


### …and when you are stuck in it

The commonest stuck-moment in this app is not "I cannot find the button". It
is **"the button is not there"** — and the answer is nearly always that this
person's role does not have it. A nurse hunting for *clear this flagged
result* will never find it: accepting an out-of-protocol lab value is a
clinical decision, and the backend gives it to doctors and admins only.

A help page cannot say that, because it does not know who is reading. So
`engine/guide.py` carries, for each topic, **the roles that topic's endpoint
actually requires** — read off its `require_role(...)` — and the answer
changes with who asked:

| Asked by | "clear flag kaise karein" |
|---|---|
| a doctor | the four steps |
| a nurse | *Your role cannot do this — ask an administrator or a doctor*, and why it sits with them |
| a coordinator | the same refusal |

Somebody who cannot do a thing is never handed the steps for it, and every
restriction explains itself — "ask a nurse" with no reason reads as a bug in
the software rather than a rule. `test_guide.py` asserts both, and asserts
the roles on each topic still equal what `require_role` enforces on that
route, so the help cannot quietly drift from the thing that returns 403.

Cues match on **words, not substrings**: "where do I check someone in" is
about checking in, but the phrase "check in" never appears in it.

---

### The badge

One row per patient here, not one per reason. The coordinator's own list
keeps a row per reason on purpose — two rows for one patient are two jobs with
two actions, and folding them would hide one — but in a three-line summary the
same name twice reads as a bug. `coordination.by_patient()` folds them, worst
severity first, and says how many reasons it stands for.

The button carries a count of what the clinic **already flagged**: open
insights plus the follow-up list. It never invents urgency and it is never a
clinical judgement — Meera is on that list because she has waited 158
minutes, not because of anything about her illness. It never opens itself
either; a clinic screen that interrupts you mid-task gets closed once and
never reopened.

---

## Getting started

### Docker (recommended)

One container builds the frontend and serves both the API and the app. No
`.env` file is required — the app self-configures (it derives and persists a
stable JWT secret into the data volume on first boot).

```bash
docker compose up --build        # then open http://localhost:8000
```

- The Excel datastore + secret persist in the `oncocare-data` volume across
  restarts (`docker compose down` keeps it; `docker compose down -v` wipes it
  and re-seeds sample data on the next start).
- To customise, uncomment the `environment` block in `docker-compose.yml`
  (e.g. set `CARE_SECRET`). All variables are optional — see `.env.example`.

### Hosted (Render)

`render.yaml` describes the same container. In Render choose **New → Blueprint**,
point it at this repository, and paste `CARE_SARVAM_KEY` when asked. Render
provides HTTPS, which the mic needs. Data is demo data and is rebuilt on restart.

### Local development (optional)

If you'd rather not use Docker:

```bash
# Backend (Python 3.11)
python -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
cd backend && PYTHONPATH=. python -m uvicorn api.main:app --reload --port 8000

# Frontend (separate terminal)
cd frontend && npm install && npm run dev    # http://localhost:5173
```

The Vite dev server proxies `/api` and `/ws` to the backend on port 8000.
The app seeds `backend/data/care.xlsx` with sample data on first run.

### The demo clock

`docker-compose.yml` pins `CARE_NOW` to **11:30**, because the seeded workbook
plays today out to 11:30 — visits done, patients in chairs, one treatment held
for results, one person waiting to be called, and an afternoon still to run.
Without the pin the app shows whatever hour you happen to open it at, which
after 14:00 is an empty clinic.

Comment the line out to let the clock follow real time. Nothing breaks: the
watchdog never no-shows a patient who has checked in or whose treatment is
held for results.

### Log in

| Role        | Username | Password    |
|-------------|----------|-------------|
| admin       | `admin`  | `admin123`  |
| nurse       | `nurse`  | `nurse123`  |
| coordinator | `coord`  | `coord123`  |
| doctor      | `doctor` | `doctor123` |

Each doctor also has their own login (`amina`, `ben`, `chloe`, `dan`,
`elena` — all `doctor123`), which is how the per-doctor scoping is
demonstrated.

**Role permissions** (enforced on the backend via `require_role`, mirrored in the UI):

| Capability | admin | nurse | coordinator | doctor |
|------------|:-----:|:-----:|:-----------:|:------:|
| **Data scope** | department | department | department | **own list** (+ toggle) |
| View dashboard, schedule, front desk, live queue | ✅ | ✅ | ✅ | ✅ |
| **Follow-ups console** | ✅ | ✅ | ✅ | ❌ |
| Book / reschedule / cancel appointments | ✅ | ✅ | ✅ | ❌ |
| Place a walk-in | ✅ | ✅ | ✅ | ❌ |
| Manage the waitlist (add, offer, accept) | ✅ | ✅ | ✅ | ❌ |
| Record what a patient replied | ✅ | ✅ | ✅ | ❌ |
| Order an investigation, hold a treatment for results | ✅ | ✅ | ✅ | ✅ |
| Clear a flagged result so treatment may proceed | ✅ | ❌ | ❌ | ✅ |
| Allow safety bookings in a clinic | ✅ | ❌ | ❌ | own only |
| Extend / swap / hand off / close a list | ✅ | ✅ | ✅ | own only |
| Undo a change | ✅ | ✅ | ✅ | own list only |
| Set the working week & case-mix rules | ✅ | ❌ | ❌ | own only |
| Record a patient's consent | ✅ | ✅ | ❌ | ❌ |
| Read a day list with clinical context | ✅ | ✅ | ✅ | own only |
| Check patients in / call them in | ✅ | ✅ | ✅ | ✅ |
| Register & resolve emergencies | ✅ | ✅ | ✅ | ✅ |
| Import patients from CSV | ✅ | ❌ | ❌ | ❌ |
| Export CSV / FHIR | ✅ | ✅ | ❌ | ❌ |
| Trigger edge cases (sick leave, overrun, breakdown, no-show, clock) | ✅ | ✅ | ❌ | ❌ |
| View Ops Console tab | ✅ | ✅ | ❌ | ❌ |
| View the event stream + message log (Activity tab) | ✅ | ✅ | ✅ | ❌ |
| View the **security audit trail** | ✅ | ❌ | ❌ | ❌ |

Four things in that table are deliberate rather than incidental:

- **Nurse is not a second admin.** The security trail is admin-only on the
  backend, so the Activity tab no longer offers a nurse a sub-tab that would
  403 on open.
- **Two clinical calls sit with the doctor, not the floor** — accepting an
  out-of-protocol lab result and allowing a clinic to be overbooked — and a
  doctor may only make the second for themselves.
- **Scope is a different question from capability.** A doctor is *allowed* to
  see the department (handing a patient over needs it), they simply do not
  *start* there.
- **The coordinator chases, they do not run the floor.** They can rebook,
  offer and phone, and move a visit when chasing someone calls for it. They
  cannot trigger an edge case, open the Ops Console or read the audit trail.

Doctors get a focused, mostly read-only console (they can still check patients in
and raise emergencies), which matches a real clinical workflow.

### Run the tests

```bash
# Backend — engine + API integration tests
PYTHONPATH=backend pytest tests -q

# Frontend — component smoke tests
cd frontend && npx vitest run
```

The backend suite (**617 tests**) covers the slot/buffer model, conflict
detection, chemo allocation, drug time-windows, the emergency priority queue
and **each of the 6 edge cases**, plus an Excel round-trip — and one file per
clinic-flow feature:

| File | Covers |
|------|--------|
| `test_visits.py` | visit types, the 15-minute candidate grid, learned durations |
| `test_walkin.py` | gap search, urgency horizons, daily cap, leave windows |
| `test_waitlist.py` | ranking, offering to several, first-accept-wins |
| `test_investigations.py` | gating, chair release, the no-show exemption, re-pencil refusals |
| `test_messaging.py` | delivery states, failed sends, reply intents |
| `test_arrivals_risk.py` | tokens, waiting time, running late, risk factors, the opt-in gate |
| `test_clinic_control.py` | extend / pull forward / swap / hand off / close list, and undo's refusals |
| `test_sessions.py` | session blocks, case-mix rules, and that an empty template changes nothing |
| `test_packed_lists.py` | the separator mismatch described under *Notes* |
| `test_privacy_context.py` | consent, message scrubbing, and the cycle/lab/flag reading |
| `test_outcomes.py` | the refusal to publish a thin median, and which direction is "better" |
| `test_gaps.py` | the coordinator list, CSV/FHIR interop, capacity, and what the patient page leaks |
| `test_gating_kpi.py` | the headline metric: recorded at release, and why it is stored rather than derived |
| `test_multilingual.py` | the patient page's language, the caregiver consent, and replies in three languages |
| `test_login_throttle.py` | that the login budget charges failures, not people signing in |
| `test_demo_refresh.py` | the seed's anchor date, and that a demo workbook rebuilds instead of rotting |
| `test_insight_grouping.py` | that collapsing repeated warnings loses no appointment, resource or severity |
| `test_scrub_boundaries.py` | that redacting a disclosure does not maul the sentence around it |
| `test_ask.py` | what the assistant answers, what it refuses, and that no view writes |
| `test_ask_api.py` | the model-first path, the fallback when Sarvam fails, and voice limits |
| `test_propose.py` | turning a model's choice into a card, masking names, and the wrong-patient guards |
| `test_replies.py` | that a refusal anywhere in a patient's reply beats a yes |
| `test_guide.py` | that the interface help tells the truth about permissions, per role |

CI (`.github/workflows/ci.yml`) runs both suites on every push.

> `test_ws.py` and `test_login_throttle.py` import the FastAPI app, so they
> need the backend requirements installed (`python-jose` in particular). To
> run the engine suites alone with just `pytest` + `openpyxl`:
> `pytest tests -q --ignore=tests/test_ws.py --ignore=tests/test_login_throttle.py --ignore=tests/test_ask_api.py`.
>
> Sarvam is faked in these suites, so they use no credit and need no key. Real
> accuracy is measured separately by `scripts/eval_ask.py`, which does need one.

---

## Dashboard

There is also one screen outside the console entirely: **`/p/<token>`**, the
patient's own view of their own visit. No session, no chrome, one column,
built for a phone.

- **Schedule** — doctor/room Gantt timeline, live summary stats, and a booking
  form with three modes: **consult** (the visit type sets the length), **chemo**
  (auto-picks the best compatible room respecting equipment + drug time-window)
  and **walk-in** (searches today's real gaps and offers the best fits).
  Below it: treatments **held for results**, the **backfill** panel a
  cancellation opens, and the **waitlist**.
- **Front Desk** — the arrivals board (token, due, arrived, waiting time,
  stage), *call next*, which doctors are running late and who is affected, and
  the day's **no-show risk** with its safety-booking opt-in.
- **My day** (on Schedule, for a doctor) — *send next patient in*, *close my
  list at…* with its plan, and the record of what changed on your list with an
  **Undo** on each entry. The appointment dialog gains a *Running the room*
  strip: extend, swap, hand over.
- **Availability** — leave as before, plus the **working week** (clinic
  sessions, ward rounds, teaching, lunch) and **case-mix rules**.
- **My Day** (a doctor's home) — the day's list with its context: cycle,
  regimen, lab chips, whether they confirmed, and any walk-in reason.
- **Did it help?** (on the dashboard) — the day's waiting times, punctuality,
  utilisation, recovered time and losses, against the clinic's own previous
  day. A block with too few timed visits says so rather than printing a
  figure.
- **The week ahead** — committed against available minutes per day, with the
  move named.
- **Doctors & Patients** — registration now ends with *What may we send?*,
  the three consent boxes. Naming the treatment is unticked by default.
- **Follow-ups** (admin, nurse, coordinator) — everyone nobody is currently
  looking after, worst first, each row with its reason and one action.
- **Live Queue** — real-time emergency priority queue (severity + sub-score),
  assigned emergencies, next-in-line, and one-click emergency registration.
- **Ops Console** — one-click buttons for each edge case (sick leave, overrun,
  breakdown, no-show, clock tick) plus live doctor/room status.
- **Activity** — live event stream, the full **audit log**, and the message log
  with delivery state and a box to record what a patient replied. A message
  held back for consent shows as **`blocked`** in amber, so the desk knows to
  phone instead.

Everything updates **live** over WebSocket — no refresh needed.

---

## Project layout

```
cancer_help/
├── Dockerfile             # multi-stage: Vite build -> FastAPI runtime
├── docker-compose.yml     # one container, volume-persisted datastore
├── .env.example           # all-optional config reference
├── backend/
│   ├── engine/            # PURE scheduling engine (no I/O)
│   │   ├── state.py       #   data model + SystemState
│   │   ├── slots.py       #   interval slot model + buffer rules
│   │   ├── conflict.py    #   hard-constraint validation
│   │   ├── allocator.py   #   score-based chemo room/slot + booking/reschedule
│   │   ├── emergency.py   #   priority queue + sub-score + resolution
│   │   ├── handlers.py    #   the 6 edge-case handlers + advance_clock
│   │   ├── visits.py      #   visit types + learned durations
│   │   ├── waitlist.py    #   waitlist matching + slot backfill
│   │   ├── investigations.py # lab gating, chair release, re-pencil
│   │   ├── arrivals.py    #   arrivals board + running late
│   │   ├── risk.py        #   no-show risk + safety-booking suggestions
│   │   ├── actions.py     #   before/after snapshots + undo
│   │   ├── clinic_control.py # the doctor's own day controls
│   │   ├── sessions.py     #   working week + case-mix rules
│   │   ├── privacy.py     #   consent on outgoing messages
│   │   ├── context.py     #   point-of-care context for a day list
│   │   ├── outcomes.py    #   did any of it help? day vs day
│   │   ├── coordination.py #  who fell through the cracks
│   │   ├── capacity.py    #   committed vs available across days
│   │   ├── patient_view.py #  what a patient may see of their own visit
│   │   ├── ask.py          #  which view a question wants; clinical refusals
│   │   ├── propose.py      #  which action a sentence wants, as a card only
│   │   ├── replies.py      #  reading a patient's reply; a refusal wins
│   │   └── result.py      #   EngineResult / Action / Severity
│   ├── api/               # FastAPI app, schemas
│   ├── services/          # security (JWT), ws, watchdog, metrics, sarvam,
│   │                      #   messaging (log / webhook / WhatsApp Cloud API),
│   │                      #   interop (CSV + FHIR-shaped)
│   ├── storage/           # Excel load/save + seed generator
│   └── data/care.xlsx     # the datastore (generated; in /data under Docker)
├── frontend/              # React + TS + Tailwind (Vite)
│   └── src/lib/i18n.ts    #   patient-facing strings: en / hi / mr, no library
├── docs/PILOT.md          # the 60-90 day pilot plan, and what would stop it
├── docs/eval/             # assistant test sheet and scored results
├── scripts/eval_ask.py    # scores the phrase matcher and Sarvam on a sheet
└── tests/                 # engine unit + API integration tests
```

## Notes & production caveats

- **Log redaction is not done, and it is the one blocker to real use.**
  Consent governs *outgoing messages* only. Patient names still reach the
  application log, so the consent boundary that holds so carefully at send
  time does not hold at write time. Nothing in this repository or in any demo
  uses real patient data, so it costs nothing today — but it has to be closed
  before a single real patient is entered, and
  [`docs/PILOT.md`](docs/PILOT.md) names it as a precondition for day 0
  rather than leaving it to be discovered.
- **Message delivery still happens inside the write lock.** Every state change
  flushes queued patient messages before broadcasting. That call now runs in
  the thread pool, so a slow provider no longer stalls the event loop or the
  watchdog — but it is still made while the mutation lock is held, so with a
  real WhatsApp or SMS driver configured and an unreachable provider, other
  *writes* queue behind it (worst case ~4s per message). With no driver
  configured, which is the default, delivery is a log write and takes no
  measurable time. The right fix is two-phase — claim a batch under the lock,
  send outside it, write results back — and it is not done.
- **PHI / security:** passwords are stored as **bcrypt** hashes (seeded demo
  creds are upgraded transparently on first use). Access is JWT-based with
  revocation, per-IP login rate-limiting, a security **audit log**, and RBAC
  across four roles (admin, nurse, coordinator, doctor) — not a ladder: a
  doctor can do clinical things a nurse cannot, and a coordinator can do
  neither. The WebSocket is authenticated. For production,
  set `CARE_SECRET` explicitly, keep PHI out of logs, and consider an IdP.
- **Clock:** the "wall clock" is the server's current time, which inside Docker
  is the container's — set `TZ` in `docker-compose.yml` (already
  `Asia/Kolkata`) or the department clock runs in UTC and the timeline's
  *now* marker, auto no-show and overrun triggers all fire at the wrong hour.
  For deterministic testing/demo override it via `CARE_NOW` or the
  `clock/advance` endpoint (the latter is gated behind the demo build flag).
- **Packed list columns:** the seed writes `backup_compatible`, `equipment` and
  `required_equipment` semicolon-separated while `to_dict` joins with commas.
  Parsing only on commas turned each into one opaque string, so **cross-specialty
  cover never matched** and a drug could only be given in a room whose equipment
  string was character-for-character identical (Cisplatin was unbookable in
  every room). Both separators are now accepted; `tests/test_packed_lists.py`
  pins it.
- **The patient link is a bearer token.** `/p/<token>` has no session: the
  token is an HMAC of the appointment id under `CARE_SECRET`, so anyone with
  the link can see that one visit. That is the right trade for a page sent by
  SMS, but it means rotating `CARE_SECRET` invalidates every link already
  sent, and a forwarded link is a forwarded appointment.
- **`/api/export/fhir` is FHIR-*shaped*, not FHIR.** Resource shapes and the
  Appointment status value set, no profiles, no terminology binding, and the
  identifier systems are local URNs. The bundle carries a `fhir-shaped` tag
  saying so; please do not let a slide claim otherwise.
- **Consent is a send-time boundary, not a storage one.** `engine/privacy.py`
  governs what leaves the building. Inside it, the activity log and the change
  history still carry patient names — role-gated, but not reduced to
  identifiers. Treat that as outstanding rather than done.
- **Messaging:** with no `CARE_SMS_WEBHOOK` set, messages go to the application
  log and are marked delivered — the demo works without credentials and the
  state transitions are real. Point that variable at a provider or gateway to
  send them for real; nothing leaves the machine until you do.
- **Sarvam is an outside service.** With a key set, typed sentences (Latin-script
  names masked) and voice clips go to Sarvam. See [What Sarvam sees](#what-sarvam-sees).
  The demo uses synthetic data only.
- **WhatsApp and SMS templates are not built.** `WhatsAppDriver` sends free text,
  which WhatsApp only accepts inside a customer-service window. A real rollout needs
  approved templates, and DLT registration for SMS in India.
- **Scale:** single-process by design (Excel store). Horizontal scaling needs
  the datastore swap described above.
