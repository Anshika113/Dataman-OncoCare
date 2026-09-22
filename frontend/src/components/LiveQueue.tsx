import { useState } from 'react'
import { api } from '../lib/api'
import { severityBadge } from './badges'
import type { Caps } from '../lib/roles'

export default function LiveQueue({ state, caps }: { state: any; caps: Caps }) {
  const patientById = Object.fromEntries(state.patients.map((p: any) => [p.id, p]))
  const doctorById = Object.fromEntries(state.doctors.map((d: any) => [d.id, d]))
  const patientsSorted = [...state.patients].sort((a: any, b: any) => a.name.localeCompare(b.name))

  const [patient_id, setPatient] = useState(patientsSorted[0]?.id || '')
  const [severity, setSeverity] = useState(3)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const [assignDoc, setAssignDoc] = useState<Record<string, string>>({})
  const doctorsSorted = [...state.doctors].sort((a: any, b: any) => a.name.localeCompare(b.name))
  const canManage = caps.canEdgeCases // nurse/admin can assign & complete

  const waiting: any[] = state.emergencies
    .filter((e: any) => e.status === 'waiting')
    .sort((a: any, b: any) => (b.severity - a.severity) || (b.subscore - a.subscore))
  const assigned: any[] = state.emergencies.filter((e: any) => e.status === 'assigned')

  async function act(fn: () => Promise<any>) {
    setBusy(true); setMsg('')
    try { const r = await fn(); setMsg(`${r.success ? '✅ ' : '⚠️ '}${r.message}`) }
    catch (e: any) { setMsg('⚠️ ' + e.message) }
    finally { setBusy(false) }
  }

  async function assignTo(e: any) {
    const docId = assignDoc[e.id]
    if (!docId) { setMsg('⚠️ Pick a doctor to assign first'); return }
    setBusy(true); setMsg('')
    try { const r = await api.assignEmergency(e.id, docId); setMsg(`${r.success ? '✅ ' : '⚠️ '}${r.message}`) }
    catch (err: any) { setMsg('⚠️ ' + err.message) }
    finally { setBusy(false) }
  }

  async function complete(e: any) {
    setBusy(true); setMsg('')
    try { const r = await api.completeEmergency(e.id); setMsg(`${r.success ? '✅ ' : '⚠️ '}${r.message}`) }
    catch (err: any) { setMsg('⚠️ ' + err.message) }
    finally { setBusy(false) }
  }

  return (
    <div className="space-y-4">
      {/* register emergency */}
      {caps.canEmergencies ? (
      <div className="card p-5">
        <h3 className="font-bold text-ink-900 mb-3">Register Emergency</h3>
        <div className="flex flex-wrap items-end gap-3">
          <div>
            <label className="label">Patient</label>
            <select className="input" value={patient_id} onChange={(e) => setPatient(e.target.value)}>
              {patientsSorted.map((p: any) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </div>
          <div>
            <label className="label">Severity</label>
            <select className="input" value={severity} onChange={(e) => setSeverity(Number(e.target.value))}>
              <option value={5}>5 — Critical</option>
              <option value={4}>4 — Urgent</option>
              <option value={3}>3 — High</option>
              <option value={2}>2 — Moderate</option>
              <option value={1}>1 — Low</option>
            </select>
          </div>
          <button className="btn-danger" disabled={busy}
            onClick={() => act(() => api.addEmergency(patient_id, severity))}>
            {busy ? '…' : '🚨 Register & auto-assign'}
          </button>
          <button className="btn-ghost" disabled={busy} onClick={() => act(() => api.resolveEmergencies())}>
            Re-run assignment
          </button>
        </div>
        {msg && <div className="mt-3 text-sm text-ink-600 bg-ink-50 rounded-lg px-3 py-2">{msg}</div>}
      </div>
      ) : (
        <div className="card p-4 flex items-center gap-3 text-sm text-ink-500">
          <span className="text-lg">🔒</span>
          Emergency registration requires a nurse or admin. You can view the live queue.
        </div>
      )}

      <div className="grid md:grid-cols-2 gap-4">
        {/* waiting queue */}
        <div className="card p-5">
          <h3 className="font-semibold mb-3 flex items-center gap-2">
            Priority Queue <span className="badge bg-rose-100 text-rose-700">{waiting.length} waiting</span>
          </h3>
          {waiting.length === 0 ? (
            <div className="text-sm text-slate-400 py-6 text-center">No emergencies waiting</div>
          ) : (
            <ul className="space-y-2">
              {waiting.map((e: any, i) => (
                <li key={e.id} className="p-3 rounded-lg bg-rose-50 border border-rose-100 space-y-2">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <span className="w-6 h-6 rounded-full bg-rose-600 text-white text-xs font-bold flex items-center justify-center">{i + 1}</span>
                      <div>
                        <div className="text-sm font-medium">{patientById[e.patient_id]?.name || e.patient_id}</div>
                        <div className="text-xs text-slate-500">since {e.created_at} · subscore {e.subscore} · tier {patientById[e.patient_id]?.priority_tier}</div>
                      </div>
                    </div>
                    <div className="flex items-center gap-2">{severityBadge(e.severity)}</div>
                  </div>
                  {canManage && (
                    <div className="flex items-center gap-2 pl-9">
                      <select className="input !py-1.5 text-xs" value={assignDoc[e.id] || ''}
                        onChange={(ev) => setAssignDoc((m) => ({ ...m, [e.id]: ev.target.value }))}>
                        <option value="">Assign to doctor…</option>
                        {doctorsSorted.map((d: any) => <option key={d.id} value={d.id}>{d.name}</option>)}
                      </select>
                      <button className="btn-primary !py-1.5 text-xs" disabled={busy || !assignDoc[e.id]}
                        onClick={() => assignTo(e)}>Assign</button>
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* assigned + next up */}
        <div className="card p-4">
          <h3 className="font-semibold mb-3">Assigned & Next Up</h3>
          <div className="space-y-2 mb-4">
            {assigned.length === 0 && <div className="text-sm text-slate-400">None assigned</div>}
            {assigned.map((e: any) => (
              <div key={e.id} className="flex items-center justify-between p-3 rounded-lg bg-emerald-50 border border-emerald-100 gap-2">
                <div className="text-sm min-w-0">{patientById[e.patient_id]?.name} → <b>{doctorById[e.assigned_doctor_id]?.name || '—'}</b></div>
                <div className="flex items-center gap-2 shrink-0">
                  {severityBadge(e.severity)}
                  {canManage && (
                    <button className="btn-ghost !px-2.5 !py-1.5 text-xs" disabled={busy}
                      onClick={() => { if (confirm(`Mark this emergency as completed?`)) complete(e) }}>
                      {busy ? '…' : '✓ Complete'}
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>

          <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-400 mb-2">Next in line (booked)</h4>
          <ul className="space-y-1">
            {state.appointments
              .filter((a: any) => a.status === 'booked')
              .sort((a: any, b: any) => a.slot_start.localeCompare(b.slot_start))
              .slice(0, 6)
              .map((a: any) => (
                <li key={a.id} className="flex items-center justify-between text-sm px-2 py-1.5 rounded hover:bg-slate-50">
                  <span>{a.slot_start} · {patientById[a.patient_id]?.name}</span>
                  <span className="text-xs text-slate-400">{doctorById[a.doctor_id]?.name?.replace('Dr. ', '')}</span>
                </li>
              ))}
          </ul>
        </div>
      </div>
    </div>
  )
}
