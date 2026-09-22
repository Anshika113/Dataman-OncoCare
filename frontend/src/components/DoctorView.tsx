import { useMemo, useState } from 'react'
import { getDoctorId } from '../lib/api'
import StatCard from './StatCard'
import Insights from './Insights'
import { statusBadge } from './badges'

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
  on_leave: 'bg-rose-100 text-rose-700',
  partially_unavailable: 'bg-amber-100 text-amber-700',
  unavailable: 'bg-rose-100 text-rose-700',
}

const AVAIL_LABEL: Record<string, string> = {
  available: 'Available',
  on_leave: 'On Leave (full day)',
  partially_unavailable: 'Partially unavailable',
  unavailable: 'Unavailable',
}
const AVAIL_TONE: Record<string, string> = {
  available: 'bg-emerald-100 text-emerald-700',
  on_leave: 'bg-rose-100 text-rose-700',
  partially_unavailable: 'bg-amber-100 text-amber-700',
  unavailable: 'bg-ink-200 text-ink-600',
}

function toMin(hhmm: string) { const [h, m] = (hhmm || '0:0').split(':').map(Number); return (h || 0) * 60 + (m || 0) }

// Focused portal for the doctor role: their own day, clickable KPIs, and a
// self-service leave panel. Everything reads the same live state the admin
// console sees, so any leave a doctor marks shows up in the admin panel
// (and vice-versa) in real time.
export default function DoctorView({ state }: { state: any }) {
  const myId = getDoctorId()
  const me = state.doctors.find((d: any) => d.id === myId) || state.doctors[0]
  const myDocId = me?.id

  const patientById = useMemo(() => Object.fromEntries(state.patients.map((p: any) => [p.id, p])), [state.patients])
  const doctorById = useMemo(() => Object.fromEntries(state.doctors.map((d: any) => [d.id, d])), [state.doctors])
  const patientName = (id: string) => patientById[id]?.name || id

  // ---- "my" data (scoped to the logged-in doctor) ----
  const myAppts = state.appointments.filter((a: any) => a.doctor_id === myDocId)
  const myUpcoming = myAppts
    .filter((a: any) => ['booked', 'rescheduled'].includes(a.status))
    .sort((a: any, b: any) => a.slot_start.localeCompare(b.slot_start))
  const myActive = myAppts.filter((a: any) => a.status === 'active')
  const myScheduledCount = myAppts.filter((a: any) =>
    ['booked', 'active', 'rescheduled', 'overrun', 'no_show'].includes(a.status)).length
  const emergencies = state.emergencies.filter((e: any) => e.status === 'waiting')
  const myAssignedEmg = state.emergencies.filter((e: any) => e.assigned_doctor_id === myDocId && e.status === 'assigned')
  const availDoctors = state.doctors.filter((d: any) => d.status === 'available').length
  const nextUp = myUpcoming[0]

  // ---- clickable drill-down ----
  const [drill, setDrill] = useState<{ title: string; icon: string; items: any[]; empty: string } | null>(null)
  const apptRow = (a: any) => ({
    key: a.id,
    primary: `${a.slot_start}–${a.slot_end} · ${patientName(a.patient_id)}`,
    secondary: a.type === 'chemo' ? '💉 Chemo' : '🩺 Consult',
    badge: a.status,
  })
  function openAppts(title: string, icon: string, list: any[], empty: string) {
    setDrill({ title, icon, items: list.map(apptRow), empty })
  }

  // ---- my active leave windows (read-only here; managed in the My Availability tab) ----
  const myLeaves = (me?.leaves || []).filter((l: any) => !l.cancelled)
    .sort((a: any, b: any) => toMin(a.start) - toMin(b.start))

  return (
    <div className="space-y-5">
      {/* header: who am I + availability */}
      <div className="card p-4 flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <div className="w-11 h-11 rounded-full bg-brand-100 text-brand-700 flex items-center justify-center text-lg font-bold">
            {me?.name?.replace('Dr. ', '')?.[0] || '?'}
          </div>
          <div>
            <div className="font-extrabold text-ink-900">{me?.name || 'Doctor'}</div>
            <div className="text-xs text-ink-400 capitalize">{me?.specialty || ''} · {nextUp ? `next: ${nextUp.slot_start} ${patientName(nextUp.patient_id)}` : 'no upcoming today'}</div>
          </div>
        </div>
        <span className={`badge ${AVAIL_TONE[me?.status] || 'bg-ink-100 text-ink-600'}`}>
          {AVAIL_LABEL[me?.status] || me?.status}
        </span>
      </div>

      {/* KPIs — every card is clickable and drills into its exact items */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard label="My scheduled" value={myScheduledCount} sub="all my appts" icon="🗓️" tone="brand"
          onClick={() => openAppts('My scheduled appointments', '🗓️',
            myAppts.filter((a: any) => ['booked', 'active', 'rescheduled', 'overrun', 'no_show'].includes(a.status)),
            'No scheduled appointments')} />
        <StatCard label="In visit now" value={myActive.length} sub="active sessions" icon="🩺" tone="emerald"
          onClick={() => openAppts('My active visits', '🩺', myActive, 'No active visits')} />
        <StatCard label="Emergencies" value={emergencies.length}
          sub={`${myAssignedEmg.length} assigned to me`} icon="🚨" tone="rose"
          alert={emergencies.length > 0}
          onClick={() => setDrill({
            title: 'Emergencies', icon: '🚨', empty: 'No emergencies',
            items: state.emergencies.map((e: any) => ({
              key: e.id, primary: `S${e.severity} · ${patientName(e.patient_id)}`,
              secondary: e.assigned_doctor_id ? '→ ' + (doctorById[e.assigned_doctor_id]?.name || '') : 'unassigned',
              badge: e.status,
            })),
          })} />
        <StatCard label="Doctors on shift" value={`${availDoctors}/${state.doctors.length}`} sub="available" icon="👩‍⚕️" tone="violet"
          onClick={() => setDrill({
            title: 'Doctors', icon: '👩‍⚕️', empty: 'No doctors',
            items: state.doctors.map((d: any) => ({ key: d.id, primary: d.name, secondary: d.specialty, badge: d.status })),
          })} />
      </div>

      {/* Proactive insights — my capacity, rebalance suggestions & clinic bottlenecks */}
      <Insights insights={state.insights || []} now={state.insights_now} state={state} />

      <div className="grid lg:grid-cols-3 gap-4">
        {/* left: my availability summary (manage in the My Availability tab) */}
        <div className="card p-5 space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="font-bold text-ink-900">🕑 My Availability</h3>
            <span className={`badge ${AVAIL_TONE[me?.status] || 'bg-ink-100 text-ink-600'}`}>
              {AVAIL_LABEL[me?.status] || me?.status}
            </span>
          </div>
          <p className="text-xs text-ink-400">
            Use the <b>My Availability</b> tab to take or cancel leave. It syncs
            to the admin console and your schedule live.
          </p>
          <div>
            <div className="label">Active leave windows</div>
            {myLeaves.length === 0 ? (
              <div className="text-sm text-ink-400 py-3 text-center">None — bookable all day</div>
            ) : (
              <ul className="space-y-2">
                {myLeaves.map((l: any) => (
                  <li key={l.id} className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2">
                    <div className="text-sm font-bold text-ink-900">{l.start} – {l.end}</div>
                    <div className="text-xs text-ink-500">{l.date ? `${l.date} · ` : ''}{l.reason}</div>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div className="text-[11px] text-ink-400">💡 Expired leaves auto-clear via the watchdog.</div>
        </div>

        {/* right: emergencies + my schedule */}
        <div className="space-y-4 lg:col-span-2">
          <div className="card p-5">
            <h3 className="font-bold text-ink-900 mb-3">⚡ Emergencies {myAssignedEmg.length > 0 && <span className="badge bg-rose-100 text-rose-700 ml-1">{myAssignedEmg.length} mine</span>}</h3>
            {emergencies.length === 0 ? (
              <div className="text-sm text-ink-400 py-4 text-center">No emergencies waiting</div>
            ) : (
              <ul className="space-y-2">
                {emergencies.sort((a: any, b: any) => b.severity - a.severity).map((e: any) => (
                  <li key={e.id} className="flex items-center justify-between p-3 rounded-lg bg-rose-50 border border-rose-100">
                    <span className="text-sm font-medium">{patientName(e.patient_id)}</span>
                    <span className="badge bg-rose-600 text-white">S{e.severity}</span>
                  </li>
                ))}
              </ul>
            )}
            {myAssignedEmg.length > 0 && (
              <div className="mt-3 pt-3 border-t border-ink-100">
                <div className="label">Assigned to me</div>
                <ul className="space-y-2">
                  {myAssignedEmg.map((e: any) => (
                    <li key={e.id} className="flex items-center justify-between p-2.5 rounded-lg bg-emerald-50 border border-emerald-100 text-sm">
                      <span>{patientName(e.patient_id)} <span className="text-ink-400">· S{e.severity}</span></span>
                      <span className="text-xs text-emerald-700 font-semibold">my patient</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>

          <div className="card p-5">
            <h3 className="font-bold text-ink-900 mb-3">🗓️ My Schedule Today</h3>
            {myUpcoming.length === 0 ? (
              <div className="text-sm text-ink-400 py-4 text-center">No upcoming appointments</div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead className="border-b border-ink-100">
                    <tr>
                      <th className="th !px-3">Time</th>
                      <th className="th !px-3">Patient</th>
                      <th className="th !px-3">Type</th>
                      <th className="th !px-3">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {myUpcoming.slice(0, 10).map((a: any) => (
                      <tr key={a.id} className="border-b border-ink-50">
                        <td className="td !px-3 font-bold text-ink-900">{a.slot_start}</td>
                        <td className="td !px-3">{patientName(a.patient_id)}</td>
                        <td className="td !px-3 text-xs">{a.type === 'chemo' ? '💉 Chemo' : '🩺 Consult'}</td>
                        <td className="td !px-3">{statusBadge(a.status)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* drill-down drawer */}
      {drill && (
        <div className="fixed inset-0 z-50" onClick={() => setDrill(null)}>
          <div className="absolute inset-0 bg-ink-900/30 backdrop-blur-[2px] animate-fadein" />
          <div onClick={(e) => e.stopPropagation()}
            className="absolute right-0 top-0 h-full w-full max-w-md bg-white shadow-2xl flex flex-col animate-slidein">
            <div className="flex items-center justify-between px-5 py-4 border-b border-ink-100">
              <div className="flex items-center gap-3">
                <span className="text-2xl">{drill.icon}</span>
                <div>
                  <div className="font-extrabold text-ink-900">{drill.title}</div>
                  <div className="text-xs text-ink-400">{drill.items.length} item{drill.items.length === 1 ? '' : 's'}</div>
                </div>
              </div>
              <button onClick={() => setDrill(null)} className="btn-ghost !px-2.5 !py-2" title="Close">
                <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" /></svg>
              </button>
            </div>
            <div className="flex-1 overflow-y-auto p-4 space-y-2">
              {drill.items.length === 0 ? (
                <div className="text-sm text-ink-400 py-10 text-center">{drill.empty}</div>
              ) : (
                drill.items.map((it: any) => (
                  <div key={it.key} className="card p-3 flex items-center justify-between gap-3">
                    <div className="min-w-0">
                      <div className="font-semibold text-ink-800 truncate">{it.primary}</div>
                      {it.secondary && <div className="text-xs text-ink-400 truncate">{it.secondary}</div>}
                    </div>
                    {it.badge && <span className={`badge shrink-0 ${BADGE_TONE[it.badge] || 'bg-ink-100 text-ink-600'}`}>{String(it.badge).replace('_', ' ')}</span>}
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
