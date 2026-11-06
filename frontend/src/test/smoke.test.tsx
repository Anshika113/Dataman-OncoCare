import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import Login from '../pages/Login'

// Smoke test: the login page renders its form and brand without crashing.
describe('Login', () => {
  it('renders username + password fields and sign-in button', () => {
    render(<Login />)
    expect(screen.getByLabelText(/username/i)).toBeInTheDocument()
    expect(screen.getAllByLabelText(/password/i).length).toBeGreaterThan(0)
    expect(screen.getByRole('button', { name: /sign in/i })).toBeInTheDocument()
    expect(screen.getAllByText(/DataMan OncoCare/i).length).toBeGreaterThan(0)
  })

  it('shows the demo-account quick-fill (admin)', () => {
    render(<Login />)
    expect(screen.getByRole('button', { name: /admin/i })).toBeInTheDocument()
  })
})
