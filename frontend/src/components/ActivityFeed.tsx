import { useState } from 'react'
import { statusBadge } from './badges'

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

export default function ActivityFeed({ events, state }: { events: any[]; state: any }) {
  const [tab, setTab] = useState<'events' | 'audit' | 'notifications' | 'resources'>('events')

  const doctorsSorted = [...state.doctors].sort((a: any, b: any) => a.name.localeCompare(b.name))
  const roomsSorted = [...state.rooms].sort((a: any, b: any) => a.name.localeCompare(b.name))

  const TABS: { id: typeof tab; label: string }[] = [
    { id: 'events', label: 'Live events' },
    { id: 'audit', label: 'Audit log' },
    { id: 'notifications', label: 'Notifications' },
    { id: 'resources', label: 'Resources' },
  ]

  return (
    <div className="space-y-4">
      <div className="card p-4 flex items-start gap-3">
        <span className="text-2xl">📜</span>
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
          {state.notifications.length === 0 ? <Empty text="No notifications sent yet." /> : (
            <ul className="space-y-2">
              {[...state.notifications].reverse().map((n: any) => (
                <li key={n.id} className="p-3 rounded-lg bg-slate-50 border border-slate-100">
                  <div className="flex items-center justify-between mb-1">
                    <span className="badge bg-brand-100 text-brand-700 uppercase">{n.channel}</span>
                    <span className="text-xs text-slate-400">{n.sent_at}</span>
                  </div>
                  <div className="text-sm text-slate-700">{n.body}</div>
                </li>
              ))}
            </ul>
          )}
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
