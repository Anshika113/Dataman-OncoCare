// Shared presentational helpers for status badges & severity.

export function statusBadge(status: string) {
  const map: Record<string, string> = {
    booked: 'bg-blue-100 text-blue-700',
    active: 'bg-emerald-100 text-emerald-700',
    overrun: 'bg-amber-100 text-amber-700',
    no_show: 'bg-slate-200 text-slate-600',
    rescheduled: 'bg-violet-100 text-violet-700',
    cancelled: 'bg-rose-100 text-rose-700',
    completed: 'bg-slate-100 text-slate-500',
    emergency_waiting: 'bg-rose-100 text-rose-700',
    available: 'bg-emerald-100 text-emerald-700',
    unavailable: 'bg-rose-100 text-rose-700',
    on_leave: 'bg-rose-100 text-rose-700',
    partially_unavailable: 'bg-amber-100 text-amber-700',
    waiting: 'bg-rose-100 text-rose-700',
    assigned: 'bg-emerald-100 text-emerald-700',
  }
  const cls = map[status] || 'bg-slate-100 text-slate-600'
  return <span className={`badge ${cls}`}>{status.replace('_', ' ')}</span>
}

export function severityBadge(sev: number) {
  const m: Record<number, string> = {
    5: 'bg-rose-600 text-white',
    4: 'bg-rose-500 text-white',
    3: 'bg-amber-500 text-white',
    2: 'bg-blue-500 text-white',
    1: 'bg-slate-400 text-white',
  }
  const labels: Record<number, string> = { 5: 'CRITICAL', 4: 'URGENT', 3: 'HIGH', 2: 'MODERATE', 1: 'LOW' }
  return <span className={`badge ${m[sev] || 'bg-slate-400 text-white'}`}>{labels[sev] || sev}</span>
}

export function typeIcon(t: string) {
  if (t === 'chemo') return <span title="chemo">💉</span>
  if (t === 'emergency') return <span title="emergency">🚨</span>
  return <span title="consult">🩺</span>
}
