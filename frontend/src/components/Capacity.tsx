import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import { Icon } from './icons'

// Capacity across days, not just this afternoon.
//
// The brief describes a pressure that builds as volumes rise; every other
// surface in the app answers "what about today?". This one answers "what
// about next week?" and names the move — shift work from the tightest day to
// the emptiest — rather than leaving two numbers side by side.

const TONE: Record<string, string> = {
  over: 'bg-rose-500',
  tight: 'bg-amber-500',
  ok: 'bg-emerald-500',
  closed: 'bg-ink-200',
}
const LABEL: Record<string, string> = {
  over: 'over-committed', tight: 'nearly full', ok: 'room to move',
  closed: 'no clinic',
}

export default function Capacity({ doctorId = '' }: { doctorId?: string }) {
  const [data, setData] = useState<any | null>(null)
  const [busy, setBusy] = useState(false)

  async function load() {
    setBusy(true)
    try { setData(await api.capacity('', 7, doctorId)) }
    catch { /* a capacity view is never worth blocking the page on */ }
    finally { setBusy(false) }
  }
  useEffect(() => { load() }, [doctorId])

  const rows: any[] = data?.rows || []

  return (
    <div className="card p-5">
      <div className="flex items-center justify-between gap-3 flex-wrap mb-1">
        <div className="flex items-center gap-2">
          <Icon name="calendar" className="w-5 h-5 text-brand-600 shrink-0" />
          <h3 className="font-bold text-ink-900">The week ahead</h3>
        </div>
        <button className="btn-ghost !py-1.5" disabled={busy} onClick={load}>
          {busy ? '…' : 'Refresh'}
        </button>
      </div>
      <div className="text-xs text-ink-500 mb-3">
        Committed against the hours the clinic actually has — leave and
        session templates included.
      </div>

      {rows.length === 0 ? (
        <div className="text-sm text-ink-400">Nothing to show yet.</div>
      ) : (
        <>
          <div className="space-y-2">
            {rows.map((r: any) => (
              <div key={r.date} className="flex items-center gap-3 flex-wrap">
                <span className="w-24 text-xs font-semibold text-ink-700 shrink-0">
                  {r.weekday ? r.weekday.toUpperCase() : ''} {r.date.slice(5)}
                </span>
                <div className="grow min-w-[140px] h-5 rounded-full bg-ink-100 overflow-hidden">
                  <div className={`h-full ${TONE[r.tone] || TONE.ok}`}
                    style={{ width: `${Math.min(100, r.pct ?? 0)}%` }} />
                </div>
                <span className="w-12 text-right text-sm font-bold text-ink-900">
                  {r.pct === null ? '—' : `${r.pct}%`}
                </span>
                <span className="w-28 text-[11px] text-ink-500 shrink-0">
                  {LABEL[r.tone] || ''}
                </span>
                <span className="text-[11px] text-ink-400">
                  {r.appointments} booked · {Math.round(r.free_min / 60)} h free
                </span>
              </div>
            ))}
          </div>

          {data.advice?.length > 0 && (
            <div className="mt-3 rounded-xl border border-ink-200 bg-ink-50/60 p-3 space-y-1">
              {data.advice.map((a: string, i: number) => (
                <div key={i} className="text-xs text-ink-700">{a}</div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}
