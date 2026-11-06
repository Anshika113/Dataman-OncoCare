import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import { Icon } from './icons'

const EMPTY = {
  name: '', contact: '', dob: '', age: '', gender: '', blood_group: '',
  mr_number: '', diagnosis: '', stage: '', allergies: '', insurance: '',
  priority_tier: 1, notes: '',
  // consent: naming the treatment is off until the patient says yes
  consent_sms: true, consent_name_treatment: false, consent_attendant: true,
}

export default function PatientForm({ open, onClose, onSaved, patient }: {
  open: boolean; onClose: () => void; onSaved: (p: any) => void; patient?: any
}) {
  const [f, setF] = useState<any>(EMPTY)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const isEdit = !!patient

  useEffect(() => {
    if (!open) return
    // blank datastore cells arrive as null, which the API rejects on save
    const known = Object.entries(patient || {}).filter(([, v]) => v != null)
    setF({ ...EMPTY, ...Object.fromEntries(known) })
  }, [open, patient])

  if (!open) return null

  const set = (k: string) => (e: any) => setF((p: any) => ({ ...p, [k]: e.target.value }))
  const check = (k: string) => (e: any) => setF((p: any) => ({ ...p, [k]: e.target.checked }))

  async function save(e: React.FormEvent) {
    e.preventDefault()
    if (!f.name.trim()) { setErr('Name is required'); return }
    setErr(''); setBusy(true)
    try {
      const body = { ...f, priority_tier: Number(f.priority_tier), age: String(f.age || '') }
      const p = isEdit ? await api.updatePatient(patient.id, body) : await api.createPatient(body)
      onSaved(p)
    } catch (e: any) { setErr(e.message) }
    finally { setBusy(false) }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-ink-950/40 backdrop-blur-sm"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div
        className="relative w-full max-w-2xl max-h-[90vh] bg-white rounded-2xl shadow-pop animate-pop flex flex-col overflow-hidden"
        onMouseDown={(e) => e.stopPropagation()}
      >
        {/* header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-ink-100 shrink-0">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-brand-100 text-brand-700 flex items-center justify-center">
              <Icon name={isEdit ? 'edit' : 'user'} className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-lg font-extrabold text-ink-900">{isEdit ? 'Edit Patient' : 'Register New Patient'}</h2>
              <p className="text-xs text-ink-400">{isEdit ? patient.id : 'Fill in the patient details below'}</p>
            </div>
          </div>
          <button onClick={onClose} className="w-8 h-8 rounded-lg hover:bg-ink-100 text-ink-400 hover:text-ink-700 text-xl leading-none" aria-label="Close">×</button>
        </div>

        {/* scrollable body */}
        <div className="overflow-y-auto p-6">
          <form onSubmit={save} className="space-y-6">
            {/* personal */}
            <section>
              <h3 className="text-xs font-bold uppercase tracking-wider text-brand-600 mb-3">Personal</h3>
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="Full name *"><input className="input" value={f.name} onChange={set('name')} placeholder="e.g. John Doe" /></Field>
                <Field label="Phone / contact"><input className="input" value={f.contact} onChange={set('contact')} placeholder="+92 …" /></Field>
                <Field label="Date of birth"><input type="date" className="input" value={f.dob} onChange={set('dob')} /></Field>
                <Field label="Age"><input className="input" value={f.age} onChange={set('age')} placeholder="45" /></Field>
                <Field label="Gender">
                  <select className="input" value={f.gender} onChange={set('gender')}>
                    <option value="">Select…</option><option>male</option><option>female</option><option>other</option>
                  </select>
                </Field>
                <Field label="Blood group">
                  <select className="input" value={f.blood_group} onChange={set('blood_group')}>
                    <option value="">Unknown</option>
                    {['A+','A-','B+','B-','AB+','AB-','O+','O-'].map((b) => <option key={b}>{b}</option>)}
                  </select>
                </Field>
                <Field label="MR Number"><input className="input" value={f.mr_number} onChange={set('mr_number')} placeholder="MR-1001" /></Field>
                <Field label="Insurance / provider"><input className="input" value={f.insurance} onChange={set('insurance')} placeholder="SEHA / Cigna / self" /></Field>
              </div>
            </section>

            {/* clinical */}
            <section>
              <h3 className="text-xs font-bold uppercase tracking-wider text-brand-600 mb-3">Clinical</h3>
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="Diagnosis"><input className="input" value={f.diagnosis} onChange={set('diagnosis')} placeholder="e.g. Breast Cancer" /></Field>
                <Field label="Stage">
                  <select className="input" value={f.stage} onChange={set('stage')}>
                    <option value="">Unknown</option><option>I</option><option>II</option><option>III</option><option>IV</option>
                  </select>
                </Field>
                <Field label="Allergies"><input className="input" value={f.allergies} onChange={set('allergies')} placeholder="None / Penicillin…" /></Field>
              </div>
              <div className="mt-4">
                <Field label="Notes"><textarea className="input min-h-[70px] resize-y" value={f.notes} onChange={set('notes')} placeholder="Any additional clinical notes" /></Field>
              </div>
            </section>

            <section>
              <h4 className="text-xs font-bold text-ink-500 uppercase tracking-wide mb-3">
                What may we send?
              </h4>
              <p className="text-xs text-ink-500 mb-3 leading-relaxed">
                A phone is often shared. Naming the treatment in a message is
                off unless the patient says otherwise.
              </p>
              <div className="space-y-2">
                <label className="flex items-start gap-3 text-sm text-ink-800 cursor-pointer">
                  <input type="checkbox" className="w-4 h-4 mt-0.5 shrink-0"
                    checked={!!f.consent_sms} onChange={check('consent_sms')} />
                  <span>
                    May we send appointment reminders and offers by SMS?
                    <span className="block text-xs text-ink-400">
                      Off means the desk phones instead — messages are held, not lost.
                    </span>
                  </span>
                </label>
                <label className="flex items-start gap-3 text-sm text-ink-800 cursor-pointer">
                  <input type="checkbox" className="w-4 h-4 mt-0.5 shrink-0"
                    checked={!!f.consent_name_treatment} onChange={check('consent_name_treatment')} />
                  <span>
                    May a message name the treatment?
                    <span className="block text-xs text-ink-400">
                      Off means drug names, the diagnosis and the room are replaced with neutral wording.
                    </span>
                  </span>
                </label>
                <label className="flex items-start gap-3 text-sm text-ink-800 cursor-pointer">
                  <input type="checkbox" className="w-4 h-4 mt-0.5 shrink-0"
                    checked={!!f.consent_attendant} onChange={check('consent_attendant')} />
                  <span>May we speak to whoever answers this number?</span>
                </label>
              </div>
            </section>

            {err && <div className="flex items-center gap-2 text-sm text-rose-700 bg-rose-50 border border-rose-100 rounded-lg px-3 py-2"><Icon name="alertTriangle" className="w-4 h-4 shrink-0" />{err}</div>}
          </form>
        </div>

        {/* sticky footer */}
        <div className="px-6 py-4 border-t border-ink-100 flex items-center justify-end gap-2 shrink-0 bg-ink-50/50">
          <button type="button" className="btn-ghost" onClick={onClose}>Cancel</button>
          <button onClick={(e) => save(e as any)} className="btn-primary" disabled={busy}>
            {busy ? 'Saving…' : isEdit ? 'Save changes' : 'Register patient'}
          </button>
        </div>
      </div>
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="label">{label}</label>
      {children}
    </div>
  )
}
