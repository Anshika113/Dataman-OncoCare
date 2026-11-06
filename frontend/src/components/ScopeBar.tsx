// Whose data am I looking at?
//
// A doctor is allowed to see the whole department — they need to, to hand a
// patient to a colleague — but should land on their own list rather than
// everyone's. This renders nothing at all for admin and nurse, who are
// department-wide by definition.

export default function ScopeBar({ mine, setMine, doctorName, noun = 'schedule' }: {
  mine: boolean
  setMine: (v: boolean) => void
  doctorName: string
  noun?: string
}) {
  return (
    <div className="flex items-center gap-2 flex-wrap min-w-0">
      <div className="flex rounded-xl border border-ink-200 overflow-hidden">
        <button type="button" onClick={() => setMine(true)}
          aria-pressed={mine}
          className={`px-3 py-1.5 text-xs font-semibold transition ${
            mine ? 'bg-brand-600 text-white' : 'bg-white text-ink-500 hover:text-ink-800'}`}>
          My {noun}
        </button>
        <button type="button" onClick={() => setMine(false)}
          aria-pressed={!mine}
          className={`px-3 py-1.5 text-xs font-semibold transition ${
            !mine ? 'bg-brand-600 text-white' : 'bg-white text-ink-500 hover:text-ink-800'}`}>
          Whole department
        </button>
      </div>
      <span className="text-[11px] text-ink-400 min-w-0">
        {mine ? doctorName || 'your list' : 'everyone — read-only beyond your own patients'}
      </span>
    </div>
  )
}
