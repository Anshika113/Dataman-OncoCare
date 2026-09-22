import { useEffect, useState } from 'react'
import { clearSession, getName, getRole, getDoctorId } from './lib/api'
import { capsFor } from './lib/roles'
import { useRealtime } from './lib/useRealtime'
import TopBar from './components/TopBar'
import Dashboard from './components/Dashboard'
import DoctorView from './components/DoctorView'
import DoctorAvailability from './components/DoctorAvailability'
import Schedule from './components/Schedule'
import LiveQueue from './components/LiveQueue'
import Patients from './components/Patients'
import OpsConsole from './components/OpsConsole'
import ActivityFeed from './components/ActivityFeed'
import Toasts from './components/Toasts'

type Tab = 'dashboard' | 'schedule' | 'queue' | 'patients' | 'availability' | 'ops' | 'activity'

export default function App() {
  const { state, connected, events, refresh } = useRealtime()
  const role = getRole()
  const caps = capsFor(role)
  const isDoctor = role === 'doctor'
  const [tab, setTab] = useState<Tab>('dashboard')

  // Doctors get a focused, read-only console: a compact "My Day" home plus
  // their schedule and the live queue. They do NOT see the admin analytics
  // dashboard, the ops console, or the audit/activity log.
  const allTabs: { id: Tab; label: string; icon: string; show: boolean }[] = isDoctor
    ? [
        { id: 'dashboard', label: 'My Day', icon: '🩺', show: true },
        { id: 'availability', label: 'My Availability', icon: '🕑', show: true },
        { id: 'schedule', label: 'Schedule', icon: '🗓️', show: true },
        { id: 'queue', label: 'Live Queue', icon: '🚦', show: true },
      ]
    : [
        { id: 'dashboard', label: 'Dashboard', icon: '📊', show: true },
        { id: 'schedule', label: 'Schedule', icon: '🗓️', show: true },
        { id: 'queue', label: 'Live Queue', icon: '🚦', show: true },
        { id: 'patients', label: 'Doctors & Patients', icon: '🧑‍🤝‍🧑', show: true },
        { id: 'availability', label: 'Availability', icon: '🕑', show: true },
        { id: 'ops', label: 'Ops Console', icon: '🛠️', show: caps.canEdgeCases },
        { id: 'activity', label: 'Activity', icon: '📜', show: caps.canAudit },
      ]
  const tabs = allTabs.filter((t) => t.show)

  // Self-heal: if state ever arrives empty (e.g. the socket reconnected into a
  // blank object after a backend restart), force a hard re-fetch so the
  // dashboard never stays stuck at all zeros.
  const patientCount = state?.patients?.length || 0
  useEffect(() => {
    if (patientCount === 0) refresh()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [patientCount])

  if (!state) {
    return (
      <div className="h-full flex items-center justify-center bg-ink-50">
        <div className="flex flex-col items-center gap-3 text-ink-400">
          <div className="w-9 h-9 border-4 border-brand-100 border-t-brand-600 rounded-full animate-spin" />
          <span className="text-sm font-medium">Connecting to department…</span>
        </div>
      </div>
    )
  }

  return (
    <div className="h-full flex flex-col">
      <TopBar connected={connected} name={getName()} role={role}
        onLogout={() => { clearSession(); window.location.href = '/login' }} />

      <nav className="flex gap-1 px-3 py-2 bg-white border-b border-ink-100 overflow-x-auto no-scrollbar">
        {tabs.map((t) => (
          <button key={t.id} onClick={() => setTab(t.id)}
            className={`nav-pill whitespace-nowrap shrink-0 ${tab === t.id
              ? 'bg-brand-600 text-white shadow-sm shadow-brand-600/25'
              : 'text-ink-500 hover:bg-ink-100 hover:text-ink-800'}`}>
            <span className="mr-1.5">{t.icon}</span>{t.label}
          </button>
        ))}
      </nav>

      <main className="flex-1 overflow-auto p-4 lg:p-6">
        <div className="max-w-[1600px] mx-auto animate-fadein" key={tab}>
          {tab === 'dashboard' && (isDoctor ? <DoctorView state={state} /> : <Dashboard state={state} />)}
          {tab === 'schedule' && <Schedule state={state} caps={caps} />}
          {tab === 'queue' && <LiveQueue state={state} caps={caps} />}
          {tab === 'patients' && !isDoctor && <Patients state={state} />}
          {tab === 'availability' && (
            <DoctorAvailability state={state} lockedDoctorId={isDoctor ? getDoctorId() : undefined} />
          )}
          {tab === 'ops' && caps.canEdgeCases && <OpsConsole state={state} />}
          {tab === 'activity' && caps.canAudit && <ActivityFeed events={events} state={state} />}
        </div>
      </main>

      <Toasts events={events} />
    </div>
  )
}
