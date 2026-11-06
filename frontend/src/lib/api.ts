// Minimal typed API client for the care backend.

const TOKEN_KEY = 'care_token'
const ROLE_KEY = 'care_role'
const NAME_KEY = 'care_name'
const DOC_KEY = 'care_doctor_id'

export function getToken() { return localStorage.getItem(TOKEN_KEY) || '' }
export function getRole() { return localStorage.getItem(ROLE_KEY) || '' }
export function getName() { return localStorage.getItem(NAME_KEY) || '' }
export function getDoctorId() { return localStorage.getItem(DOC_KEY) || '' }
export function isAuthenticated() { return !!getToken() }

export function setSession(token: string, role: string, name: string, doctor_id = '') {
  localStorage.setItem(TOKEN_KEY, token)
  localStorage.setItem(ROLE_KEY, role)
  localStorage.setItem(NAME_KEY, name)
  localStorage.setItem(DOC_KEY, doctor_id || '')
}
export async function logout() {
  const tok = getToken()
  try {
    await fetch('/api/logout', {
      method: 'POST',
      headers: { Authorization: 'Bearer ' + tok },
    })
  } catch {
    /* best-effort; we clear the session regardless */
  }
  clearSession()
}

export function clearSession() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(ROLE_KEY)
  localStorage.removeItem(NAME_KEY)
  localStorage.removeItem(DOC_KEY)
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

function humanize(status: number, detail: string): string {
  // Map the backend's {"detail": "..."} payloads to friendly copy.
  if (detail) {
    try {
      const j = JSON.parse(detail)
      if (j && typeof j.detail === 'string') return j.detail
      // FastAPI validation errors: [{ loc: ['body', 'field'], msg: '...' }]
      if (j && Array.isArray(j.detail) && j.detail[0]?.msg) {
        const { loc, msg } = j.detail[0]
        return `${String(loc?.[loc.length - 1] ?? 'Input').replace(/_/g, ' ')}: ${msg}`
      }
    } catch {
      if (!detail.includes('<html')) return detail
    }
  }
  const fallback: Record<number, string> = {
    400: 'That request was invalid.',
    401: 'Your session has expired. Please sign in again.',
    403: 'You do not have permission to do that.',
    404: 'That item was not found.',
    409: 'That action conflicts with the current schedule.',
    429: 'Too many attempts. Please wait a moment and try again.',
    500: 'Something went wrong on our side. Please try again.',
  }
  return fallback[status] || `Request failed (${status}).`
}

async function req<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  const tok = getToken()
  if (tok) headers['Authorization'] = 'Bearer ' + tok
  const res = await fetch(path, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (res.status === 401) {
    clearSession()
    window.location.href = '/login'
    throw new ApiError(401, 'unauthorized')
  }
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new ApiError(res.status, humanize(res.status, text))
  }
  return res.json() as Promise<T>
}

