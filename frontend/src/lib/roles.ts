// Role -> UI capability map (mirrors backend require_role()).

export interface Caps {
  canBook: boolean
  canEdgeCases: boolean
  canEmergencies: boolean
  canCheckin: boolean
  canAudit: boolean
}

export function capsFor(role: string): Caps {
  switch (role) {
    case 'admin':
      return { canBook: true, canEdgeCases: true, canEmergencies: true, canCheckin: true, canAudit: true }
    case 'nurse':
      return { canBook: true, canEdgeCases: true, canEmergencies: true, canCheckin: true, canAudit: true }
    case 'doctor':
      return { canBook: false, canEdgeCases: false, canEmergencies: true, canCheckin: true, canAudit: false }
    default:
      return { canBook: false, canEdgeCases: false, canEmergencies: false, canCheckin: false, canAudit: false }
  }
}

export const ROLE_LABEL: Record<string, string> = {
  admin: 'Administrator',
  nurse: 'Nurse / Ops',
  doctor: 'Doctor (Read-only)',
}

export const ROLE_TONE: Record<string, string> = {
  admin: 'bg-brand-100 text-brand-700',
  nurse: 'bg-emerald-100 text-emerald-700',
  doctor: 'bg-amber-100 text-amber-700',
}
