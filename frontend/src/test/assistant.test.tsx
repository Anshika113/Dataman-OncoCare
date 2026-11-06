import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import Assistant from '../components/Assistant'
import { api } from '../lib/api'

const proposal = {
  kind: 'proposal',
  via: 'model',
  proposal: {
    action: 'hand_off',
    summary: 'Hand Meera Nair to Dr. Ben Ortiz',
    appointment_id: 'A1',
    to_doctor_id: 'D2',
    to_doctor_name: 'Dr. Ben Ortiz',
    note: 'counts back at 11',
  },
}

async function ask() {
  render(<Assistant state={{}} />)
  fireEvent.click(screen.getByLabelText('Ask the clinic'))
  fireEvent.change(screen.getByPlaceholderText('Ask about today…'), {
    target: { value: 'Meera ko Dr. Ben ko de do' },
  })
  fireEvent.click(screen.getByLabelText('Ask'))
  await screen.findByText('Hand Meera Nair to Dr. Ben Ortiz')
}

describe('the assistant only proposes', () => {
  beforeEach(() => {
    Element.prototype.scrollIntoView = vi.fn()
    vi.restoreAllMocks()
    vi.spyOn(api, 'askCapabilities').mockResolvedValue({ model: true })
    vi.spyOn(api, 'ask').mockResolvedValue(proposal)
  })

  it('changes nothing until Confirm, then sends the edited note', async () => {
    const handOff = vi.spyOn(api, 'handOff').mockResolvedValue({
      success: true, message: 'handed over', data: { action_id: 'X1' },
    })
    await ask()
    expect(screen.getByText('understood by Sarvam AI')).toBeTruthy()
    expect(handOff).not.toHaveBeenCalled()

    fireEvent.change(screen.getByDisplayValue('counts back at 11'), {
      target: { value: 'counts back at 11:05' },
    })
    fireEvent.click(screen.getByText('Confirm'))

    await screen.findByText('handed over')
    expect(handOff).toHaveBeenCalledWith('A1', 'D2', 'asked through the assistant', 'counts back at 11:05')
    expect(screen.getByText('Undo')).toBeTruthy()
  })

  it('does nothing when cancelled', async () => {
    const handOff = vi.spyOn(api, 'handOff')
    await ask()
    fireEvent.click(screen.getByText('Cancel'))
    await waitFor(() => screen.getByText('Cancelled. Nothing changed.'))
    expect(handOff).not.toHaveBeenCalled()
  })
})
