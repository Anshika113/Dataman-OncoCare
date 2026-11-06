import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../lib/api'
import { statusBadge, typeIcon } from './badges'
import ConfirmDialog from './ConfirmDialog'
import { Icon, Message } from './icons'
import ScopeBar from './ScopeBar'
import DayControls from './DayControls'
import type { Caps } from '../lib/roles'

const START = 8 * 60, END = 18 * 60, PX_PER_MIN = 1.1
// width of the resource (doctor / room) label column at the left of every row
const LABEL_W = 192

function toMin(hhmm: string) { const [h, m] = hhmm.split(':').map(Number); return h * 60 + m }
function toHHMM(mins: number) { return `${String(Math.floor(mins / 60)).padStart(2, '0')}:${String(mins % 60).padStart(2, '0')}` }
// "2026-10-29" -> "Thu, Oct 29" (and a short "Today" label when it's the active day)
function fmtDay(iso: string, activeDay?: string) {
  if (!iso) return ''
  try {
    const d = new Date(iso + 'T00:00:00')
    const s = d.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' })
    return iso === activeDay ? `${s} (active)` : s
  } catch { return iso }
}

export default function Schedule({ state, caps }: { state: any; caps: Caps }) {
  const [mode, setMode] = useState<'doctors' | 'rooms'>('doctors')
  // A doctor lands on their own clinic; admin and nurse are department-wide.
  const [mine, setMine] = useState(!!caps.scopeDoctorId)
  const scopeId = mine ? caps.scopeDoctorId : ''
  const myName = state.doctors.find((d: any) => d.id === caps.scopeDoctorId)?.name || ''
  /** Does this appointment belong to the view the user is scoped to? */
  const inScope = (a: any) => !scopeId || a.doctor_id === scopeId
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)

  const roomById = useMemo(() => Object.fromEntries(state.rooms.map((r: any) => [r.id, r])), [state.rooms])
  const patientById = useMemo(() => Object.fromEntries(state.patients.map((p: any) => [p.id, p])), [state.patients])
  const drugById = useMemo(() => Object.fromEntries(state.drugs.map((g: any) => [g.id, g])), [state.drugs])

  // Day selector for the timeline. Defaults to the active working day (or today
  // if the backend hasn't told us yet); can switch to any day the schedule spans.
  const days = useMemo(() => {
    const set = new Set<string>()
    if (state.active_day) set.add(state.active_day)
    state.appointments.forEach((a: any) => { if (a.date) set.add(a.date) })
    return [...set].sort()
  }, [state.appointments, state.active_day])
  const [day, setDay] = useState<string>(state.active_day || '')
  // keep the selected day valid as state refreshes (e.g. new appointments land)
  const effectiveDay = days.includes(day) ? day : (days[0] || state.active_day || '')
  // alphabetical option lists
  const patientsSorted = useMemo(() => [...state.patients].sort((a: any, b: any) => a.name.localeCompare(b.name)), [state.patients])
  const doctorsSorted = useMemo(() => [...state.doctors].sort((a: any, b: any) => a.name.localeCompare(b.name)), [state.doctors])
  const drugsSorted = useMemo(() => [...state.drugs].sort((a: any, b: any) => a.name.localeCompare(b.name)), [state.drugs])

  const rows = (mode === 'doctors'
    ? state.doctors
        .filter((d: any) => !scopeId || d.id === scopeId)
        .map((d: any) => ({ id: d.id, label: d.name, sub: d.specialty, status: d.status }))
    : state.rooms.map((r: any) => ({ id: r.id, label: r.name, sub: r.type, status: r.status })))
    .sort((a: any, b: any) => a.label.localeCompare(b.label))

  const width = (END - START) * PX_PER_MIN

  // "Now" line: a vertical marker at the current department time so staff can
  // see at a glance which sessions have started / are overdue. Driven by the
  // backend clock (state.now): the browser's own clock can be in a different
  // timezone, which parked the marker hours away from the real department time.
  // Only drawn on the active day — other days have no "now".
  const nowMin = (() => {
    if (effectiveDay && state.active_day && effectiveDay !== state.active_day) return null
    const m = state.now ? toMin(state.now) : NaN
    if (Number.isNaN(m)) return null
    return m >= START && m <= END ? m : null
  })()
  const nowX = nowMin != null ? (nowMin - START) * PX_PER_MIN : null

  // booking form
  const [patient_id, setPatient] = useState(state.patients[0]?.id || '')
  const [doctor_id, setDoctor] = useState(state.doctors[0]?.id || '')
  const [drug_id, setDrug] = useState(state.drugs[0]?.id || '')
  const [preferred, setPreferred] = useState('09:00')
  const [date, setDate] = useState(() => new Date().toISOString().slice(0, 10))
  const [type, setType] = useState<'consult' | 'chemo' | 'walkin'>('consult')
  const [recs, setRecs] = useState<any[]>([])
  const [visitType, setVisitType] = useState('new_case')

  // walk-in intake: a patient at the desk with no appointment
  const [reason, setReason] = useState('')
  const [urgency, setUrgency] = useState<'routine' | 'soon' | 'urgent'>('routine')
  const [walkDoctor, setWalkDoctor] = useState('')   // '' = any available doctor
  const [walk, setWalk] = useState<any | null>(null) // result of the gap search

  // backfill: what a cancellation freed and who could take it
  const [backfill, setBackfill] = useState<any | null>(null)
  const [picked, setPicked] = useState<string[]>([])
  const [wlBusy, setWlBusy] = useState(false)
  const [wlMsg, setWlMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const waitlist: any[] = (state.waitlist || [])
    .filter((w: any) => !scopeId || !w.doctor_id || w.doctor_id === scopeId)

  // investigations: treatments held for results, and the orders behind them
  const gated: any[] = (state.gated || []).filter(inScope)
  const investigations: any[] = state.investigations || []
  const [invBusy, setInvBusy] = useState('')
  const [invMsg, setInvMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const [labKind, setLabKind] = useState('CBC')

  async function runInv(key: string, fn: () => Promise<any>) {
    setInvBusy(key); setInvMsg(null)
    try {
      const r = await fn()
      setInvMsg({ ok: !!r.success, text: r.message })
      // gating frees the chair, so the response carries who could use it
      if (r.success && r.waitlist_matches && selAppt) {
        setBackfill({
          slot: {
            doctor_id: selAppt.doctor_id,
            slot_start: selAppt.slot_start,
            slot_end: selAppt.slot_end,
            date: selAppt.date,
          },
          matches: r.waitlist_matches,
        })
        setPicked(r.waitlist_matches.filter((m: any) => m.reachable).map((m: any) => m.entry_id))
      }
    } catch (e: any) { setInvMsg({ ok: false, text: e.message }) }
    finally { setInvBusy('') }
  }

  // Visit types come from the backend so the catalogue has one home. The
  // learned median is fetched per doctor — it is a suggestion, never applied.
  const visitTypes: any[] = state.visit_types || []
  const [learned, setLearned] = useState<Record<string, any>>({})
  const learnFor = type === 'walkin' ? walkDoctor : doctor_id
  useEffect(() => {
    let live = true
    if (!learnFor) { setLearned({}); return }
    api.visitDurations(learnFor)
      .then((r) => {
        if (!live) return
        const m: Record<string, any> = {}
        for (const v of r.visit_types || []) if (v.learned) m[v.key] = v.learned
        setLearned(m)
      })
      .catch(() => { if (live) setLearned({}) })
    return () => { live = false }
  }, [learnFor])

  // minutes this booking will occupy: a doctor-specific learned length the
  // user accepted, else the visit type's planned length
  const [durationOverride, setDurationOverride] = useState<number | null>(null)
  const plannedMin = visitTypes.find((v) => v.key === visitType)?.default_min ?? 30
  const consultMin = durationOverride ?? plannedMin
  const learnedHere = learned[visitType]
  // a new visit type (or doctor) invalidates an accepted override
  useEffect(() => { setDurationOverride(null) }, [visitType, learnFor])

  // selected appointment (for the action panel: cancel / reschedule / complete / check-in)
  const [selAppt, setSelAppt] = useState<any | null>(null)
  const [actBusy, setActBusy] = useState('')
  const [actMsg, setActMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const [confirmCancel, setConfirmCancel] = useState(false)
  const canManage = caps.canBook // nurse/admin can manage appointments
  // A doctor cannot book, but may rearrange the patients already on their own
  // list: extend, swap, hand over. The backend enforces the same boundary.
  const canControl = (a: any) =>
    caps.canBook || (!!caps.scopeDoctorId && a?.doctor_id === caps.scopeDoctorId)
  const [handTo, setHandTo] = useState('')
  const [handNote, setHandNote] = useState('')
  const [swapWith, setSwapWith] = useState('')

  // Live preview: highlight the selected doctor's row at the chosen time so the
  // user sees on the timeline whether the slot is free (green) or clashing (red).
  const previewDoctorId = doctor_id
  const previewStart = preferred ? toMin(preferred) : NaN
  const previewEnd = previewStart + 30
  const previewConflict = useMemo(() => {
    if (!previewDoctorId || !preferred || Number.isNaN(previewStart)) return false
    return state.appointments.some((a: any) =>
      a.date === effectiveDay &&
      a.doctor_id === previewDoctorId &&
      ['booked', 'active', 'overrun', 'rescheduled'].includes(a.status) &&
      toMin(a.slot_start) < previewEnd && toMin(a.slot_end) > previewStart)
  }, [state.appointments, effectiveDay, previewDoctorId, preferred, previewEnd, previewStart])

  // Hover probe: as the mouse moves across the grid, show a vertical cursor at
  // the exact time and list which doctors are scheduled (or free) at that moment.
  const gridRef = useRef<HTMLDivElement>(null)
  const [hoverX, setHoverX] = useState<number | null>(null) // px from grid left
  const [pinnedX, setPinnedX] = useState<number | null>(null) // clicked / pinned
  const probeX = pinnedX ?? hoverX
  const probeMin = probeX != null ? Math.round((START + probeX / PX_PER_MIN) / 15) * 15 : null

  // One tile per resource, always built (even with nothing probed) so the
  // readout below the timeline keeps a constant height. It used to mount only
  // on hover, which toggled the page scrollbar and shifted the whole table
  // sideways every time the mouse entered or left the grid.
  // count === null -> nothing probed yet, render the muted placeholder.
  const probeTiles = useMemo(() => {
    const source: any[] = mode === 'doctors'
      ? state.doctors.filter((d: any) => !scopeId || d.id === scopeId)
      : state.rooms
    return [...source]
      .sort((a: any, b: any) => a.name.localeCompare(b.name))
      .map((r: any) => ({
        id: r.id,
        name: r.name,
        count: probeMin == null ? null : state.appointments.filter((a: any) =>
          a.date === effectiveDay &&
          (!scopeId || a.doctor_id === scopeId) &&
          (mode === 'doctors' ? a.doctor_id === r.id : a.room_id === r.id) &&
          ['booked', 'active', 'overrun', 'rescheduled'].includes(a.status) &&
          toMin(a.slot_start) <= probeMin && toMin(a.slot_end) > probeMin).length,
      }))
  }, [mode, state.doctors, state.rooms, state.appointments, effectiveDay, probeMin, scopeId])

  // Mouse x -> timeline px, snapped to the 15-minute grid. Returns null outside
  // the timeline (e.g. over the label column, which the grid also spans — not
  // subtracting it used to draw the probe a whole label-width right of the
  // cursor). Snapping also means a mouse sweep only sets state when the probe
  // really moves, instead of re-rendering every row on every pixel.
  function probeAt(clientX: number) {
    const el = gridRef.current
    if (!el) return null
    const x = clientX - el.getBoundingClientRect().left - LABEL_W
    if (x < 0 || x > width) return null
    const min = Math.round((START + x / PX_PER_MIN) / 15) * 15
    return (min - START) * PX_PER_MIN
  }
  function handleGridMove(e: React.MouseEvent) {
    if (pinnedX != null) return
    setHoverX(probeAt(e.clientX))
  }
  function handleGridLeave() { if (pinnedX == null) setHoverX(null) }
  function handleGridClick(e: React.MouseEvent) {
    const x = probeAt(e.clientX)
    if (x == null) return // clicks on the label column neither pin nor unpin
    setPinnedX((prev) => (prev === x ? null : x))
  }

  async function book() {
    if (!preferred) { setMsg({ ok: false, text: 'Pick a preferred start time first' }); return }
    setBusy(true); setMsg(null); setRecs([])
    try {
      const r = await api.bookWithRecs({
        patient_id, doctor_id,
        appt_type: type,
        drug_id: type === 'chemo' ? drug_id : null,
        preferred_start: preferred,
        slot_start: preferred,
        slot_end: type === 'chemo' ? toHHMM(toMin(preferred) + 30) : null,
        visit_type: type === 'consult' ? visitType : null,
        duration_min: type === 'consult' ? consultMin : null,
        date,
      })
      if (r.success) {
        setMsg({ ok: true, text: `${r.message}${date ? ` on ${date}` : ''}` })
        setPreferred('')
      } else {
        setMsg({ ok: false, text: r.message })
        setRecs(r.recommended || [])
      }
    } catch (e: any) { setMsg({ ok: false, text: e.message }) }
    finally { setBusy(false) }
  }

  // Walk-in: ask where this patient could go today. Reads only — the engine
  // searches gaps that already exist and moves nobody.
  async function findWalkIn() {
    setBusy(true); setMsg(null); setWalk(null); setRecs([])
    try {
      const r = await api.walkInOptions({
        doctor_id: walkDoctor || null,
        visit_type: visitType,
        duration_min: consultMin,
        urgency,
        limit: 3,
      })
      setWalk(r)
      if (!r.options?.length) {
        setMsg({
          ok: false,
          text: r.at_cap?.length
            ? `Nothing free before ${r.searched_until} — at daily cap: ${r.at_cap.join(', ')}`
            : `No gap before ${r.searched_until}. Widen the urgency or book the next working day.`,
        })
      }
    } catch (e: any) { setMsg({ ok: false, text: e.message }) }
    finally { setBusy(false) }
  }

  async function holdWalkIn(opt: any) {
    setBusy(true); setMsg(null)
    try {
      const r = await api.bookWalkIn({
        patient_id,
        doctor_id: opt.doctor_id,
        slot_start: opt.slot_start,
        slot_end: opt.slot_end,
        visit_type: visitType,
        reason,
        urgency,
      })
      setMsg({ ok: !!r.success, text: r.message })
      if (r.success) { setWalk(null); setReason('') }
    } catch (e: any) { setMsg({ ok: false, text: e.message }) }
    finally { setBusy(false) }
  }

  async function bookRec(rec: any) {
    setBusy(true); setMsg(null)
    try {
      const r = await api.bookWithRecs({
        patient_id, doctor_id,
        appt_type: type,
        drug_id: type === 'chemo' ? drug_id : null,
        preferred_start: rec.slot_start,
        slot_start: rec.slot_start,
        slot_end: rec.slot_end,
        visit_type: type === 'consult' ? visitType : null,
        date,
      })
      setMsg({ ok: !!r.success, text: `${r.message}${date ? ` on ${date}` : ''}` })
      if (r.success) { setRecs([]); setPreferred('') }
    } catch (e: any) { setMsg({ ok: false, text: e.message }) }
    finally { setBusy(false) }
  }

  // appointment management actions (cancel / reschedule / complete / check-in)
  function closeAppt() { setSelAppt(null); setActMsg(null); setConfirmCancel(false) }
  async function act(kind: string, fn: () => Promise<any>) {
    setActBusy(kind); setActMsg(null)
    try {
      const r = await fn()
      setActMsg({ ok: !!r.success, text: r.message })
      if (r.success) {
        // a cancellation hands back the slot it freed and who could take it
        if (r.freed_slot) {
          setBackfill({ slot: r.freed_slot, matches: r.waitlist_matches || [] })
          setPicked((r.waitlist_matches || [])
            .filter((m: any) => m.reachable)
            .map((m: any) => m.entry_id))
          setWlMsg(null)
        }
        closeAppt()
      }
    } catch (e: any) { setActMsg({ ok: false, text: e.message }) }
    finally { setActBusy('') }
  }

  // Offer the freed slot to everyone picked. First accept wins; the engine
  // tells the rest it is gone.
  async function offerSlot() {
    if (!backfill || picked.length === 0) return
    setWlBusy(true); setWlMsg(null)
    try {
      const r = await api.offerWaitlist({
        entry_ids: picked,
        doctor_id: backfill.slot.doctor_id,
        slot_start: backfill.slot.slot_start,
        slot_end: backfill.slot.slot_end,
      })
      setWlMsg({ ok: !!r.success, text: r.message })
    } catch (e: any) { setWlMsg({ ok: false, text: e.message }) }
    finally { setWlBusy(false) }
  }

  async function acceptSlot(entryId: string) {
    if (!backfill) return
    setWlBusy(true); setWlMsg(null)
    try {
      const r = await api.acceptWaitlist(entryId, {
        doctor_id: backfill.slot.doctor_id,
        slot_start: backfill.slot.slot_start,
        slot_end: backfill.slot.slot_end,
      })
      setWlMsg({ ok: !!r.success, text: r.message })
      if (r.success) setBackfill(null)
    } catch (e: any) { setWlMsg({ ok: false, text: e.message }) }
    finally { setWlBusy(false) }
  }

  async function dropFromWaitlist(id: string) {
    setWlBusy(true)
    try { await api.removeWaitlist(id) }
    catch (e: any) { setWlMsg({ ok: false, text: e.message }) }
    finally { setWlBusy(false) }
  }

  async function addToWaitlist() {
    setWlBusy(true); setWlMsg(null)
    try {
      const r = await api.addWaitlist({
        patient_id, doctor_id: type === 'walkin' ? walkDoctor : doctor_id,
        visit_type: visitType, reason: reason || 'wants an earlier slot',
      })
      setWlMsg({ ok: !!r.success, text: r.message })
    } catch (e: any) { setWlMsg({ ok: false, text: e.message }) }
    finally { setWlBusy(false) }
  }

  return (
    <div className="space-y-4">
      {caps.scopeDoctorId && (
        <DayControls state={state} doctorId={caps.scopeDoctorId} />
      )}

      {/* booking */}
      {caps.canBook ? (
      <div className="card p-5">
        <h3 className="font-bold text-ink-900 mb-3">New booking</h3>
        <div className="flex flex-wrap items-end gap-3">
          <div>
            <label className="label">New booking</label>
            <select className="input" value={type} onChange={(e) => setType(e.target.value as any)}>
              <option value="consult">Consult</option>
              <option value="chemo">Chemo</option>
              <option value="walkin">Walk-in</option>
            </select>
          </div>
          {type !== 'chemo' && visitTypes.length > 0 && (
            <div>
              <label className="label">Visit type</label>
              <select className="input" value={visitType} onChange={(e) => setVisitType(e.target.value)}
                title="Decides how long the slot is">
                {visitTypes.map((v: any) => (
                  <option key={v.key} value={v.key}>{v.label} — {v.default_min} min</option>
                ))}
              </select>
            </div>
          )}
          <div>
            <label className="label">Patient</label>
            <select className="input" value={patient_id} onChange={(e) => setPatient(e.target.value)}>
              {patientsSorted.map((p: any) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </div>
          {type !== 'walkin' ? (
          <div>
            <label className="label">Doctor</label>
            <select className="input" value={doctor_id} onChange={(e) => setDoctor(e.target.value)}>
              {doctorsSorted.map((d: any) => {
                const fullyOff = d.status === 'on_leave' || d.status === 'unavailable'
                const suffix = d.status === 'available' ? ''
                  : d.status === 'partially_unavailable' ? ' (partial leave)'
                  : ' (unavailable)'
                return <option key={d.id} value={d.id} disabled={fullyOff}>{d.name}{suffix}</option>
              })}
            </select>
          </div>
          ) : (
            <>
              <div>
                <label className="label">Doctor</label>
                <select className="input" value={walkDoctor} onChange={(e) => setWalkDoctor(e.target.value)}>
                  <option value="">Any available</option>
                  {doctorsSorted.map((d: any) => {
                    const fullyOff = d.status === 'on_leave' || d.status === 'unavailable'
                    return <option key={d.id} value={d.id} disabled={fullyOff}>{d.name}</option>
                  })}
                </select>
              </div>
              <div className="grow min-w-[200px]">
                <label className="label">Reason</label>
                <input type="text" className="input w-full" value={reason} placeholder="why they came in"
                  onChange={(e) => setReason(e.target.value)} />
              </div>
              <div>
                <label className="label">Urgency</label>
                <select className="input" value={urgency} onChange={(e) => setUrgency(e.target.value as any)}>
                  <option value="routine">Routine — any time today</option>
                  <option value="soon">Soon — within 3 hours</option>
                  <option value="urgent">Urgent — within the hour</option>
                </select>
              </div>
            </>
          )}
          {type === 'chemo' && (
            <div>
              <label className="label">Drug</label>
              <select className="input" value={drug_id} onChange={(e) => setDrug(e.target.value)}>
                {drugsSorted.map((g: any) => <option key={g.id} value={g.id}>{g.name} ({g.tw_start}–{g.tw_end})</option>)}
              </select>
            </div>
          )}
          {type !== 'walkin' && (
            <>
              <div>
                <label className="label">Date</label>
                <input type="date" className="input" value={date} onChange={(e) => setDate(e.target.value)} />
              </div>
              <div>
                <label className="label">Preferred start</label>
                <input type="time" className="input" value={preferred} onChange={(e) => setPreferred(e.target.value)} />
              </div>
            </>
          )}
          {type === 'walkin' ? (
            <button className="btn-primary" onClick={findWalkIn} disabled={busy}>
              {busy ? 'Searching…' : 'Find a slot today'}
            </button>
          ) : (
            <button className="btn-primary" onClick={book} disabled={busy}>{busy ? 'Booking…' : 'Book'}</button>
          )}
        </div>
        {type !== 'chemo' && (
          <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
            <span className="badge bg-ink-100 text-ink-700">
              {type === 'walkin'
                ? `Needs ${consultMin} min`
                : `Books ${consultMin} min — ${preferred || '--:--'}${preferred ? `–${toHHMM(toMin(preferred) + consultMin)}` : ''}`}
            </span>
            {learnedHere ? (
              learnedHere.differs ? (
                <span className="inline-flex items-center gap-2 rounded-full border border-brand-200 bg-brand-50 px-3 py-1 text-brand-800">
                  <Icon name="info" className="w-3.5 h-3.5 shrink-0" />
                  These actually run a median of <b>{learnedHere.median_min} min</b> for this doctor
                  <span className="text-brand-600/70">({learnedHere.samples} visits)</span>
                  {durationOverride === learnedHere.suggested_min ? (
                    <span className="font-bold text-emerald-700">using {learnedHere.suggested_min} min</span>
                  ) : (
                    <button type="button" className="font-bold underline"
                      onClick={() => setDurationOverride(learnedHere.suggested_min)}>
                      use {learnedHere.suggested_min} min
                    </button>
                  )}
                  {durationOverride != null && (
                    <button type="button" className="underline text-ink-500"
                      onClick={() => setDurationOverride(null)}>keep {plannedMin}</button>
                  )}
                </span>
              ) : (
                <span className="text-ink-400">Matches how long they really run ({learnedHere.samples} visits timed)</span>
              )
            ) : (
              <span className="text-ink-400">No learned length yet — needs a few completed visits</span>
            )}
          </div>
        )}
        {msg && <div className="mt-3 text-sm bg-ink-50 rounded-lg px-3 py-2"><Message ok={msg.ok} text={msg.text} /></div>}

        {type === 'walkin' && walk?.options?.length > 0 && (
          <div className="mt-4 rounded-xl border border-brand-200 bg-brand-50 p-4">
            <div className="flex items-center gap-2 mb-1">
              <Icon name="info" className="w-5 h-5 text-brand-600 shrink-0" />
              <div>
                <div className="text-sm font-bold text-brand-800">Best fit today</div>
                <div className="text-xs text-brand-700/80">
                  Real gaps in the remaining day — no booked patient moves. Searched to {walk.searched_until}.
                </div>
              </div>
            </div>
            <div className="mt-3 space-y-2">
              {walk.options.map((o: any) => (
                <div key={`${o.doctor_id}-${o.slot_start}`}
                  className="rounded-xl border border-brand-200 bg-white px-3.5 py-3 flex items-center gap-3 flex-wrap">
                  <span className="text-lg font-extrabold text-ink-900">{o.slot_start}</span>
                  <span className="text-xs text-ink-400">–{o.slot_end}</span>
                  <span className="text-sm font-semibold text-ink-800">{o.doctor_name}</span>
                  <span className="badge bg-emerald-100 text-emerald-700">
                    fits a {o.gap_min} min gap
                  </span>
                  <span className="text-xs text-ink-500">
                    {o.minutes_away === 0 ? 'now' : `in ${o.minutes_away} min`}
                    {o.after ? ` · after ${o.after}` : ''} · cap {o.cap_used}/{o.cap_total}
                  </span>
                  <button className="btn-primary ml-auto !py-1.5" disabled={busy}
                    onClick={() => holdWalkIn(o)}>
                    {busy ? '…' : 'Hold this slot'}
                  </button>
                </div>
              ))}
            </div>
            {walk.at_cap?.length > 0 && (
              <div className="mt-2 text-xs text-amber-700">
                At daily cap, not offered: {walk.at_cap.join(', ')}
              </div>
            )}
          </div>
        )}

        {recs.length > 0 && (
          <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-4">
            <div className="flex items-center gap-2 mb-3">
              <Icon name="info" className="w-5 h-5 text-amber-600 shrink-0" />
              <div>
                <div className="text-sm font-bold text-amber-800">
                  Preferred slot unavailable — here are the next available times
                </div>
                <div className="text-xs text-amber-700/80">
                  Closest free slots for {state.doctors.find((d: any) => d.id === doctor_id)?.name}. Pick one to book instantly.
                </div>
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              {recs.map((rec: any, i) => (
                <button key={i} onClick={() => bookRec(rec)} disabled={busy}
                  className="group rounded-xl border border-amber-300 bg-white px-3.5 py-2.5 text-left hover:border-brand-400 hover:shadow-sm transition">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-extrabold text-ink-900 group-hover:text-brand-700">{rec.slot_start}</span>
                    <span className="text-xs text-ink-400">– {rec.slot_end}</span>
                  </div>
                  <div className="text-[11px] text-ink-500 mt-0.5">
                    {rec.room_name ? `Room ${rec.room_name}` : 'Consult'} · {rec.delta_min} min away
                  </div>
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
      ) : (
        <div className="card p-4 flex items-center gap-3 text-sm text-ink-500">
          <Icon name="lock" className="w-5 h-5 text-ink-400 shrink-0" />
          Booking is available to nurses and admins. Your role is read-only for scheduling.
        </div>
      )}

      {/* treatments held for results */}
      {gated.length > 0 && (
        <div className="card p-5 border-amber-200">
          <div className="flex items-center gap-2 mb-1">
            <Icon name="clock" className="w-5 h-5 text-amber-600 shrink-0" />
            <h3 className="font-bold text-ink-900">
              Held for results
              <span className="badge bg-amber-100 text-amber-700 ml-2">{gated.length}</span>
            </h3>
          </div>
          <div className="text-xs text-ink-500 mb-3">
            These patients are here. Their chair went back to the pool, and they will not be marked no-show.
          </div>
          <div className="space-y-2">
            {gated.map((g: any) => {
              const rd = g.readiness
              const blocked = rd.status === 'blocked'
              return (
                <div key={g.appointment_id}
                  className={`rounded-xl border px-3.5 py-3 ${blocked ? 'border-rose-200 bg-rose-50/60' : 'border-amber-200 bg-amber-50/60'}`}>
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-sm font-bold text-ink-900">{g.patient_name}</span>
                    <span className="text-xs text-ink-500">
                      was {g.slot_start}–{g.slot_end} · {state.doctors.find((d: any) => d.id === g.doctor_id)?.name}
                    </span>
                    <span className={`badge ${blocked ? 'bg-rose-100 text-rose-700' : 'bg-amber-100 text-amber-700'}`}>
                      {blocked ? 'needs your call' : `waiting${rd.eta ? ` · ETA ${rd.eta}` : ''}`}
                    </span>
                    {g.held_room_id && (
                      <span className="badge bg-emerald-100 text-emerald-700">
                        {roomById[g.held_room_id]?.name || g.held_room_id} released
                      </span>
                    )}
                  </div>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {rd.all.map((i: any) => (
                      <span key={i.id}
                        className={`text-[11px] rounded-lg px-2 py-1 border ${
                          i.status === 'flagged' ? 'bg-rose-50 border-rose-200 text-rose-700'
                            : i.status === 'resulted' ? 'bg-emerald-50 border-emerald-200 text-emerald-700'
                            : 'bg-white border-ink-200 text-ink-600'}`}>
                        <b>{i.kind}</b>{i.value ? ` ${i.value}` : ''} · {i.status}
                        {i.status === 'pending' && i.eta ? ` (ETA ${i.eta})` : ''}
                        {i.status === 'pending' && (
                          <ResultEntry kind={i.kind} busy={invBusy !== ''}
                            onSave={(b) => runInv('res' + i.id, () => api.resultInvestigation(i.id, b))} />
                        )}
                        {i.status === 'flagged' && caps.canClearFlag && (
                          <button className="ml-1.5 underline font-bold" disabled={invBusy !== ''}
                            onClick={() => runInv('clear' + i.id, () => api.clearInvestigation(i.id))}>
                            accept and proceed
                          </button>
                        )}
                      </span>
                    ))}
                  </div>
                  {caps.canBook && (
                    <div className="mt-2.5 flex gap-2 flex-wrap">
                      <button className="btn-primary !py-1.5" disabled={invBusy !== '' || !rd.ready}
                        title={rd.ready ? 'Find the next slot and chair' : 'Blocked until the result is in or accepted'}
                        onClick={() => runInv('rp' + g.appointment_id, () => api.repencilAppointment(g.appointment_id))}>
                        {invBusy === 'rp' + g.appointment_id ? '…' : 'Proceed — find a slot'}
                      </button>
                      <button className="btn-danger !py-1.5" disabled={invBusy !== ''}
                        onClick={() => runInv('df' + g.appointment_id,
                          () => api.cancelAppointment(g.appointment_id, 'cycle deferred on results'))}>
                        Defer cycle
                      </button>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
          {invMsg && <div className="mt-3 text-sm bg-ink-50 rounded-lg px-3 py-2"><Message ok={invMsg.ok} text={invMsg.text} /></div>}
        </div>
      )}

      {/* backfill: a cancellation just freed a slot */}
      {backfill && (
        <div className="card p-5 border-violet-200">
          <div className="flex items-center justify-between gap-3 flex-wrap mb-1">
            <div className="flex items-center gap-2">
              <Icon name="calendar" className="w-5 h-5 text-violet-600 shrink-0" />
              <h3 className="font-bold text-ink-900">
                {backfill.slot.slot_start} released
                <span className="ml-2 text-sm font-medium text-ink-500">
                  {state.doctors.find((d: any) => d.id === backfill.slot.doctor_id)?.name} ·{' '}
                  {toMin(backfill.slot.slot_end) - toMin(backfill.slot.slot_start)} min
                </span>
              </h3>
            </div>
            <button className="btn-ghost !py-1.5" onClick={() => setBackfill(null)}>Leave it empty</button>
          </div>

          {backfill.matches.length === 0 ? (
            <div className="text-sm text-ink-500 mt-2">
              Nobody on the waitlist can take this slot. Add a patient below and it will be matched next time.
            </div>
          ) : (
            <>
              <div className="text-xs text-ink-500 mb-3">
                {backfill.matches.length} waitlist match{backfill.matches.length > 1 ? 'es' : ''} — ranked by who can actually get here.
              </div>
              <div className="space-y-2">
                {backfill.matches.map((m: any, i: number) => (
                  <div key={m.entry_id}
                    className={`rounded-xl border px-3.5 py-3 flex items-center gap-3 flex-wrap ${m.reachable ? 'border-ink-200 bg-white' : 'border-ink-100 bg-ink-50'}`}>
                    <input type="checkbox" className="w-4 h-4 shrink-0" checked={picked.includes(m.entry_id)}
                      id={`wl-${m.entry_id}`}
                      onChange={(e) => setPicked((prev) => e.target.checked
                        ? [...prev, m.entry_id]
                        : prev.filter((x) => x !== m.entry_id))} />
                    <label htmlFor={`wl-${m.entry_id}`} className="flex items-center gap-2 cursor-pointer">
                      <span className="badge bg-violet-100 text-violet-700">{i + 1}</span>
                      <span className="text-sm font-bold text-ink-900">{m.patient_name}</span>
                    </label>
                    <span className="text-xs text-ink-500">{m.why.join(' · ')}</span>
                    <span className={`badge ml-auto ${m.in_building ? 'bg-emerald-100 text-emerald-700' : m.reachable ? 'bg-amber-100 text-amber-700' : 'bg-ink-100 text-ink-500'}`}>
                      {m.in_building ? 'here now' : m.reachable ? `~${m.eta_min} min` : 'unlikely'}
                    </span>
                    <button className="btn-ghost !py-1.5" disabled={wlBusy}
                      onClick={() => acceptSlot(m.entry_id)}>Book this one</button>
                  </div>
                ))}
              </div>
              <div className="mt-3 flex items-center gap-2 flex-wrap">
                <button className="btn-primary" disabled={wlBusy || picked.length === 0} onClick={offerSlot}>
                  {wlBusy ? '…' : `Offer to ${picked.length} — first accept wins`}
                </button>
                <span className="text-xs text-ink-400">Offering only messages them; nobody is booked until one accepts.</span>
              </div>
            </>
          )}
          {wlMsg && <div className="mt-3 text-sm bg-ink-50 rounded-lg px-3 py-2"><Message ok={wlMsg.ok} text={wlMsg.text} /></div>}
        </div>
      )}

      {/* waitlist */}
      {(waitlist.length > 0 || caps.canBook) && (
        <div className="card p-5">
          <div className="flex items-center justify-between gap-3 flex-wrap mb-3">
            <h3 className="font-bold text-ink-900">
              Waitlist
              {waitlist.length > 0 && <span className="badge bg-violet-100 text-violet-700 ml-2">{waitlist.length}</span>}
            </h3>
            {caps.canBook && (
              <button className="btn-ghost !py-1.5" disabled={wlBusy} onClick={addToWaitlist}
                title="Adds the patient currently selected in the booking form">
                Add selected patient
              </button>
            )}
          </div>
          {waitlist.length === 0 ? (
            <div className="text-sm text-ink-400">
              Empty. Patients here are offered any slot that frees up, before it becomes dead time.
            </div>
          ) : (
            <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-2">
              {waitlist.map((w: any) => (
                <div key={w.id} className="rounded-xl border border-ink-200 px-3 py-2.5 flex items-start gap-2">
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-bold text-ink-900 truncate">{w.patient_name}</div>
                    <div className="text-xs text-ink-500 truncate">
                      {w.doctor_name}{w.reason ? ` · ${w.reason}` : ''}
                    </div>
                    <div className="text-[11px] text-ink-400 mt-0.5">
                      {w.in_building ? 'in the building' : `~${w.travel_min} min away`}
                      {w.status === 'offered' ? ' · offered' : ''}
                    </div>
                  </div>
                  {caps.canBook && (
                    <button className="btn-ghost !px-2 !py-1 text-xs" disabled={wlBusy}
                      onClick={() => dropFromWaitlist(w.id)} title="Remove from waitlist">Remove</button>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* timeline */}
      <div className="card p-5">
        <div className="flex items-center justify-between mb-4 gap-3 flex-wrap">
          {/* the inner group needs to wrap too, or on a phone the scope
              toggle is clipped and the day selector runs off the card */}
          <div className="flex items-center gap-3 flex-wrap min-w-0">
            <h3 className="font-bold text-ink-900">Schedule — {mode === 'doctors' ? 'by Doctor' : 'by Room'}</h3>
            {caps.scopeDoctorId && caps.canViewDepartment && (
              <ScopeBar mine={mine} setMine={setMine} doctorName={myName} />
            )}
            {/* day selector: switch which working day the timeline shows */}
            {days.length > 0 && (
              <div className="relative">
                <Icon name="calendar" className="w-4 h-4 text-ink-400 absolute left-2.5 top-1/2 -translate-y-1/2 pointer-events-none" />
                <select className="input !pl-8 !py-1.5 text-sm font-semibold" value={effectiveDay}
                  onChange={(e) => setDay(e.target.value)} title="Show this day's schedule">
                  {days.map((d) => <option key={d} value={d}>{fmtDay(d, state.active_day)}</option>)}
                </select>
              </div>
            )}
          </div>
          <div className="flex rounded-xl border border-ink-200 overflow-hidden">
            {(['doctors', 'rooms'] as const).map((m) => (
              <button key={m} onClick={() => setMode(m)}
                className={`px-3.5 py-1.5 text-sm font-semibold transition ${mode === m ? 'bg-brand-600 text-white' : 'bg-white text-ink-500 hover:text-ink-800'}`}>
                {m === 'doctors' ? 'Doctors' : 'Rooms'}
              </button>
            ))}
          </div>
        </div>

        <div className="overflow-x-auto">
          <div className="min-w-[900px]">
            {/* time axis */}
            <div className="flex border-b border-slate-200 mb-1">
              <div className="w-48 shrink-0" />
              <div className="relative h-6" style={{ width }}>
                {Array.from({ length: (END - START) / 60 + 1 }).map((_, i) => (
                  <span key={i} className="absolute text-[11px] text-slate-400 -translate-x-1/2"
                    style={{ left: (i * 60 * PX_PER_MIN) }}>{toHHMM(START + i * 60)}</span>
                ))}
              </div>
            </div>

            {/* rows + hover probe overlay share one positioned container */}
            <div ref={gridRef}
              onMouseMove={handleGridMove} onMouseLeave={handleGridLeave} onClick={handleGridClick}
              className="relative">
              {rows.map((row: any) => (
                <div key={row.id} className="flex items-center border-b border-slate-100">
                  <div className="w-48 shrink-0 pr-3">
                    <div className="text-sm font-medium flex items-center gap-2">
                      {row.label} {statusBadge(row.status)}
                    </div>
                    <div className="text-xs text-slate-400 capitalize">{row.sub}</div>
                  </div>
                  <div className="relative h-12 rounded" style={{ width, background: 'repeating-linear-gradient(90deg,#f8fafc 0,#f8fafc 1px,transparent 1px,transparent 60px)' }}>
                    {/* clash warning on the selected doctor's row — only shown when
                        the chosen time overlaps an existing booking (no "free" tick) */}
                    {mode === 'doctors' && row.id === previewDoctorId && preferred && previewConflict && (
                      <div className="pointer-events-none absolute top-0 bottom-0 z-10 border-x-2 border-rose-500 bg-rose-400/25"
                        style={{ left: (previewStart - START) * PX_PER_MIN, width: 30 * PX_PER_MIN }}>
                        <span className="absolute -top-0.5 left-1/2 -translate-x-1/2 -translate-y-full text-[10px] font-bold whitespace-nowrap px-1.5 py-0.5 rounded-full shadow-sm bg-rose-500 text-white inline-flex items-center gap-1">
                          <Icon name="alertTriangle" className="w-3 h-3" /> clash
                        </span>
                      </div>
                    )}
                    {state.appointments
                      .filter((a: any) => a.date === effectiveDay)
                      .filter(inScope)
                      .filter((a: any) => mode === 'doctors' ? a.doctor_id === row.id : a.room_id === row.id)
                      .filter((a: any) => ['booked', 'active', 'overrun', 'rescheduled'].includes(a.status))
                      .map((a: any) => {
                        const left = (toMin(a.slot_start) - START) * PX_PER_MIN
                        const w = Math.max(24, (toMin(a.slot_end) - toMin(a.slot_start)) * PX_PER_MIN)
                        const tone = a.status === 'overrun' ? 'bg-amber-300 border-amber-500'
                          : a.status === 'active' ? 'bg-emerald-300 border-emerald-500'
                          : a.status === 'rescheduled' ? 'bg-violet-300 border-violet-500'
                          : 'bg-brand-300 border-brand-500'
                        return (
                          <div key={a.id}
                            onClick={(e) => { e.stopPropagation(); setSelAppt(a); setActMsg(null) }}
                            title={`${patientById[a.patient_id]?.name || a.patient_id}\n${fmtDay(a.date)}\n${a.slot_start}–${a.slot_end}\n${roomById[a.room_id]?.name || 'no room'}${a.drug_id ? ' · ' + (drugById[a.drug_id]?.name || '') : ''}\n${a.status}\n— click to manage`}
                            className={`absolute top-1 bottom-1 rounded-md border-2 px-1.5 py-0.5 text-[11px] font-medium text-slate-800 overflow-hidden cursor-pointer hover:brightness-95 hover:z-20 ${tone}`}
                            style={{ left, width: w }}>
                            <div className="truncate">{typeIcon(a.type)} {patientById[a.patient_id]?.name.split(' ')[0] || '?'}</div>
                            <div className="truncate text-[10px] opacity-80">{a.slot_start}</div>
                          </div>
                        )
                      })}
                  </div>
                </div>
              ))}

              {/* "now" line: current department time */}
              {nowX != null && (
                <div className="pointer-events-none absolute top-0 bottom-0 z-10 w-0.5 bg-rose-500"
                  style={{ left: LABEL_W + nowX }}>
                  <span className="absolute top-0 -translate-x-1/2 text-[10px] font-bold px-1.5 py-0.5 rounded-b-md text-white shadow-sm bg-rose-500">
                    now
                  </span>
                </div>
              )}

              {/* vertical probe cursor (offset by the 12rem label column) */}
              {probeX != null && (
                <div className="pointer-events-none absolute top-0 bottom-0 z-20 w-px bg-brand-500"
                  style={{ left: LABEL_W + probeX }}>
                  <span className={`absolute -top-2 -translate-x-1/2 text-[10px] font-bold px-1.5 py-0.5 rounded-full text-white shadow-sm ${pinnedX != null ? 'bg-brand-700' : 'bg-brand-500'}`}>
                    {probeMin != null ? toHHMM(probeMin) : ''}
                  </span>
                </div>
              )}
            </div>

            {/* hover/click probe readout - always mounted so hovering the grid
                cannot change the page height (that toggled the scrollbar and
                made the whole table jump sideways). */}
            <div className={`mt-3 rounded-xl border p-3 text-sm ${probeMin != null ? 'border-brand-200 bg-brand-50' : 'border-ink-100 bg-ink-50/60'}`}>
              <div className="flex items-center gap-2 mb-2">
                <span className={`font-extrabold ${probeMin != null ? 'text-brand-800' : 'text-ink-300'}`}>
                  {probeMin != null ? toHHMM(probeMin) : '--:--'}
                </span>
                <span className="text-xs text-ink-400">
                  {probeMin == null
                    ? 'hover the timeline to see who is busy at a given time, click to pin'
                    : mode === 'doctors' ? 'who is scheduled at this time:' : 'rooms with a session at this time:'}
                  {pinnedX != null && <button onClick={() => setPinnedX(null)} className="ml-2 text-xs underline text-brand-700">clear pin</button>}
                </span>
              </div>
              <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-1.5">
                {probeTiles.map((t: any) => (
                  <div key={t.id}
                    className={`rounded-lg px-2.5 py-1.5 flex items-center justify-between gap-2 border ${
                      t.count == null ? 'bg-white border-ink-100'
                        : t.count ? 'bg-amber-50 border-amber-200'
                        : 'bg-emerald-50 border-emerald-200'}`}>
                    <span className={`truncate font-medium ${t.count == null ? 'text-ink-400' : 'text-ink-800'}`}>{t.name}</span>
                    <span className={`text-[11px] font-bold shrink-0 ${
                      t.count == null ? 'text-ink-300'
                        : t.count ? 'text-amber-700'
                        : 'text-emerald-700'}`}>
                      {t.count == null ? '-'
                        : t.count ? `${t.count} ${mode === 'doctors' ? 'appt' : 'session'}${t.count > 1 ? 's' : ''}`
                        : 'free'}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* appointment action modal — click a block on the timeline to open */}
      {selAppt && (() => {
        const a = selAppt
        const isCancelable = ['booked', 'rescheduled'].includes(a.status)
        const isCompletable = ['booked', 'active', 'rescheduled', 'overrun'].includes(a.status)
        const isChecked = a.checked_in
        return (
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4" onClick={closeAppt}>
            <div className="absolute inset-0 bg-ink-900/30 backdrop-blur-[2px] animate-fadein" />
            <div onClick={(e) => e.stopPropagation()}
              className="relative w-full max-w-md bg-white rounded-2xl shadow-pop animate-fadein">
              <div className="flex items-center justify-between px-5 py-4 border-b border-ink-100">
                <div className="flex items-center gap-3">
                  <span className="text-2xl">{typeIcon(a.type)}</span>
                  <div>
                    <div className="font-extrabold text-ink-900">{patientById[a.patient_id]?.name || a.patient_id}</div>
                    <div className="text-xs text-ink-400">{a.slot_start}–{a.slot_end} · {a.status.replace('_', ' ')}</div>
                  </div>
                </div>
                <button onClick={closeAppt} className="btn-ghost !px-2.5 !py-2" title="Close">
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" /></svg>
                </button>
              </div>

              <div className="p-5 space-y-3">
                <dl className="grid grid-cols-2 gap-y-2 text-sm">
                  <dt className="text-ink-400">Date</dt>
                  <dd className="text-ink-800 font-medium text-right">{fmtDay(a.date, state.active_day)}</dd>
                  <dt className="text-ink-400">Doctor</dt>
                  <dd className="text-ink-800 font-medium text-right">{state.doctors.find((d: any) => d.id === a.doctor_id)?.name || '—'}</dd>
                  <dt className="text-ink-400">Room</dt>
                  <dd className="text-ink-800 font-medium text-right">{roomById[a.room_id]?.name || 'consult (no room)'}</dd>
                  <dt className="text-ink-400">Drug</dt>
                  <dd className="text-ink-800 font-medium text-right">{a.drug_id ? drugById[a.drug_id]?.name || '—' : '—'}</dd>
                  <dt className="text-ink-400">Check-in</dt>
                  <dd className="text-ink-800 font-medium text-right">{isChecked ? 'Yes' : 'No'}</dd>
                </dl>

                {(() => {
                  const mine = investigations.filter((i: any) => i.appointment_id === a.id)
                  const openBlocking = mine.filter((i: any) => i.blocking && i.status !== 'resulted')
                  return (
                    <div className="rounded-xl border border-ink-100 p-3">
                      <div className="text-xs font-bold text-ink-500 uppercase tracking-wide mb-2">Readiness</div>
                      {mine.length === 0 ? (
                        <div className="text-xs text-ink-400">No investigations ordered.</div>
                      ) : (
                        <div className="flex flex-wrap gap-1.5 mb-2">
                          {mine.map((i: any) => (
                            <span key={i.id}
                              className={`text-[11px] rounded-lg px-2 py-1 border ${
                                i.status === 'flagged' ? 'bg-rose-50 border-rose-200 text-rose-700'
                                  : i.status === 'resulted' ? 'bg-emerald-50 border-emerald-200 text-emerald-700'
                                  : 'bg-ink-50 border-ink-200 text-ink-600'}`}>
                              <b>{i.kind}</b>{i.value ? ` ${i.value}` : ''} · {i.status}
                              {i.status === 'pending' && (
                                <ResultEntry kind={i.kind} busy={invBusy !== ''}
                                  onSave={(b) => runInv('res' + i.id, () => api.resultInvestigation(i.id, b))} />
                              )}
                            </span>
                          ))}
                        </div>
                      )}
                      {canManage && (
                        <div className="flex items-end gap-2 flex-wrap">
                          <div>
                            <label className="label" htmlFor="lab-kind">Order</label>
                            <select id="lab-kind" className="input !py-1.5 text-sm" value={labKind}
                              onChange={(e) => setLabKind(e.target.value)}>
                              <option>CBC</option>
                              <option>LFT</option>
                              <option>RFT</option>
                              <option>Imaging</option>
                            </select>
                          </div>
                          <button className="btn-ghost !py-1.5" disabled={invBusy !== ''}
                            onClick={() => runInv('order', () => api.orderInvestigation({
                              patient_id: a.patient_id, kind: labKind, appointment_id: a.id,
                            }))}>
                            {invBusy === 'order' ? '…' : 'Order'}
                          </button>
                          {openBlocking.length > 0 && !a.awaiting_results && (
                            <button className="btn-primary !py-1.5" disabled={invBusy !== ''}
                              title="Keeps the patient's place and frees the chair"
                              onClick={() => runInv('gate', () => api.gateAppointment(a.id))}>
                              {invBusy === 'gate' ? '…' : 'Hold for results'}
                            </button>
                          )}
                        </div>
                      )}
                      {invMsg && <div className="mt-2 text-xs"><Message ok={invMsg.ok} text={invMsg.text} /></div>}
                    </div>
                  )
                })()}

                {actMsg && <div className="text-sm rounded-lg bg-ink-50 px-3 py-2"><Message ok={actMsg.ok} text={actMsg.text} /></div>}

                {canControl(a) && (
                  <div className="rounded-xl border border-brand-100 bg-brand-50/50 p-3 space-y-2">
                    <div className="text-xs font-bold text-brand-800 uppercase tracking-wide">
                      Running the room
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-xs text-ink-500">More time:</span>
                      {[5, 10, 15].map((m) => (
                        <button key={m} className="btn-ghost !py-1 text-xs" disabled={actBusy !== ''}
                          onClick={() => act('ext' + m, () => api.extendVisit(a.id, m))}>
                          {actBusy === 'ext' + m ? '…' : `+${m} min`}
                        </button>
                      ))}
                    </div>

                    <div className="space-y-2">
                      <div className="flex flex-wrap items-end gap-2">
                        <div>
                          <label className="label" htmlFor="hand-to">Hand over to</label>
                          <select id="hand-to" className="input !py-1.5 text-sm"
                            value={handTo} onChange={(e) => setHandTo(e.target.value)}>
                            <option value="">pick a colleague…</option>
                            {state.doctors
                              .filter((d: any) => d.id !== a.doctor_id)
                              .map((d: any) => (
                                <option key={d.id} value={d.id}
                                  disabled={d.status === 'on_leave' || d.status === 'unavailable'}>
                                  {d.name} · {d.specialty}
                                </option>
                              ))}
                          </select>
                        </div>
                        <button className="btn-ghost !py-1.5" disabled={actBusy !== '' || !handTo}
                          onClick={() => act('hand', async () => {
                            const r = await api.handOff(
                              a.id, handTo,
                              'handed over by the treating doctor', handNote)
                            setHandNote('')
                            return r
                          })}>
                          {actBusy === 'hand' ? '…' : 'Hand over'}
                        </button>
                      </div>
                      {/* The hand-off already moves the patient. This is the
                          part a colleague actually needs: what you would have
                          told them on the phone. */}
                      <div>
                        <label className="label" htmlFor="hand-note">
                          Note for them <span className="font-normal text-ink-400">(optional)</span>
                        </label>
                        <textarea id="hand-note" rows={2} maxLength={500}
                          className="input !py-1.5 text-sm w-full"
                          placeholder="Counts back at 11:05, keen to go ahead today. Attendant waiting outside."
                          value={handNote} onChange={(e) => setHandNote(e.target.value)} />
                      </div>
                    </div>

                    <div className="flex flex-wrap items-end gap-2">
                      <div>
                        <label className="label" htmlFor="swap-with">Swap with</label>
                        <select id="swap-with" className="input !py-1.5 text-sm"
                          value={swapWith} onChange={(e) => setSwapWith(e.target.value)}>
                          <option value="">another of my patients…</option>
                          {state.appointments
                            .filter((x: any) => x.id !== a.id && x.doctor_id === a.doctor_id
                              && x.date === a.date
                              && ['booked', 'rescheduled', 'active'].includes(x.status))
                            .sort((x: any, y: any) => x.slot_start.localeCompare(y.slot_start))
                            .map((x: any) => (
                              <option key={x.id} value={x.id}>
                                {x.slot_start} · {patientById[x.patient_id]?.name || x.patient_id}
                              </option>
                            ))}
                        </select>
                      </div>
                      <button className="btn-ghost !py-1.5" disabled={actBusy !== '' || !swapWith}
                        onClick={() => act('swap', () => api.swapAppointments(a.id, swapWith))}>
                        {actBusy === 'swap' ? '…' : 'Swap'}
                      </button>
                    </div>
                  </div>
                )}

                {canManage ? (
                  <div className="grid grid-cols-2 gap-2 pt-1">
                    {isCancelable && (
                      <button className="btn-danger" disabled={actBusy !== ''}
                        onClick={() => setConfirmCancel(true)}>
                        {actBusy === 'cancel' ? '…' : 'Cancel booking'}
                      </button>
                    )}
                    {isCancelable && (
                      <button className="btn-primary" disabled={actBusy !== ''}
                        onClick={() => act('resched', () => api.rescheduleAuto(a.id, { reason: 'manual auto-reschedule', allow_backup_doctor: true }))}>
                        {actBusy === 'resched' ? '…' : 'Auto-reschedule'}
                      </button>
                    )}
                    <button className="btn-ghost" disabled={actBusy !== '' || isChecked}
                      onClick={() => act('checkin', () => api.checkin(a.id, true))}>
                      {actBusy === 'checkin' ? '…' : isChecked ? 'Checked in' : 'Check in'}
                    </button>
                    {isCompletable && (
                      <button className="btn-primary" disabled={actBusy !== ''}
                        onClick={() => act('complete', () => api.completeVisit(a.id))}>
                        {actBusy === 'complete' ? '…' : 'Mark visit done'}
                      </button>
                    )}
                  </div>
                ) : (
                  <div className="text-xs text-ink-400 flex items-center gap-2">
                    <Icon name="lock" className="w-3.5 h-3.5 shrink-0" />
                    {canControl(a)
                      ? 'Booking and cancelling are handled by the desk.'
                      : 'This patient is not on your list.'}
                  </div>
                )}
              </div>
            </div>
          </div>
        )
      })()}

      <ConfirmDialog
        open={confirmCancel && !!selAppt}
        title="Cancel appointment"
        message={`Cancel the ${selAppt ? `${selAppt.slot_start}–${selAppt.slot_end}` : ''} appointment for ${patientById[selAppt?.patient_id]?.name || 'this patient'}? The slot will be released and the next patient notified.`}
        confirmLabel="Cancel appointment"
        danger
        onConfirm={() => { if (selAppt) act('cancel', () => api.cancelAppointment(selAppt.id)) }}
        onCancel={() => setConfirmCancel(false)}
      />
    </div>
  )
}

// File a lab result. Out of protocol keeps the treatment blocked until a doctor
// or admin accepts it; the app never decides that on its own.
function ResultEntry({ kind, busy, onSave }: {
  kind: string; busy: boolean; onSave: (b: { value: string; flagged: boolean }) => void
}) {
  const [value, setValue] = useState('')
  const [flagged, setFlagged] = useState(false)
  return (
    <span className="ml-1.5 inline-flex items-center gap-1.5">
      <input className="input !py-0.5 !px-2 !w-28 text-[11px]" value={value}
        aria-label={`${kind} result`} placeholder="result value"
        onChange={(e) => setValue(e.target.value)} />
      <label className="inline-flex items-center gap-1 cursor-pointer">
        <input type="checkbox" checked={flagged} onChange={(e) => setFlagged(e.target.checked)} />
        out of protocol
      </label>
      <button className="underline font-bold" disabled={busy || !value.trim()}
        onClick={() => onSave({ value: value.trim(), flagged })}>
        save
      </button>
    </span>
  )
}
