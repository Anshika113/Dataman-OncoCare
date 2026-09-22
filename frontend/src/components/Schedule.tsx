import { useMemo, useRef, useState } from 'react'
import { api } from '../lib/api'
import { statusBadge, typeIcon } from './badges'
import type { Caps } from '../lib/roles'

const START = 8 * 60, END = 18 * 60, PX_PER_MIN = 1.1

function toMin(hhmm: string) { const [h, m] = hhmm.split(':').map(Number); return h * 60 + m }
function toHHMM(mins: number) { return `${String(Math.floor(mins / 60)).padStart(2, '0')}:${String(mins % 60).padStart(2, '0')}` }

export default function Schedule({ state, caps }: { state: any; caps: Caps }) {
  const [mode, setMode] = useState<'doctors' | 'rooms'>('doctors')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')

  const roomById = useMemo(() => Object.fromEntries(state.rooms.map((r: any) => [r.id, r])), [state.rooms])
  const patientById = useMemo(() => Object.fromEntries(state.patients.map((p: any) => [p.id, p])), [state.patients])
  const drugById = useMemo(() => Object.fromEntries(state.drugs.map((g: any) => [g.id, g])), [state.drugs])
  // alphabetical option lists
  const patientsSorted = useMemo(() => [...state.patients].sort((a: any, b: any) => a.name.localeCompare(b.name)), [state.patients])
  const doctorsSorted = useMemo(() => [...state.doctors].sort((a: any, b: any) => a.name.localeCompare(b.name)), [state.doctors])
  const drugsSorted = useMemo(() => [...state.drugs].sort((a: any, b: any) => a.name.localeCompare(b.name)), [state.drugs])

  const rows = (mode === 'doctors'
    ? state.doctors.map((d: any) => ({ id: d.id, label: d.name, sub: d.specialty, status: d.status }))
    : state.rooms.map((r: any) => ({ id: r.id, label: r.name, sub: r.type, status: r.status })))
    .sort((a: any, b: any) => a.label.localeCompare(b.label))

  const width = (END - START) * PX_PER_MIN

  // booking form
  const [patient_id, setPatient] = useState(state.patients[0]?.id || '')
  const [doctor_id, setDoctor] = useState(state.doctors[0]?.id || '')
  const [drug_id, setDrug] = useState(state.drugs[0]?.id || '')
  const [preferred, setPreferred] = useState('09:00')
  const [date, setDate] = useState(() => new Date().toISOString().slice(0, 10))
  const [type, setType] = useState<'consult' | 'chemo'>('consult')
  const [recs, setRecs] = useState<any[]>([])

  // selected appointment (for the action panel: cancel / reschedule / complete / check-in)
  const [selAppt, setSelAppt] = useState<any | null>(null)
  const [actBusy, setActBusy] = useState('')
  const [actMsg, setActMsg] = useState('')
  const canManage = caps.canBook // nurse/admin can manage appointments

  // Live preview: highlight the selected doctor's row at the chosen time so the
  // user sees on the timeline whether the slot is free (green) or clashing (red).
  const previewDoctorId = doctor_id
  const previewStart = preferred ? toMin(preferred) : NaN
  const previewEnd = previewStart + 30
  const previewConflict = useMemo(() => {
    if (!previewDoctorId || !preferred || Number.isNaN(previewStart)) return false
    return state.appointments.some((a: any) =>
      a.doctor_id === previewDoctorId &&
      ['booked', 'active', 'overrun', 'rescheduled'].includes(a.status) &&
      toMin(a.slot_start) < previewEnd && toMin(a.slot_end) > previewStart)
  }, [state.appointments, previewDoctorId, preferred, previewEnd, previewStart])

  // Hover probe: as the mouse moves across the grid, show a vertical cursor at
  // the exact time and list which doctors are scheduled (or free) at that moment.
  const gridRef = useRef<HTMLDivElement>(null)
  const [hoverX, setHoverX] = useState<number | null>(null) // px from grid left
  const [pinnedX, setPinnedX] = useState<number | null>(null) // clicked / pinned
  const probeX = pinnedX ?? hoverX
  const probeMin = probeX != null ? Math.round((START + probeX / PX_PER_MIN) / 15) * 15 : null

  const busyAt = probeMin != null
    ? state.doctors
        .map((d: any) => ({
          doctor: d,
          appts: state.appointments.filter((a: any) =>
            a.doctor_id === d.id &&
            ['booked', 'active', 'overrun', 'rescheduled'].includes(a.status) &&
            toMin(a.slot_start) <= probeMin && toMin(a.slot_end) > probeMin),
        }))
        .sort((a: any, b: any) => a.doctor.name.localeCompare(b.doctor.name))
    : []

  function handleGridMove(e: React.MouseEvent) {
    if (pinnedX != null) return
    const el = gridRef.current
    if (!el) return
    const rect = el.getBoundingClientRect()
    const x = Math.max(0, Math.min(width, e.clientX - rect.left))
    setHoverX(x)
  }
  function handleGridLeave() { if (pinnedX == null) setHoverX(null) }
  function handleGridClick(e: React.MouseEvent) {
    const el = gridRef.current
    if (!el) return
    const rect = el.getBoundingClientRect()
    const x = Math.max(0, Math.min(width, e.clientX - rect.left))
    setPinnedX((prev) => (prev === x ? null : x))
  }

  async function book() {
    setBusy(true); setMsg(''); setRecs([])
    try {
      const r = await api.bookWithRecs({
        patient_id, doctor_id,
        appt_type: type,
        drug_id: type === 'chemo' ? drug_id : null,
        preferred_start: preferred,
        slot_start: preferred,
        slot_end: toHHMM(toMin(preferred) + 30),
        date,
      })
      if (r.success) {
        setMsg(`✅ ${r.message}${date ? ` on ${date}` : ''}`)
        setPreferred('')
      } else {
        setMsg(`⚠️ ${r.message}`)
        setRecs(r.recommended || [])
      }
    } catch (e: any) { setMsg('⚠️ ' + e.message) }
    finally { setBusy(false) }
  }

  async function bookRec(rec: any) {
    setBusy(true); setMsg('')
    try {
      const r = await api.bookWithRecs({
        patient_id, doctor_id,
        appt_type: type,
        drug_id: type === 'chemo' ? drug_id : null,
        preferred_start: rec.slot_start,
        slot_start: rec.slot_start,
        slot_end: rec.slot_end,
        date,
      })
      setMsg(r.success ? `✅ ${r.message}${date ? ` on ${date}` : ''}` : `⚠️ ${r.message}`)
      if (r.success) { setRecs([]); setPreferred('') }
    } catch (e: any) { setMsg('⚠️ ' + e.message) }
    finally { setBusy(false) }
  }

  // appointment management actions (cancel / reschedule / complete / check-in)
  function closeAppt() { setSelAppt(null); setActMsg('') }
  async function act(kind: string, fn: () => Promise<any>) {
    setActBusy(kind); setActMsg('')
    try {
      const r = await fn()
      setActMsg(`${r.success ? '✅' : '⚠️'} ${r.message}`)
      if (r.success) closeAppt()
    } catch (e: any) { setActMsg('⚠️ ' + e.message) }
    finally { setActBusy('') }
  }

  return (
    <div className="space-y-4">
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
            </select>
          </div>
          <div>
            <label className="label">Patient</label>
            <select className="input" value={patient_id} onChange={(e) => setPatient(e.target.value)}>
              {patientsSorted.map((p: any) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </div>
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
          {type === 'chemo' && (
            <div>
              <label className="label">Drug</label>
              <select className="input" value={drug_id} onChange={(e) => setDrug(e.target.value)}>
                {drugsSorted.map((g: any) => <option key={g.id} value={g.id}>{g.name} ({g.tw_start}–{g.tw_end})</option>)}
              </select>
            </div>
          )}
          <div>
            <label className="label">Date</label>
            <input type="date" className="input" value={date} onChange={(e) => setDate(e.target.value)} />
          </div>
          <div>
            <label className="label">Preferred start</label>
            <input type="time" className="input" value={preferred} onChange={(e) => setPreferred(e.target.value)} />
          </div>
          <button className="btn-primary" onClick={book} disabled={busy}>{busy ? 'Booking…' : 'Book'}</button>
        </div>
        {msg && <div className="mt-3 text-sm text-ink-600 bg-ink-50 rounded-lg px-3 py-2">{msg}</div>}

        {recs.length > 0 && (
          <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-4">
            <div className="flex items-center gap-2 mb-3">
              <span className="text-lg">💡</span>
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
          <span className="text-lg">🔒</span>
          Booking is available to nurses and admins. Your role is read-only for scheduling.
        </div>
      )}

      {/* timeline */}
      <div className="card p-5">
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-bold text-ink-900">Schedule — {mode === 'doctors' ? 'by Doctor' : 'by Room'}</h3>
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
                      <div className="absolute top-0 bottom-0 z-10 border-x-2 border-rose-500 bg-rose-400/25"
                        style={{ left: (previewStart - START) * PX_PER_MIN, width: 30 * PX_PER_MIN }}>
                        <span className="absolute -top-0.5 left-1/2 -translate-x-1/2 -translate-y-full text-[10px] font-bold whitespace-nowrap px-1.5 py-0.5 rounded-full shadow-sm bg-rose-500 text-white">
                          ⚠ clash
                        </span>
                      </div>
                    )}
                    {state.appointments
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
                            onClick={(e) => { e.stopPropagation(); setSelAppt(a); setActMsg('') }}
                            title={`${patientById[a.patient_id]?.name || a.patient_id}\n${a.slot_start}–${a.slot_end}\n${roomById[a.room_id]?.name || 'no room'}${a.drug_id ? ' · ' + (drugById[a.drug_id]?.name || '') : ''}\n${a.status}\n— click to manage`}
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

              {/* vertical probe cursor (offset by the 12rem label column) */}
              {probeX != null && (
                <div className="pointer-events-none absolute top-0 bottom-0 z-20 w-px bg-brand-500"
                  style={{ left: 192 + probeX }}>
                  <span className={`absolute -top-2 -translate-x-1/2 text-[10px] font-bold px-1.5 py-0.5 rounded-full text-white shadow-sm ${pinnedX != null ? 'bg-brand-700' : 'bg-brand-500'}`}>
                    {probeMin != null ? toHHMM(probeMin) : ''}
                  </span>
                </div>
              )}
            </div>

            {/* hover/click probe readout */}
            {probeMin != null && (
              <div className="mt-3 rounded-xl border border-brand-200 bg-brand-50 p-3 text-sm">
                <div className="flex items-center gap-2 mb-2">
                  <span className="font-extrabold text-brand-800">{toHHMM(probeMin)}</span>
                  <span className="text-xs text-brand-600/80">
                    {mode === 'doctors' ? 'who is scheduled at this time:' : 'rooms with a session at this time:'}
                    {pinnedX != null && <button onClick={() => setPinnedX(null)} className="ml-2 text-xs underline text-brand-700">clear pin</button>}
                  </span>
                </div>
                {mode === 'doctors' ? (
                  <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-1.5">
                    {busyAt.map(({ doctor, appts }: any) => (
                      <div key={doctor.id}
                        className={`rounded-lg px-2.5 py-1.5 flex items-center justify-between gap-2 ${appts.length ? 'bg-amber-50 border border-amber-200' : 'bg-emerald-50 border border-emerald-200'}`}>
                        <span className="truncate font-medium text-ink-800">{doctor.name}</span>
                        <span className={`text-[11px] font-bold shrink-0 ${appts.length ? 'text-amber-700' : 'text-emerald-700'}`}>
                          {appts.length ? `${appts.length} appt${appts.length > 1 ? 's' : ''}` : 'free'}
                        </span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-1.5">
                    {state.rooms.map((r: any) => {
                      const appts = state.appointments.filter((a: any) =>
                        a.room_id === r.id &&
                        ['booked', 'active', 'overrun', 'rescheduled'].includes(a.status) &&
                        toMin(a.slot_start) <= probeMin && toMin(a.slot_end) > probeMin)
                      return (
                        <div key={r.id}
                          className={`rounded-lg px-2.5 py-1.5 flex items-center justify-between gap-2 ${appts.length ? 'bg-amber-50 border border-amber-200' : 'bg-emerald-50 border border-emerald-200'}`}>
                          <span className="truncate font-medium text-ink-800">{r.name}</span>
                          <span className={`text-[11px] font-bold shrink-0 ${appts.length ? 'text-amber-700' : 'text-emerald-700'}`}>
                            {appts.length ? `${appts.length} session${appts.length > 1 ? 's' : ''}` : 'free'}
                          </span>
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>
            )}
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
                  <dt className="text-ink-400">Doctor</dt>
                  <dd className="text-ink-800 font-medium text-right">{state.doctors.find((d: any) => d.id === a.doctor_id)?.name || '—'}</dd>
                  <dt className="text-ink-400">Room</dt>
                  <dd className="text-ink-800 font-medium text-right">{roomById[a.room_id]?.name || 'consult (no room)'}</dd>
                  <dt className="text-ink-400">Drug</dt>
                  <dd className="text-ink-800 font-medium text-right">{a.drug_id ? drugById[a.drug_id]?.name || '—' : '—'}</dd>
                  <dt className="text-ink-400">Check-in</dt>
                  <dd className="text-ink-800 font-medium text-right">{isChecked ? 'Yes' : 'No'}</dd>
                </dl>

                {actMsg && <div className="text-sm rounded-lg bg-ink-50 px-3 py-2 text-ink-700">{actMsg}</div>}

                {canManage ? (
                  <div className="grid grid-cols-2 gap-2 pt-1">
                    {isCancelable && (
                      <button className="btn-danger" disabled={actBusy !== ''}
                        onClick={() => { if (confirm(`Cancel this appointment for ${patientById[a.patient_id]?.name}?`)) act('cancel', () => api.cancelAppointment(a.id)) }}>
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
                    <span>🔒</span> Your role is read-only for this appointment.
                  </div>
                )}
              </div>
            </div>
          </div>
        )
      })()}
    </div>
  )
}


