import {
  ResponsiveContainer, PieChart, Pie, Cell, BarChart, Bar,
  XAxis, YAxis, CartesianGrid, Tooltip,
} from 'recharts'

export const PALETTE = ['#2543eb', '#10b981', '#f59e0b', '#f43f5e', '#8b5cf6', '#06b6d4']

export function Donut({ data, centerLabel, centerValue }: {
  data: { name: string; value: number }[]
  centerLabel?: string
  centerValue?: string | number
}) {
  const total = data.reduce((s, d) => s + d.value, 0)
  return (
    <div className="relative">
      <ResponsiveContainer width="100%" height={180}>
        <PieChart>
          <Pie data={data} dataKey="value" nameKey="name" cx="50%" cy="50%"
            innerRadius={58} outerRadius={82} paddingAngle={2} strokeWidth={0}>
            {data.map((_, i) => <Cell key={i} fill={PALETTE[i % PALETTE.length]} />)}
          </Pie>
          <Tooltip contentStyle={tooltipStyle} />
        </PieChart>
      </ResponsiveContainer>
      <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
        <span className="text-2xl font-extrabold text-ink-900">{centerValue ?? total}</span>
        {centerLabel && <span className="text-[11px] font-semibold text-ink-400 uppercase tracking-wide">{centerLabel}</span>}
      </div>
    </div>
  )
}

export function HoursBar({ data }: { data: { hour: string; count: number }[] }) {
  return (
    <ResponsiveContainer width="100%" height={200}>
      <BarChart data={data} margin={{ top: 8, right: 4, left: -20, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#eceef2" />
        <XAxis dataKey="hour" tick={{ fontSize: 11, fill: '#7b869c' }} axisLine={false} tickLine={false} />
        <YAxis tick={{ fontSize: 11, fill: '#7b869c' }} axisLine={false} tickLine={false} allowDecimals={false} />
        <Tooltip contentStyle={tooltipStyle} cursor={{ fill: '#f6f7f9' }} />
        <Bar dataKey="count" name="Appointments" fill="#2543eb" radius={[6, 6, 0, 0]} maxBarSize={38} />
      </BarChart>
    </ResponsiveContainer>
  )
}

export function Legend({ data }: { data: { name: string; value: number }[] }) {
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1.5 mt-3">
      {data.map((d, i) => (
        <div key={d.name} className="flex items-center gap-1.5 text-xs text-ink-600">
          <span className="w-2.5 h-2.5 rounded-full" style={{ background: PALETTE[i % PALETTE.length] }} />
          <span className="font-medium">{d.name}</span>
          <span className="text-ink-400">{d.value}</span>
        </div>
      ))}
    </div>
  )
}

const tooltipStyle: React.CSSProperties = {
  borderRadius: 12,
  border: '1px solid #eceef2',
  boxShadow: '0 8px 24px -8px rgba(16,24,40,.2)',
  fontSize: 12,
  padding: '8px 12px',
}
