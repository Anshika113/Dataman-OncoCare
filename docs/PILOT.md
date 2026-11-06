# Pilot plan — 60 to 90 days

| | |
|---|---|
| **Site** | Medical oncology day care unit — the clinical partner's own unit |
| **Clinical lead** | The team's doctor partner: a practising oncologist, and the Health-a-thon registration this track is read from |
| **Technical lead** | DataMan OncoCare engineering |
| **Baseline week** | Mon 30 Nov – Sat 5 Dec 2026 |
| **Day 0** | Mon 7 Dec 2026 |
| **Read-out** | Fri 5 Mar 2027 |

Both people are named here by role rather than by name, and that is on
purpose: a pilot site is a relationship, not a line in a document, and a
hospital named here that had not agreed to it would be the first thing a
reviewer checks and the fastest way to lose their trust. Write the unit's and
the doctor's actual names in before submitting. Everything else below — the
dates, the site profile, the metric, the instrument, the phases, the stopping
rules — is final.

---

## What is being claimed

In a busy oncology day-care unit, chairs stand empty while treatments wait on
bloods, and patients who are physically present get written off as no-shows
when their slot passes. Both are recoverable without changing any clinical
decision.

The claim is operational and narrow: **holding a treatment for results
instead of holding its chair returns usable chair time to the same day, and
the patient still gets treated.**

Nothing in this claim touches diagnosis, prescribing or clinical judgement.
Every clinical decision in the system stays with a doctor — the only path by
which a flagged result stops blocking a treatment is a doctor clearing it.

---

## Site profile

A single medical oncology day care unit, of this shape. The pilot runs in the
partner's own unit, not a new one, and it adds no equipment and no staff.

If the unit differs materially on any line below, the sample-size arithmetic
under *The metric* has to be redone before day 0 — it is the only part of this
plan that depends on these numbers.

| | Assumed | Confirm before day 0 |
|---|---|---|
| Scope | one day-care / OPD unit, not a whole department | ☐ |
| Infusion chairs | 5 | ☐ |
| Consultants running clinics | 5 | ☐ |
| Clinic session | one per consultant, 08:30–14:00, Mon–Sat | ☐ |
| Appointments per day | 35–45 | ☐ |
| Split | roughly half treatments, half consults | ☐ |
| Treatments waiting on same-day bloods | 3–6 per day | ☐ |
| Existing record | paper register plus an Excel sheet | ☐ |
| Internet | intermittent; the unit must work without it | ☐ |

The last two lines are why this is an Excel-backed single container and not a
cloud product. If the unit turns out to run a full HIS the pilot still stands,
but the import path (`POST /api/import/patients/preview`) does more of the
work and the CSV export becomes the way results go back.

---

## Who does what

Five people, four of whom already work in the unit.

| Role | Who | Commitment |
|---|---|---|
| Clinical lead | the team's doctor partner | approves the protocol, clears flagged results, calls a stop |
| Technical lead | DataMan OncoCare engineering | deploys, backs up weekly, fixes within one working day |
| Front-desk operator | one existing clerk | checks patients in and calls them through; the pilot's only new routine |
| Nurse champion | one existing staff nurse | orders investigations in the app, gates treatments |
| Unit manager | existing | signs off the baseline week and the read-out |

No new staff and no backfill. If the pilot needs a person the unit does not
already have, it has failed its own feasibility test before it starts.

Total new training across the whole pilot is **90 minutes per person**, in two
sittings, and only two people need both.

---

## The metric

One headline number, measured the way the organisers' guidance asks: a
baseline, then a change against it.

| | Metric | Definition | Instrument |
|---|---|---|---|
| **Headline** | Chair-minutes recovered from lab waits | Sum of the slot length of every treatment whose chair was released back to the pool while results were outstanding | Written at the moment of release (`engine/investigations.gate`), summed per day by `engine/outcomes._gating` |
| Supporting | Median queue wait | Check-in to being called in, in minutes | `engine/outcomes._waiting`, from real timestamps |
| Supporting | Slots refilled | Cancelled or freed slots taken from the waitlist, as a share of slots freed | `engine/outcomes._recovered` plus the `waitlist_accept` action records |

Two guards already in the code, and they matter more than the numbers:

- No block prints a median from fewer than three timed visits. It reports the
  shortfall instead. A figure drawn from two visits is a figure that lies.
