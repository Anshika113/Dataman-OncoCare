import { useEffect, useRef, useState } from 'react'
import { api } from '../lib/api'
import { Icon } from './icons'

// The assistant: a floating button, and Ctrl-K for anyone who learns it. Two
// doors, one panel.
//
// It looks, and it proposes. Nothing changes until a person presses Confirm on
// a card, which calls the same endpoint as the button elsewhere in the app,
// with the same role check and the same Undo. Every answer below is rendered
// from rows the API returned; this component never composes a sentence about a
// patient and never prints a number the backend did not send. The worst a
// wrong guess can do is show the wrong table or a card nobody confirms.
//
// The badge counts what the clinic already flagged — follow-ups and insights.
// It never invents urgency, and it is never a clinical judgement: a patient
// is on that list because of a clock, not because of their illness.

type Help = {
  topic: string
  title: string
  where: string
  allowed: boolean
  steps: string[]
  who_can: string
  why_not: string
  note: string
}

type Proposal = {
  action: 'extend' | 'pull_forward' | 'hand_off' | 'close_list'
  summary: string
  appointment_id?: string
  patient_name?: string
  doctor_id?: string
  doctor_name?: string
  minutes?: number
  to_doctor_id?: string
  to_doctor_name?: string
  note?: string
  from_time?: string
}

type Ask = {
  kind: 'view' | 'help' | 'refused' | 'cannot_write' | 'unclear' | 'proposal'
  proposal?: Proposal | null
  via?: string
  help?: Help
  view?: string
  title?: string
  reason?: string
  suggestions?: string[]
  rows?: any[]
  held?: any[]
  source?: string
  patient_name?: string
  scoped_to?: string
}

const STAGE_TONE: Record<string, string> = {
  ready: 'bg-emerald-50 text-emerald-700',
  in_labs: 'bg-amber-50 text-amber-700',
  with_doctor: 'bg-brand-50 text-brand-700',
  not_arrived: 'bg-ink-100 text-ink-600',
  done: 'bg-ink-100 text-ink-500',
}
const SEV_TONE: Record<string, string> = {
  critical: 'bg-rose-100 text-rose-700',
  warning: 'bg-amber-100 text-amber-700',
  info: 'bg-ink-100 text-ink-600',
}

function Pill({ tone, children }: { tone: string; children: any }) {
  return (
    <span className={`text-[10px] font-bold uppercase tracking-wide px-1.5 py-0.5 rounded ${tone}`}>
      {children}
    </span>
  )
}

function Row({ left, right }: { left: any; right?: any }) {
  return (
    <div className="flex justify-between gap-3 py-1.5 border-b border-ink-100 last:border-0">
      <div className="min-w-0 text-ink-900">{left}</div>
      {right !== undefined && (
        <div className="shrink-0 text-right font-semibold text-ink-900">{right}</div>
      )}
    </div>
  )
}

