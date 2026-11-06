// Typed contracts for the backend state payload. These mirror the dataclasses
// in backend/engine/state.py. Keeping them here (instead of `any` everywhere)
// means a field rename on the backend is a compile-time error in the UI.

export type Role = 'admin' | 'nurse' | 'doctor'

export interface Doctor {
  id: string
  name: string
  specialty: string
  daily_cap: number
  status: 'available' | 'unavailable' | 'on_leave' | 'partially_unavailable'
  backup_compatible: string[]
  leave_reason: string
  leaves: LeaveEntry[]
}

export interface LeaveEntry {
  id: string
  start: string
  end: string
  reason: string
  date: string
  created_at: string
  cancelled: boolean | number
}

export interface Room {
  id: string
  name: string
  type: 'infusion_chair' | 'isolation' | 'exam'
  equipment: string[]
  status: 'available' | 'unavailable'
  available_until: string
}

export interface Drug {
  id: string
  name: string
  tw_start: string
  tw_end: string
  grace_minutes: number
  required_equipment: string[]
}

export interface Patient {
  id: string
  name: string
  contact: string
  priority_tier: number
  dob: string
  age: string
  gender: string
  blood_group: string
  mr_number: string
  diagnosis: string
  stage: string
  allergies: string
  insurance: string
  notes: string
  // derived by GET /api/patients
  appointment_count?: number
  status?: string
  label?: string
  upcoming?: number
  visits?: number
}

export type ApptStatus =
  | 'booked' | 'active' | 'overrun' | 'no_show' | 'rescheduled'
  | 'cancelled' | 'completed' | 'visited' | 'emergency_waiting'

export interface Appointment {
  id: string
  patient_id: string
  doctor_id: string
  date: string            // YYYY-MM-DD the appointment falls on
  slot_start: string
  slot_end: string
  type: 'consult' | 'chemo' | 'emergency'
  status: ApptStatus
  room_id: string
  drug_id: string
  severity: number
  buffer_before: number
  buffer_after: number
  checked_in: number | boolean
  reschedule_reason: string
  visit_count: number
  last_visited: string
  // derived
  patient_name?: string
  doctor_name?: string
  room_name?: string
  drug_name?: string
  is_revisit?: boolean
}

export interface Emergency {
  id: string
  patient_id: string
  severity: number
  created_at: string
  subscore: number
  assigned_doctor_id: string
  status: 'waiting' | 'assigned' | 'completed'
}

export interface LogEntry {
  id: string
  kind: string
  appointment_id: string
  before: string
  after: string
  reason: string
  at: string
}

export interface Notification {
  id: string
  patient_id: string
  channel: string
  body: string
  sent_at: string
  status: 'pending' | 'sent' | 'failed'
}

export interface Insight {
  kind: string
  severity: 'info' | 'warning' | 'critical'
  title: string
  detail: string
  action: string
  resource_id: string
  resource_name: string
  affected: string[]
  metric: Record<string, unknown>
  horizon_min: number
}

export interface AppState {
  now: string
  active_day: string
  doctors: Doctor[]
  rooms: Room[]
  drugs: Drug[]
  patients: Patient[]
  appointments: Appointment[]
  emergencies: Emergency[]
  insights: Insight[]
  insights_now: string
  logs: LogEntry[]
  notifications: Notification[]
}

export interface WsEvent {
  type: string
  at?: string
  [key: string]: unknown
}
