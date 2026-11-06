import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import { Icon, Message } from './icons'

// The controls a doctor already uses in the corridor — "send the next one in",
// "I'm closing at one" — plus the record of what the scheduler did to their
// day and a way to put it back.
//
// Nothing here acts on another doctor's list: the backend refuses it and the
// UI never offers it.

export default function DayControls({ state, doctorId }: {
  state: any; doctorId: string
}) {
  const [busy, setBusy] = useState('')
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const [closeAt, setCloseAt] = useState('13:00')
  const [plan, setPlan] = useState<any | null>(null)
  const [history, setHistory] = useState<any[]>([])

  const me = state.doctors.find((d: any) => d.id === doctorId)

  async function loadHistory() {
    try { setHistory((await api.actions(doctorId, 12)).actions || []) }
    catch { /* history is a convenience; never block the page on it */ }
  }
  useEffect(() => { loadHistory() }, [doctorId, state.appointments])

  async function run(key: string, fn: () => Promise<any>) {
    setBusy(key); setMsg(null)
    try {
      const r = await fn()
      setMsg({ ok: r.success !== false, text: r.message || 'done' })
      await loadHistory()
      return r
    } catch (e: any) {
      setMsg({ ok: false, text: e.message })
      return null
    } finally { setBusy('') }
  }

  async function previewClose() {
    const r = await run('plan', () => api.closeList(doctorId, closeAt, false))
    if (r) setPlan(r.data || null)
  }

  async function applyClose() {
    const r = await run('apply', () => api.closeList(doctorId, closeAt, true))
    if (r?.success) setPlan(null)
  }

  if (!doctorId) return null

  return (
    <div className="card p-5">
      <div className="flex items-center gap-2 mb-1">
        <Icon name="stethoscope" className="w-5 h-5 text-brand-600 shrink-0" />
        <h3 className="font-bold text-ink-900">My day</h3>
        {me && <span className="text-xs text-ink-400">{me.name}</span>}
      </div>
      <div className="text-xs text-ink-500 mb-3">
        Your list only. Every change below is recorded with its reason and can be undone.
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <button className="btn-primary" disabled={busy !== ''}
          onClick={() => run('pull', () => api.pullForward(doctorId))}>
          {busy === 'pull' ? '…' : 'Send next patient in'}
        </button>

        <div className="flex items-end gap-2">
          <div>
            <label className="label" htmlFor="close-at">Close my list at</label>
            <input id="close-at" type="time" className="input !py-1.5"
              value={closeAt} onChange={(e) => setCloseAt(e.target.value)} />
          </div>
          <button className="btn-ghost !py-1.5" disabled={busy !== ''}
            onClick={previewClose}>
            {busy === 'plan' ? '…' : 'Show who it affects'}
          </button>
        </div>
      </div>

      {plan && (
        <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50/60 p-3">
          {plan.plan?.length === 0 ? (
            <div className="text-sm text-ink-600">Nothing booked after {closeAt}.</div>
          ) : (
            <>
              <div className="text-sm font-semibold text-ink-800 mb-2">
                {plan.plan.length} patient(s) after {closeAt}
              </div>
              <div className="space-y-1.5">
                {plan.plan.map((p: any) => (
                  <div key={p.appointment_id}
                    className="flex items-center gap-2 flex-wrap text-sm">
                    <span className="font-semibold text-ink-900 w-14">{p.was}</span>
                    <span className="text-ink-800">{p.patient_name}</span>
                    {p.covered ? (
                      <span className="badge bg-emerald-100 text-emerald-700">
                        → {p.to_doctor_name} at {p.to_slot}
                      </span>
                    ) : (
                      <span className="badge bg-rose-100 text-rose-700">no cover available</span>
                    )}
                  </div>
                ))}
              </div>
              <div className="mt-3 flex gap-2 flex-wrap">
                <button className="btn-primary !py-1.5" disabled={busy !== ''}
                  onClick={applyClose}>
                  {busy === 'apply' ? '…' : `Close the list — move ${plan.plan.filter((p: any) => p.covered).length}`}
                </button>
                <button className="btn-ghost !py-1.5" onClick={() => setPlan(null)}>
                  Keep my list open
                </button>
              </div>
              {plan.uncovered?.length > 0 && (
                <div className="mt-2 text-xs text-rose-700">
                  {plan.uncovered.length} patient(s) have no cover and will stay on your list.
                </div>
              )}
            </>
          )}
        </div>
      )}

      {msg && <div className="mt-3 text-sm bg-ink-50 rounded-lg px-3 py-2"><Message ok={msg.ok} text={msg.text} /></div>}

      {/* what changed, and why */}
      <div className="mt-4 pt-4 border-t border-ink-100">
        <div className="text-xs font-bold text-ink-500 uppercase tracking-wide mb-2">
          What changed on your list
        </div>
        {history.length === 0 ? (
          <div className="text-sm text-ink-400">Nothing has moved today.</div>
        ) : (
          <div className="space-y-1.5">
            {history.map((h: any) => (
              <div key={h.id}
                className={`rounded-xl border px-3 py-2 flex items-start gap-3 flex-wrap ${
                  h.undone ? 'border-ink-100 bg-ink-50/60' : 'border-ink-200'}`}>
                <span className="text-xs text-ink-400 w-11 shrink-0 pt-0.5">{h.at}</span>
                <div className="min-w-0 grow basis-48">
                  <div className={`text-sm ${h.undone ? 'text-ink-400 line-through' : 'text-ink-900'}`}>
                    {h.summary}
                  </div>
                  <div className="text-xs text-ink-500">
                    {h.why}{h.by && h.by !== 'system' ? ` · by ${h.by}` : h.by === 'system' ? ' · automatic' : ''}
                  </div>
                </div>
                {h.undone ? (
                  <span className="badge bg-ink-100 text-ink-500">undone</span>
                ) : h.blocked_by ? (
                  <span className="badge bg-ink-100 text-ink-500"
                    title={`"${h.blocked_by}" happened afterwards`}>superseded</span>
                ) : h.reversible ? (
                  <button className="btn-ghost !py-1 text-xs" disabled={busy !== ''}
                    onClick={() => run('undo' + h.id, () => api.undoAction(h.id))}>
                    {busy === 'undo' + h.id ? '…' : 'Undo'}
                  </button>
                ) : null}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
