import type { SVGProps } from 'react'

// A single dependency-free icon set (stroke-based, currentColor) so the UI uses
// crisp, themeable line icons instead of emoji. Every glyph is sized via
// Tailwind utility classes on the <Icon> element (e.g. className="w-5 h-5").

export type IconName =
  | 'dashboard' | 'calendar' | 'pulse' | 'clipboard' | 'activity'
  | 'clock' | 'settings' | 'alert' | 'alertTriangle' | 'check' | 'checkCircle'
  | 'x' | 'xCircle' | 'lock' | 'zap' | 'shield' | 'stethoscope' | 'syringe'
  | 'users' | 'user' | 'userPlus' | 'edit' | 'phone' | 'bed' | 'siren'
  | 'hourglass' | 'refresh' | 'chartBar' | 'trendUp' | 'flask' | 'info'
  | 'ban' | 'arrowRight' | 'note' | 'plus' | 'chevronRight' | 'cross'

const PATHS: Record<IconName, JSX.Element> = {
  dashboard: <><rect x="3" y="3" width="7" height="9" rx="1" /><rect x="14" y="3" width="7" height="5" rx="1" /><rect x="14" y="12" width="7" height="9" rx="1" /><rect x="3" y="16" width="7" height="5" rx="1" /></>,
  calendar: <><rect x="3" y="4" width="18" height="18" rx="2" /><path d="M16 2v4M8 2v4M3 10h18" /></>,
  pulse: <path d="M22 12h-4l-3 9L9 3l-3 9H2" />,
  clipboard: <><rect x="8" y="2" width="8" height="4" rx="1" /><path d="M16 4h2a2 2 0 012 2v14a2 2 0 01-2 2H6a2 2 0 01-2-2V6a2 2 0 012-2h2" /></>,
  activity: <path d="M22 12h-4l-3 9L9 3l-3 9H2" />,
  clock: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>,
  settings: <path d="M12 15a3 3 0 100-6 3 3 0 000 6z" />,
  alert: <><circle cx="12" cy="12" r="9" /><path d="M12 8v4M12 16h.01" /></>,
  alertTriangle: <><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" /><path d="M12 9v4M12 17h.01" /></>,
  check: <path d="M20 6L9 17l-5-5" />,
  checkCircle: <><circle cx="12" cy="12" r="9" /><path d="M8 12l3 3 5-6" /></>,
  x: <path d="M18 6L6 18M6 6l12 12" />,
  xCircle: <><circle cx="12" cy="12" r="9" /><path d="M15 9l-6 6M9 9l6 6" /></>,
  lock: <><rect x="4" y="11" width="16" height="10" rx="2" /><path d="M8 11V7a4 4 0 018 0v4" /></>,
  zap: <path d="M13 2L3 14h7l-1 8 10-12h-7l1-8z" />,
  shield: <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />,
  stethoscope: <path d="M5 3v6a4 4 0 008 0V3M9 15v2a5 5 0 0010 0v-1" />,
  syringe: <path d="M18 2l4 4M17 3l4 4M14 6l4 4M19 7l-9 9-4 1 1-4 9-9zM9 13l2 2" />,
  users: <><path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2" /><circle cx="9" cy="7" r="4" /><path d="M23 21v-2a4 4 0 00-3-3.87M16 3.13a4 4 0 010 7.75" /></>,
  user: <><circle cx="12" cy="8" r="4" /><path d="M4 21v-1a6 6 0 016-6h4a6 6 0 016 6v1" /></>,
  userPlus: <><path d="M16 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2" /><circle cx="8.5" cy="7" r="4" /><path d="M20 8v6M23 11h-6" /></>,
  edit: <path d="M12 20h9M16.5 3.5a2.12 2.12 0 013 3L7 19l-4 1 1-4z" />,
  phone: <path d="M22 16.92v3a2 2 0 01-2.18 2 19.79 19.79 0 01-8.63-3.07 19.5 19.5 0 01-6-6 19.79 19.79 0 01-3.07-8.67A2 2 0 014.11 2h3a2 2 0 012 1.72c.13.96.36 1.9.7 2.81a2 2 0 01-.45 2.11L8.09 9.91a16 16 0 006 6l1.27-1.27a2 2 0 012.11-.45c.9.34 1.85.57 2.81.7A2 2 0 0122 16.92z" />,
  bed: <><path d="M3 8v10M3 12h18v6M3 16h18" /><path d="M7 12V9a1 1 0 011-1h3a1 1 0 011 1v3" /></>,
  siren: <><path d="M7 18v-6a5 5 0 0110 0v6" /><path d="M5 21h14a1 1 0 001-1v-1H4v1a1 1 0 001 1zM12 3v2M4.9 6.9L3.5 5.5M19.1 6.9l1.4-1.4" /></>,
  hourglass: <path d="M6 2h12M6 22h12M7 2v4l5 5 5-5V2M7 22v-4l5-5 5 5v4" />,
  refresh: <path d="M23 4v6h-6M1 20v-6h6M3.51 9a9 9 0 0114.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0020.49 15" />,
  chartBar: <path d="M3 3v18h18M8 17V9M13 17V5M18 17v-6" />,
  trendUp: <path d="M22 7l-8.5 8.5-5-5L2 17M16 7h6v6" />,
  flask: <path d="M9 2h6M10 2v6.5L4.5 18a2 2 0 001.8 3h11.4a2 2 0 001.8-3L14 8.5V2M7 14h10" />,
  info: <><circle cx="12" cy="12" r="9" /><path d="M12 11v5M12 8h.01" /></>,
  ban: <><circle cx="12" cy="12" r="9" /><path d="M5.6 5.6l12.8 12.8" /></>,
  arrowRight: <path d="M5 12h14M13 6l6 6-6 6" />,
  note: <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8zM14 2v6h6M9 13h6M9 17h6" />,
  plus: <path d="M12 5v14M5 12h14" />,
  chevronRight: <path d="M9 18l6-6-6-6" />,
  cross: <path d="M12 3v18M3 12h18" />,
}

export function Icon({ name, ...props }: { name: IconName } & SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8}
      strokeLinecap="round" strokeLinejoin="round" aria-hidden {...props}>
      {PATHS[name]}
    </svg>
  )
}

// Consistent, icon-led status/feedback line (replaces ad-hoc emoji prefixes).
export function Message({ ok, text }: { ok: boolean; text: string }) {
  return (
    <span className={`inline-flex items-center gap-1.5 font-medium ${ok ? 'text-emerald-700' : 'text-rose-700'}`}>
      <Icon name={ok ? 'checkCircle' : 'alertTriangle'} className="w-4 h-4 shrink-0" />
      <span>{text}</span>
    </span>
  )
}
