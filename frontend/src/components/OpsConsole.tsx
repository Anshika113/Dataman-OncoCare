import { useState } from 'react'
import { api } from '../lib/api'

function toMin(hhmm: string) { const [h, m] = (hhmm || '0:0').split(':').map(Number); return (h || 0) * 60 + (m || 0) }
function toHHMM(mins: number) { mins = Math.max(0, mins); return `${String(Math.floor(mins / 60)).padStart(2, '0')}:${String(mins % 60).padStart(2, '0')}` }

export default function OpsConsole({ state }: { state: any }) {
  const [busy, setBusy] = useState('')
  const [lastResult, setLastResult] = useState('')
  const [simCount, setSimCount] = useState(() => (JSON.parse(localStorage.getItem('care_sim_ids') || '[]') as string[]).length)

  const patientById = Object.fromEntries(state.patients.map((p: any) => [p.id, p]))

  const roomsSorted = [...state.rooms].sort((a: any, b: any) => a.name.localeCompare(b.name))
  const apptsSorted = [...state.appointments].filter((a: any) => ['booked', 'active'].includes(a.status))
    .sort((a: any, b: any) => a.slot_start.localeCompare(b.slot_start))

  const [apptId, setApptId] = useState(apptsSorted[0]?.id || '')
  const [roomId, setRoomId] = useState(roomsSorted[0]?.id || '')

  async function run(key: string, fn: () => Promise<any>) {
    setBusy(key)
    try {
      const r = await fn()
      setLastResult(`${r.success ? '✅' : '⚠️'} ${r.message}`)
    } catch (e: any) {
      setLastResult(`⚠️ ${e.message}`)
    } finally {
      setBusy('')
    }
  }

  // ---- Demo: generate a realistic busy load so Proactive Insights light up ----
  async function simulateBusy() {
    setBusy('sim')
    try {
      const nowM = toMin(state.insights_now || '12:00')
      // workday is 08:00–18:00; book a packed 2h block fully inside it
      let base = Math.floor(nowM / 30) * 30
      base = Math.max(480, Math.min(base, 960)) // clamp to 08:00..16:00 start
      const inHours = nowM >= 480 && nowM <= 1050 // 08:00..17:30

      // target doctor: available, fewest upcoming sessions (least likely to collide)
      const upcoming = (did: string) => state.appointments
        .filter((a: any) => a.doctor_id === did && ['booked', 'rescheduled', 'active'].includes(a.status)
          && toMin(a.slot_start) >= nowM - 30).length
      const avail = state.doctors.filter((d: any) => d.status === 'available')
      if (!avail.length) throw new Error('no available doctor to load')
      avail.sort((a: any, b: any) => upcoming(a.id) - upcoming(b.id))
      const D1 = avail[0]
      const patients = state.patients
      if (!patients.length) throw new Error('no patients to book')

      const before = new Set((await api.appointments()).map((a: any) => a.id))
      let ok = 0
      for (let i = 0; i < 4; i++) {
        const s = toHHMM(base + i * 30), e = toHHMM(base + i * 30 + 30)
        const p = patients[i % patients.length]
        const r = await api.bookConsult({ patient_id: p.id, doctor_id: D1.id, slot_start: s, slot_end: e })
        if (r.success) ok++
      }
      // check in any simulated session that has already started (keeps the window packed, avoids no-show churn)
      const after = await api.appointments()
      const createdAppts = after.filter((a: any) => !before.has(a.id))
      for (const a of createdAppts) if (toMin(a.slot_start) <= nowM) await api.checkin(a.id, true)
      const created = createdAppts.map((a: any) => a.id)
      const prev = JSON.parse(localStorage.getItem('care_sim_ids') || '[]') as string[]
      localStorage.setItem('care_sim_ids', JSON.stringify([...prev, ...created]))
      setSimCount((prev.length) + created.length)

      const note = inHours
        ? `Proactive Insights now show a bottleneck + rebalance for ${D1.name}.`
        : `Booked inside clinic hours, but the clock (${state.insights_now}) is outside 08:00–17:30, so the live bottleneck won't show until the clock is in-hours.`
      setLastResult(`✅ Simulated busy period: +${ok} back-to-back sessions on ${D1.name} from ${toHHMM(base)} → ${toHHMM(base + 120)}. ${note}`)
    } catch (e: any) {
      setLastResult(`⚠️ ${e.message}`)
    } finally {
      setBusy('')
    }
  }

  async function clearSimulated() {
    setBusy('clear')
    try {
      const ids = JSON.parse(localStorage.getItem('care_sim_ids') || '[]') as string[]
      let n = 0
      for (const id of ids) {
        try { const r = await api.cancelAppointment(id, 'simulated load cleared'); if (r.success) n++ } catch { /* already moved/done */ }
      }
      localStorage.setItem('care_sim_ids', '[]')
      setSimCount(0)
      setLastResult(`✅ Cleared ${n} simulated session(s).`)
    } catch (e: any) {
      setLastResult(`⚠️ ${e.message}`)
    } finally {
      setBusy('')
    }
  }

  return (
    <div className="space-y-4">
      <div className="card p-4 flex items-start gap-3">
        <span className="text-2xl">🛠️</span>
        <div>
          <h3 className="font-bold text-ink-900">Operations Console — Incident Response</h3>
          <p className="text-xs text-ink-400">
            React to live disruptions (overruns, no-shows, room breakdowns, clock). Every action
            is recorded in the <b>Activity</b> tab. Planned leave is managed in the <b>Availability</b> tab.
          </p>
        </div>
      </div>

      <div className="card p-4 border-l-4 border-l-violet-500">
        <div className="flex items-start gap-3">
          <span className="text-2xl">🧪</span>
          <div className="flex-1">
            <h3 className="font-bold text-ink-900">Simulate busy period <span className="badge bg-violet-100 text-violet-700 ml-1">demo</span></h3>
            <p className="text-xs text-ink-400 mt-0.5">
              Books 4 back-to-back sessions on the least-busy doctor for the next two hours so the
              <b> Proactive Insights</b> panel lights up with a <b>bottleneck</b> and a <b>rebalance</b>
              suggestion you can act on. Run it during clinic hours (08:00–17:30) for the live window.
            </p>
            <div className="flex items-center gap-3 mt-3 flex-wrap">
              <button className="btn-primary" disabled={busy === 'sim'} onClick={simulateBusy}>
                {busy === 'sim' ? 'Booking…' : '⚡ Simulate busy period'}
              </button>
              <button className="btn-ghost" disabled={busy === 'clear' || simCount === 0} onClick={clearSimulated}>
                {busy === 'clear' ? 'Clearing…' : `Clear simulated load${simCount ? ` (${simCount})` : ''}`}
              </button>
              {lastResult && <span className="text-xs font-mono text-ink-600 max-w-[520px]">{lastResult}</span>}
            </div>
          </div>
        </div>
      </div>

      <div className="grid md:grid-cols-2 gap-4">
        <Scenario title="A. Chemo session overrun" desc="Flags the active chemo session as overrun (past grace), logs it and auto-pushes the next patient in the room.">
          <Select label="Active chemo session" value={apptId} onChange={setApptId}
            options={apptsSorted.map((a: any) => ({ value: a.id, label: `${a.slot_start} ${patientById[a.patient_id]?.name} (${a.status})` }))} />
          <button className="btn-amber" disabled={busy === 'ov'} onClick={() => run('ov', () => api.overrun(apptId))}>
            {busy === 'ov' ? '…' : 'Log overrun'}
          </button>
        </Scenario>

        <Scenario title="B. Room equipment breakdown" desc="Flags the room unavailable and reassigns affected sessions to a compatible room. Use 'Restore' to bring it back.">
          <Select label="Room" value={roomId} onChange={setRoomId}
            options={roomsSorted.map((r: any) => ({ value: r.id, label: `${r.name} (${r.status})` }))} />
          <div className="flex gap-2">
            <button className="btn-danger" disabled={busy === 'bd'} onClick={() => run('bd', () => api.breakdown(roomId))}>
              {busy === 'bd' ? '…' : 'Report breakdown'}
            </button>
            <button className="btn-primary" disabled={busy === 'rs'} onClick={() => run('rs', () => api.restoreRoom(roomId))}>
              {busy === 'rs' ? '…' : 'Restore room'}
            </button>
          </div>
        </Scenario>

        <Scenario title="C. Patient no-show" desc="Records a no-show, releases the slot and notifies the next patient in the queue.">
          <Select label="Appointment" value={apptId} onChange={setApptId}
            options={apptsSorted.map((a: any) => ({ value: a.id, label: `${a.slot_start} ${patientById[a.patient_id]?.name} (${a.status})` }))} />
          <button className="btn-ghost" disabled={busy === 'ns'} onClick={() => run('ns', () => api.noShow(apptId))}>
            {busy === 'ns' ? '…' : 'Record no-show'}
          </button>
        </Scenario>
      </div>

      <div className="card p-4">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div>
            <h3 className="font-semibold">D. Clock & auto-triggers</h3>
            <p className="text-xs text-slate-500">Advance the wall clock; the engine auto-fires no-show, overrun and leave-expiry watchdogs.</p>
          </div>
          <div className="flex items-center gap-3">
            {lastResult && <span className="text-xs font-mono text-slate-600 max-w-[420px] truncate">{lastResult}</span>}
            <button className="btn-primary" disabled={busy === 'clk'} onClick={() => run('clk', () => api.advanceClock())}>
              {busy === 'clk' ? '…' : '⏱ Advance clock tick'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

function Scenario({ title, desc, children }: { title: string; desc: string; children: React.ReactNode }) {
  return (
    <div className="card p-4">
      <h3 className="font-semibold text-sm">{title}</h3>
      <p className="text-xs text-slate-500 mb-3">{desc}</p>
      <div className="flex flex-wrap items-end gap-2">{children}</div>
    </div>
  )
}

function Select({ label, value, onChange, options }: {
  label: string; value: string; onChange: (v: string) => void; options: { value: string; label: string }[]
}) {
  return (
    <div>
      <label className="label">{label}</label>
      <select className="input min-w-[160px]" value={value} onChange={(e) => onChange(e.target.value)}>
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </div>
  )
}
