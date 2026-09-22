import { useMemo, useState } from 'react'
import { Donut, HoursBar, Legend, PALETTE } from './Charts'
import StatCard from './StatCard'
import Insights from './Insights'

function toMin(hhmm: string) { const [h, m] = (hhmm || '0:0').split(':').map(Number); return (h || 0) * 60 + (m || 0) }

export default function Dashboard({ state }: { state: any }) {
  const appts = state.appointments

  const stats = useMemo(() => {
    const doctors = state.doctors
    const rooms = state.rooms
    const availD = doctors.filter((d: any) => d.status === 'available').length
    const availR = rooms.filter((r: any) => r.status === 'available').length
    // "active schedule" = every appointment that has a status we still track
    // (booked, active, rescheduled, overrun, no_show). We deliberately do NOT
    // exclude no_show/overrun so the demo never shows an all-zero dashboard just
    // because the wall clock has passed the seeded slot times.
    const active = appts.filter((a: any) =>
      ['booked', 'active', 'rescheduled', 'overrun', 'no_show'].includes(a.status))
    const chemo = active.filter((a: any) => a.type === 'chemo').length
    const consult = active.filter((a: any) => a.type === 'consult').length
    const overruns = appts.filter((a: any) => a.status === 'overrun').length
    const noShows = appts.filter((a: any) => a.status === 'no_show').length
    const resched = appts.filter((a: any) => a.status === 'rescheduled').length

    // emergencies (a separate object from appointments — track them explicitly)
    const emgs = state.emergencies
    const waitingEmg = emgs.filter((e: any) => e.status === 'waiting').length
    const assignedEmg = emgs.filter((e: any) => e.status === 'assigned').length
    const totalEmg = emgs.length
    const criticalEmg = emgs.filter((e: any) => e.severity >= 4).length

    // "live now" = only genuinely in-progress sessions (drives occupancy + busy staff)
    const live = appts.filter((a: any) => ['booked', 'active'].includes(a.status))

    // busy doctors (with >=1 live appt OR an assigned emergency)
    const busyDoctors = new Set([
      ...live.map((a: any) => a.doctor_id),
      ...emgs.filter((e: any) => e.status === 'assigned' && e.assigned_doctor_id).map((e: any) => e.assigned_doctor_id),
    ]).size

    // occupancy by room (alphabetical) — only live sessions occupy a room
    const roomData = [...rooms]
      .sort((a: any, b: any) => a.name.localeCompare(b.name))
      .map((r: any) => {
        const cnt = live.filter((a: any) => a.room_id === r.id).length
        return { name: r.name.replace('Infusion ', 'Inf ').replace('Isolation ', 'Iso '), value: cnt }
      })
      .filter((d: any) => d.value > 0)

    // appointments per hour (full-day schedule, all tracked statuses)
    const hourCounts: Record<number, number> = {}
    active.forEach((a: any) => {
      const h = Math.floor(toMin(a.slot_start) / 60)
      hourCounts[h] = (hourCounts[h] || 0) + 1
    })
    const hours = Object.keys(hourCounts).map(Number).sort((a, b) => a - b)
      .map((h) => ({ hour: `${String(h).padStart(2, '0')}:00`, count: hourCounts[h] }))

    const occupancyPct = rooms.length ? Math.round((availR / rooms.length) * 100) : 0

    return {
      availD, doctors: doctors.length, availR, rooms: rooms.length,
      active: active.length, chemo, consult, overruns, noShows, resched,
      waitingEmg, assignedEmg, totalEmg, criticalEmg,
      busyDoctors, roomData, hours, occupancyPct, live,
    }
  }, [state, appts])

  const statusData = [
    { name: 'Booked', value: appts.filter((a: any) => a.status === 'booked').length },
    { name: 'Active', value: appts.filter((a: any) => a.status === 'active').length },
    { name: 'Overrun', value: stats.overruns },
    { name: 'Resched.', value: stats.resched },
    { name: 'No-show', value: stats.noShows },
  ].filter((d) => d.value > 0)

  const typeData = [
    { name: 'Chemo', value: stats.chemo },
    { name: 'Consult', value: stats.consult },
  ]

  const emergencyData = [
    { name: 'Critical', value: state.emergencies.filter((e: any) => e.severity === 5).length },
    { name: 'Urgent', value: state.emergencies.filter((e: any) => e.severity === 4).length },
    { name: 'High', value: state.emergencies.filter((e: any) => e.severity === 3).length },
    { name: 'Moderate', value: state.emergencies.filter((e: any) => e.severity === 2).length },
    { name: 'Low', value: state.emergencies.filter((e: any) => e.severity === 1).length },
  ].filter((d: any) => d.value > 0)

  // ---- clickable drill-down: every box opens a list of the exact items behind it ----
  const [drill, setDrill] = useState<{ title: string; icon: string; items: any[]; empty: string } | null>(null)
  const doctorById = useMemo(() => Object.fromEntries(state.doctors.map((d: any) => [d.id, d])), [state.doctors])
  const roomById = useMemo(() => Object.fromEntries(state.rooms.map((r: any) => [r.id, r])), [state.rooms])
  const patientName = (id: string) => state.patients.find((p: any) => p.id === id)?.name || id

  const apptRow = (a: any) => ({
    key: a.id,
    primary: `${a.slot_start}–${a.slot_end} · ${patientName(a.patient_id)}`,
    secondary: `${doctorById[a.doctor_id]?.name || ''}${a.room_id ? ' · ' + (roomById[a.room_id]?.name || '') : ''}`,
    badge: a.status,
    type: a.type,
  })

  function openAppts(title: string, icon: string, list: any[], empty: string) {
    setDrill({ title, icon, items: list.map(apptRow), empty })
  }

  return (
    <div className="space-y-5">
      {/* KPI row — every card is clickable and drills into its exact items */}
      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3">
        <StatCard label="Doctors" value={`${stats.availD}/${stats.doctors}`} sub="available" icon="👩‍⚕️" tone="brand"
          onClick={() => setDrill({
            title: 'Doctors', icon: '👩‍⚕️', empty: 'No doctors',
            items: state.doctors.map((d: any) => ({ key: d.id, primary: d.name, secondary: d.specialty, badge: d.status })),
          })} />
        <StatCard label="Rooms" value={`${stats.availR}/${stats.rooms}`} sub={`${stats.occupancyPct}% up`} icon="🛏️" tone="emerald"
          onClick={() => setDrill({
            title: 'Rooms', icon: '🛏️', empty: 'No rooms',
            items: state.rooms.map((r: any) => ({ key: r.id, primary: r.name, secondary: r.type, badge: r.status })),
          })} />
        <StatCard label="Scheduled" value={stats.active} sub="active today" icon="🗓️" tone="violet"
          onClick={() => openAppts('Scheduled appointments', '🗓️',
            appts.filter((a: any) => ['booked', 'active', 'rescheduled', 'overrun', 'no_show'].includes(a.status)),
            'No scheduled appointments')} />
        <StatCard label="Chemo" value={stats.chemo} sub={`${stats.consult} consults`} icon="💉" tone="brand"
          onClick={() => openAppts('Chemo & consult sessions', '💉',
            appts.filter((a: any) => ['booked', 'active', 'rescheduled', 'overrun', 'no_show'].includes(a.status) && a.type === 'chemo').concat(
              appts.filter((a: any) => ['booked', 'active', 'rescheduled', 'overrun', 'no_show'].includes(a.status) && a.type === 'consult')),
            'No sessions')} />
        <StatCard label="Overruns" value={stats.overruns} sub={`${stats.noShows} no-shows`} icon="⏱️" tone="amber" alert={stats.overruns > 0}
          onClick={() => openAppts('Overruns & no-shows', '⏱️',
            appts.filter((a: any) => ['overrun', 'no_show'].includes(a.status)),
            'No overruns or no-shows')} />
        <StatCard label="Emergencies" value={stats.totalEmg}
          sub={`${stats.waitingEmg} waiting · ${stats.assignedEmg} assigned`} icon="🚨" tone="rose"
          alert={stats.waitingEmg > 0 || stats.criticalEmg > 0}
          onClick={() => setDrill({
            title: 'Emergencies', icon: '🚨', empty: 'No emergencies',
            items: state.emergencies.map((e: any) => ({
              key: e.id, primary: `Severity ${e.severity} · ${patientName(e.patient_id)}`,
              secondary: doctorById[e.assigned_doctor_id]?.name ? '→ ' + doctorById[e.assigned_doctor_id].name : 'unassigned',
              badge: e.status,
            })),
          })} />
      </div>

      {/* Proactive insights — forward-looking bottlenecks + recommendations */}
      <Insights insights={state.insights || []} now={state.insights_now} state={state} />

      {/* Charts row — each card is clickable and drills into its exact items */}
      <div className="grid lg:grid-cols-4 gap-4">
        <div className="card p-5 cursor-pointer card-hover"
          onClick={() => openAppts('Appointments by type', '📊',
            appts.filter((a: any) => ['booked', 'active', 'rescheduled', 'overrun', 'no_show'].includes(a.status)),
            'No appointments')}>
          <h3 className="font-bold text-ink-900">Appointments by type</h3>
          <p className="text-xs text-ink-400 mb-1">Active schedule composition · click for list</p>
          <Donut data={typeData} centerLabel="active" centerValue={stats.active} />
          <Legend data={typeData} />
        </div>

        <div className="card p-5 cursor-pointer card-hover"
          onClick={() => openAppts('Status breakdown', '📊', appts, 'No appointments')}>
          <h3 className="font-bold text-ink-900">Status breakdown</h3>
          <p className="text-xs text-ink-400 mb-1">Where every appointment stands · click for list</p>
          <Donut data={statusData} centerLabel="total" centerValue={appts.length} />
          <Legend data={statusData} />
        </div>

        <div className="card p-5 cursor-pointer card-hover"
          onClick={() => setDrill({
            title: 'Emergencies by severity', icon: '🚨', empty: 'No emergencies',
            items: state.emergencies.map((e: any) => ({
              key: e.id, primary: `Severity ${e.severity} · ${patientName(e.patient_id)}`,
              secondary: doctorById[e.assigned_doctor_id]?.name ? '→ ' + doctorById[e.assigned_doctor_id].name : 'unassigned',
              badge: e.status,
            })),
          })}>
          <h3 className="font-bold text-ink-900">Emergencies by severity</h3>
          <p className="text-xs text-ink-400 mb-1">All registered emergencies · click for list</p>
          {emergencyData.length === 0 ? (
            <Empty>No emergencies yet</Empty>
          ) : (
            <>
              <Donut data={emergencyData} centerLabel="total" centerValue={stats.totalEmg} />
              <Legend data={emergencyData} />
            </>
          )}
        </div>

        <div className="card p-5 cursor-pointer card-hover"
          onClick={() => setDrill({
            title: 'Room utilization', icon: '🛏️', empty: 'No room usage',
            items: state.rooms.map((r: any) => ({
              key: r.id, primary: r.name,
              secondary: stats.live.filter((a: any) => a.room_id === r.id).length + ' active session(s)',
              badge: r.status,
            })),
          })}>
          <h3 className="font-bold text-ink-900">Room utilization</h3>
          <p className="text-xs text-ink-400 mb-3">Active sessions per chemo room · click for list</p>
          {stats.roomData.length === 0 ? (
            <Empty>No room usage yet</Empty>
          ) : (
            <>
              <Donut data={stats.roomData} centerLabel="sessions" centerValue={stats.roomData.reduce((s: number, d: any) => s + d.value, 0)} />
              <Legend data={stats.roomData} />
            </>
          )}
        </div>
      </div>

      {/* Hourly load */}
      <div className="grid lg:grid-cols-3 gap-4">
        <div className="card p-5 lg:col-span-2 cursor-pointer card-hover"
          onClick={() => openAppts('Hourly load — all scheduled', '📈',
            appts.filter((a: any) => ['booked', 'active', 'rescheduled', 'overrun', 'no_show'].includes(a.status)),
            'No appointments')}>
          <h3 className="font-bold text-ink-900">Hourly load</h3>
          <p className="text-xs text-ink-400 mb-3">Scheduled appointments per hour · click for list</p>
          {stats.hours.length === 0 ? <Empty>No appointments to chart</Empty> : <HoursBar data={stats.hours} />}
        </div>

        <div className="card p-5">
          <h3 className="font-bold text-ink-900 mb-3">Workforce</h3>
          <div className="space-y-3">
            <Meter label="Doctors on shift" value={stats.busyDoctors} max={stats.doctors} tone={PALETTE[0]} />
            <Meter label="Rooms available" value={stats.availR} max={stats.rooms} tone={PALETTE[1]} />
            <div className="pt-3 border-t border-ink-100 grid grid-cols-2 gap-3 text-center">
              <MiniStat label="Rescheduled" value={stats.resched}
                onClick={() => openAppts('Rescheduled', '🔁', appts.filter((a: any) => a.status === 'rescheduled'), 'No rescheduled appointments')} />
              <MiniStat label="No-shows" value={stats.noShows}
                onClick={() => openAppts('No-shows', '🚫', appts.filter((a: any) => a.status === 'no_show'), 'No no-shows')} />
            </div>
          </div>
        </div>
      </div>

      {/* drill-down drawer */}
      {drill && <DrillDrawer drill={drill} onClose={() => setDrill(null)} />}
    </div>
  )
}