/** A change somebody asked for. Nothing has happened until Confirm. */
function ProposalCard({ p }: { p: Proposal }) {
  const [note, setNote] = useState(p.note || '')
  const [plan, setPlan] = useState<any>(null)
  const [stage, setStage] = useState<'ask' | 'busy' | 'done' | 'dropped'>('ask')
  const [result, setResult] = useState<any>(null)
  const [undone, setUndone] = useState('')

  // Closing a list moves other people, so the card shows who before it asks.
  useEffect(() => {
    if (p.action !== 'close_list') return
    api.closeList(p.doctor_id!, p.from_time!, false)
      .then(setPlan)
      .catch((e) => setPlan({ message: e.message }))
  }, [p.action, p.doctor_id, p.from_time])

  async function confirm() {
    setStage('busy')
    try {
      let r: any
      if (p.action === 'extend') r = await api.extendVisit(p.appointment_id!, p.minutes!)
      else if (p.action === 'pull_forward') r = await api.pullForward(p.doctor_id!)
      else if (p.action === 'hand_off') {
        r = await api.handOff(p.appointment_id!, p.to_doctor_id!, 'asked through the assistant', note)
      } else r = await api.closeList(p.doctor_id!, p.from_time!, true)
      setResult(r)
    } catch (e: any) {
      setResult({ success: false, message: e.message })
    }
    setStage('done')
  }

  async function undo() {
    try {
      const r = await api.undoAction(result.data.action_id)
      setUndone(r.message || 'Put back.')
    } catch (e: any) {
      setUndone(e.message)
    }
  }

  return (
    <div className="card p-4">
      <div className="text-[10px] font-bold uppercase tracking-wide text-amber-700 mb-1">
        {stage === 'done' ? 'Result' : 'Proposed. Nothing has changed yet'}
      </div>
      <div className="text-sm font-bold text-ink-900 leading-snug">{p.summary}</div>

      {p.action === 'hand_off' && stage === 'ask' && (
        <label className="block mt-2">
          <span className="text-[11px] text-ink-600">Note for {p.to_doctor_name}</span>
          <textarea className="input !py-1.5 text-sm w-full mt-0.5" rows={2} maxLength={500}
            value={note} onChange={(e) => setNote(e.target.value)} />
        </label>
      )}

      {plan && stage === 'ask' && (
        <div className="mt-2 text-[11px] text-ink-700">
          <div className="mb-1">{plan.message}</div>
          {(plan.data?.plan || []).map((row: any) => (
            <Row key={row.appointment_id}
              left={<>{row.was} {row.patient_name}</>}
              right={<span className="font-normal">
                {row.covered ? `${row.to_doctor_name} ${row.to_slot}` : 'no cover'}
              </span>} />
          ))}
        </div>
      )}

      {stage === 'ask' && (
        <div className="flex gap-2 mt-3">
          <button className="btn-primary !px-3 !py-1.5 text-sm" onClick={confirm}>Confirm</button>
          <button className="text-sm text-ink-600 hover:text-ink-900 px-2"
            onClick={() => setStage('dropped')}>Cancel</button>
        </div>
      )}
      {stage === 'busy' && <div className="text-[11px] text-ink-500 mt-2">working…</div>}
      {stage === 'dropped' && <div className="text-sm text-ink-600 mt-2">Cancelled. Nothing changed.</div>}
      {stage === 'done' && result && (
        <div className="mt-2 text-sm text-ink-900">
          {result.message}
          {result.success && result.data?.action_id && !undone && (
            <button className="block text-[11px] text-brand-700 font-semibold mt-1" onClick={undo}>Undo</button>
          )}
          {undone && <div className="text-[11px] text-ink-600 mt-1">{undone}</div>}
        </div>
      )}
    </div>
  )
}

