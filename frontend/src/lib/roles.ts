// Role -> UI capability map (mirrors backend require_role()).
//
// Two things live here, and they are different questions:
//
//   * CAPABILITIES — may this person perform this action? These mirror the
//     backend exactly; where the UI and `require_role` disagree the user
//     either sees a button that 403s or is denied one they are allowed.
//   * SCOPE — whose data should they be looking at by default? A doctor is
//     allowed to see the department (they need to, to hand a patient to a
//     colleague) but should land on their own list, not everyone's.

export interface Caps {
  /** Book, reschedule, cancel, walk-ins, waitlist. */
  canBook: boolean
  /** Simulate sick leave / overrun / breakdown / clock (Ops Console). */
  canEdgeCases: boolean
  /** Register and resolve emergencies. */
  canEmergencies: boolean
  /** Mark a patient arrived and call them in. */
  canCheckin: boolean
  /** The security audit trail — admin only on the backend. */
  canAudit: boolean
  /** The event stream + message log (Activity tab). */
  canActivity: boolean
  /** Add, edit and delete patient records. */
  canManagePatients: boolean
  /** Accept an out-of-protocol lab result so treatment may proceed.
   *  Clinical judgement: doctor or admin, never a nurse. */
  canClearFlag: boolean
  /** Allow overbooking in a clinic (a doctor may only set their own). */
  canSetSafetyBooking: boolean
  /** Default to this doctor's own data; '' means the whole department. */
  scopeDoctorId: string
  /** May widen the view back out to the department. */
  canViewDepartment: boolean
}

const NOBODY: Caps = {
  canBook: false,
  canEdgeCases: false,
  canEmergencies: false,
  canCheckin: false,
  canAudit: false,
  canActivity: false,
  canManagePatients: false,
  canClearFlag: false,
  canSetSafetyBooking: false,
  scopeDoctorId: '',
  canViewDepartment: false,
}

export function capsFor(role: string, doctorId = ''): Caps {
  switch (role) {
    case 'admin':
      return {
        ...NOBODY,
        canBook: true,
        canEdgeCases: true,
        canEmergencies: true,
        canCheckin: true,
        canAudit: true,
        canActivity: true,
        canManagePatients: true,
        canClearFlag: true,
        canSetSafetyBooking: true,
        canViewDepartment: true,
      }
    case 'nurse':
      // Runs the floor: everything operational, nothing clinical and nothing
      // from the security trail (/api/audit is admin-only on the backend).
      return {
        ...NOBODY,
        canBook: true,
        canEdgeCases: true,
        canEmergencies: true,
        canCheckin: true,
        canActivity: true,
        canManagePatients: true,
        canViewDepartment: true,
      }
    case 'coordinator':
      // Follows the patients who have fallen off somebody's list: rebooks,
      // offers freed slots, chases labs, phones whoever could not be
      // messaged. Not the floor, and no clinical calls.
      return {
        ...NOBODY,
        canBook: true,
        canEmergencies: true,
        canCheckin: true,
        canActivity: true,
        canViewDepartment: true,
      }
    case 'doctor':
      // Scoped to their own clinic by default. They keep the clinical calls
      // (accepting a flagged result, allowing overbooking in their own list)
      // and can widen the view to the department to hand a patient over.
      return {
        ...NOBODY,
        canEmergencies: true,
        canCheckin: true,
        canClearFlag: true,
        canSetSafetyBooking: true,
        scopeDoctorId: doctorId,
        canViewDepartment: true,
      }
    default:
      return NOBODY
  }
}

export const ROLE_LABEL: Record<string, string> = {
  admin: 'Administrator',
  coordinator: 'Care Coordinator',
  nurse: 'Nurse / Ops',
  doctor: 'Doctor',
}

export const ROLE_TONE: Record<string, string> = {
  admin: 'bg-brand-100 text-brand-700',
  coordinator: 'bg-violet-100 text-violet-700',
  nurse: 'bg-emerald-100 text-emerald-700',
  doctor: 'bg-amber-100 text-amber-700',
}
