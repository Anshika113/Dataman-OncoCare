// Proactive Insights — surfaces the backend's forward-looking analysis
// (bottlenecks, capacity, waits, drug-window pressure, spare capacity) with a
// concrete recommendation for each. Data arrives live via `state.insights`.
// Every card is clickable (drills into the exact appointments) AND, where the
// role allows, exposes a one-click action that performs the recommended fix via
// the existing engine endpoints.

import { useMemo, useState } from 'react'
import { api, getRole } from '../lib/api'
import { capsFor } from '../lib/roles'

const KIND_ICON: Record<string, string> = {
  wait_time: '⏳',
  queue_overflow: '🐌',
  doctor_cap: '📋',
  drug_window: '💉',
  load_rebalance: '🔁',
  underutilised: '🪑',
}

const KIND_LABEL: Record<string, string> = {
  wait_time: 'Waiting',
  queue_overflow: 'Bottleneck',
  doctor_cap: 'Capacity',
  drug_window: 'Drug window',
  load_rebalance: 'Rebalance',
  underutilised: 'Spare capacity',
}

const SEV: Record<string, { accent: string; icon: string; badge: string; ring: string }> = {
  critical: { accent: 'border-l-rose-500', icon: 'bg-rose-50 text-rose-600', badge: 'bg-rose-100 text-rose-700', ring: 'hover:ring-rose-200' },
  warning: { accent: 'border-l-amber-500', icon: 'bg-amber-50 text-amber-600', badge: 'bg-amber-100 text-amber-700', ring: 'hover:ring-amber-200' },
  info: { accent: 'border-l-ink-200', icon: 'bg-ink-50 text-ink-400', badge: 'bg-ink-100 text-ink-500', ring: 'hover:ring-ink-200' },
}

const BADGE_TONE: Record<string, string> = {
  booked: 'bg-brand-100 text-brand-700',
  active: 'bg-emerald-100 text-emerald-700',
  overrun: 'bg-amber-100 text-amber-700',
  rescheduled: 'bg-violet-100 text-violet-700',
  no_show: 'bg-rose-100 text-rose-700',
  visited: 'bg-emerald-100 text-emerald-700',
  cancelled: 'bg-ink-100 text-ink-500',
  completed: 'bg-emerald-100 text-emerald-700',
  waiting: 'bg-amber-100 text-amber-700',
  assigned: 'bg-brand-100 text-brand-700',
  available: 'bg-emerald-100 text-emerald-700',
  on_leave: 'bg-amber-100 text-amber-700',
  unavailable: 'bg-rose-100 text-rose-700',
  partially_unavailable: 'bg-violet-100 text-violet-700',
}

function chips(ins: any): { label: string; value: string }[] {
  const m = ins.metric || {}
  const out: { label: string; value: string }[] = []
  const push = (label: string, value: string | number | undefined) => {
    if (value !== undefined && value !== '') out.push({ label, value: String(value) })
  }
  switch (ins.kind) {
    case 'wait_time':
      push('late', m.late_min ? `${m.late_min}m` : undefined)
      push('waiting', m.waited_min ? `${m.waited_min}m` : undefined)
      if (m.severity) push('severity', `S${m.severity}`)
      break
    case 'queue_overflow':
      push('sessions', m.sessions)
      push('window', m.window_min ? `${m.window_min}m` : undefined)
      break
    case 'doctor_cap':
      push('used', m.used !== undefined ? `${m.used}/${m.cap}` : undefined)
      push('left', m.remaining)
      if (m.full_by) push('full by', m.full_by)
      break
    case 'drug_window':
      if (m.window) push('window', m.window)
      if (m.slot_start) push('starts', m.slot_start)
      break
    case 'load_rebalance':
      push('busy', m.busy_sessions)
      if (m.busy_remaining !== undefined) push('left', m.busy_remaining)
      break
    case 'underutilised':
      push('free', m.free_window_min ? `next ${m.free_window_min}m` : undefined)
      break
  }
  return out
}