/** One renderer per view. Rows are drawn, never summarised. */
function Answer({ a }: { a: Ask }) {
  const rows = a.rows || []

  if (a.kind === 'proposal' && a.proposal) return <ProposalCard p={a.proposal} />

  // Stuck in the interface. The steps only appear if this person's role
  // actually has the thing; otherwise the honest answer is who does, and
  // why it sits with them — "ask a nurse" with no reason reads as a bug.
  if (a.help) {
    const h = a.help
    return (
      <div className="card p-4">
        <div className="text-sm font-bold text-ink-900 leading-snug">{h.title}</div>
        <div className="text-[11px] text-ink-600 mb-2.5">on the {h.where} tab</div>

        {h.allowed ? (
          <ol className="text-sm text-ink-900 space-y-1.5 list-none">
            {h.steps.map((st, i) => (
              <li key={i} className="flex gap-2">
                <span className="font-mono text-[11px] text-brand-700 font-semibold shrink-0 mt-0.5">
                  {i + 1}
                </span>
                <span className="min-w-0 leading-relaxed">{st}</span>
              </li>
            ))}
          </ol>
        ) : (
          <div className="rounded-lg bg-amber-50 border border-amber-200 px-3 py-2">
            <div className="text-sm text-ink-900 font-semibold">
              Your role cannot do this — ask {h.who_can}.
            </div>
            {h.why_not && (
              <div className="text-[11px] text-ink-700 mt-1 leading-relaxed">{h.why_not}</div>
            )}
          </div>
        )}

        {h.note && (
          <div className="text-[11px] text-ink-600 mt-2.5 leading-relaxed border-t border-ink-100 pt-2">
            {h.note}
          </div>
        )}
      </div>
    )
  }

  if (a.kind !== 'view') {
    return (
      <div className="card p-4">
        <div className="text-sm text-ink-900">{a.reason}</div>
        {a.suggestions && a.suggestions.length > 0 && (
          <div className="text-[11px] text-ink-500 mt-2 leading-relaxed">
            Try: {a.suggestions.slice(0, 3).join(' · ')}
          </div>
        )}
      </div>
    )
  }

  if (rows.length === 0) {
    return (
      <div className="card p-4">
        <div className="text-sm font-bold text-ink-900 mb-1 leading-snug">{a.title}</div>
        <div className="text-sm text-ink-600">Nothing to show right now.</div>
      </div>
    )
  }

  return (
    <div className="card p-4">
      <div className="text-sm font-bold text-ink-900 mb-1.5 leading-snug">
        {a.title}
        {a.patient_name ? ` · ${a.patient_name}` : ''}
      </div>

      {(a.view === 'waiting' || a.view === 'not_called' || a.view === 'patient') &&
        rows.map((r: any) => (
          <Row key={r.appointment_id}
            left={<><span className="font-mono text-[11px] text-brand-700 font-semibold mr-1.5">{r.token}</span>
              {r.patient_name}<span className="text-ink-500"> · {r.doctor_name}</span></>}
            right={<>{r.waiting_min} min{' '}
              <Pill tone={STAGE_TONE[r.stage] || STAGE_TONE.not_arrived}>
                {String(r.stage).replace('_', ' ')}
              </Pill></>} />
        ))}

      {a.view === 'emergency_queue' && rows.map((r: any) => (
        <Row key={r.emergency_id}
          left={<>{r.patient_name}<span className="text-ink-500"> · since {r.since}</span></>}
          right={<Pill tone="bg-rose-100 text-rose-700">{r.severity}</Pill>} />
      ))}

      {a.view === 'held' && rows.map((r: any) => (
        <Row key={r.appointment_id}
          left={<>{r.patient_name}<span className="text-ink-500"> · was {r.slot_start}</span></>}
          right={r.held_room_id ? 'chair released' : '—'} />
      ))}

      {a.view === 'free_rooms' && rows.map((r: any) => (
        <Row key={r.room_id} left={r.room_name}
          right={<Pill tone={r.idle ? 'bg-emerald-50 text-emerald-700' : 'bg-ink-100 text-ink-600'}>
            {r.idle ? 'idle' : 'in use'}
          </Pill>} />
      ))}

      {a.view === 'running_late' && rows.map((r: any) => (
        <Row key={r.doctor_id} left={r.doctor_name}
          right={<>{r.behind_min} min behind</>} />
      ))}

      {a.view === 'my_day' && rows.map((r: any) => (
        <Row key={r.appointment_id}
          left={<><span className="font-mono text-[11px] text-ink-600 mr-1.5">{r.slot_start}</span>
            {r.patient_name}</>}
          right={r.visit_label} />
      ))}

      {a.view === 'follow_ups' && rows.map((r: any, i: number) => (
        <Row key={r.appointment_id || i}
          left={<><Pill tone={SEV_TONE[r.severity] || SEV_TONE.info}>{r.severity}</Pill>
            <span className="ml-1.5">{r.patient_name}</span></>}
          right={<span className="font-normal text-ink-600 text-[11px]">{r.summary}</span>} />
      ))}

      {/* An insight's title explains itself ("No slack in 3 clinics"); a
          follow-up's title is only a patient's name, so it needs its reason
          beside it or the row says nothing. */}
      {a.view === 'attention' && rows.map((r: any, i: number) => (
        <div key={i} className="py-1.5 border-b border-ink-100 last:border-0">
          <div className="flex items-start gap-2">
            <Pill tone={SEV_TONE[r.severity] || SEV_TONE.info}>{r.severity}</Pill>
            <span className="text-ink-900 min-w-0">{r.title}</span>
          </div>
          {r.detail && (
            <div className="text-[11px] text-ink-600 mt-0.5 leading-relaxed">
              {r.detail}
              {r.reasons > 1 && (
                <span className="text-ink-500"> · {r.reasons} reasons</span>
              )}
            </div>
          )}
        </div>
      ))}

      {a.view === 'patient' && (a.held || []).length > 0 && (
        <div className="text-[11px] text-amber-700 bg-amber-50 rounded-lg px-2.5 py-1.5 mt-2">
          Held for results — the chair went back to the pool. Not a no-show.
        </div>
      )}

      {a.source && (
        <div className="text-[10px] text-ink-500 font-mono mt-2">from {a.source}</div>
      )}
    </div>
  )
}

/** Questions worth offering before anyone has typed anything. */
const STARTERS = [
  'Who is waiting longest',
  "Who hasn't been called",
  'Any chairs free',
  'Am I running late',
  'Anything I should look at',
  'How do I hold a treatment',
]

type Turn = { question: string; answer: Ask | null }

/** Longest clip we record. Sarvam's short-audio endpoint stops at 30 seconds. */
const MAX_CLIP_MS = 25000

