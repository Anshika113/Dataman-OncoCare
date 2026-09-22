import { useEffect, useRef, useState } from 'react'
import { api } from '../lib/api'

const EMPTY = {
  name: '', contact: '', dob: '', age: '', gender: '', blood_group: '',
  mr_number: '', diagnosis: '', stage: '', allergies: '', insurance: '',
  priority_tier: 1, notes: '',
}

const MIN_W = 360
const MAX_W = () => Math.min(860, window.innerWidth * 0.9)

export default function PatientForm({ open, onClose, onSaved, patient }: {
  open: boolean; onClose: () => void; onSaved: (p: any) => void; patient?: any
}) {
  const [f, setF] = useState<any>(EMPTY)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [width, setWidth] = useState(520)
  const [dragging, setDragging] = useState(false)
  const dragRef = useRef<{ startX: number; startW: number } | null>(null)
  const isEdit = !!patient

  useEffect(() => {
    if (open) setF(patient ? { ...EMPTY, ...patient } : EMPTY)
  }, [open, patient])

  // resize by dragging the left edge of the panel
  useEffect(() => {
    if (!dragging) return
    const move = (e: MouseEvent) => {
      const d = dragRef.current
      if (!d) return
      const next = d.startW + (d.startX - e.clientX)  // drag left edge leftward = wider
      setWidth(Math.max(MIN_W, Math.min(MAX_W(), next)))
    }
    const up = () => { setDragging(false); dragRef.current = null }
    window.addEventListener('mousemove', move)
    window.addEventListener('mouseup', up)
    return () => {
      window.removeEventListener('mousemove', move)
      window.removeEventListener('mouseup', up)
    }
  }, [dragging])

  if (!open) return null

  const set = (k: string) => (e: any) => setF((p: any) => ({ ...p, [k]: e.target.value }))

  async function save(e: React.FormEvent) {
    e.preventDefault()
    if (!f.name.trim()) { setErr('Name is required'); return }
    setErr(''); setBusy(true)
    try {
      const body = { ...f, priority_tier: Number(f.priority_tier), age: f.age || '' }
      const p = isEdit ? await api.updatePatient(patient.id, body) : await api.createPatient(body)
      onSaved(p)
    } catch (e: any) { setErr(e.message) }
    finally { setBusy(false) }
  }

  return (
    <div className={`fixed inset-0 z-50 flex justify-end bg-ink-950/40 backdrop-blur-sm ${dragging ? 'cursor-ew-resize select-none' : ''}`}
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div
        className="relative h-full bg-white shadow-pop animate-slidein flex flex-col"
        style={{ width }}
        onMouseDown={(e) => e.stopPropagation()}
      >
        {/* resize handle (left edge) */}
        <div
          className="absolute left-0 top-0 bottom-0 w-1.5 cursor-ew-resize hover:bg-brand-400/60 active:bg-brand-500 z-10"
          title="Drag to resize"
          onMouseDown={(e) => {
            e.preventDefault()
            dragRef.current = { startX: e.clientX, startW: width }
            setDragging(true)
          }}
        />

        {/* header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-ink-100 shrink-0">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-brand-100 text-brand-700 flex items-center justify-center text-lg">
              {isEdit ? '✏️' : '🧑'}
            </div>
            <div>
              <h2 className="text-lg font-extrabold text-ink-900">{isEdit ? 'Edit Patient' : 'Register New Patient'}</h2>
              <p className="text-xs text-ink-400">{isEdit ? patient.id : 'Fill in the patient details below'}</p>
            </div>
          </div>
          <button onClick={onClose} className="w-8 h-8 rounded-lg hover:bg-ink-100 text-ink-400 hover:text-ink-700 text-xl leading-none">×</button>
        </div>

        {/* scrollable body */}
        <div className="flex-1 overflow-y-auto p-6">
          <form onSubmit={save} className="space-y-6">
            {/* personal */}
            <section>
              <h3 className="text-xs font-bold uppercase tracking-wider text-brand-600 mb-3">Personal</h3>
              <div className={`grid gap-4 ${width > 560 ? 'sm:grid-cols-2' : 'grid-cols-1'}`}>
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
              <div className={`grid gap-4 ${width > 560 ? 'sm:grid-cols-2' : 'grid-cols-1'}`}>
                <Field label="Diagnosis"><input className="input" value={f.diagnosis} onChange={set('diagnosis')} placeholder="e.g. Breast Cancer" /></Field>
                <Field label="Stage">
                  <select className="input" value={f.stage} onChange={set('stage')}>
                    <option value="">Unknown</option><option>I</option><option>II</option><option>III</option><option>IV</option>
                  </select>
                </Field>
                <Field label="Allergies"><input className="input" value={f.allergies} onChange={set('allergies')} placeholder="None / Penicillin…" /></Field>
                <Field label="Priority tier">
                  <select className="input" value={f.priority_tier} onChange={set('priority_tier')}>
                    {[1,2,3,4,5].map((n) => <option key={n} value={n}>{n} {n === 5 ? '(VIP)' : ''}</option>)}
                  </select>
                </Field>
              </div>
              <div className="mt-4">
                <Field label="Notes"><textarea className="input min-h-[70px] resize-y" value={f.notes} onChange={set('notes')} placeholder="Any additional clinical notes" /></Field>
              </div>
            </section>

            {err && <div className="text-sm text-rose-700 bg-rose-50 border border-rose-100 rounded-lg px-3 py-2">⚠️ {err}</div>}
          </form>
        </div>

        {/* sticky footer */}
        <div className="px-6 py-4 border-t border-ink-100 flex items-center justify-between gap-3 shrink-0 bg-ink-50/50">
          <span className="text-[11px] text-ink-400">Drag the left edge to resize</span>
          <div className="flex gap-2">
            <button type="button" className="btn-ghost" onClick={onClose}>Cancel</button>
            <button onClick={(e) => save(e as any)} className="btn-primary" disabled={busy}>
              {busy ? 'Saving…' : isEdit ? 'Save changes' : 'Register patient'}
            </button>
          </div>
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
