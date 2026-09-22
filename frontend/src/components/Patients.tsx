import { useMemo, useState } from 'react'
import { api, getRole } from '../lib/api'
import PatientForm from './PatientForm'
import PatientDetail from './PatientDetail'

const STATUS_TONE: Record<string, string> = {
  emergency: 'bg-rose-100 text-rose-700',
  active: 'bg-emerald-100 text-emerald-700',
  scheduled: 'bg-blue-100 text-blue-700',
  revisit: 'bg-violet-100 text-violet-700',
  new: 'bg-ink-100 text-ink-600',
}

export default function Patients({ state }: { state: any }) {
  const role = getRole()
  const canEdit = role === 'admin' || role === 'nurse'
  const [q, setQ] = useState('')
  const [showForm, setShowForm] = useState(false)
  const [editing, setEditing] = useState<any>(null)
  const [viewing, setViewing] = useState<string | null>(null)

  const patients = useMemo(() => state.patients, [state.patients])
  const filtered = patients
    .filter((p: any) =>
      !q || p.name.toLowerCase().includes(q.toLowerCase()) ||
      (p.mr_number || '').toLowerCase().includes(q.toLowerCase()) ||
      (p.diagnosis || '').toLowerCase().includes(q.toLowerCase()))
    .sort((a: any, b: any) => a.name.localeCompare(b.name))

  async function removePatient(p: any) {
    if (!confirm(`Delete patient "${p.name}"? This cannot be undone.`)) return
    try {
      await api.deletePatient(p.id)
      if (viewing === p.id) setViewing(null)
    } catch (e: any) {
      alert(e.message)
    }
  }

  // derive status for list (mirrors backend _patient_status)
  const statusOf = (p: any) => {
    const appts = state.appointments.filter((a: any) => a.patient_id === p.id)
    const hasEmg = state.emergencies.some((e: any) => e.patient_id === p.id && ['waiting', 'assigned'].includes(e.status))
    if (hasEmg) return { status: 'emergency', label: 'In Emergency' }
    if (appts.some((a: any) => a.status === 'active')) return { status: 'active', label: 'In Visit' }
    if (appts.some((a: any) => ['booked', 'rescheduled'].includes(a.status))) return { status: 'scheduled', label: 'Scheduled' }
    if (appts.some((a: any) => ['visited', 'completed'].includes(a.status) || a.visit_count > 0)) return { status: 'revisit', label: 'Revisit' }
    return { status: 'new', label: 'New Patient' }
  }

  return (
    <div className="space-y-4">
      {/* header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h2 className="text-xl font-extrabold text-ink-900">Doctors & Patients</h2>
          <p className="text-sm text-ink-400">
            {role === 'doctor'
              ? 'Read-only view — your role cannot register or edit patients.'
              : `${state.patients.length} registered · click a patient for full details & history`}
          </p>
        </div>
        {canEdit && (
          <button className="btn-primary" onClick={() => { setEditing(null); setShowForm(true) }}>
            + Register New Patient
          </button>
        )}
      </div>

      {/* search */}
      <div className="relative max-w-md">
        <span className="absolute left-3.5 top-1/2 -translate-y-1/2 text-ink-300">
          <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-4.35-4.35M17 11a6 6 0 11-12 0 6 6 0 0112 0z" /></svg>
        </span>
        <input className="input pl-10" placeholder="Search by name, MR#, diagnosis…" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>

      {/* table */}
      <div className="card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead className="bg-ink-50 border-b border-ink-100">
              <tr>
                <th className="th">Patient</th>
                <th className="th">MR #</th>
                <th className="th">Diagnosis</th>
                <th className="th">Contact</th>
                <th className="th">Status</th>
                {canEdit && <th className="th text-right">Actions</th>}
              </tr>
            </thead>
            <tbody>
              {filtered.map((p: any) => {
                const st = statusOf(p)
                return (
                  <tr key={p.id} onClick={() => setViewing(p.id)}
                    className="border-b border-ink-50 hover:bg-brand-50/40 cursor-pointer transition"
                    title={canEdit ? 'View details' : 'Read-only'}>
                    <td className="td">
                      <div className="flex items-center gap-3">
                        <div className="w-9 h-9 rounded-full bg-brand-100 text-brand-700 flex items-center justify-center text-sm font-bold shrink-0">
                          {p.name[0]}
                        </div>
                        <div>
                          <div className="font-semibold text-ink-900">{p.name}</div>
                          <div className="text-xs text-ink-400">{p.diagnosis || '—'} {p.stage ? `· Stage ${p.stage}` : ''}</div>
                        </div>
                      </div>
                    </td>
                    <td className="td font-mono text-xs">{p.mr_number || '—'}</td>
                    <td className="td">{p.diagnosis || '—'}</td>
                    <td className="td text-xs">{p.contact || '—'}</td>
                    <td className="td"><span className={`badge ${STATUS_TONE[st.status]}`}>{st.label}</span></td>
                    {canEdit && (
                      <td className="td text-right whitespace-nowrap" onClick={(e) => e.stopPropagation()}>
                        <button className="btn-ghost !px-2.5 !py-1.5 text-xs" onClick={() => { setEditing(p); setShowForm(true) }}>Edit</button>
                        {role === 'admin' && (
                          <button className="btn-ghost !px-2.5 !py-1.5 text-xs !text-rose-600 hover:!bg-rose-50"
                            onClick={() => removePatient(p)}>Delete</button>
                        )}
                      </td>
                    )}
                  </tr>
                )
              })}
              {filtered.length === 0 && (
                <tr><td colSpan={canEdit ? 6 : 5} className="td text-center text-ink-400 py-8">No patients found</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <PatientForm open={showForm} patient={editing} onClose={() => setShowForm(false)}
        onSaved={() => setShowForm(false)} />
      <PatientDetail patientId={viewing} onClose={() => setViewing(null)} />
    </div>
  )
}
