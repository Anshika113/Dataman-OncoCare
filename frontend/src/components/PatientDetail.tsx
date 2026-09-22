import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import { statusBadge, severityBadge } from './badges'

const STATUS_TONE: Record<string, string> = {
  emergency: 'bg-rose-100 text-rose-700',
  active: 'bg-emerald-100 text-emerald-700',
  scheduled: 'bg-blue-100 text-blue-700',
  revisit: 'bg-violet-100 text-violet-700',
  new: 'bg-ink-100 text-ink-600',
}

export default function PatientDetail({ patientId, onClose }: { patientId: string | null; onClose: () => void }) {
  const [data, setData] = useState<any>(null)
  const [loading, setLoading] = useState(false)
  const [msg, setMsg] = useState('')

  useEffect(() => {
    if (!patientId) return
    setLoading(true); setMsg('')
    api.patientHistory(patientId).then(setData).catch((e) => setMsg(e.message))
      .finally(() => setLoading(false))
  }, [patientId])

  async function completeVisit(apptId: string) {
    try {
      const r = await api.completeVisit(apptId)
      setMsg(r.success ? `✅ ${r.message}` : `⚠️ ${r.message}`)
      const fresh = await api.patientHistory(patientId!)
      setData(fresh)
    } catch (e: any) { setMsg(e.message) }
  }

  if (!patientId) return null
  const p = data?.patient

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-ink-950/40 backdrop-blur-sm"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div className="w-full max-w-lg h-full bg-white shadow-pop animate-slidein overflow-y-auto">
        {/* header */}
        <div className="sticky top-0 bg-white/95 backdrop-blur border-b border-ink-100 px-6 py-4 flex items-start justify-between">
          <div className="flex items-center gap-3">
            <div className="w-12 h-12 rounded-2xl bg-brand-100 text-brand-700 flex items-center justify-center text-lg font-extrabold">
              {p?.name?.[0]?.toUpperCase() || '?'}
            </div>
            <div>
              <h2 className="text-lg font-extrabold text-ink-900">{p?.name || '…'}</h2>
              {data && (
                <span className={`badge mt-1 ${STATUS_TONE[data.status.status]}`}>{data.status.label}</span>
              )}
            </div>
          </div>
          <button onClick={onClose} className="text-ink-400 hover:text-ink-700 text-2xl leading-none">×</button>
        </div>

        <div className="p-6 space-y-6">
          {loading && <div className="text-sm text-ink-400 py-8 text-center">Loading…</div>}

          {p && (
            <>
              {/* details grid */}
              <section>
                <h3 className="text-xs font-bold uppercase tracking-wider text-ink-400 mb-3">Details</h3>
                <div className="grid grid-cols-2 gap-x-4 gap-y-3">
                  <Info label="Contact" value={p.contact} />
                  <Info label="MR Number" value={p.mr_number} />
                  <Info label="Age / Gender" value={[p.age, p.gender].filter(Boolean).join(' / ')} />
                  <Info label="Blood group" value={p.blood_group} />
                  <Info label="Diagnosis" value={p.diagnosis} />
                  <Info label="Stage" value={p.stage} />
                  <Info label="Allergies" value={p.allergies || 'None'} accent={!!p.allergies} />
                  <Info label="Insurance" value={p.insurance} />
                </div>
                {p.notes && (
                  <div className="mt-3 text-sm bg-ink-50 rounded-lg px-3 py-2 text-ink-600">📝 {p.notes}</div>
                )}
              </section>

              {/* visit summary */}
              <section className="grid grid-cols-3 gap-3">
                <Stat label="Total visits" value={data.status.visits} />
                <Stat label="Upcoming" value={data.status.upcoming} />
                <Stat label="Emergencies" value={data.emergencies.length} />
              </section>

              {msg && <div className="text-sm text-ink-700 bg-ink-50 rounded-lg px-3 py-2">{msg}</div>}

              {/* appointment history */}
              <section>
                <h3 className="text-xs font-bold uppercase tracking-wider text-ink-400 mb-3">
                  Appointment History ({data.appointments.length})
                </h3>
                {data.appointments.length === 0 ? (
                  <div className="text-sm text-ink-400 py-4 text-center">No appointments yet</div>
                ) : (
                  <ul className="space-y-2">
                    {data.appointments.map((a: any) => (
                      <li key={a.id} className="rounded-xl border border-ink-100 p-3">
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <span className="text-sm font-bold text-ink-900">{a.slot_start}</span>
                            <span className="text-xs text-ink-400">{a.doctor_name}</span>
                            {a.is_revisit && <span className="badge bg-violet-100 text-violet-700">revisit</span>}
                          </div>
                          {statusBadge(a.status)}
                        </div>
                        <div className="text-xs text-ink-500 mt-1">
                          {a.type === 'chemo' ? '💉 Chemo' : '🩺 Consult'}
                          {a.room_name ? ` · Room ${a.room_name}` : ''}
                          {a.visit_count > 0 && ` · Visit #${a.visit_count}`}
                        </div>
                        {['active', 'booked', 'rescheduled'].includes(a.status) && (
                          <button onClick={() => completeVisit(a.id)}
                            className="btn-outline-brand !text-xs !px-2.5 !py-1.5 mt-2">
                            ✓ Mark visit complete
                          </button>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              {/* emergencies */}
              {data.emergencies.length > 0 && (
                <section>
                  <h3 className="text-xs font-bold uppercase tracking-wider text-ink-400 mb-3">Emergencies</h3>
                  <ul className="space-y-2">
                    {data.emergencies.map((e: any) => (
                      <li key={e.id} className="flex items-center justify-between rounded-xl bg-rose-50 border border-rose-100 p-3">
                        <span className="text-sm text-ink-700">Since {e.created_at}</span>
                        <span className="flex gap-2">{severityBadge(e.severity)}{statusBadge(e.status)}</span>
                      </li>
                    ))}
                  </ul>
                </section>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}

function Info({ label, value, accent }: { label: string; value?: string; accent?: boolean }) {
  return (
    <div>
      <div className="text-[11px] font-bold uppercase tracking-wide text-ink-400">{label}</div>
      <div className={`text-sm font-medium ${accent ? 'text-rose-600' : 'text-ink-800'}`}>{value || '—'}</div>
    </div>
  )
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-xl bg-ink-50 py-3 text-center">
      <div className="text-xl font-extrabold text-ink-900">{value}</div>
      <div className="text-[11px] font-semibold text-ink-400 uppercase tracking-wide">{label}</div>
    </div>
  )
}
