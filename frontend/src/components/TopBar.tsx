import { ROLE_LABEL, ROLE_TONE } from '../lib/roles'

export default function TopBar({ connected, name, role, onLogout }: {
  connected: boolean; name: string; role: string; onLogout: () => void
}) {
  return (
    <header className="flex items-center justify-between px-4 lg:px-6 py-3 bg-white border-b border-ink-100 shadow-sm">
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-brand-500 to-brand-700 flex items-center justify-center text-white text-xl shadow-sm shadow-brand-600/30">✚</div>
        <div>
          <div className="font-extrabold text-ink-900 leading-tight tracking-tight">Dataman OncoCare</div>
          <div className="text-[11px] text-ink-400 font-medium">Cancer Care · Scheduling & Operations</div>
        </div>
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
