import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import { Icon, Message } from './icons'

// A doctor's working week and the house rules inside it.
//
// Until the scheduler knows about clinic sessions, the ward round, teaching
// and lunch, it will keep producing a day nobody would accept — and every one
// of those bookings has to be undone by hand. An empty template means
// "available all day", exactly as the app behaved before.

const DAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'] as const
const DAY_LABEL: Record<string, string> = {
  mon: 'Mon', tue: 'Tue', wed: 'Wed', thu: 'Thu', fri: 'Fri', sat: 'Sat', sun: 'Sun',
}

const KINDS = [
  { key: 'clinic', label: 'Clinic — bookable' },
  { key: 'ward_round', label: 'Ward round' },
  { key: 'teaching', label: 'Teaching' },
  { key: 'lunch', label: 'Lunch' },
  { key: 'admin', label: 'Admin time' },
]
const KIND_TONE: Record<string, string> = {
  clinic: 'bg-brand-100 text-brand-700',
  ward_round: 'bg-amber-100 text-amber-700',
  teaching: 'bg-amber-100 text-amber-700',
  lunch: 'bg-amber-100 text-amber-700',
  admin: 'bg-ink-100 text-ink-600',
}

const RULE_KINDS = [
  { key: 'max_consecutive', label: 'No more than N in a row' },
  { key: 'not_after', label: 'Before this time only' },
  { key: 'not_before', label: 'After this time only' },
]

let seq = 0
const tempId = (p: string) => `${p}-new-${++seq}`

