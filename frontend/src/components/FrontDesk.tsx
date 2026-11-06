import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import { Icon, Message } from './icons'
import ScopeBar from './ScopeBar'
import type { Caps } from '../lib/roles'

// Front desk console: the waiting room as a board, plus the day's no-show
// risk. Everything here is read from live state; the only writes are calling
// a patient in, messaging a doctor's affected patients, and a doctor's own
// safety-booking switch.

const STAGE: Record<string, { label: string; tone: string }> = {
  ready: { label: 'Ready', tone: 'bg-emerald-100 text-emerald-700' },
  in_labs: { label: 'In labs', tone: 'bg-amber-100 text-amber-700' },
  with_doctor: { label: 'With doctor', tone: 'bg-brand-100 text-brand-700' },
  not_arrived: { label: 'Not arrived', tone: 'bg-ink-100 text-ink-500' },
  done: { label: 'Seen', tone: 'bg-ink-100 text-ink-400' },
}

const LEVEL: Record<string, string> = {
  high: 'bg-rose-100 text-rose-700',
  medium: 'bg-amber-100 text-amber-700',
  low: 'bg-emerald-100 text-emerald-700',
}

export default function FrontDesk({ state, caps, role, doctorId }: {
  state: any; caps: Caps; role: string; doctorId: string
}) {
  const [busy, setBusy] = useState('')
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const [risk, setRisk] = useState<any | null>(null)
  // A doctor sees their own waiting room first; the desk sees everyone.
  const [mine, setMine] = useState(!!caps.scopeDoctorId)
  const scopeId = mine ? caps.scopeDoctorId : ''
  useEffect(() => { setRisk(null) }, [scopeId])
  const myName = state.doctors.find((d: any) => d.id === caps.scopeDoctorId)?.name || ''

  const board: any[] = (state.arrivals || [])
    .filter((r: any) => !scopeId || r.doctor_id === scopeId)
  const late: any[] = (state.running_late || [])
    .filter((r: any) => !scopeId || r.doctor_id === scopeId)
  const waiting = board.filter((r) => r.stage === 'ready' || r.stage === 'in_labs')
  const nextUp = board.find((r) => r.stage === 'ready') || null

  async function run(key: string, fn: () => Promise<any>) {
    setBusy(key); setMsg(null)
    try {
      const r = await fn()
      setMsg({ ok: r.success !== false, text: r.message || 'done' })
    } catch (e: any) { setMsg({ ok: false, text: e.message }) }
    finally { setBusy('') }
  }

  async function loadRisk() {
    setBusy('risk'); setMsg(null)
    try { setRisk(await api.risk('', scopeId)) }
    catch (e: any) { setMsg({ ok: false, text: e.message }) }
    finally { setBusy('') }
  }

  // Name who a late doctor is holding up. Deliberately does not invent a new
  // time — the clinic does not know one yet, and a wrong promise is worse
  // than none.
  function whoIsAffected(row: any) {
    const affected = board.filter(
      (r) => r.doctor_id === row.doctor_id && (r.stage === 'ready' || r.stage === 'in_labs'))
    setMsg({
      ok: true,
      text: `${affected.length} waiting on ${row.doctor_name}: `
        + affected.map((r) => `${r.patient_name} (${r.waiting_min} min)`).join(', '),
    })
  }

  return (
    <div className="space-y-4">
      {/* running late */}
      {late.length > 0 && (
        <div className="card p-5 border-amber-200">
          <div className="flex items-center gap-2 mb-3">
            <Icon name="alertTriangle" className="w-5 h-5 text-amber-600 shrink-0" />
            <h3 className="font-bold text-ink-900">Running late</h3>
          </div>
          <div className="space-y-2">
            {late.map((l: any) => (
              <div key={l.doctor_id}
                className="rounded-xl border border-amber-200 bg-amber-50/60 px-3.5 py-3 flex items-center gap-3 flex-wrap">
                <span className="text-sm font-bold text-ink-900">{l.doctor_name}</span>
                <span className="badge bg-amber-100 text-amber-700">{l.behind_min} min behind</span>
                <span className="text-xs text-ink-600">
                  {l.affected} waiting · longest {l.longest_wait_min} min · {l.patients.join(', ')}
                </span>
                {caps.canBook && (
                  <button className="btn-ghost !py-1.5 ml-auto"
                    onClick={() => whoIsAffected(l)}>Who is affected?</button>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* arrivals board */}
      <div className="card p-5">
        <div className="flex items-center justify-between gap-3 flex-wrap mb-3">
          <div className="flex flex-col gap-2">
            <h3 className="font-bold text-ink-900">Arrivals board</h3>
            <div className="text-xs text-ink-500">
              {waiting.length} waiting · {scopeId ? 'your patients today' : 'everyone expected today, not just emergencies'}
            </div>
            {caps.scopeDoctorId && caps.canViewDepartment && (
              <ScopeBar mine={mine} setMine={setMine} doctorName={myName} noun="waiting room" />
            )}
          </div>
          {nextUp && caps.canCheckin && (
            <button className="btn-primary" disabled={busy !== ''}
              onClick={() => run('call', () => api.callPatient(nextUp.appointment_id))}>
              {busy === 'call' ? '…' : `Call ${nextUp.token} — ${nextUp.patient_name}`}
            </button>
          )}
        </div>

        {board.length === 0 ? (
          <div className="text-sm text-ink-400">Nothing booked for today.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-[11px] uppercase tracking-wide text-ink-500 border-b border-ink-100">
                  <th className="td !px-3">Token</th>
                  <th className="td !px-3">Patient</th>
                  <th className="td !px-3">Doctor</th>
                  <th className="td !px-3">Due</th>
                  <th className="td !px-3">Arrived</th>
                  <th className="td !px-3">Waiting</th>
                  <th className="td !px-3">Stage</th>
                  <th className="td !px-3"></th>
                </tr>
              </thead>
              <tbody>
                {board.map((r: any) => {
                  const st = STAGE[r.stage] || STAGE.not_arrived
                  return (
                    <tr key={r.appointment_id} className="border-b border-ink-50">
                      <td className="td !px-3 font-extrabold text-brand-700">{r.token || '—'}</td>
                      <td className="td !px-3">
                        <span className="font-semibold text-ink-900">{r.patient_name}</span>
                        {r.walk_in && <span className="badge bg-violet-100 text-violet-700 ml-2">walk-in</span>}
                      </td>
                      <td className="td !px-3 text-ink-600">{r.doctor_name}</td>
                      <td className="td !px-3 text-ink-600">{r.slot_start}</td>
                      <td className="td !px-3 text-ink-600">{r.arrived_at || '—'}</td>
                      <td className={`td !px-3 font-semibold ${
                        r.severity === 'critical' ? 'text-rose-700'
                          : r.severity === 'warning' ? 'text-amber-700' : 'text-ink-500'}`}>
                        {r.waiting_min ? `${r.waiting_min} min` : '—'}
                      </td>
                      <td className="td !px-3"><span className={`badge ${st.tone}`}>{st.label}</span></td>
                      <td className="td !px-3 text-right">
                        {caps.canCheckin && r.stage === 'not_arrived' && (
                          <button className="btn-ghost !py-1 text-xs" disabled={busy !== ''}
                            onClick={() => run('ci' + r.appointment_id,
                              () => api.checkin(r.appointment_id, true))}>Mark arrived</button>
                        )}
                        {caps.canCheckin && r.stage === 'ready' && (
                          <button className="btn-ghost !py-1 text-xs" disabled={busy !== ''}
                            onClick={() => run('call' + r.appointment_id,
                              () => api.callPatient(r.appointment_id))}>Call in</button>
                        )}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
        {msg && <div className="mt-3 text-sm bg-ink-50 rounded-lg px-3 py-2"><Message ok={msg.ok} text={msg.text} /></div>}
      </div>

      {/* no-show risk */}
      <div className="card p-5">
        <div className="flex items-center justify-between gap-3 flex-wrap mb-3">
          <div>
            <h3 className="font-bold text-ink-900">No-show risk</h3>
            <div className="text-xs text-ink-500">
              Scored from attendance history and whether the patient replied. Nothing is overbooked automatically.
            </div>
          </div>
          <button className="btn-ghost" disabled={busy !== ''} onClick={loadRisk}>
            {busy === 'risk' ? '…' : risk ? 'Refresh' : 'Score today'}
          </button>
        </div>

        {!risk ? (
          <div className="text-sm text-ink-400">Not scored yet.</div>
        ) : (
          <>
            <div className="flex gap-2 flex-wrap mb-3">
              <span className="badge bg-rose-100 text-rose-700">{risk.counts.high} high</span>
              <span className="badge bg-amber-100 text-amber-700">{risk.counts.medium} medium</span>
              <span className="badge bg-emerald-100 text-emerald-700">{risk.counts.low} low</span>
            </div>

            <div className="space-y-1.5">
              {risk.rows.slice(0, 8).map((r: any) => (
                <div key={r.appointment_id}
                  className="rounded-xl border border-ink-200 px-3 py-2 flex items-center gap-3 flex-wrap">
                  <span className="text-sm font-bold text-ink-900 w-14">{r.slot_start}</span>
                  <span className="text-sm text-ink-800">{r.patient_name}</span>
                  <span className="text-xs text-ink-500">{r.factors.join(' · ')}</span>
                  <span className={`badge ml-auto ${LEVEL[r.level]}`}>{r.level}</span>
                </div>
              ))}
            </div>

            {risk.needs_doctor_opt_in?.length > 0 && (
              <div className="mt-3 rounded-xl border border-ink-200 bg-ink-50 p-3 text-sm">
                <div className="font-semibold text-ink-800 mb-1">
                  {risk.needs_doctor_opt_in.length} high-risk slot(s) could carry a safety booking
                </div>
                <div className="text-xs text-ink-500">
                  Off until the doctor turns it on for their own clinic — a scheduler must never
                  double-book behind a doctor&rsquo;s back.
                </div>
                {role === 'doctor' && doctorId && (
                  <button className="btn-primary !py-1.5 mt-2" disabled={busy !== ''}
                    onClick={() => run('opt', () => api.setSafetyBooking(doctorId, true))}>
                    Allow safety bookings in my clinic
                  </button>
                )}
              </div>
            )}

            {risk.safety_bookings?.length > 0 && (
              <div className="mt-3 rounded-xl border border-brand-200 bg-brand-50 p-3 text-sm">
                <div className="font-semibold text-brand-800 mb-1">
                  Safety bookings allowed for {risk.safety_bookings.length} slot(s)
                </div>
                <div className="text-xs text-brand-700/80">
                  {risk.safety_bookings.map((s: any) =>
                    `${s.slot_start} ${s.doctor_name}`).join(' · ')}
                </div>
              </div>
            )}

            {risk.remind_early?.length > 0 && (
              <div className="mt-3 text-xs text-ink-500">
                Cheapest first move — {risk.remind_early.length} patient(s) never confirmed:{' '}
                {risk.remind_early.map((r: any) => `${r.patient_name} (${r.slot_start})`).join(', ')}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