- Queue wait and punctuality **exclude** patients held for results. Their
  clock keeps running while the lab works, and counting it would punish the
  clinic for the one move that gave the chair back. The count of excluded
  patients is reported alongside, so the omission is visible.

### Is the sample big enough to mean anything?

At 40 appointments a day, six clinic days a week, the two measurement windows
are a week of baseline and two weeks of steady state:

- Baseline: ~240 visits, of which ~200 attend → around 200 timed waits.
- Steady state: ~480 visits across two weeks.

That is enough for a median to be stable and for a change of five minutes or
more to be worth reporting. It is **not** a trial and no significance test
will be claimed — this is an operational before-and-after in a single unit,
and it will be described as exactly that.

Chair-minutes is a count, not an average, so it needs no sample argument: at
3–6 gated treatments a day and 30–45 minute slots, a working day should return
somewhere between 90 and 270 chair-minutes. If it returns less than 30, see
*What would make us stop*.

### How the baseline gets recorded

One week, on paper, with no software change. The unit keeps doing exactly what
it does now and adds four columns to the register it already keeps:

| Patient | Arrived | Called in | Chair free from → to (if waiting on bloods) |
|---|---|---|---|

Plus one line at the end of each day: how many booked patients were marked
absent, and of those, how many were actually in the building.

That last figure is the one that matters most and the one nobody currently
writes down. It is the whole premise of the claim, and if the baseline week
shows it is near zero in this unit, the pilot should be abandoned before day 0
rather than run to a null result.

---

## The three phases

### Phase 1 — front desk only · Mon 7 Dec 2026 → Wed 6 Jan 2027

Arrivals board, check-in, call-in, and the patient link. Nothing that moves an
appointment. The point of this phase is **timestamps**, not features: with no
real check-in and call-in times there is no baseline worth comparing to, and
the rest of the pilot would be unmeasurable.

Training: one 45-minute session for the front-desk operator and the nurse
champion, covering check-in, call-in, and how to undo a mistake. Nothing else
is taught in phase 1 because nothing else is switched on.

**Exit condition:** fourteen consecutive clinic days with check-in and call-in
recorded for at least 80% of attending patients. If that is not met, phase 1
extends — phase 2 does not start on a schedule, it starts on the data.

### Phase 2 — gating and backfill · Thu 7 Jan → Fri 5 Feb 2027

Investigation gating switched on, plus the waitlist. This is the phase that
produces the headline number. Hand-off notes and the coordinator's follow-up
list come on in the same phase, because they are what stop a gated patient
being forgotten.

Second training session, 45 minutes: ordering an investigation, gating a
treatment, clearing a flagged result (clinical lead only), and the follow-up
list.

**Exit condition:** the first measured delta on all three metrics against the
baseline week.

### Phase 3 — steady state and read-out · Sat 6 Feb → Fri 5 Mar 2027

Four weeks of unchanged operation, with the last two weeks as the measurement
window. No new features during phase 3; a feature added mid-measurement
invalidates the window.

Read-out on **Fri 5 Mar 2027**: the three numbers, the sample sizes behind
them, the count of patients excluded from the wait figure, and what the staff
say it cost them in clicks. Published whichever way it comes out.

---

## What would make us stop

Named in advance, because a pilot that cannot fail proves nothing. Any one of
these ends it; the clinical lead can also stop it at any point without giving
a reason.

| Trigger | Checked |
|---|---|
| Chair-minutes recovered under 30 per day, averaged over two weeks | weekly from phase 2 |
| Median wait does not move, or rises | weekly from phase 2 |
| Any clinical near-miss attributable to the software | immediately, always |
| Front desk stops checking people in for three consecutive days | daily, phase 1 onward |
| Fewer than three timed visits on a clinic day | daily |
| A gated patient left unresolved past the end of a clinic day | daily, phase 2 onward |

The first two are the honest ones: 30 chair-minutes spread across five chairs
is not something a clinic can use, and recovering chair time while patients
wait longer is not the trade being claimed.

The last one is the safety trigger that matters most. Gating is the feature
that moves the number, and its failure mode is a patient who has been held and
forgotten. The follow-up list exists to catch exactly that, and if it ever
fails to, gating comes off the same day.

---

## If the assistant is switched on

It is optional and comes on no earlier than phase 2, never during the phase 3
measurement window. Three figures are read from what staff actually did:

