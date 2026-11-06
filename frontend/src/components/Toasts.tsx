import { useEffect, useRef, useState } from 'react'

interface Toast { id: number; msg: string; tone: string }

const TONE: Record<string, string> = {
  critical: 'border-rose-500 bg-rose-50 text-rose-800',
  warning: 'border-amber-500 bg-amber-50 text-amber-800',
  info: 'border-brand-500 bg-brand-50 text-brand-800',
}

let _seq = 0

export default function Toasts({ events }: { events: any[] }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const seenRef = useRef<string | null>(null)
  const timers = useRef<number[]>([])

  useEffect(() => {
    // only react to the newest event, and only once (identified by its type+at)
    if (!events.length) return
    const e = events[0]
    if (!e.message) return
    const key = `${e.type}:${e.at ?? e.message}`
    if (key === seenRef.current) return
    seenRef.current = key
    const tone = e.severity === 'critical' ? 'critical' : e.severity === 'warning' ? 'warning' : 'info'
    const id = ++_seq
    setToasts((prev) => [{ id, msg: e.message, tone }, ...prev].slice(0, 4))
    const timer = window.setTimeout(
      () => setToasts((prev) => prev.filter((x) => x.id !== id)), 6000)
    timers.current.push(timer)
  }, [events])

  useEffect(() => () => timers.current.forEach(clearTimeout), [])

  return (
    <div className="fixed bottom-4 right-4 space-y-2 z-50 w-80 max-w-[calc(100vw-2rem)]"
      role="status" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} className={`card border-l-4 px-4 py-3 text-sm shadow-lg ${TONE[t.tone]}`}>
          {t.msg}
        </div>
      ))}
    </div>
  )
}