function Meter({ label, value, max, tone }: { label: string; value: number; max: number; tone: string }) {
  const pct = max ? Math.round((value / max) * 100) : 0
  return (
    <div>
      <div className="flex justify-between text-xs font-semibold text-ink-600 mb-1">
        <span>{label}</span><span className="text-ink-400">{value}/{max}</span>
      </div>
      <div className="h-2.5 rounded-full bg-ink-100 overflow-hidden">
        <div className="h-full rounded-full transition-all" style={{ width: `${pct}%`, background: tone }} />
      </div>
    </div>
  )
}

function MiniStat({ label, value, onClick }: { label: string; value: number; onClick?: () => void }) {
  return (
    <div onClick={onClick}
      className={`rounded-xl bg-ink-50 py-3 ${onClick ? 'cursor-pointer hover:bg-ink-100 transition' : ''}`}>
      <div className="text-xl font-extrabold text-ink-900">{value}</div>
      <div className="text-[11px] font-semibold text-ink-400 uppercase tracking-wide">{label}{onClick ? ' ·' : ''}</div>
    </div>
  )
}

const BADGE_TONE: Record<string, string> = {
  booked: 'bg-brand-100 text-brand-700',
  active: 'bg-emerald-100 text-emerald-700',
  overrun: 'bg-amber-100 text-amber-700',
  rescheduled: 'bg-violet-100 text-violet-700',
  no_show: 'bg-rose-100 text-rose-700',
  visited: 'bg-emerald-100 text-emerald-700',
  waiting: 'bg-amber-100 text-amber-700',
  assigned: 'bg-brand-100 text-brand-700',
  resolved: 'bg-emerald-100 text-emerald-700',
  available: 'bg-emerald-100 text-emerald-700',
  on_leave: 'bg-amber-100 text-amber-700',
  unavailable: 'bg-rose-100 text-rose-700',
  partially_unavailable: 'bg-violet-100 text-violet-700',
}

function DrillDrawer({ drill, onClose }: {
  drill: { title: string; icon: string; items: any[]; empty: string }
  onClose: () => void
}) {
  return (
    <div className="fixed inset-0 z-50" onClick={onClose}>
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
          <button onClick={onClose} className="btn-ghost !px-2.5 !py-2" title="Close">
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
                {it.badge && <span className={`badge shrink-0 ${BADGE_TONE[it.badge] || 'bg-ink-100 text-ink-600'}`}>{it.badge.replace('_', ' ')}</span>}
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  )
}

function Empty({ children }: { children: React.ReactNode }) {
  return <div className="text-sm text-ink-400 py-10 text-center">{children}</div>
}
