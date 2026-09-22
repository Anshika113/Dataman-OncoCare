// Minimal typed API client for the care backend.

export const BASE_URL = import.meta.env.VITE_API_URL || ''

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
export function clearSession() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(ROLE_KEY)
  localStorage.removeItem(NAME_KEY)
  localStorage.removeItem(DOC_KEY)
}

async function req<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  const tok = getToken()
  if (tok) headers['Authorization'] = 'Bearer ' + tok
  const res = await fetch(BASE_URL + path, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (res.status === 401) {
    clearSession()
    window.location.href = '/login'
    throw new Error('unauthorized')
  }
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`HTTP ${res.status}: ${text || res.statusText}`)
  }
  return res.json() as Promise<T>
}

export const api = {
  login: (u: string, p: string) =>
    req<{ token: string; role: string; name: string; doctor_id: string }>('/api/login', 'POST', { username: u, password: p }),
  state: () => req<any>('/api/state'),
  insights: () => req<any>('/api/insights'),
  doctors: () => req<any[]>('/api/doctors'),
  appointments: () => req<any[]>('/api/appointments'),
  queue: () => req<any>('/api/queue'),
  logs: () => req<any[]>('/api/logs'),
  notifications: () => req<any[]>('/api/notifications'),

   bookConsult: (b: any) => req<any>('/api/appointments/consult', 'POST', b),
   bookChemo: (b: any) => req<any>('/api/appointments/chemo', 'POST', b),
   bookWithRecs: (b: any) => req<any>('/api/appointments/book-with-recs', 'POST', b),
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