/** Browsers record WebM, which Sarvam does not list. 16 kHz mono WAV it does. */
async function toWav(recording: Blob): Promise<Blob> {
  const ctx = new AudioContext()
  const decoded = await ctx.decodeAudioData(await recording.arrayBuffer())
  await ctx.close()
  const off = new OfflineAudioContext(1, Math.ceil(decoded.duration * 16000), 16000)
  const src = off.createBufferSource()
  src.buffer = decoded
  src.connect(off.destination)
  src.start()
  const pcm = (await off.startRendering()).getChannelData(0)

  const view = new DataView(new ArrayBuffer(44 + pcm.length * 2))
  const tag = (at: number, s: string) => {
    for (let i = 0; i < s.length; i++) view.setUint8(at + i, s.charCodeAt(i))
  }
  tag(0, 'RIFF'); view.setUint32(4, 36 + pcm.length * 2, true); tag(8, 'WAVE')
  tag(12, 'fmt '); view.setUint32(16, 16, true); view.setUint16(20, 1, true)
  view.setUint16(22, 1, true); view.setUint32(24, 16000, true)
  view.setUint32(28, 32000, true); view.setUint16(32, 2, true)
  view.setUint16(34, 16, true); tag(36, 'data')
  view.setUint32(40, pcm.length * 2, true)
  pcm.forEach((v, i) => {
    const s = Math.max(-1, Math.min(1, v))
    view.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true)
  })
  return new Blob([view], { type: 'audio/wav' })
}