type Row = { key: string; primary: string; secondary?: string; badge?: string; type?: string }
type Act = { label: string; run: () => Promise<any> }

export default function Insights({ insights, now, state }: { insights: any[]; now?: string; state: any }) {
  const list = insights || []
  const alerts = list.filter((i) => i.severity !== 'info').length
  const [selected, setSelected] = useState<any | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [results, setResults] = useState<Record<string, { ok: boolean; msg: string }>>({})

  const role = getRole()
  const caps = capsFor(role)
  const isStaff = role === 'admin' || role === 'nurse'

  const apptById = useMemo(() => Object.fromEntries((state?.appointments || []).map((a: any) => [a.id, a])), [state?.appointments])
  const emgById = useMemo(() => Object.fromEntries((state?.emergencies || []).map((e: any) => [e.id, e])), [state?.emergencies])
  const docById = useMemo(() => Object.fromEntries((state?.doctors || []).map((d: any) => [d.id, d])), [state?.doctors])
  const roomById = useMemo(() => Object.fromEntries((state?.rooms || []).map((r: any) => [r.id, r])), [state?.rooms])
  const patientName = (id: string) => state?.patients?.find((p: any) => p.id === id)?.name || id

  // ---- one-click recommended action (role-gated) ----
  const actionFor = (ins: any): Act | null => {
    const first = (ins.affected || [])[0]
    const last = (ins.affected || []).slice(-1)[0]
    switch (ins.kind) {
      case 'wait_time':
        if (ins.metric?.severity != null) {
          // an emergency is waiting -> assign a free doctor (staff only)
          return isStaff ? { label: 'Assign free doctor', run: () => api.resolveEmergencies() } : null
        }
        // a patient is late / waiting -> check them in
        return caps.canCheckin && first ? { label: 'Check in now', run: () => api.checkin(first, true) } : null
      case 'queue_overflow':
        // relieve the packed resource by shifting its last session elsewhere
        return isStaff && last
          ? { label: 'Shift last session', run: () => api.rescheduleAuto(last, { allow_backup_doctor: true, reason: 'proactive: relieve bottleneck' }) }
          : null
      case 'drug_window':
        // pull the session back inside the drug window (same doctor)
        return isStaff && first
          ? { label: 'Move into window', run: () => api.rescheduleAuto(first, { allow_backup_doctor: false, reason: 'proactive: drug window' }) }
          : null
      case 'load_rebalance':
        // move the suggested session to a compatible free doctor
        return isStaff && ins.metric?.move_appt
          ? { label: 'Rebalance now', run: () => api.rescheduleAuto(ins.metric.move_appt, { allow_backup_doctor: true, reason: 'proactive: rebalance workload' }) }
          : null
      default:
        return null // doctor_cap / underutilised are guidance, not one-click fixes
    }
  }

  const doAction = async (key: string, act: Act) => {
    setBusy(key)
    try {
      const r = await act.run()
      setResults((prev) => ({ ...prev, [key]: { ok: !!r?.success, msg: r?.message || 'Done' } }))
    } catch (e: any) {
      setResults((prev) => ({ ...prev, [key]: { ok: false, msg: e?.message || 'Action failed' } }))
    } finally {
      setBusy(null)
    }
  }

  const rowsFor = (ins: any): Row[] => {
    const rows: Row[] = []
    for (const id of (ins.affected || [])) {
      const a = apptById[id]
      if (a) {
        rows.push({
          key: id,
          primary: `${a.slot_start}–${a.slot_end} · ${patientName(a.patient_id)}`,
          secondary: `${docById[a.doctor_id]?.name || ''}${a.room_id ? ' · ' + (roomById[a.room_id]?.name || '') : ''}`,
          badge: a.status,
          type: a.type,
        })
      } else {
        const e = emgById[id]
        if (e) {
          rows.push({ key: id, primary: `S${e.severity} · ${patientName(e.patient_id)}`, secondary: 'Emergency', badge: e.status })
        } else {
          rows.push({ key: id, primary: id, secondary: '—' })
        }
      }
    }
    return rows
  }

  const ActionButton = ({ ins, key, big }: { ins: any; key: string; big?: boolean }) => {
    const act = actionFor(ins)
    if (!act) return null
    const inFlight = busy === key
    const res = results[key]
    return (
      <div className={big ? '' : 'flex flex-col items-end gap-1'}>
        <button
          disabled={inFlight}
          onClick={(e) => { e.stopPropagation(); doAction(key, act) }}
          className={`inline-flex items-center gap-1.5 rounded-lg bg-brand-600 text-white font-semibold hover:bg-brand-700 active:scale-[.98] transition disabled:opacity-60 disabled:cursor-not-allowed ${big ? 'px-3.5 py-2 text-sm' : 'px-2.5 py-1 text-[11px]'}`}>
          {inFlight ? (
            <><span className="w-3 h-3 border-2 border-white/40 border-t-white rounded-full animate-spin" />Working…</>
          ) : (
            <><span>⚡</span>{act.label}</>
          )}
        </button>
        {res && (
          <span className={`text-[10px] font-semibold ${res.ok ? 'text-emerald-600' : 'text-rose-600'}`}>
            {res.ok ? '✓ ' : '✕ '}{res.msg}
          </span>
        )}
      </div>
    )
  }

  return (
    <section className="card p-5">
      <div className="flex items-center justify-between gap-3 mb-4">
        <div>
          <h3 className="font-bold text-ink-900 flex items-center gap-2">
            <span className="text-lg">🛰️</span> Proactive Insights
            {now && <span className="text-[11px] font-semibold text-ink-400">as of {now}</span>}
          </h3>
          <p className="text-xs text-ink-400 mt-0.5">
            Forward-looking bottlenecks, capacity and waits — click a card for details, or run the ⚡ action.
          </p>
        </div>
        {alerts > 0 ? (
          <span className="badge bg-rose-100 text-rose-700 shrink-0">
            {alerts} need{alerts === 1 ? 's' : ''} attention
          </span>
        ) : (
          <span className="badge bg-emerald-100 text-emerald-700 shrink-0">flowing smoothly</span>
        )}
      </div>

      {list.length === 0 ? (
        <div className="text-sm text-ink-400 py-8 text-center">
          No bottlenecks detected — the clinic is flowing smoothly.
        </div>
      ) : (
        <div className="grid md:grid-cols-2 xl:grid-cols-3 gap-3">
          {list.map((ins, idx) => {
            const sev = SEV[ins.severity] || SEV.info
            const cs = chips(ins)
            const key = `${ins.kind}-${ins.resource_id}-${idx}`
            const nAffected = (ins.affected || []).length
            const act = actionFor(ins)
            return (
              <div key={key}
                role="button" tabIndex={0}
                onClick={() => setSelected(ins)}
                onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') setSelected(ins) }}
                className={`rounded-xl border border-ink-100 border-l-4 ${sev.accent} bg-white p-3.5 flex flex-col gap-2 cursor-pointer transition hover:-translate-y-0.5 hover:shadow-pop hover:ring-2 ${sev.ring}`}>
                <div className="flex items-start gap-2.5">
                  <div className={`w-9 h-9 rounded-xl flex items-center justify-center text-lg shrink-0 ${sev.icon}`}>
                    {KIND_ICON[ins.kind] || '📌'}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="text-[10px] font-bold uppercase tracking-wider text-ink-400">
                        {KIND_LABEL[ins.kind] || ins.kind}
                      </span>
                      <span className={`badge ${sev.badge}`}>{ins.severity}</span>
                    </div>
                    <div className="font-bold text-ink-900 text-sm leading-tight mt-0.5">
                      {ins.title}
                    </div>
                  </div>
                  <span className="text-ink-300 text-lg leading-none mt-0.5" aria-hidden>›</span>
                </div>

                <p className="text-xs text-ink-500 leading-relaxed">{ins.detail}</p>

                {ins.action && (
                  <div className="text-xs font-semibold text-brand-700 bg-brand-50 rounded-lg px-2.5 py-1.5 leading-snug">
                    <span className="mr-1">→</span>{ins.action}
                  </div>
                )}

                <div className="flex flex-wrap items-center gap-1.5 mt-auto pt-1">
                  {cs.map((c) => (
                    <span key={c.label} className="text-[10px] font-semibold text-ink-500 bg-ink-50 rounded-md px-1.5 py-0.5">
                      {c.label} <span className="text-ink-800">{c.value}</span>
                    </span>
                  ))}
                  <div className="ml-auto flex items-center gap-2">
                    {act && <ActionButton ins={ins} key={key} />}
                    <span className="text-[10px] font-semibold text-brand-600">
                      {nAffected > 0 ? `view ${nAffected} appt${nAffected === 1 ? '' : 's'}` : 'details'} →
                    </span>
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* drill-down drawer */}
      {selected && (
        <div className="fixed inset-0 z-50" onClick={() => setSelected(null)}>
          <div className="absolute inset-0 bg-ink-900/30 backdrop-blur-[2px] animate-fadein" />
          <div onClick={(e) => e.stopPropagation()}
            className="absolute right-0 top-0 h-full w-full max-w-md bg-white shadow-2xl flex flex-col animate-slidein">
            <div className="flex items-start justify-between px-5 py-4 border-b border-ink-100 gap-3">
              <div className="flex items-start gap-3">
                <div className={`w-10 h-10 rounded-xl flex items-center justify-center text-xl shrink-0 ${(SEV[selected.severity] || SEV.info).icon}`}>
                  {KIND_ICON[selected.kind] || '📌'}
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] font-bold uppercase tracking-wider text-ink-400">
                      {KIND_LABEL[selected.kind] || selected.kind}
                    </span>
                    <span className={`badge ${(SEV[selected.severity] || SEV.info).badge}`}>{selected.severity}</span>
                  </div>
                  <div className="font-extrabold text-ink-900 mt-0.5">{selected.title}</div>
                  {selected.resource_name && (
                    <div className="text-xs text-ink-400">Resource: {selected.resource_name}</div>
                  )}
                </div>
              </div>
              <button onClick={() => setSelected(null)} className="btn-ghost !px-2.5 !py-2 shrink-0" title="Close">
                <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" /></svg>
              </button>
            </div>

            <div className="flex-1 overflow-y-auto p-5 space-y-4">
              <p className="text-sm text-ink-600 leading-relaxed">{selected.detail}</p>

              {selected.action && (
                <div className="rounded-xl bg-brand-50 border border-brand-100 p-3">
                  <div className="label !mb-1">Recommended action</div>
                  <div className="text-sm font-semibold text-brand-800">{selected.action}</div>
                  <div className="mt-2">
                    <ActionButton ins={selected} key={`drawer-${selected.kind}-${selected.resource_id}`} big />
                  </div>
                </div>
              )}

              <div>
                <div className="label">Affected ({rowsFor(selected).length})</div>
                {rowsFor(selected).length === 0 ? (
                  <div className="text-sm text-ink-400 py-4 text-center">
                    No specific appointments — this flags available capacity to absorb demand.
                  </div>
                ) : (
                  <div className="space-y-2">
                    {rowsFor(selected).map((r) => (
                      <div key={r.key} className="card p-3 flex items-center justify-between gap-3">
                        <div className="min-w-0">
                          <div className="font-semibold text-ink-800 truncate">
                            {r.type === 'chemo' ? '💉 ' : r.type === 'consult' ? '🩺 ' : ''}{r.primary}
                          </div>
                          {r.secondary && <div className="text-xs text-ink-400 truncate">{r.secondary}</div>}
                        </div>
                        {r.badge && <span className={`badge shrink-0 ${BADGE_TONE[r.badge] || 'bg-ink-100 text-ink-600'}`}>{String(r.badge).replace('_', ' ')}</span>}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </section>
  )
}
