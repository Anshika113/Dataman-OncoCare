import { useState } from 'react'
import { api, setSession } from '../lib/api'
import { Icon, type IconName } from '../components/icons'

export default function Login() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPw, setShowPw] = useState(false)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setErr(''); setBusy(true)
    try {
      const r = await api.login(username, password)
      setSession(r.token, r.role, r.name, r.doctor_id)
      window.location.href = '/'
    } catch (e: any) {
      setErr(e.message || 'Login failed')
    } finally {
      setBusy(false)
    }
  }

  const features: { icon: IconName; t: string; d: string }[] = [
    { icon: 'calendar', t: 'Smart scheduling', d: 'Conflict-free doctor & chemo-room allocation' },
    { icon: 'zap', t: 'Live priority queue', d: '5-level emergency triage in real time' },
    { icon: 'shield', t: 'Automatic recovery', d: 'Sick leave, overruns, breakdowns handled' },
  ]

  return (
    <div className="h-full flex bg-ink-50">
      {/* Left brand panel */}
      <div className="hidden lg:flex lg:w-1/2 relative overflow-hidden bg-gradient-to-br from-brand-800 via-brand-900 to-ink-950 text-white">
        <div className="absolute inset-0 opacity-20"
          style={{ backgroundImage: 'radial-gradient(circle at 20% 20%, #559ca9 0, transparent 40%), radial-gradient(circle at 80% 0, #37808d 0, transparent 35%), radial-gradient(circle at 60% 90%, #8bbdc6 0, transparent 40%)' }} />
        <div className="absolute -bottom-24 -right-24 w-96 h-96 rounded-full bg-brand-500/20 blur-3xl" />
        <div className="relative flex flex-col justify-between p-12 w-full">
          <div className="flex items-center gap-3">
            <div className="w-11 h-11 rounded-2xl bg-white/10 backdrop-blur border border-white/20 flex items-center justify-center text-white"><Icon name="cross" className="w-6 h-6" strokeWidth={2.2} /></div>
            <span className="text-lg font-bold tracking-tight">DataMan OncoCare</span>
          </div>

          <div>
            <h1 className="text-4xl xl:text-5xl font-extrabold leading-tight tracking-tight">
              Run your oncology<br />department with <span className="text-brand-300">clarity</span>.
            </h1>
            <p className="mt-4 text-brand-100/70 max-w-md text-[15px] leading-relaxed">
              A real-time patient care system that schedules doctors, manages the
              queue, and recovers automatically from the day's disruptions.
            </p>

            <div className="mt-10 space-y-4">
              {features.map((f) => (
                <div key={f.t} className="flex items-start gap-3">
                    <div className="w-10 h-10 rounded-xl bg-white/10 border border-white/15 flex items-center justify-center text-white shrink-0"><Icon name={f.icon} className="w-5 h-5" /></div>
                  <div>
                    <div className="font-semibold text-sm">{f.t}</div>
                    <div className="text-xs text-brand-100/60">{f.d}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="text-xs text-brand-100/50">© {new Date().getFullYear()} DataMan OncoCare · Patient Scheduling & Operations</div>
        </div>
      </div>

      {/* Right form panel */}
      <div className="flex-1 flex items-center justify-center p-6">
        <div className="w-full max-w-sm animate-fadein">
          <div className="lg:hidden flex items-center gap-2.5 mb-8">
            <div className="w-10 h-10 rounded-xl bg-brand-600 flex items-center justify-center text-white"><Icon name="cross" className="w-5 h-5" strokeWidth={2.2} /></div>
            <span className="text-lg font-bold text-ink-900">DataMan OncoCare</span>
          </div>

          <h2 className="text-2xl font-extrabold text-ink-900 tracking-tight">Welcome back</h2>
          <p className="text-sm text-ink-400 mt-1 mb-8">Sign in to the operations console.</p>

          <form onSubmit={submit} className="space-y-4">
            <div>
              <label htmlFor="login-user" className="label">Username</label>
              <div className="relative">
                <span className="absolute left-3.5 top-1/2 -translate-y-1/2 text-ink-300" aria-hidden>
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" /></svg>
                </span>
                <input id="login-user" className="input pl-10" value={username} onChange={(e) => setUsername(e.target.value)} autoFocus placeholder="username" autoComplete="username" />
              </div>
            </div>
            <div>
              <label htmlFor="login-pass" className="label">Password</label>
              <div className="relative">
                <span className="absolute left-3.5 top-1/2 -translate-y-1/2 text-ink-300" aria-hidden>
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" d="M16 11V7a4 4 0 00-8 0v4M5 11h14v10H5z" /></svg>
                </span>
                <input id="login-pass" className="input pl-10 pr-10" type={showPw ? 'text' : 'password'} value={password} onChange={(e) => setPassword(e.target.value)} placeholder="••••••••" autoComplete="current-password" />
                <button type="button" onClick={() => setShowPw(s => !s)} aria-label={showPw ? 'Hide password' : 'Show password'} className="absolute right-3 top-1/2 -translate-y-1/2 text-ink-400 hover:text-ink-600 text-xs font-semibold">
                  {showPw ? 'HIDE' : 'SHOW'}
                </button>
              </div>
            </div>

            {err && (
              <div className="flex items-center gap-2 text-sm text-rose-700 bg-rose-50 border border-rose-100 rounded-xl px-3 py-2.5">
                <Icon name="alertTriangle" className="w-4 h-4 shrink-0" />{err}
              </div>
            )}

            <button className="btn-primary w-full !py-3 text-[15px]" disabled={busy}>
              {busy ? (
                <><span className="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" />Signing in…</>
              ) : 'Sign in'}
            </button>
          </form>

          <div className="mt-8 pt-6 border-t border-ink-100">
            <div className="text-[11px] font-bold uppercase tracking-wider text-ink-400 mb-3">Demo accounts</div>
            {/* All four roles the brief names — doctors, nurses, front-desk and
                care coordinators — are one click each. The coordinator was
                missing, which meant the follow-up console it exists for was
                effectively unreachable for anyone exploring the app. */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              {[['admin', 'Admin'], ['nurse', 'Nurse'], ['coord', 'Coordinator'],
                ['doctor', 'Doctor']].map(([u, label]) => (
                <button key={u} onClick={() => { setUsername(u); setPassword(u === 'coord' ? 'coord123' : u + '123') }}
                  className="rounded-xl border border-ink-200 bg-white px-2 py-2 text-xs font-semibold text-ink-600 hover:border-brand-300 hover:text-brand-700 transition">
                  {label}
                </button>
              ))}
            </div>

            <div className="text-[11px] font-bold uppercase tracking-wider text-ink-400 mt-5 mb-3">
              Or a named doctor — each sees only their own list
            </div>
            <div className="grid grid-cols-3 sm:grid-cols-5 gap-2">
              {[['amina', 'Amina'], ['ben', 'Ben'], ['chloe', 'Chloe'],
                ['dan', 'Dan'], ['elena', 'Elena']].map(([u, label]) => (
                <button key={u} onClick={() => { setUsername(u); setPassword('doctor123') }}
                  className="rounded-xl border border-ink-200 bg-white px-2 py-2 text-xs font-semibold text-ink-600 hover:border-brand-300 hover:text-brand-700 transition">
                  {label}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
