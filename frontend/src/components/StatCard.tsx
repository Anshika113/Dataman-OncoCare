export default function StatCard({ label, value, sub, icon, tone = 'brand', alert, onClick }: {
  label: string; value: string | number; sub?: string; icon: string
  tone?: 'brand' | 'emerald' | 'amber' | 'rose' | 'violet'
  alert?: boolean
  onClick?: () => void
}) {
  const tones: Record<string, string> = {
    brand: 'bg-brand-50 text-brand-600',
    emerald: 'bg-emerald-50 text-emerald-600',
    amber: 'bg-amber-50 text-amber-600',
    rose: 'bg-rose-50 text-rose-600',
    violet: 'bg-violet-50 text-violet-600',
  }
  return (
    <div
      onClick={onClick}
      role={onClick ? 'button' : undefined}
      className={`card card-hover p-5 ${alert ? 'ring-2 ring-rose-200' : ''} ${onClick ? 'cursor-pointer active:scale-[0.99] transition-transform' : ''}`}>
      <div className="flex items-start justify-between">
        <div>
          <div className="text-[11px] font-bold uppercase tracking-wider text-ink-400">{label}</div>
          <div className="text-3xl font-extrabold text-ink-900 mt-1">{value}</div>
          {sub && <div className="text-xs text-ink-400 mt-0.5">{sub}</div>}
        </div>
        <div className={`w-11 h-11 rounded-2xl flex items-center justify-center text-xl ${tones[tone]}`}>{icon}</div>
      </div>
    </div>
  )
}