export const api = {
  login: (u: string, p: string) =>
    req<{ token: string; role: string; name: string; doctor_id: string }>('/api/login', 'POST', { username: u, password: p }),
  health: () => req<{ ok: boolean }>('/health'),
  state: () => req<any>('/api/state'),
  insights: () => req<any>('/api/insights'),
  dates: () => req<{ active_day: string; days: string[] }>('/api/dates'),
  doctors: () => req<any[]>('/api/doctors'),
  appointments: () => req<any[]>('/api/appointments'),
  queue: () => req<any>('/api/queue'),
  logs: () => req<any[]>('/api/logs'),
  notifications: () => req<any[]>('/api/notifications'),

   bookConsult: (b: any) => req<any>('/api/appointments/consult', 'POST', b),
   bookChemo: (b: any) => req<any>('/api/appointments/chemo', 'POST', b),
   bookWithRecs: (b: any) => req<any>('/api/appointments/book-with-recs', 'POST', b),
  visitDurations: (doctorId: string) =>
    req<any>(`/api/doctors/${doctorId}/visit-durations`, 'GET'),
  walkInOptions: (b: any) => req<any>('/api/walk-ins/options', 'POST', b),
  followUps: (date = '') =>
    req<any>(`/api/follow-ups?date=${encodeURIComponent(date)}`, 'GET'),
  capacity: (start = '', days = 7, doctorId = '') =>
    req<any>(`/api/capacity?start=${encodeURIComponent(start)}`
      + `&days=${days}&doctor_id=${encodeURIComponent(doctorId)}`, 'GET'),
  patientLink: (apptId: string) =>
    req<any>(`/api/appointments/${apptId}/patient-link`, 'GET'),
  previewImport: (csv: string) =>
    req<any>('/api/import/patients/preview', 'POST', { csv }),
  importPatients: (csv: string) =>
    req<any>('/api/import/patients', 'POST', { csv }),

  // the read-only assistant: it chooses a view, the server fetches the rows
  ask: (question: string) => req<any>('/api/ask', 'POST', { question }),
  askCapabilities: () => req<{ model: boolean }>('/api/ask/capabilities'),
  askVoice: async (clip: Blob): Promise<{ transcript: string }> => {
    const form = new FormData()
    form.append('file', clip, 'clip.wav')
    const tok = getToken()
    const res = await fetch('/api/ask/voice', {
      method: 'POST',
      headers: tok ? { Authorization: 'Bearer ' + tok } : {},
      body: form,
    })
    if (!res.ok) {
      const text = await res.text().catch(() => '')
      throw new ApiError(res.status, humanize(res.status, text))
    }
    return res.json()
  },

  outcomes: (date = '', against = '', doctorId = '') =>
    req<any>(`/api/outcomes?date=${encodeURIComponent(date)}`
      + `&against=${encodeURIComponent(against)}`
      + `&doctor_id=${encodeURIComponent(doctorId)}`, 'GET'),

  // consent + point-of-care context
  setConsent: (patientId: string, b: any) =>
    req<any>(`/api/patients/${patientId}/consent`, 'PUT', b),
  dayContext: (doctorId: string, date = '') =>
    req<any>(`/api/doctors/${doctorId}/day-context?date=${encodeURIComponent(date)}`, 'GET'),

  // working week + case-mix rules
  week: (doctorId: string) => req<any>(`/api/doctors/${doctorId}/week`, 'GET'),
  dayPlan: (doctorId: string, date = '') =>
    req<any>(`/api/doctors/${doctorId}/day-plan?date=${encodeURIComponent(date)}`, 'GET'),
  setSessions: (doctorId: string, sessions: any[]) =>
    req<any>(`/api/doctors/${doctorId}/sessions`, 'PUT', { sessions }),
  setRules: (doctorId: string, rules: any[]) =>
    req<any>(`/api/doctors/${doctorId}/rules`, 'PUT', { rules }),

  // doctor's own day controls
  extendVisit: (id: string, minutes: number) =>
    req<any>(`/api/appointments/${id}/extend`, 'POST', { minutes }),
  pullForward: (doctorId: string) =>
    req<any>(`/api/doctors/${doctorId}/pull-forward`, 'POST', {}),
  swapAppointments: (id: string, otherId: string) =>
    req<any>(`/api/appointments/${id}/swap`, 'POST', { other_appointment_id: otherId }),
  handOff: (id: string, toDoctorId: string, reason = '', note = '') =>
    req<any>(`/api/appointments/${id}/hand-off`, 'POST',
      { to_doctor_id: toDoctorId, reason, note }),
  closeList: (doctorId: string, fromTime: string, apply = false) =>
    req<any>(`/api/doctors/${doctorId}/close-list`, 'POST', { from_time: fromTime, apply }),
  actions: (doctorId = '', limit = 20) =>
    req<any>(`/api/actions?doctor_id=${encodeURIComponent(doctorId)}&limit=${limit}`, 'GET'),
  undoAction: (id: string) => req<any>(`/api/actions/${id}/undo`, 'POST', {}),
  arrivals: () => req<any>('/api/arrivals'),
  callPatient: (id: string) => req<any>(`/api/appointments/${id}/call`, 'POST', {}),
  risk: (date = '', doctorId = '') =>
    req<any>(`/api/risk?date=${encodeURIComponent(date)}&doctor_id=${encodeURIComponent(doctorId)}`, 'GET'),
  setSafetyBooking: (doctorId: string, enabled: boolean) =>
    req<any>(`/api/doctors/${doctorId}/safety-booking`, 'PUT', { enabled }),
  replyNotification: (id: string, text: string) =>
    req<any>(`/api/notifications/${id}/reply`, 'POST', { text }),
  investigations: () => req<any[]>('/api/investigations'),
  orderInvestigation: (b: any) => req<any>('/api/investigations', 'POST', b),
  resultInvestigation: (id: string, b: any) =>
    req<any>(`/api/investigations/${id}/result`, 'POST', b),
  clearInvestigation: (id: string) =>
    req<any>(`/api/investigations/${id}/clear`, 'POST', {}),
  readiness: (apptId: string) =>
    req<any>(`/api/appointments/${apptId}/readiness`, 'GET'),
  gateAppointment: (apptId: string) =>
    req<any>(`/api/appointments/${apptId}/gate`, 'POST', {}),
  repencilAppointment: (apptId: string) =>
    req<any>(`/api/appointments/${apptId}/repencil`, 'POST', {}),
  waitlist: () => req<any[]>('/api/waitlist'),
  addWaitlist: (b: any) => req<any>('/api/waitlist', 'POST', b),
  removeWaitlist: (id: string) => req<any>(`/api/waitlist/${id}`, 'DELETE'),
  matchWaitlist: (b: any) => req<any>('/api/waitlist/match', 'POST', b),
  offerWaitlist: (b: any) => req<any>('/api/waitlist/offer', 'POST', b),
  acceptWaitlist: (id: string, b: any = {}) =>
    req<any>(`/api/waitlist/${id}/accept`, 'POST', b),
  bookWalkIn: (b: any) => req<any>('/api/walk-ins', 'POST', b),
   completeVisit: (id: string) => req<any>(`/api/appointments/${id}/complete-visit`, 'POST', {}),
   cancelAppointment: (id: string, reason = 'patient request') =>
     req<any>(`/api/appointments/${id}/cancel`, 'POST', { reason }),

  // patients
  patients: () => req<any[]>('/api/patients'),
  createPatient: (b: any) => req<any>('/api/patients', 'POST', b),
  updatePatient: (id: string, b: any) => req<any>(`/api/patients/${id}`, 'PUT', b),
  deletePatient: (id: string) => req<any>(`/api/patients/${id}`, 'DELETE'),
  patientHistory: (id: string) => req<any>(`/api/patients/${id}/history`, 'GET'),
  reschedule: (id: string, b: any) => req<any>(`/api/appointments/${id}/reschedule`, 'POST', b),
  rescheduleAuto: (id: string, b: any = {}) => req<any>(`/api/appointments/${id}/reschedule-auto`, 'POST', b),
  checkin: (id: string, checked_in = true) => req<any>(`/api/appointments/${id}/checkin`, 'POST', { checked_in }),

  sickLeave: (docId: string, reason = 'sick leave') => req<any>(`/api/doctors/${docId}/sick-leave`, 'POST', { reason }),
  takeLeave: (docId: string, b: any) => req<any>(`/api/doctors/${docId}/leave`, 'POST', b),
  cancelLeave: (docId: string, leave_id?: string) => req<any>(`/api/doctors/${docId}/leave/cancel`, 'POST', { leave_id }),
  markAvailable: (docId: string) => req<any>(`/api/doctors/${docId}/available`, 'POST', {}),
  expireLeaves: () => req<any>('/api/doctors/expire-leaves', 'POST', {}),
  overrun: (apptId: string) => req<any>(`/api/appointments/${apptId}/overrun`, 'POST', {}),
   breakdown: (roomId: string, available_until = '23:59', reason = 'equipment breakdown') =>
     req<any>(`/api/rooms/${roomId}/breakdown`, 'POST', { available_until, reason }),
   restoreRoom: (roomId: string, reason = 'equipment repaired') =>
     req<any>(`/api/rooms/${roomId}/restore`, 'POST', { reason }),
   noShow: (apptId: string, no_show_min = 15) => req<any>(`/api/appointments/${apptId}/no-show`, 'POST', { no_show_min }),
   advanceClock: (no_show_min = 15) => req<any>('/api/clock/advance', 'POST', { no_show_min }),

   addEmergency: (patient_id: string, severity: number) => req<any>('/api/emergencies', 'POST', { patient_id, severity }),
   resolveEmergencies: () => req<any>('/api/emergencies/resolve', 'POST'),
   assignEmergency: (emergencyId: string, doctorId: string) =>
     req<any>(`/api/emergencies/${emergencyId}/assign`, 'POST', { doctor_id: doctorId }),
   completeEmergency: (emergencyId: string) =>
     req<any>(`/api/emergencies/${emergencyId}/complete`, 'POST', {}),
}
