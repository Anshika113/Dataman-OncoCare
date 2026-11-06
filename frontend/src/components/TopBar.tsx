import { ROLE_LABEL, ROLE_TONE } from '../lib/roles'

export default function TopBar({ connected, name, role, onLogout, onMenu }: {
  connected: boolean; name: string; role: string; onLogout: () => void
  onMenu?: () => void
}) {
  return (
    <header className="flex items-center justify-between px-4 lg:px-6 py-3 bg-white border-b border-ink-100 shadow-sm">
      <div className="min-w-0 flex items-center gap-2">
        {/* On a phone the navigation is a drawer, so it needs a way in. */}
        {onMenu && (
          <button onClick={onMenu} aria-label="Open menu"
            className="md:hidden w-9 h-9 -ml-1 rounded-lg flex items-center justify-center text-ink-500 hover:bg-ink-100 hover:text-ink-800 flex-shrink-0">
            <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
              <path strokeLinecap="round" d="M4 6h16M4 12h16M4 18h16" />
            </svg>
          </button>
        )}
        {/* The brand mark lives in the left sidebar; this header carries a
            lightweight context label for the current section. */}
        <div className="text-[11px] text-ink-400 font-medium truncate">Cancer Care · Scheduling &amp; Operations</div>
      </div>

      <div className="flex items-center gap-3 lg:gap-5">
        <div className={`hidden sm:flex items-center gap-2 text-xs font-semibold px-3 py-1.5 rounded-full ${connected ? 'bg-emerald-50 text-emerald-700' : 'bg-rose-50 text-rose-700'}`}>
          <span className={`w-2 h-2 rounded-full ${connected ? 'bg-emerald-500 animate-pulse' : 'bg-rose-500'}`} />
          {connected ? 'Live' : 'Reconnecting…'}
        </div>

        <div className="flex items-center gap-3 pl-3 border-l border-ink-100">
          <div className="text-right hidden sm:block">
            <div className="text-sm font-bold text-ink-800 leading-tight">{name}</div>
            <div className={`badge mt-0.5 ${ROLE_TONE[role] || 'bg-ink-100 text-ink-600'}`}>{ROLE_LABEL[role] || role}</div>
          </div>
          <div className="w-9 h-9 rounded-full bg-brand-100 text-brand-700 flex items-center justify-center text-sm font-bold">
            {name?.[0]?.toUpperCase() || '?'}
          </div>
          <button onClick={onLogout} className="btn-ghost !px-3 !py-2 text-xs" title="Log out">
            <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" /></svg>
            <span className="hidden sm:inline">Log out</span>
          </button>
        </div>
      </div>
    </header>
  )
}
