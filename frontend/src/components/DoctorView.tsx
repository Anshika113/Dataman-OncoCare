import { useEffect, useMemo, useState } from 'react'
import { api, getDoctorId } from '../lib/api'
import StatCard from './StatCard'
import Insights from './Insights'
import Outcomes from './Outcomes'
import { Icon, type IconName } from './icons'

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
  // The day list, each row carrying what the doctor needs before the patient
  // walks in. It is a reading of data the system already holds.
  const [ctxRows, setCtxRows] = useState<any[]>([])
  useEffect(() => {
    let live = true
    const me = getDoctorId()
    if (!me) { setCtxRows([]); return }
    api.dayContext(me)
      .then((r) => { if (live) setCtxRows(r.rows || []) })
      .catch(() => { if (live) setCtxRows([]) })
    return () => { live = false }
  }, [state.appointments, state.investigations])

  const myId = getDoctorId()
  const me = state.doctors.find((d: any) => d.id === myId) || state.doctors[0]
  const myDocId = me?.id

  const patientById = useMemo(() => Object.fromEntries(state.patients.map((p: any) => [p.id, p])), [state.patients])
  const doctorById = useMemo(() => Object.fromEntries(state.doctors.map((d: any) => [d.id, d])), [state.doctors])
  const patientName = (id: string) => patientById[id]?.name || id

  // ---- "my" data (scoped to the logged-in doctor AND the active working day) ----
  const myAppts = state.appointments.filter(
    (a: any) => a.doctor_id === myDocId && a.date === state.active_day)
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
  const [drill, setDrill] = useState<{ title: string; icon: IconName; items: any[]; empty: string } | null>(null)
  const apptRow = (a: any) => ({
    key: a.id,
    primary: `${a.slot_start}–${a.slot_end} · ${patientName(a.patient_id)}`,
    secondary: a.type === 'chemo' ? 'Chemo' : 'Consult',
    badge: a.status,
  })
  function openAppts(title: string, icon: IconName, list: any[], empty: string) {
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
        <StatCard label="My scheduled" value={myScheduledCount} sub="all my appts" icon="calendar" tone="brand"
          onClick={() => openAppts('My scheduled appointments', 'calendar',
            myAppts.filter((a: any) => ['booked', 'active', 'rescheduled', 'overrun', 'no_show'].includes(a.status)),
            'No scheduled appointments')} />
        <StatCard label="In visit now" value={myActive.length} sub="active sessions" icon="stethoscope" tone="emerald"
          onClick={() => openAppts('My active visits', 'stethoscope', myActive, 'No active visits')} />
        <StatCard label="Emergencies" value={emergencies.length}
          sub={`${myAssignedEmg.length} assigned to me`} icon="siren" tone="rose"
          alert={emergencies.length > 0}
          onClick={() => setDrill({
            title: 'Emergencies', icon: 'siren', empty: 'No emergencies',
            items: state.emergencies.map((e: any) => ({
              key: e.id, primary: `S${e.severity} · ${patientName(e.patient_id)}`,
              secondary: e.assigned_doctor_id ? '→ ' + (doctorById[e.assigned_doctor_id]?.name || '') : 'unassigned',
              badge: e.status,
            })),
          })} />
        <StatCard label="Doctors on shift" value={`${availDoctors}/${state.doctors.length}`} sub="available" icon="users" tone="violet"
          onClick={() => setDrill({
            title: 'Doctors', icon: 'users', empty: 'No doctors',
            items: state.doctors.map((d: any) => ({ key: d.id, primary: d.name, secondary: d.specialty, badge: d.status })),
          })} />
      </div>

      {/* Proactive insights — my capacity, rebalance suggestions & clinic bottlenecks */}
      <Outcomes doctorId={getDoctorId()} title="Did it help? — my day" />

      <Insights insights={state.insights || []} now={state.insights_now} state={state} />

      <div className="grid lg:grid-cols-3 gap-4">
        {/* left: my availability summary (manage in the My Availability tab) */}
        <div className="card p-5 space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="font-bold text-ink-900 flex items-center gap-2"><Icon name="clock" className="w-4 h-4 text-brand-600" /> My Availability</h3>
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
          <div className="text-[11px] text-ink-400 flex items-center gap-1.5"><Icon name="info" className="w-3.5 h-3.5 shrink-0" /> Expired leaves auto-clear via the watchdog.</div>
        </div>

        {/* right: emergencies + my schedule */}
        <div className="space-y-4 lg:col-span-2">
          <div className="card p-5">
            <h3 className="font-bold text-ink-900 mb-3 flex items-center gap-2"><Icon name="siren" className="w-4 h-4 text-rose-500" /> Emergencies {myAssignedEmg.length > 0 && <span className="badge bg-rose-100 text-rose-700 ml-1">{myAssignedEmg.length} mine</span>}</h3>
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
            <h3 className="font-bold text-ink-900 mb-3 flex items-center gap-2"><Icon name="calendar" className="w-4 h-4 text-brand-600" /> My Schedule Today</h3>
            {ctxRows.length === 0 ? (
              <div className="text-sm text-ink-400 py-4 text-center">Nothing booked for today</div>
            ) : (
              <div className="space-y-2">
                {ctxRows.slice(0, 10).map((r: any) => (
                  <div key={r.appointment_id}
                    className="rounded-xl border border-ink-200 px-3.5 py-3">
                    <div className="flex items-baseline gap-2 flex-wrap">
                      <span className="text-sm font-extrabold text-ink-900">{r.slot_start}</span>
                      <span className="text-sm font-semibold text-ink-900">{r.patient_name}</span>
                      {r.cycle ? (
                        <span className="badge bg-violet-100 text-violet-700">{r.visit_label}</span>
                      ) : (
                        <span className="badge bg-ink-100 text-ink-600">{r.visit_label}</span>
                      )}
                      {r.regimen && <span className="text-xs text-ink-500">{r.regimen}</span>}
                      {r.room && <span className="text-xs text-ink-400">· {r.room}</span>}
                    </div>

                    {/* What the handing-over doctor wrote. Shown in full
                        rather than behind a tap: a colleague does not write
                        one of these unless it matters. */}
                    {r.handoff_note && (
                      <div className="mt-2 rounded-lg border border-brand-200 bg-brand-50 px-3 py-2">
                        <div className="text-[10px] font-bold uppercase tracking-wide text-brand-700">
                          {r.handoff_from ? `Note from ${r.handoff_from}` : 'Handover note'}
                        </div>
                        <div className="text-[13px] text-ink-800 leading-relaxed mt-0.5">
                          {r.handoff_note}
                        </div>
                      </div>
                    )}

                    {(r.labs?.chips?.length > 0 || r.flags?.length > 0) && (
                      <div className="mt-1.5 flex flex-wrap gap-1.5">
                        {r.labs.chips.map((c: any, i: number) => (
                          <span key={`l${i}`}
                            className={`text-[11px] rounded-lg px-2 py-0.5 border ${
                              c.tone === 'alert' ? 'bg-rose-50 border-rose-200 text-rose-700'
                                : c.tone === 'ok' ? 'bg-emerald-50 border-emerald-200 text-emerald-700'
                                : 'bg-amber-50 border-amber-200 text-amber-700'}`}>
                            {c.text}
                          </span>
                        ))}
                        {r.flags.map((fl: any, i: number) => (
                          <span key={`f${i}`}
                            className={`text-[11px] rounded-lg px-2 py-0.5 border ${
                              fl.tone === 'alert' ? 'bg-rose-50 border-rose-200 text-rose-700'
                                : fl.tone === 'ok' ? 'bg-emerald-50 border-emerald-200 text-emerald-700'
                                : fl.tone === 'info' ? 'bg-brand-50 border-brand-200 text-brand-700'
                                : 'bg-ink-50 border-ink-200 text-ink-600'}`}>
                            {fl.text}
                          </span>
                        ))}
                      </div>
                    )}

                    {(r.notes?.length > 0 || r.last_seen) && (
                      <div className="mt-1.5 text-[11px] text-ink-500">
                        {r.last_seen ? `Last seen ${r.last_seen}` : ''}
                        {r.last_seen && r.notes?.length ? ' · ' : ''}
                        {r.notes?.join(' · ')}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* drill-down drawer */}
      {drill && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4" onClick={() => setDrill(null)}>
          <div className="absolute inset-0 bg-ink-900/30 backdrop-blur-[2px] animate-fadein" />
          <div onClick={(e) => e.stopPropagation()}
            className="relative w-full max-w-md max-h-[85vh] bg-white rounded-2xl shadow-pop flex flex-col overflow-hidden animate-pop">
            <div className="flex items-center justify-between px-5 py-4 border-b border-ink-100 shrink-0">
              <div className="flex items-center gap-3">
                <span className="text-brand-600"><Icon name={drill.icon} className="w-7 h-7" /></span>
                <div>
                  <div className="font-extrabold text-ink-900">{drill.title}</div>
                  <div className="text-xs text-ink-400">{drill.items.length} item{drill.items.length === 1 ? '' : 's'}</div>
                </div>
              </div>
              <button onClick={() => setDrill(null)} className="btn-ghost !px-2.5 !py-2" title="Close">
                <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" /></svg>
              </button>
            </div>
            <div className="overflow-y-auto p-4 space-y-2">
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
