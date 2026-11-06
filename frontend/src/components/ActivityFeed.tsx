import { useState } from 'react'
import { api } from '../lib/api'
import { statusBadge } from './badges'
import { Icon, Message } from './icons'
import type { Caps } from '../lib/roles'

// Delivery is a real state now, not a label that always said "pending".
const DELIVERY_TONE: Record<string, string> = {
  pending: 'bg-slate-200 text-slate-600',
  sent: 'bg-blue-100 text-blue-700',
  delivered: 'bg-emerald-100 text-emerald-700',
  failed: 'bg-rose-100 text-rose-700',
  // held because the patient did not agree to be messaged — phone them
  blocked: 'bg-amber-100 text-amber-700',
}

const KIND_TONE: Record<string, string> = {
  sick_leave: 'bg-amber-100 text-amber-700',
  overrun: 'bg-amber-100 text-amber-700',
  overrun_cascade: 'bg-amber-100 text-amber-700',
  breakdown: 'bg-rose-100 text-rose-700',
  no_show: 'bg-slate-200 text-slate-600',
  emergency_assigned: 'bg-rose-100 text-rose-700',
  reschedule: 'bg-violet-100 text-violet-700',
  reschedule_offered: 'bg-violet-100 text-violet-700',
  book: 'bg-blue-100 text-blue-700',
}