export default function WorkingWeek({ state, doctorId, canEdit }: {
  state: any; doctorId: string; canEdit: boolean
}) {
  const [sessions, setSessions] = useState<any[]>([])
  const [rules, setRules] = useState<any[]>([])
  const [busy, setBusy] = useState('')
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)

  const visitTypes: any[] = state.visit_types || []
  const doc = state.doctors.find((d: any) => d.id === doctorId)

  useEffect(() => {
    let live = true
    if (!doctorId) return
    api.week(doctorId)
      .then((w) => {
        if (!live) return
        setSessions(w.sessions || [])
        setRules(w.rules || [])
        setMsg(null)
      })
      .catch(() => { if (live) { setSessions([]); setRules([]) } })
    return () => { live = false }
  }, [doctorId])

  function toggleDay(idx: number, day: string) {
    setSessions((prev) => prev.map((b, i) => {
      if (i !== idx) return b
      const days: string[] = b.days?.includes('*') ? [...DAYS] : [...(b.days || [])]
      return { ...b, days: days.includes(day) ? days.filter((d) => d !== day) : [...days, day] }
    }))
  }

  function addSession() {
    setSessions((prev) => [...prev, {
      id: tempId('SES'), days: ['mon'], start: '09:00', end: '13:00',
      kind: 'clinic', label: '',
    }])
  }

  function addRule() {
    setRules((prev) => [...prev, {
      id: tempId('RUL'), kind: 'max_consecutive', visit_type: 'new_case',
      value: '3', enabled: 1,
    }])
  }

  async function save(what: 'sessions' | 'rules') {
    setBusy(what); setMsg(null)
    try {
      const r = what === 'sessions'
        ? await api.setSessions(doctorId, sessions.map((b) => ({
            id: String(b.id).includes('-new-') ? '' : b.id,
            days: b.days?.length ? b.days : ['*'],
            start: b.start, end: b.end, kind: b.kind, label: b.label || '',
          })))
        : await api.setRules(doctorId, rules.map((r2) => ({
            id: String(r2.id).includes('-new-') ? '' : r2.id,
            kind: r2.kind, visit_type: r2.visit_type,
            value: String(r2.value), enabled: !!Number(r2.enabled),
          })))
      setMsg({ ok: r.success !== false, text: r.message || 'saved' })
      if (r.week) { setSessions(r.week.sessions || []); setRules(r.week.rules || []) }
    } catch (e: any) { setMsg({ ok: false, text: e.message }) }
    finally { setBusy('') }
  }

  if (!doctorId) return null

  return (
    <div className="space-y-4">
      {/* the working week */}
      <div className="card p-5">
        <div className="flex items-center justify-between gap-3 flex-wrap mb-1">
          <div className="flex items-center gap-2">
            <Icon name="calendar" className="w-5 h-5 text-brand-600 shrink-0" />
            <h3 className="font-bold text-ink-900">Working week</h3>
            {doc && <span className="text-xs text-ink-400">{doc.name}</span>}
          </div>
          {canEdit && (
            <div className="flex gap-2">
              <button className="btn-ghost !py-1.5" onClick={addSession}>Add a session</button>
              <button className="btn-primary !py-1.5" disabled={busy !== ''}
                onClick={() => save('sessions')}>
                {busy === 'sessions' ? '…' : 'Save week'}
              </button>
            </div>
          )}
        </div>

        {sessions.length === 0 ? (
          <div className="text-sm text-ink-500">
            No template — the scheduler treats this doctor as available 08:00&ndash;18:00 every day.
            Add a clinic session and booking is confined to it.
          </div>
        ) : (
          <div className="space-y-2 mt-3">
            {sessions.map((b: any, i: number) => (
              <div key={b.id} className="rounded-xl border border-ink-200 p-3 flex flex-wrap items-end gap-3">
                <div>
                  <label className="label" htmlFor={`kind-${b.id}`}>Kind</label>
                  <select id={`kind-${b.id}`} className="input !py-1.5 text-sm" value={b.kind}
                    disabled={!canEdit}
                    onChange={(e) => setSessions((prev) => prev.map((x, j) =>
                      j === i ? { ...x, kind: e.target.value } : x))}>
                    {KINDS.map((k) => <option key={k.key} value={k.key}>{k.label}</option>)}
                  </select>
                </div>
                <div>
                  <label className="label" htmlFor={`from-${b.id}`}>From</label>
                  <input id={`from-${b.id}`} type="time" className="input !py-1.5 text-sm"
                    value={b.start} disabled={!canEdit}
                    onChange={(e) => setSessions((prev) => prev.map((x, j) =>
                      j === i ? { ...x, start: e.target.value } : x))} />
                </div>
                <div>
                  <label className="label" htmlFor={`to-${b.id}`}>To</label>
                  <input id={`to-${b.id}`} type="time" className="input !py-1.5 text-sm"
                    value={b.end} disabled={!canEdit}
                    onChange={(e) => setSessions((prev) => prev.map((x, j) =>
                      j === i ? { ...x, end: e.target.value } : x))} />
                </div>
                <div className="grow min-w-[140px]">
                  <label className="label" htmlFor={`label-${b.id}`}>Label</label>
                  <input id={`label-${b.id}`} type="text" className="input !py-1.5 text-sm w-full"
                    value={b.label || ''} placeholder="e.g. OPD clinic" disabled={!canEdit}
                    onChange={(e) => setSessions((prev) => prev.map((x, j) =>
                      j === i ? { ...x, label: e.target.value } : x))} />
                </div>

                <div className="w-full flex items-center gap-2 flex-wrap">
                  <span className={`badge ${KIND_TONE[b.kind] || KIND_TONE.admin}`}>
                    {b.kind === 'clinic' ? 'bookable' : 'blocked'}
                  </span>
                  {DAYS.map((d) => {
                    const on = b.days?.includes('*') || b.days?.includes(d)
                    return (
                      <button key={d} type="button" disabled={!canEdit}
                        aria-pressed={on}
                        onClick={() => toggleDay(i, d)}
                        className={`px-2.5 py-1 rounded-lg text-xs font-semibold border transition ${
                          on ? 'bg-brand-600 text-white border-brand-600'
                             : 'bg-white text-ink-500 border-ink-200'}`}>
                        {DAY_LABEL[d]}
                      </button>
                    )
                  })}
                  {canEdit && (
                    <button className="btn-ghost !px-2.5 !py-1 text-xs ml-auto"
                      onClick={() => setSessions((prev) => prev.filter((_x, j) => j !== i))}>
                      Remove
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* case-mix rules */}
      <div className="card p-5">
        <div className="flex items-center justify-between gap-3 flex-wrap mb-1">
          <div className="flex items-center gap-2">
            <Icon name="info" className="w-5 h-5 text-brand-600 shrink-0" />
            <h3 className="font-bold text-ink-900">Case-mix rules</h3>
          </div>
          {canEdit && (
            <div className="flex gap-2">
              <button className="btn-ghost !py-1.5" onClick={addRule}>Add a rule</button>
              <button className="btn-primary !py-1.5" disabled={busy !== ''}
                onClick={() => save('rules')}>
                {busy === 'rules' ? '…' : 'Save rules'}
              </button>
            </div>
          )}
        </div>

        {rules.length === 0 ? (
          <div className="text-sm text-ink-500">
            None. Booking is limited only by slots, buffers and the daily cap.
          </div>
        ) : (
          <div className="space-y-2 mt-3">
            {rules.map((r: any, i: number) => (
              <div key={r.id} className="rounded-xl border border-ink-200 p-3 flex flex-wrap items-end gap-3">
                <div>
                  <label className="label" htmlFor={`rk-${r.id}`}>Rule</label>
                  <select id={`rk-${r.id}`} className="input !py-1.5 text-sm" value={r.kind}
                    disabled={!canEdit}
                    onChange={(e) => setRules((prev) => prev.map((x, j) =>
                      j === i ? { ...x, kind: e.target.value } : x))}>
                    {RULE_KINDS.map((k) => <option key={k.key} value={k.key}>{k.label}</option>)}
                  </select>
                </div>
                <div>
                  <label className="label" htmlFor={`rv-${r.id}`}>Applies to</label>
                  <select id={`rv-${r.id}`} className="input !py-1.5 text-sm" value={r.visit_type}
                    disabled={!canEdit}
                    onChange={(e) => setRules((prev) => prev.map((x, j) =>
                      j === i ? { ...x, visit_type: e.target.value } : x))}>
                    {visitTypes.map((v: any) => (
                      <option key={v.key} value={v.key}>{v.label}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="label" htmlFor={`rn-${r.id}`}>
                    {r.kind === 'max_consecutive' ? 'How many' : 'Time'}
                  </label>
                  <input id={`rn-${r.id}`}
                    type={r.kind === 'max_consecutive' ? 'number' : 'time'}
                    min="1" className="input !py-1.5 text-sm" value={r.value}
                    disabled={!canEdit}
                    onChange={(e) => setRules((prev) => prev.map((x, j) =>
                      j === i ? { ...x, value: e.target.value } : x))} />
                </div>
                <label className="flex items-center gap-2 text-sm text-ink-700 pb-1.5">
                  <input type="checkbox" className="w-4 h-4" checked={!!Number(r.enabled)}
                    disabled={!canEdit}
                    onChange={(e) => setRules((prev) => prev.map((x, j) =>
                      j === i ? { ...x, enabled: e.target.checked ? 1 : 0 } : x))} />
                  On
                </label>
                {r.describe && (
                  <span className="text-xs text-ink-500 grow min-w-[160px]">{r.describe}</span>
                )}
                {canEdit && (
                  <button className="btn-ghost !px-2.5 !py-1 text-xs ml-auto"
                    onClick={() => setRules((prev) => prev.filter((_x, j) => j !== i))}>
                    Remove
                  </button>
                )}
              </div>
            ))}
          </div>
        )}

        <div className="mt-3 text-[11px] text-ink-400 flex items-center gap-1.5">
          <Icon name="info" className="w-3.5 h-3.5 shrink-0" />
          Walk-ins, backfill and auto-reschedule all inherit these — they use the same slot search.
        </div>
      </div>

      {msg && <div className="text-sm bg-ink-50 rounded-lg px-3 py-2"><Message ok={msg.ok} text={msg.text} /></div>}
    </div>
  )
}
