import { useEffect, useState } from 'react'
import { Icon, type IconName } from './icons'

export interface NavItem {
  id: string
  label: string
  icon: IconName
}

// A left navigation rail that collapses to icons by default and expands to show
// labels on hover (or when an item is clicked, which pins it open). When
// collapsed, the content area beside it keeps full width so the dashboard fills
// the page.
//
// On a phone there is no hover and no room: a 76px rail costs a fifth of the
// screen to show icons nobody can read. There it becomes a drawer — off
// canvas until the menu button is pressed, labels always visible, and closing
// itself as soon as something is chosen.
export default function Sidebar({
  items, active, onSelect, mobileOpen = false, onClose,
}: {
  items: NavItem[]
  active: string
  onSelect: (id: string) => void
  mobileOpen?: boolean
  onClose?: () => void
}) {
  const [open, setOpen] = useState(false)   // hover-expanded
  const [pinned, setPinned] = useState(false) // click-pinned (sticky)
  const [phone, setPhone] = useState(
    () => typeof window !== 'undefined'
      && window.matchMedia('(max-width: 767px)').matches)

  useEffect(() => {
    const mq = window.matchMedia('(max-width: 767px)')
    const sync = (e: MediaQueryListEvent) => setPhone(e.matches)
    mq.addEventListener('change', sync)
    return () => mq.removeEventListener('change', sync)
  }, [])

  // Escape closes the drawer, which is the one thing every drawer must do.
  useEffect(() => {
    if (!mobileOpen) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose?.() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [mobileOpen, onClose])

  const expanded = phone || open || pinned
  const togglePin = () => { if (open) setPinned((p) => !p) }

  return (
    <nav
      onMouseEnter={() => { if (!phone) setOpen(true) }}
      onMouseLeave={() => { if (!phone) setOpen(false) }}
      className={`fixed inset-y-0 left-0 z-40 md:relative md:z-20 flex-shrink-0 h-full flex flex-col bg-white border-r border-ink-100 shadow-sm overflow-hidden transition-transform md:transition-[width] duration-200 ease-out md:translate-x-0 ${
        mobileOpen ? 'translate-x-0 shadow-pop' : '-translate-x-full'}`}
      style={{ width: phone ? 264 : (expanded ? 248 : 76) }}
      aria-label="Primary"
      aria-hidden={phone && !mobileOpen ? true : undefined}
    >
      {/* brand — always visible, expands with the labels */}
      <div className="flex items-center gap-3 px-4 pt-4 pb-3 h-16 flex-shrink-0 border-b border-ink-100/70">
        <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-brand-500 to-brand-700 flex items-center justify-center text-white shadow-sm shadow-brand-600/30 flex-shrink-0">
          <Icon name="cross" className="w-5 h-5" strokeWidth={2.2} />
        </div>
        <div className={`overflow-hidden whitespace-nowrap transition-all duration-200 ${expanded ? 'opacity-100 flex-1 min-w-0' : 'opacity-0 max-w-0'}`}>
          <div className="font-extrabold text-ink-900 leading-tight tracking-tight truncate">DataMan OncoCare</div>
          <div className="text-[10px] text-ink-400 font-medium">Care Scheduling</div>
        </div>
        {phone && (
          <button onClick={onClose} aria-label="Close menu"
            className="ml-auto w-9 h-9 rounded-lg flex items-center justify-center text-ink-400 hover:bg-ink-100 hover:text-ink-700">
            <Icon name="x" className="w-5 h-5" />
          </button>
        )}
      </div>

      {/* nav items */}
      <div className="flex-1 flex flex-col gap-1 px-3 py-3 overflow-y-auto">
        {items.map((t) => {
          const isActive = active === t.id
          return (
            <button
              key={t.id}
              onClick={() => { onSelect(t.id); if (phone) onClose?.(); else setPinned(true) }}
              title={t.label}
              aria-label={t.label}
              aria-current={isActive ? 'page' : undefined}
              className={`group relative flex items-center gap-3 px-3 h-11 rounded-xl whitespace-nowrap overflow-hidden transition-colors ${
                isActive
                  ? 'bg-brand-600 text-white shadow-sm shadow-brand-600/25'
                  : 'text-ink-500 hover:bg-ink-100 hover:text-ink-800'
              }`}
            >
              {/* active accent bar */}
              {isActive && <span className="absolute left-0 top-1/2 -translate-y-1/2 h-6 w-1 rounded-r bg-white/80" />}
              <Icon name={t.icon} className="w-5 h-5 flex-shrink-0" />
              <span className={`font-semibold transition-all duration-200 ${expanded ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'}`}>
                {t.label}
              </span>
            </button>
          )
        })}
      </div>

      {/* pin control — meaningless on a phone, where the drawer is never a rail */}
      <div className="flex-shrink-0 border-t border-ink-100/70 px-3 py-2 hidden md:block">
        <button
          onClick={togglePin}
          title={pinned ? 'Collapse menu' : 'Expand menu'}
          className="w-full h-9 rounded-lg flex items-center gap-3 px-3 text-ink-400 hover:bg-ink-100 hover:text-ink-700 transition-colors"
        >
          <Icon
            name="chevronRight"
            className={`w-5 h-5 flex-shrink-0 transition-transform duration-200 ${expanded ? 'rotate-0' : 'rotate-180'}`}
          />
          <span className={`text-xs font-semibold whitespace-nowrap overflow-hidden transition-all duration-200 ${expanded ? 'opacity-100' : 'opacity-0 max-w-0'}`}>
            {pinned ? 'Collapse' : 'Expand'}
          </span>
        </button>
      </div>
    </nav>
  )
}
