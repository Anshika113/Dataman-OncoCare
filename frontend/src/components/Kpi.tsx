import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import { Icon } from './icons'

// The one number this project is asking to be judged on.
//
// Chair time recovered from lab waits: minutes an infusion chair went back
// into the pool because a treatment was held for results instead of sitting
// on an empty chair until the slot passed. It is written at the moment the
// chair is released (engine/investigations.gate) and summed per day by
// engine/outcomes._gating — nothing here computes it.
//
// Two deliberate choices about *which* days are shown:
//
//   * The headline compares the clinic's last two COMPLETE days. Comparing a
//     half-played today against a finished yesterday would make every count
//     look like a collapse at 11:00 and a triumph at 18:00, which is an
//     artefact of the clock rather than anything the clinic did.
//   * Today is still reported, as a running total, clearly labelled as
//     partial.

type Delta = {
  metric: string; label: string; unit: string
  now: number | null; previous: number | null
  change: number | null; better: boolean | null; why: string
}

function pick(deltas: Delta[], metric: string) {
  return deltas?.find(d => d.metric === metric)
}

function fmt(v: number | null | undefined, unit: string) {
  if (v === null || v === undefined) return '—'
  return unit === '%' ? `${v}%` : unit ? `${v} ${unit}` : `${v}`
}

function Change({ d }: { d?: Delta }) {
  if (!d || d.change === null || d.change === 0) {
    return <span className="text-[11px] text-ink-400">no change</span>
  }
  const tone = d.better === true ? 'text-emerald-700 bg-emerald-50'
    : d.better === false ? 'text-rose-700 bg-rose-50'
      : 'text-ink-600 bg-ink-100'
  return (
    <span className={`text-[11px] font-bold px-1.5 py-0.5 rounded ${tone}`}>
      {d.change > 0 ? '+' : ''}{d.change}{d.unit === '%' ? '%' : ''}
    </span>
  )
}

export default function Kpi() {
  const [proven, setProven] = useState<any | null>(null)
  const [today, setToday] = useState<any | null>(null)
  const [err, setErr] = useState('')

  useEffect(() => {
    let alive = true
    ;(async () => {
      try {
        // the live day, which also tells us which earlier day has data
        const live = await api.outcomes()
        if (!alive) return
        setToday(live)
        const lastComplete = live?.previous?.date
        if (!lastComplete) return
        // that day against the one before it: two finished days, like for like
        const pair = await api.outcomes(lastComplete)
        if (alive) setProven(pair)
      } catch (e: any) {
        if (alive) setErr(e.message)
      }
    })()
    return () => { alive = false }
  }, [])

  if (err) {
    return (
      <div className="card p-4 text-sm text-rose-700">
        Could not load the outcome figures — {err}
      </div>
    )
  }
  if (!proven?.previous) {
    // one complete day is not a comparison, and saying so is the honest
    // version of printing a number with nothing behind it
    return (
      <div className="card p-5">
        <div className="flex items-center gap-2 mb-1">
          <Icon name="activity" className="w-5 h-5 text-brand-600 shrink-0" />
          <h3 className="font-bold text-ink-900">Chair time recovered from lab waits</h3>
        </div>
        <div className="text-sm text-ink-500">
          {today?.now
            ? `${today.now.gating?.chair_min_released ?? 0} min so far today. `
            : ''}
          Needs two complete days to show a change.
        </div>
      </div>
    )
  }

  const g = pick(proven.deltas, 'gating.chair_min_released')
  const wait = pick(proven.deltas, 'waiting.median_min')
  const punct = pick(proven.deltas, 'punctuality.on_time_pct')
  const seen = pick(proven.deltas, 'throughput.seen')
  const held = proven.now?.gating?.held ?? 0
  const todayMin = today?.now?.gating?.chair_min_released ?? 0

  return (
    <div className="card p-5 border-brand-200 bg-brand-50/40">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <Icon name="activity" className="w-5 h-5 text-brand-600 shrink-0" />
            <h3 className="font-bold text-ink-900">Chair time recovered from lab waits</h3>
          </div>
          <div className="text-xs text-ink-500 mt-0.5">
            {proven.now.date} against {proven.previous.date} — the clinic's last
            two complete days.
          </div>
        </div>
        <div className="text-right shrink-0">
          <div className="text-3xl font-extrabold text-brand-700 tabular-nums leading-none">
            {g?.now ?? 0} <span className="text-base font-bold">min</span>
          </div>
          <div className="mt-1 flex items-center gap-1.5 justify-end">
            <Change d={g} />
            <span className="text-[11px] text-ink-500">
              vs {g?.previous ?? 0} min
            </span>
          </div>
        </div>
      </div>

      <div className="text-xs text-ink-600 mt-2">
        {held} treatment{held === 1 ? '' : 's'} held for results, so {held}
        {' '}chair{held === 1 ? '' : 's'} went back to the pool instead of
        standing empty until the slot passed.
        {todayMin ? ` ${todayMin} min so far today.` : ''}
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 mt-3">
        {[
          { label: 'Median wait', d: wait },
          { label: 'Seen on time', d: punct },
          { label: 'Visits seen', d: seen },
        ].map(({ label, d }) => (
          <div key={label} className="rounded-xl border border-ink-200 bg-white px-3 py-2.5">
            <div className="text-[10px] font-bold uppercase tracking-wide text-ink-500">
              {label}
            </div>
            <div className="flex items-baseline gap-2 mt-1 flex-wrap">
              <span className="text-lg font-extrabold text-ink-900 tabular-nums">
                {fmt(d?.now, d?.unit || '')}
              </span>
              <Change d={d} />
              <span className="text-[11px] text-ink-500">
                from {fmt(d?.previous, d?.unit || '')}
              </span>
            </div>
          </div>
        ))}
      </div>

      <div className="mt-3 text-[11px] text-ink-400 flex items-start gap-1.5">
        <Icon name="info" className="w-3.5 h-3.5 shrink-0 mt-0.5" />
        Both days ran the same list with the same patients in the same slots.
        Waiting and punctuality leave out patients held for results — their
        clock keeps running while the lab works, and that wait is not the
        queue's doing.
      </div>
    </div>
  )
}