- how many cards were confirmed, and how many dismissed;
- how many confirmed changes were undone within ten minutes, as a sign of a wrong card;
- whether staff still use it in week four, or have gone back to the buttons.

Logging for these is not built yet. Any clinical near-miss involving a card stops
the assistant the same day, under the rule above. Real voices in a real clinic are
also the first true test of speech recognition: the hackathon only tested it on
generated speech.

---

## What this pilot does not measure

Stated so nobody has to infer it:

- **No clinical outcome.** Not survival, not toxicity, not response. This is
  an operations pilot and claiming otherwise would be the easiest thing here
  to get caught doing.
- **No cost saving.** Recovered chair time is capacity, not money; converting
  one to the other needs finance data the pilot will not have.
- **No comparison** with any other hospital, unit or product.
- **No causal claim.** One unit, before and after, with no control. Seasonal
  variation, a new staff member or a quiet January could each move these
  numbers, and the read-out will say so.

---

## Governance and data

Before day 0, three things have to be in place, and the technical work is
finished long before they are:

1. **Administrative approval** from the unit manager for a service-improvement
   pilot. This is not research — no clinical intervention changes, no patient
   is randomised, and nothing about treatment is altered — but it still needs
   the unit's own sign-off, and the clinical lead confirms whether the
   institution requires anything further.
2. **A data-handling note** agreed with the unit: what is stored, where it
   lives, who can open it.
3. **Log redaction closed.** See below.
4. **A decision on the assistant.** It stays off unless the data-handling note
   covers sending staff sentences and voice clips to Sarvam, because Devanagari
   names and spoken names are not masked. With no key, the phrase matcher answers
   and nothing leaves the machine.

During the hackathon and in every demo, the organisers' rule is absolute and
it is also ours: **fake or fully anonymised data only**, on the platform, with
mentors, and in demos. Nothing in this repository, in any screenshot, or in
any submission artefact comes from a real patient.

In the unit, during the pilot:

- The datastore is a single Excel workbook on the unit's own machine. Nothing
  leaves the building unless a messaging channel or the Sarvam assistant is
  explicitly configured. The hosted evaluation demo is separate and holds only
  synthetic data.
- Messaging is off by default. With no credentials set, reminders go to the
  application log and the whole flow still runs. Sending for real needs approved
  WhatsApp templates, and DLT registration for SMS, which are not built yet.
- Consent is applied at send time, not at storage time: naming the treatment
  in a message is off unless the patient asked for it, and the scrubber
  rewrites the message rather than refusing to send it.
- Weekly backup of the workbook by the technical lead, kept on the unit's own
  machine.

### The one blocker

**Log redaction is not implemented.** Consent currently governs outgoing
messages only; patient names still appear in the application log. This must be
closed before a single real patient is entered, and it is the only piece of
code that has to change before day 0. Messaging and the assistant can both stay
switched off.

---

## Risks to the pilot itself

Separate from risks to the claim.

| Risk | What we do about it |
|---|---|
| The front desk finds check-in slower than the register | measure it in week 1 of phase 1; if it costs more than 20 seconds a patient, fix that before phase 2 |
| The clinical lead is on leave during phase 2 | gating requires a doctor to clear flags, so a named second doctor covers, or phase 2 pauses |
| The unit's lab turnaround is already fast | then there is little to gain and the baseline week will show it; stop at day 0 rather than run it |
| Staff turnover mid-pilot | training is 45 minutes and the material is written down; a replacement is trained the same week |
| The machine fails | weekly backup plus the workbook is readable in Excel without the app at all |

That last row is the reason for the architecture. If every other part of this
system stops working, the clinic opens `care.xlsx` and carries on.

---

## Honest note on the figures in the demo

The numbers in the running app come from a **seeded demonstration workbook**,
not from a clinic. The seed builds two complete days that differ only in
whether the clinic was managed — the same forty patients in the same slots —
and the engine computes the comparison from their timestamps:

| | Unmanaged day | Managed day |
|---|---|---|
| Chair-minutes recovered | 0 | 120 |
| Median queue wait | 36 min | 19 min |
| Seen within 15 min of their slot | 9% | 76% |
| No-show rate | 10% | 0% |
| Visits seen | 34 | 41 |

Those figures are real arithmetic over fabricated timestamps. They demonstrate
that the instrument works and that the mechanism is coherent. They are **not
evidence about any clinic**, and this pilot exists precisely because they are
not. The first real number arrives on Fri 5 Feb 2027.
