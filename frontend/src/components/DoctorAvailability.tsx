import { useState } from 'react'
import { api } from '../lib/api'

const STATUS_TONE: Record<string, string> = {
  available: 'bg-emerald-100 text-emerald-700',
  on_leave: 'bg-rose-100 text-rose-700',
  partially_unavailable: 'bg-amber-100 text-amber-700',
  unavailable: 'bg-ink-200 text-ink-600',
}
const STATUS_LABEL: Record<string, string> = {
  available: 'Available',
  on_leave: 'On Leave (full day)',
  partially_unavailable: 'Partially unavailable',
  unavailable: 'Unavailable',
}

export default function DoctorAvailability({ state, lockedDoctorId }: { state: any; lockedDoctorId?: string }) {
  const [docId, setDocId] = useState(lockedDoctorId || state.doctors[0]?.id || '')
  const [date, setDate] = useState(() => new Date().toISOString().slice(0, 10))
  const [start, setStart] = useState('10:00')
  const [end, setEnd] = useState('12:00')
  const [reason, setReason] = useState('leave')
  const [fullDay, setFullDay] = useState(false)
  const [busy, setBusy] = useState('')
  const [msg, setMsg] = useState('')

  const doctorsSorted = [...state.doctors].sort((a: any, b: any) => a.name.localeCompare(b.name))
  const doc = state.doctors.find((d: any) => d.id === docId)

  async function run(key: string, fn: () => Promise<any>) {
    setBusy(key); setMsg('')
    try { const r = await fn(); setMsg(`${r.success ? '✅' : '⚠️'} ${r.message}`) }
    catch (e: any) { setMsg('⚠️ ' + e.message) }
    finally { setBusy('') }
  }

  const activeLeaves = (doc?.leaves || []).filter((l: any) => !l.cancelled)

  return (
    <div className="card p-5">
      <div className="flex items-center gap-2 mb-1">
        <h3 className="font-bold text-ink-900">{lockedDoctorId ? 'My Availability & Leave' : 'Doctor Availability & Leave'}</h3>
      </div>
      <p className="text-xs text-ink-400 mb-4">
        {lockedDoctorId
          ? 'Mark your own leave. It instantly updates the schedule, auto-moves your affected bookings to a backup, and appears in the admin console live.'
          : <>Put a doctor on a <b>time-bounded</b> leave (or full day). Bookings are blocked only during that window, affected appointments auto-move to backups, and the doctor <b>automatically becomes available again</b> when the leave is cancelled or its window expires.</>}
      </p>

      <div className="grid lg:grid-cols-2 gap-5">
        {/* left: controls */}
        <div className="space-y-3">
          <div>
            <label className="label">Doctor</label>
            <select className="input" value={docId} onChange={(e) => setDocId(e.target.value)} disabled={!!lockedDoctorId}>
              {doctorsSorted.map((d: any) => (
                <option key={d.id} value={d.id}>{d.name} — {STATUS_LABEL[d.status] || d.status}</option>
              ))}
            </select>
            {lockedDoctorId && <p className="text-[11px] text-ink-400 mt-1">You can only manage your own availability.</p>}
          </div>

          <div className={`rounded-xl border p-3 ${fullDay ? 'border-rose-200 bg-rose-50' : 'border-amber-200 bg-amber-50'}`}>
            <label className="flex items-center gap-2 text-sm font-semibold text-ink-700 cursor-pointer">
              <input type="checkbox" checked={fullDay} onChange={(e) => setFullDay(e.target.checked)} className="accent-rose-600" />
              Full-day leave (sick leave)
            </label>
            {!fullDay && (
              <div className="grid grid-cols-3 gap-3 mt-3">
                <div>
                  <label className="label">Date</label>
                  <input type="date" className="input" value={date} onChange={(e) => setDate(e.target.value)} />
                </div>
                <div>
                  <label className="label">Leave starts</label>
                  <input type="time" className="input" value={start} onChange={(e) => setStart(e.target.value)} />
                </div>
                <div>
                  <label className="label">Leave ends</label>
                  <input type="time" className="input" value={end} onChange={(e) => setEnd(e.target.value)} />
                </div>
              </div>
            )}
            <div className="mt-3">
              <label className="label">Reason</label>
              <input className="input" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="lunch / procedure / clinic elsewhere" />
            </div>
          </div>

          <div className="flex flex-wrap gap-2">
            <button className="btn-amber" disabled={busy === 'take'}
              onClick={() => run('take', () => api.takeLeave(docId, {
                start: fullDay ? '08:00' : start,
                end: fullDay ? '18:00' : end,
                reason, full_day: fullDay, date,
              }))}>
              {busy === 'take' ? '…' : fullDay ? '🏥 Put on full-day leave' : '🕑 Put on time-bounded leave'}
            </button>
            <button className="btn-ghost" disabled={busy === 'mark' || !doc}
              onClick={() => run('mark', () => api.markAvailable(docId))}>
              {busy === 'mark' ? '…' : '✓ Mark fully available'}
            </button>
          </div>

          {msg && <div className="text-sm text-ink-700 bg-ink-50 rounded-lg px-3 py-2">{msg}</div>}
        </div>

        {/* right: current status + active leaves */}
        <div className="space-y-3">
          <div className="rounded-xl bg-ink-50 p-4">
            <div className="flex items-center justify-between">
              <span className="text-sm font-semibold text-ink-700">{doc?.name || '—'}</span>
              <span className={`badge ${STATUS_TONE[doc?.status] || 'bg-ink-100 text-ink-600'}`}>
                {STATUS_LABEL[doc?.status] || doc?.status}
              </span>
            </div>
            <div className="mt-2 text-xs text-ink-400">
              {activeLeaves.length === 0
                ? 'No active leaves — bookable all day.'
                : `${activeLeaves.length} active leave window(s).`}
            </div>
          </div>

          <div>
            <div className="label">Active leave windows</div>
            {activeLeaves.length === 0 ? (
              <div className="text-sm text-ink-400 py-4 text-center">None</div>
            ) : (
              <ul className="space-y-2">
                {activeLeaves.map((l: any) => (
                  <li key={l.id} className="flex items-center justify-between rounded-lg border border-amber-200 bg-amber-50 px-3 py-2">
                    <div>
                      <div className="text-sm font-bold text-ink-900">{l.start} – {l.end}</div>
                      <div className="text-xs text-ink-500">{l.date ? `${l.date} · ` : ''}{l.reason}</div>
                    </div>
                    <button className="btn-ghost !px-2.5 !py-1.5 text-xs" disabled={busy === `c-${l.id}`}
                      onClick={() => run(`c-${l.id}`, () => api.cancelLeave(docId, l.id))}>
                      {busy === `c-${l.id}` ? '…' : 'Cancel leave'}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <div className="text-[11px] text-ink-400">
            💡 Expired leaves are auto-cleared by the watchdog — no manual action needed.
          </div>
        </div>
      </div>
    </div>
  )
}
