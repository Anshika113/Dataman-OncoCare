import { useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { logout, getName, getRole, getDoctorId } from './lib/api'
import { capsFor } from './lib/roles'
import { useRealtime } from './lib/useRealtime'
import TopBar from './components/TopBar'
import Sidebar, { type NavItem } from './components/Sidebar'
import Dashboard from './components/Dashboard'
import DoctorView from './components/DoctorView'
import DoctorAvailability from './components/DoctorAvailability'
import WorkingWeek from './components/WorkingWeek'
import Schedule from './components/Schedule'
import LiveQueue from './components/LiveQueue'
import FrontDesk from './components/FrontDesk'
import FollowUps from './components/FollowUps'
import Patients from './components/Patients'
import OpsConsole from './components/OpsConsole'
import ActivityFeed from './components/ActivityFeed'
import Toasts from './components/Toasts'
import Assistant from './components/Assistant'
import { type IconName } from './components/icons'

type Tab = 'dashboard' | 'schedule' | 'frontdesk' | 'followups' | 'queue' | 'patients' | 'availability' | 'ops' | 'activity'

// The Ops Console contains demo/simulation controls (simulate busy period,
// advance clock). It is only shown in a dev/demo build (VITE_DEMO=true) so a
// production deployment never exposes clock-fast-forward or fake bookings.
const DEMO = (import.meta.env.VITE_DEMO === 'true' || import.meta.env.DEV)

const TAB_IDS: Tab[] = ['dashboard', 'schedule', 'frontdesk', 'followups', 'queue', 'patients', 'availability', 'ops', 'activity']

export default function App() {
  const { state, connected, events, refresh } = useRealtime()
  const role = getRole()
  const caps = capsFor(role, getDoctorId())
  const isDoctor = role === 'doctor'
  const navigate = useNavigate()
  const location = useLocation()

  // Tab is kept in the URL (/schedule, /queue, …) so views are deep-linkable
  // and survive a refresh. Unknown/missing paths default to the dashboard.
  const urlTab = (() => {
    const seg = location.pathname.replace(/^\/+/, '').split('/')[0] as Tab
    return TAB_IDS.includes(seg) ? seg : 'dashboard'
  })()
  const [tab, setTabState] = useState<Tab>(urlTab)
  const [navOpen, setNavOpen] = useState(false)   // phone drawer

  useEffect(() => { setTabState(urlTab) }, [urlTab])
  const setTab = (t: Tab) => { setTabState(t); navigate(`/${t}`, { replace: false }) }

  // Doctors get a focused, read-only console: a compact "My Day" home plus
  // their schedule and the live queue. They do NOT see the admin analytics
  // dashboard, the ops console, or the audit/activity log.
  const allTabs: { id: Tab; label: string; icon: IconName; show: boolean }[] = isDoctor
    ? [
        { id: 'dashboard', label: 'My Day', icon: 'stethoscope', show: true },
        { id: 'availability', label: 'My Availability', icon: 'clock', show: true },
        { id: 'schedule', label: 'Schedule', icon: 'calendar', show: true },
        { id: 'frontdesk', label: 'Waiting Room', icon: 'users', show: true },
        { id: 'queue', label: 'Live Queue', icon: 'siren', show: true },
      ]
    : [
        { id: 'dashboard', label: 'Dashboard', icon: 'dashboard', show: true },
        { id: 'schedule', label: 'Schedule', icon: 'calendar', show: true },
        { id: 'frontdesk', label: 'Front Desk', icon: 'users', show: true },
        { id: 'followups', label: 'Follow-ups', icon: 'siren', show: caps.canBook },
        { id: 'queue', label: 'Live Queue', icon: 'siren', show: true },
        { id: 'patients', label: 'Doctors & Patients', icon: 'users', show: true },
        { id: 'availability', label: 'Availability', icon: 'clock', show: true },
        { id: 'ops', label: 'Ops Console', icon: 'settings', show: caps.canEdgeCases && DEMO },
        { id: 'activity', label: 'Activity', icon: 'activity', show: caps.canActivity },
      ]
  const tabs = allTabs.filter((t) => t.show)
  const navItems: NavItem[] = tabs.map((t) => ({ id: t.id, label: t.label, icon: t.icon }))

  // A URL can name a tab this role or build doesn't offer (e.g. a doctor opening
  // /activity); send it home rather than rendering an empty page.
  const tabAllowed = tabs.some((t) => t.id === tab)
  useEffect(() => {
    if (!tabAllowed) navigate('/dashboard', { replace: true })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tabAllowed])

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
    <div className="h-full flex flex-row">
      {/* Left navigation rail — icons by default, expands on hover/click.
          On a phone it is a drawer instead; see Sidebar. */}
      <Sidebar items={navItems} active={tab} mobileOpen={navOpen}
        onClose={() => setNavOpen(false)}
        onSelect={(id) => setTab(id as Tab)} />

      {navOpen && (
        <div className="fixed inset-0 z-30 bg-ink-900/40 md:hidden"
          onClick={() => setNavOpen(false)} aria-hidden="true" />
      )}

      {/* Content column: top bar + scrolling main area */}
      <div className="flex-1 min-w-0 flex flex-col">
        <TopBar connected={connected} name={getName()} role={role}
          onMenu={() => setNavOpen(true)}
          onLogout={async () => { await logout(); window.location.href = '/login' }} />

        <main className="flex-1 overflow-auto scroll-stable p-4 lg:p-6">
          {/* Content is anchored to the left edge of the column and fills its
              full width, so the dashboard fills the space beside the sidebar.
              When the sidebar collapses, main widens and this reflows to match —
              no leftover centered margin on the left. */}
          <div className="w-full min-w-0 max-w-[1920px] animate-fadein" key={tab}>
            {tab === 'dashboard' && (isDoctor ? <DoctorView state={state} /> : <Dashboard state={state} />)}
            {tab === 'schedule' && <Schedule state={state} caps={caps} />}
            {tab === 'frontdesk' && (
              <FrontDesk state={state} caps={caps} role={role} doctorId={getDoctorId()} />
            )}
            {tab === 'followups' && caps.canBook && <FollowUps state={state} caps={caps} />}
            {tab === 'queue' && <LiveQueue state={state} caps={caps} />}
            {tab === 'patients' && caps.canManagePatients && <Patients state={state} />}
            {tab === 'availability' && (
              <div className="space-y-4">
                <DoctorAvailability state={state} lockedDoctorId={isDoctor ? getDoctorId() : undefined} />
                <WorkingWeek state={state}
                  doctorId={isDoctor ? getDoctorId() : (state.doctors[0]?.id || '')}
                  canEdit={role === 'admin' || isDoctor} />
              </div>
            )}
            {tab === 'ops' && tabAllowed && <OpsConsole state={state} />}
            {tab === 'activity' && caps.canActivity && <ActivityFeed events={events} state={state} caps={caps} />}
          </div>
        </main>
      </div>

      {/* Looks only: no booking, no cancelling, nothing to undo. */}
      <Assistant state={state} />

      <Toasts events={events} />
    </div>
  )
}
