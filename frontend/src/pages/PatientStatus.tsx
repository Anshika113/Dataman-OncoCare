import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { LANGS, advice, isLang, stage as stageText, t, type Lang } from '../lib/i18n'

// The patient's own view of their own visit.
//
// Unauthenticated by design: the link token is the credential. It is defined
// by what it leaves out — no other patient's name, no diagnosis, no
// specialty, and the treatment named only where that was consented to.
//
// Built for a phone on a hospital connection: one column, large type, no
// chrome, and it keeps showing the last answer if a refresh fails.
//
// It opens in the language the clinic recorded for this patient, which is the
// point: a toggle nobody finds is not multilingual. The toggle is still there
// because the person holding the phone is often a son or a daughter, and the
// record belongs to their parent.

const STAGE_TONE: Record<string, string> = {
  ready: 'bg-emerald-50 border-emerald-200 text-emerald-800',
  in_labs: 'bg-amber-50 border-amber-200 text-amber-800',
  with_doctor: 'bg-brand-50 border-brand-200 text-brand-800',
  not_arrived: 'bg-ink-50 border-ink-200 text-ink-700',
  done: 'bg-ink-50 border-ink-200 text-ink-600',
  cancelled: 'bg-rose-50 border-rose-200 text-rose-800',
}

const LANG_KEY = 'oncocare.patient.lang'

export default function PatientStatus() {
  const { token = '' } = useParams()
  const [s, setS] = useState<any | null>(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [said, setSaid] = useState('')
  // null = the patient has not overridden anything, so follow the record
  const [chosen, setChosen] = useState<Lang | null>(() => {
    try {
      const v = localStorage.getItem(LANG_KEY)
      return isLang(v) ? v : null
    } catch { return null }
  })

  const lang: Lang = chosen ?? (isLang(s?.language) ? s.language : 'en')

  function choose(l: Lang) {
    setChosen(l)
    try { localStorage.setItem(LANG_KEY, l) } catch { /* private window */ }
  }

  async function load() {
    try {
      const r = await fetch(`/api/p/${encodeURIComponent(token)}`)
      if (r.status === 404) { setErr(t(lang, 'invalid_link')); return }
      if (!r.ok) throw new Error('unreachable')
      setS(await r.json())
      setErr('')
    } catch {
      // keep whatever is on screen rather than blanking it
      if (!s) setErr(t(lang, 'unreachable'))
    }
  }

  useEffect(() => {
    load()
    const t = setInterval(load, 30000)
    return () => clearInterval(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token])

  async function answer(coming: boolean) {
    setBusy(true)
    try {
      await fetch(`/api/p/${encodeURIComponent(token)}/confirm`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ coming }),
      })
      setSaid(t(lang, coming ? 'thanks_coming' : 'thanks_cannot'))
      load()
    } catch { setSaid(t(lang, 'send_failed')) }
    finally { setBusy(false) }
  }

  return (
    <div className="min-h-full bg-ink-50 flex justify-center px-4 py-8">
      <div className="w-full max-w-md">
        {/* Large enough to hit with a thumb, and in each language's own
            script so it needs no reading to find. */}
        <div className="flex justify-center gap-1.5 mb-4" role="group"
          aria-label="Language">
          {LANGS.map(l => (
            <button key={l.code} onClick={() => choose(l.code)}
              aria-pressed={lang === l.code}
              className={`text-xs font-semibold rounded-full px-3 py-1.5 border transition ${
                lang === l.code
                  ? 'bg-brand-600 border-brand-600 text-white'
                  : 'bg-white border-ink-200 text-ink-600'}`}>
              {l.label}
            </button>
          ))}
        </div>

        <div className="text-center mb-5">
          <div className="text-sm font-bold text-ink-900">{t(lang, 'brand')}</div>
          <div className="text-xs text-ink-500">{t(lang, 'subtitle')}</div>
        </div>

        {err && (
          <div className="card p-5 text-center text-sm text-ink-600">{err}</div>
        )}

        {s && (
          <div className="space-y-3">
            {s.token && (
              <div className="card p-5 text-center">
                <div className="text-xs font-bold uppercase tracking-wide text-ink-500">
                  {t(lang, 'your_number')}
                </div>
                <div className="text-4xl font-extrabold text-brand-700 mt-1">{s.token}</div>
              </div>
            )}

            <div className={`rounded-2xl border p-5 ${STAGE_TONE[s.stage] || STAGE_TONE.not_arrived}`}>
              <div className="text-lg font-extrabold">
                {stageText(lang, s.stage, s.stage_text)}
              </div>
              {(s.advice_key || s.advice) && (
                <div className="text-sm mt-1 leading-relaxed">
                  {advice(lang, s.advice_key, s.advice_vars) || s.advice}
                </div>
              )}
            </div>

            <div className="card p-5 space-y-2 text-sm">
              <div className="flex justify-between gap-3">
                <span className="text-ink-500">{t(lang, 'booked_for')}</span>
                <span className="font-semibold text-ink-900">{s.booked_for}</span>
              </div>
              {s.doctor_name && (
                <div className="flex justify-between gap-3">
                  <span className="text-ink-500">{t(lang, 'with_doctor')}</span>
                  <span className="font-semibold text-ink-900">{s.doctor_name}</span>
                </div>
              )}
              {s.treatment && (
                <div className="flex justify-between gap-3">
                  <span className="text-ink-500">{t(lang, 'treatment')}</span>
                  <span className="font-semibold text-ink-900">{s.treatment}</span>
                </div>
              )}
              {s.arrived_at && (
                <div className="flex justify-between gap-3">
                  <span className="text-ink-500">{t(lang, 'checked_in')}</span>
                  <span className="font-semibold text-ink-900">{s.arrived_at}</span>
                </div>
              )}
              {s.stage === 'ready' && (
                <div className="flex justify-between gap-3">
                  <span className="text-ink-500">{t(lang, 'ahead_of_you')}</span>
                  <span className="font-semibold text-ink-900">{s.people_ahead}</span>
                </div>
              )}
            </div>

            {s.can_confirm && !said && (
              <div className="card p-5">
                <div className="text-sm font-semibold text-ink-900 mb-1">
                  {t(lang, 'coming_question')}
                </div>
                <div className="text-xs text-ink-500 mb-3">
                  {t(lang, 'coming_help')}
                </div>
                <div className="flex gap-2">
                  <button className="btn-primary grow" disabled={busy}
                    onClick={() => answer(true)}>{t(lang, 'yes_coming')}</button>
                  <button className="btn-ghost grow" disabled={busy}
                    onClick={() => answer(false)}>{t(lang, 'cannot_make')}</button>
                </div>
                {s.confirmed && (
                  <div className="text-xs text-ink-400 mt-2">
                    {t(lang, 'previously')}{' '}
                    {t(lang, s.confirmed === 'yes' ? 'answer_coming' : 'answer_cannot')}
                  </div>
                )}
              </div>
            )}

            {said && (
              <div className="card p-4 text-sm text-ink-700 text-center">{said}</div>
            )}

            {/* Shown only where the patient already said someone with them may
                be spoken to about the appointment — the same consent flag the
                outgoing messages obey. */}
            {s.attendant_ok && (
              <div className="card p-4">
                <div className="text-[10px] font-bold uppercase tracking-wide text-ink-500">
                  {t(lang, 'caregiver_title')}
                </div>
                <div className="text-[13px] text-ink-700 mt-0.5 leading-relaxed">
                  {t(lang, 'caregiver_body')}
                </div>
              </div>
            )}

            <div className="text-[11px] text-ink-400 text-center leading-relaxed px-2">
              {t(lang, 'footer')}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
