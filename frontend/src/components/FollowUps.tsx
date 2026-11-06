import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import { Icon, Message } from './icons'
import type { Caps } from '../lib/roles'

// The care coordinator's console.
//
// The desk runs the room in front of them; this lists the patients who are
// no longer in front of anybody — a dropped no-show, a lab nobody chased, an
// arrival nobody called, a message that could not be sent. Each row carries
// the reason and the one action that would clear it.

const TONE: Record<string, string> = {
  critical: 'border-rose-200 bg-rose-50/60',
  warning: 'border-amber-200 bg-amber-50/60',
  info: 'border-ink-200 bg-white',
}
const BADGE: Record<string, string> = {
  critical: 'bg-rose-100 text-rose-700',
  warning: 'bg-amber-100 text-amber-700',
  info: 'bg-ink-100 text-ink-600',
}

export default function FollowUps({ state, caps }: { state: any; caps: Caps }) {
  const [data, setData] = useState<any | null>(null)
  const [busy, setBusy] = useState('')
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)

  async function load() {
    try { setData(await api.followUps()) }
    catch (e: any) { setMsg({ ok: false, text: e.message }) }
  }
  useEffect(() => { load() }, [state.appointments, state.notifications])

  async function run(key: string, fn: () => Promise<any>) {
    setBusy(key); setMsg(null)
    try {
      const r = await fn()
      setMsg({ ok: r.success !== false, text: r.message || 'done' })
      await load()
    } catch (e: any) { setMsg({ ok: false, text: e.message }) }
    finally { setBusy('') }
  }

  const rows: any[] = data?.rows || []
  const counts = data?.counts || {}

  return (
    <div className="space-y-4">
      <div className="card p-5">
        <div className="flex items-center justify-between gap-3 flex-wrap mb-1">
          <div className="flex items-center gap-2">
            <Icon name="users" className="w-5 h-5 text-violet-600 shrink-0" />
            <h3 className="font-bold text-ink-900">Follow-ups</h3>
            {rows.length > 0 && (
              <span className="badge bg-violet-100 text-violet-700">{rows.length}</span>
            )}
          </div>
          <button className="btn-ghost !py-1.5" onClick={load}>Refresh</button>
        </div>
        <div className="text-xs text-ink-500">
          Patients nobody is currently looking after. The desk runs the room;
          this is everyone who has fallen off a list.
        </div>

        {rows.length > 0 && (
          <div className="flex gap-2 flex-wrap mt-3">
            {counts.critical ? <span className="badge bg-rose-100 text-rose-700">{counts.critical} need attention now</span> : null}
            {counts.warning ? <span className="badge bg-amber-100 text-amber-700">{counts.warning} to chase</span> : null}
            {counts.info ? <span className="badge bg-ink-100 text-ink-600">{counts.info} to tidy</span> : null}
          </div>
        )}
      </div>

      {rows.length === 0 ? (
        <div className="card p-8 text-center">
          <div className="text-sm font-semibold text-ink-800">Nobody has fallen off a list.</div>
          <div className="text-xs text-ink-500 mt-1">
            No dropped no-shows, stale lab gates, stranded arrivals or unsent messages.
          </div>
        </div>
      ) : (
        <div className="space-y-2">
          {rows.map((r: any, i: number) => (
            <div key={`${r.kind}-${r.ref}-${i}`}
              className={`rounded-xl border px-4 py-3 ${TONE[r.severity] || TONE.info}`}>
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-sm font-bold text-ink-900">{r.patient_name}</span>
                <span className={`badge ${BADGE[r.severity] || BADGE.info}`}>
                  {r.kind.replace(/_/g, ' ')}
                </span>
                {r.when && <span className="text-xs text-ink-400">{r.when}</span>}
              </div>
              <div className="text-sm text-ink-800 mt-0.5">{r.summary}</div>
              <div className="text-xs text-ink-500">{r.why}</div>

              <div className="mt-2 flex items-center gap-2 flex-wrap">
                <span className="text-xs font-semibold text-ink-700">{r.action}</span>
                {caps.canBook && r.kind === 'waitlist_stale' && (
                  <button className="btn-ghost !py-1 text-xs" disabled={busy !== ''}
                    onClick={() => run('wl' + r.ref, () => api.removeWaitlist(r.ref))}>
                    Take off the waitlist
                  </button>
                )}
                {caps.canCheckin && r.kind === 'stranded' && (
                  <button className="btn-ghost !py-1 text-xs" disabled={busy !== ''}
                    onClick={() => run('call' + r.ref, () => api.callPatient(r.ref))}>
                    Call them in
                  </button>
                )}
                {caps.canBook && r.kind === 'no_show_unrebooked' && (
                  <button className="btn-ghost !py-1 text-xs" disabled={busy !== ''}
                    onClick={() => run('rb' + r.ref,
                      () => api.rescheduleAuto(r.ref, { reason: 'rebooked after a missed visit', allow_backup_doctor: true }))}>
                    Auto-rebook
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {msg && <div className="card p-3 text-sm"><Message ok={msg.ok} text={msg.text} /></div>}
    </div>
  )
}
