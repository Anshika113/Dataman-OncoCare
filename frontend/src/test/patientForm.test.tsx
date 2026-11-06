import { describe, it, expect, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import PatientForm from '../components/PatientForm'

// Blank datastore cells arrive as null. The API only accepts strings, so a
// patient with blank fields used to be impossible to edit (422).
describe('PatientForm', () => {
  it('saves a patient whose optional fields are null as empty strings', async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ id: 'PAT-1' }), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
    const onSaved = vi.fn()
    const patient = { id: 'PAT-1', name: 'Test', allergies: null, notes: null, age: 37, priority_tier: 1 }

    render(<PatientForm open patient={patient} onClose={() => {}} onSaved={onSaved} />)
    fireEvent.click(screen.getByRole('button', { name: /save changes/i }))

    await waitFor(() => expect(onSaved).toHaveBeenCalled())
    const body = JSON.parse((fetchMock.mock.calls[0] as any)[1].body)
    expect(body).toMatchObject({ allergies: '', notes: '', age: '37' })
    vi.unstubAllGlobals()
  })
})