export default function Assistant({ state }: { state: any }) {
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const [busy, setBusy] = useState(false)
  // A transcript, not a result box. Somebody who asked three things should be
  // able to look back at the first; and seeing your own question on screen is
  // how you tell "it misheard me" from "there is nothing to show".
  const [turns, setTurns] = useState<Turn[]>([])
  const [model, setModel] = useState(false)
  const [recording, setRecording] = useState(false)
  const recorder = useRef<MediaRecorder | null>(null)
  const inputRef = useRef<HTMLInputElement | null>(null)
  const endRef = useRef<HTMLDivElement | null>(null)

  // What the clinic already flagged. Not a judgement — a count of rows that
  // exist on the follow-up list and the insights panel.
  const attention = (state?.insights?.length || 0)
    + (state?.follow_ups_total || 0)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setOpen((v) => !v)
      } else if (e.key === 'Escape') {
        setOpen(false)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  useEffect(() => { if (open) inputRef.current?.focus() }, [open])

  useEffect(() => {
    if (!open) return
    api.askCapabilities().then((c) => setModel(c.model)).catch(() => setModel(false))
  }, [open])

  // Keep the latest exchange in view as the transcript grows.
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: 'end', behavior: 'smooth' })
  }, [turns, busy])

  async function send(question: string) {
    const text = question.trim()
    if (!text || busy) return
    // The question goes up straight away and the box empties, so it is
    // obvious it was sent. The answer lands underneath it a moment later.
    setTurns((t) => [...t, { question: text, answer: null }])
    setQ('')
    setBusy(true)
    try {
      const a = await api.ask(text)
      setTurns((t) => t.map((x, i) => (i === t.length - 1 ? { ...x, answer: a } : x)))
    } catch (e: any) {
      const a: Ask = { kind: 'unclear', reason: e.message || 'Could not reach the clinic.' }
      setTurns((t) => t.map((x, i) => (i === t.length - 1 ? { ...x, answer: a } : x)))
    } finally {
      setBusy(false)
      inputRef.current?.focus()
    }
  }

  const canRecord = model && typeof MediaRecorder !== 'undefined'
    && !!navigator.mediaDevices && window.isSecureContext

  function say(reason: string) {
    setTurns((t) => [...t, { question: '(voice)', answer: { kind: 'unclear', reason } }])
  }

  async function toggleMic() {
    if (recording) { recorder.current?.stop(); return }
    let stream: MediaStream
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    } catch {
      say('The browser did not allow the microphone. Please type it.')
      return
    }
    const parts: Blob[] = []
    const rec = new MediaRecorder(stream)
    recorder.current = rec
    rec.ondataavailable = (e) => parts.push(e.data)
    rec.onstop = async () => {
      stream.getTracks().forEach((tr) => tr.stop())
      setRecording(false)
      setBusy(true)
      let heard = ''
      try {
        heard = (await api.askVoice(await toWav(new Blob(parts, { type: rec.mimeType })))).transcript
      } catch (e: any) {
        say(e.message || 'I could not hear that. Please type it.')
      }
      setBusy(false)
      if (heard) send(heard)
      else if (!parts.length) say('I could not hear that. Please type it.')
    }
    rec.start()
    setRecording(true)
    window.setTimeout(() => { if (rec.state === 'recording') rec.stop() }, MAX_CLIP_MS)
  }

  if (!open) {
    return (
      <button onClick={() => setOpen(true)} aria-label="Ask the clinic"
        className="fixed right-4 bottom-4 z-40 w-13 h-13 rounded-full bg-brand-600 text-white shadow-pop flex items-center justify-center hover:bg-brand-700 transition"
        style={{ width: 52, height: 52 }}>
        <Icon name="activity" className="w-6 h-6" />
        {attention > 0 && (
          <span className="absolute -top-1 -right-1 min-w-[21px] h-[21px] px-1 rounded-full bg-rose-600 text-white text-[11px] font-bold flex items-center justify-center border-2 border-ink-50">
            {attention}
          </span>
        )}
      </button>
    )
  }

  return (
    <>
      <div className="fixed inset-0 z-40 sm:hidden bg-ink-900/30" onClick={() => setOpen(false)} aria-hidden="true" />
      <div className="fixed z-50 bg-white border border-ink-200 rounded-2xl shadow-pop overflow-hidden flex flex-col
                      inset-x-3 bottom-3 top-16 sm:inset-x-auto sm:top-auto sm:right-4 sm:bottom-4 sm:w-[340px] sm:max-h-[70vh]">
        {/* Every other panel in this app is a white card with a border and a
            dark title. A near-black bar was an invention; this is the house
            style, and it stops the assistant reading as a different product. */}
        <div className="flex items-center justify-between px-3.5 py-3 bg-white border-b border-ink-100 shrink-0">
          <span className="text-sm font-bold text-ink-900">Ask the clinic</span>
          <span className="text-[11px] text-ink-500 flex items-center gap-2.5">
            {turns.length > 0 && (
              <button onClick={() => setTurns([])}
                className="text-ink-500 hover:text-ink-900">Clear</button>
            )}
            <span className="hidden sm:inline font-mono">Ctrl K</span>
            <button onClick={() => setOpen(false)} aria-label="Close"
              className="text-ink-500 hover:text-ink-900 text-sm leading-none">✕</button>
          </span>
        </div>

        <div className="flex-1 overflow-auto px-3 py-3 bg-ink-50 min-h-0">
          {turns.length === 0 && (
            <div className="py-1">
              <div className="text-sm text-ink-800 leading-relaxed mb-3">
                {model
                  ? <>Ask, or tell me what you need: &ldquo;is patient ko 10 minute aur do&rdquo;.
                      I show you a card first, and nothing changes until you confirm.</>
                  : <>I can look things up and show you where things are.
                      I only look — I cannot book or cancel.</>}
              </div>
              {/* Tapping beats reading a run-on list of examples, and it
                  teaches the phrasings that work. */}
              <div className="flex flex-wrap gap-1.5">
                {STARTERS.map((s) => (
                  <button key={s} onClick={() => send(s)}
                    className="text-xs text-ink-800 bg-white border border-ink-200 rounded-full px-2.5 py-1.5 hover:border-brand-300 hover:text-brand-700 transition">
                    {s}
                  </button>
                ))}
              </div>
              <div className="text-[11px] text-ink-500 mt-3">
                English, हिंदी or मराठी.
                {model && ' What you say or type here is sent to Sarvam AI to read it. Demo data only.'}
              </div>
            </div>
          )}

          {turns.map((t, i) => (
            <div key={i} className="mb-3 last:mb-0">
              <div className="flex justify-end mb-1.5">
                <span className="bg-brand-600 text-white text-sm rounded-2xl rounded-br-sm px-3 py-1.5 max-w-[85%] break-words">
                  {t.question}
                </span>
              </div>
              {t.answer
                ? <>
                    <Answer a={t.answer} />
                    {t.answer.via === 'model' && (
                      <div className="text-[10px] text-ink-500 px-1 mt-1">understood by Sarvam AI</div>
                    )}
                  </>
                : <div className="text-[11px] text-ink-500 px-1">looking…</div>}
            </div>
          ))}
          <div ref={endRef} />
        </div>

        <form className="shrink-0 border-t border-ink-100 p-2.5 flex gap-2 bg-white"
          onSubmit={(e) => { e.preventDefault(); send(q) }}>
          <input ref={inputRef} className="input !py-2 text-sm grow min-w-0"
            placeholder="Ask about today…" value={q}
            onChange={(e) => setQ(e.target.value)} maxLength={300} />
          {canRecord && (
            <button type="button" onClick={toggleMic} disabled={busy}
              aria-label={recording ? 'Stop recording' : 'Speak'}
              className={`!px-3 !py-2 rounded-lg border text-sm ${recording
                ? 'bg-rose-600 border-rose-600 text-white' : 'bg-white border-ink-200 text-ink-800'}`}>
              {recording ? 'Stop' : 'Mic'}
            </button>
          )}
          <button className="btn-primary !px-3 !py-2" disabled={busy || !q.trim()}
            aria-label="Ask">{busy ? '…' : '↑'}</button>
        </form>
      </div>
    </>
  )
}
