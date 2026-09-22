import { useEffect, useState } from 'react'

interface Toast { id: number; msg: string; tone: string }

const TONE: Record<string, string> = {
  critical: 'border-rose-500 bg-rose-50 text-rose-800',
  warning: 'border-amber-500 bg-amber-50 text-amber-800',
  info: 'border-brand-500 bg-brand-50 text-brand-800',
}

export default function Toasts({ events }: { events: any[] }) {
  const [toasts, setToasts] = useState<Toast[]>([])

  useEffect(() => {
    if (!events.length) return
    const e = events[0]
    if (!e.message) return
    const tone = e.severity === 'critical' ? 'critical' : e.severity === 'warning' ? 'warning' : 'info'
    const t: Toast = { id: Date.now(), msg: e.message, tone }
    setToasts((prev) => [t, ...prev].slice(0, 4))
    setTimeout(() => setToasts((prev) => prev.filter((x) => x.id !== t.id)), 6000)
  }, [events])

  return (
    <div className="fixed bottom-4 right-4 space-y-2 z-50 w-80">
      {toasts.map((t) => (
        <div key={t.id} className={`card border-l-4 px-4 py-3 text-sm shadow-lg ${TONE[t.tone]}`}>
          {t.msg}
        </div>
      ))}
    </div>
  )
}