export default function ActivityFeed(
  { events, state, caps }: { events: any[]; state: any; caps: Caps },
) {
  const [tab, setTab] = useState<'events' | 'audit' | 'notifications' | 'resources'>('events')

  // Replies are what close the loop: a confirmed patient is a kept slot and a
  // declined one frees it hours before a no-show would have.
  const [replyFor, setReplyFor] = useState<string | null>(null)
  const [replyText, setReplyText] = useState('')
  const [msgBusy, setMsgBusy] = useState(false)
  const [msgOut, setMsgOut] = useState<{ ok: boolean; text: string } | null>(null)
  const patientById = Object.fromEntries(state.patients.map((p: any) => [p.id, p]))

  async function sendReply(id: string) {
    if (!replyText.trim()) return
    setMsgBusy(true); setMsgOut(null)
    try {
      const r = await api.replyNotification(id, replyText.trim())
      setMsgOut({
        ok: true,
        text: `read as "${r.intent}"` + (r.acted?.message ? ` — ${r.acted.message}` : ''),
      })
      setReplyFor(null); setReplyText('')
    } catch (e: any) { setMsgOut({ ok: false, text: e.message }) }
    finally { setMsgBusy(false) }
  }

  const doctorsSorted = [...state.doctors].sort((a: any, b: any) => a.name.localeCompare(b.name))
  const roomsSorted = [...state.rooms].sort((a: any, b: any) => a.name.localeCompare(b.name))

  // The security trail is admin-only on the backend, so a nurse is not shown
  // a tab that would 403 on open.
  const TABS: { id: typeof tab; label: string }[] = [
    { id: 'events', label: 'Live events' },
    ...(caps.canAudit ? [{ id: 'audit' as typeof tab, label: 'Audit log' }] : []),
    { id: 'notifications', label: 'Messages' },
    { id: 'resources', label: 'Resources' },
  ]

  return (
    <div className="space-y-4">
      <div className="card p-4 flex items-start gap-3">
        <span className="text-brand-600"><Icon name="activity" className="w-6 h-6" /></span>
        <div>
          <h3 className="font-bold text-ink-900">Activity & Records</h3>
          <p className="text-xs text-ink-400">
            The single home for everything that happened: live events, the audit trail,
            patient notifications, and current doctor/room status. Actions live in the <b>Ops Console</b>.
          </p>
        </div>
      </div>

      <div className="flex gap-1 flex-wrap">
        {TABS.map((t) => (
          <button key={t.id} onClick={() => setTab(t.id)}
            className={`px-3 py-1.5 text-sm rounded-lg ${tab === t.id ? 'bg-brand-600 text-white' : 'bg-white border border-slate-300 text-slate-600'}`}>
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'events' && (
        <div className="card p-4">
          {events.length === 0 ? <Empty text="No live events yet. Trigger an action in the Ops Console." /> :
            <ul className="space-y-1 font-mono text-sm">
              {events.map((e, i) => (
                <li key={i} className="flex gap-3 items-start p-2 rounded hover:bg-slate-50">
                  <span className="text-slate-400 shrink-0">{e.at}</span>
                  <span className="badge bg-brand-100 text-brand-700 shrink-0">{e.type}</span>
                  <span className="text-slate-600">{e.message || JSON.stringify(e).slice(0, 160)}</span>
                </li>
              ))}
            </ul>}
        </div>
      )}

      {tab === 'audit' && (
        <div className="card overflow-hidden">
          {state.logs.length === 0 ? <Empty text="No audit entries yet." /> : (
            <table className="w-full">
              <thead className="bg-slate-50 border-b border-slate-200">
                <tr><th className="th">Time</th><th className="th">Kind</th><th className="th">Ref</th><th className="th">Before → After</th><th className="th">Reason</th></tr>
              </thead>
              <tbody>
                {[...state.logs].reverse().map((l: any) => (
                  <tr key={l.id} className="border-b border-slate-100">
                    <td className="td text-slate-400">{l.at}</td>
                    <td className="td"><span className={`badge ${KIND_TONE[l.kind] || 'bg-slate-100 text-slate-600'}`}>{l.kind}</span></td>
                    <td className="td font-mono text-xs">{l.appointment_id}</td>
                    <td className="td text-xs font-mono">{l.before || '—'} → {l.after || '—'}</td>
                    <td className="td text-xs text-slate-500">{l.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {tab === 'notifications' && (
        <div className="card p-4">
          <div className="text-xs text-ink-500 mb-3">
            Sent through the <b>{state.messaging_driver || 'log'}</b> driver. Set
            <code className="mx-1">CARE_SMS_WEBHOOK</code> to route these to a real provider.
          </div>
          {state.notifications.length === 0 ? <Empty text="No messages yet." /> : (
            <ul className="space-y-2">
              {[...state.notifications].reverse().map((n: any) => (
                <li key={n.id} className="p-3 rounded-lg bg-slate-50 border border-slate-100">
                  <div className="flex items-center gap-2 mb-1 flex-wrap">
                    <span className="badge bg-brand-100 text-brand-700 uppercase">{n.channel}</span>
                    <span className="text-sm font-semibold text-ink-800">
                      {patientById[n.patient_id]?.name || n.patient_id}
                    </span>
                    {n.kind && <span className="badge bg-violet-100 text-violet-700">{n.kind}</span>}
                    <span className={`badge ${DELIVERY_TONE[n.status] || DELIVERY_TONE.pending}`}>
                      {n.status}{n.delivered_at ? ` ${n.delivered_at}` : ''}
                    </span>
                    <span className="text-xs text-slate-400 ml-auto">{n.sent_at}</span>
                  </div>
                  <div className="text-sm text-slate-700">{n.body}</div>

                  {n.reply ? (
                    <div className="mt-2 text-sm rounded-lg bg-white border border-slate-200 px-3 py-2">
                      <span className="text-xs text-ink-400 mr-2">replied {n.replied_at}</span>
                      <span className="text-ink-800">{n.reply}</span>
                    </div>
                  ) : replyFor === n.id ? (
                    <div className="mt-2 flex items-center gap-2 flex-wrap">
                      <label className="sr-only" htmlFor={`rep-${n.id}`}>Patient reply</label>
                      <input id={`rep-${n.id}`} className="input !py-1.5 text-sm grow min-w-[180px]"
                        value={replyText} placeholder="what the patient replied"
                        onChange={(e) => setReplyText(e.target.value)} />
                      <button className="btn-primary !py-1.5" disabled={msgBusy}
                        onClick={() => sendReply(n.id)}>{msgBusy ? '…' : 'Record'}</button>
                      <button className="btn-ghost !py-1.5" onClick={() => setReplyFor(null)}>Cancel</button>
                    </div>
                  ) : (
                    <button className="mt-2 text-xs underline text-brand-700"
                      onClick={() => { setReplyFor(n.id); setReplyText(''); setMsgOut(null) }}>
                      Record a reply
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}
          {msgOut && <div className="mt-3 text-sm bg-ink-50 rounded-lg px-3 py-2"><Message ok={msgOut.ok} text={msgOut.text} /></div>}
        </div>
      )}

      {tab === 'resources' && (
        <div className="grid md:grid-cols-2 gap-4">
          <div className="card p-4">
            <h3 className="font-semibold mb-2">Doctors</h3>
            <ul className="space-y-1">
              {doctorsSorted.map((d: any) => (
                <li key={d.id} className="flex items-center justify-between text-sm">
                  <span>{d.name}</span>
                  <span className="flex gap-2 items-center">
                    <span className="text-xs text-slate-400">{d.specialty}</span>
                    {statusBadge(d.status)}
                  </span>
                </li>
              ))}
            </ul>
          </div>
          <div className="card p-4">
            <h3 className="font-semibold mb-2">Rooms</h3>
            <ul className="space-y-1">
              {roomsSorted.map((r: any) => (
                <li key={r.id} className="flex items-center justify-between text-sm">
                  <span>{r.name}</span>
                  <span className="flex gap-2 items-center">
                    <span className="text-xs text-slate-400">{r.type}{r.available_until ? ` · until ${r.available_until}` : ''}</span>
                    {statusBadge(r.status)}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}
    </div>
  )
}

function Empty({ text }: { text: string }) {
  return <div className="text-sm text-slate-400 py-8 text-center">{text}</div>
}
