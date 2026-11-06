import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import { Icon } from './icons'

// Did any of it help?
//
// Everything else in the app changes the day; this is the only surface that
// reports on it. Two rules it keeps: a block computed from too few timed
// visits says so instead of printing a number, and a change is only shown
// against the clinic's own previous day — never against a target.

function fmt(v: any, unit: string) {
  if (v === null || v === undefined) return '—'
  return `${v}${unit === '%' ? '%' : unit ? ` ${unit}` : ''}`
}

export default function Outcomes({ doctorId = '', title = 'Did it help?' }: {
  doctorId?: string; title?: string
}) {
  const [data, setData] = useState<any | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  async function load() {
    setBusy(true); setErr('')
    try { setData(await api.outcomes('', '', doctorId)) }
    catch (e: any) { setErr(e.message) }
    finally { setBusy(false) }
  }
  useEffect(() => { load() }, [doctorId])

  const now = data?.now
  const prev = data?.previous

  return (
    <div className="card p-5">
      <div className="flex items-center justify-between gap-3 flex-wrap mb-1">
        <div className="flex items-center gap-2">
          <Icon name="activity" className="w-5 h-5 text-brand-600 shrink-0" />
          <h3 className="font-bold text-ink-900">{title}</h3>
        </div>
        <button className="btn-ghost !py-1.5" disabled={busy} onClick={load}>
          {busy ? '…' : 'Refresh'}
        </button>
      </div>
      <div className="text-xs text-ink-500 mb-3">
        {prev
          ? `${now?.date} against ${prev.date} — the clinic's own previous day.`
          : data?.why || 'Measured from real check-in and call-in times.'}
      </div>

      {err && <div className="text-sm text-rose-700">{err}</div>}

      {now && (
        <>
          {/* the change, metric by metric */}
          {data.deltas?.length > 0 && (
            <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-2 mb-3">
              {data.deltas.map((d: any) => (
                <div key={d.metric} className="rounded-xl border border-ink-200 px-3 py-2.5">
                  <div className="text-[10px] font-bold uppercase tracking-wide text-ink-500">
                    {d.label}
                  </div>
                  <div className="flex items-baseline gap-2 mt-1 flex-wrap">
                    <span className="text-xl font-extrabold text-ink-900">
                      {fmt(d.now, d.unit)}
                    </span>
                    {d.change === null ? (
                      <span className="text-[11px] text-ink-400">{d.why}</span>
                    ) : d.change === 0 ? (
                      <span className="text-[11px] text-ink-500">unchanged</span>
                    ) : (
                      <span className={`text-[11px] font-bold ${
                        d.better === true ? 'text-emerald-700'
                          : d.better === false ? 'text-rose-700' : 'text-ink-500'}`}>
                        {d.change > 0 ? '+' : ''}{d.change}{d.unit === '%' ? '%' : ''}
                        {' '}vs {fmt(d.previous, d.unit)}
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* the detail, including what could not be measured */}
          <div className="grid sm:grid-cols-2 gap-2">
            <div className="rounded-xl border border-ink-200 px-3 py-2.5">
              <div className="text-[10px] font-bold uppercase tracking-wide text-ink-500">Waiting</div>
              {now.waiting.enough ? (
                <div className="text-sm text-ink-800 mt-1 leading-relaxed">
                  Median <b>{now.waiting.median_min} min</b>, mean {now.waiting.mean_min} min
                  <span className="block text-xs text-ink-500">
                    {now.waiting.measured} timed visits · worst {now.waiting.worst_min} min
                    {now.waiting.worst_patient ? ` (${now.waiting.worst_patient})` : ''}
                  </span>
                </div>
              ) : (
                <div className="text-sm text-ink-400 mt-1">Not measured — {now.waiting.why}</div>
              )}
            </div>

            <div className="rounded-xl border border-ink-200 px-3 py-2.5">
              <div className="text-[10px] font-bold uppercase tracking-wide text-ink-500">Punctuality</div>
              {now.punctuality.enough ? (
                <div className="text-sm text-ink-800 mt-1 leading-relaxed">
                  <b>{now.punctuality.on_time}</b> of {now.punctuality.measured} seen within 15 min
                  <span className="block text-xs text-ink-500">
                    median {now.punctuality.median_late_min} min past the booked time
                  </span>
                </div>
              ) : (
                <div className="text-sm text-ink-400 mt-1">Not measured — {now.punctuality.why}</div>
              )}
            </div>

            <div className="rounded-xl border border-ink-200 px-3 py-2.5">
              <div className="text-[10px] font-bold uppercase tracking-wide text-ink-500">Time recovered</div>
              <div className="text-sm text-ink-800 mt-1 leading-relaxed">
                <b>{now.recovered.walk_ins}</b> walk-in{now.recovered.walk_ins === 1 ? '' : 's'} placed
                {now.recovered.walk_in_min ? ` (${now.recovered.walk_in_min} min)` : ''},
                {' '}<b>{now.recovered.backfilled}</b> slot{now.recovered.backfilled === 1 ? '' : 's'} backfilled
                <span className="block text-xs text-ink-500">
                  capacity that would otherwise have gone unused
                </span>
              </div>
            </div>

            <div className="rounded-xl border border-ink-200 px-3 py-2.5">
              <div className="text-[10px] font-bold uppercase tracking-wide text-ink-500">Lost</div>
              <div className="text-sm text-ink-800 mt-1 leading-relaxed">
                <b>{now.losses.no_shows}</b> no-show{now.losses.no_shows === 1 ? '' : 's'},
                {' '}{now.losses.cancelled} cancelled, {now.losses.overruns} overran
                <span className="block text-xs text-ink-500">
                  out of {now.appointments} booked
                </span>
              </div>
            </div>
          </div>

          <div className="mt-3 text-[11px] text-ink-400 flex items-start gap-1.5">
            <Icon name="info" className="w-3.5 h-3.5 shrink-0 mt-0.5" />
            Waiting is arrival to being called in, from real timestamps. A block
            with fewer than 3 timed visits reports that rather than a figure.
          </div>
        </>
      )}
    </div>
  )
}
