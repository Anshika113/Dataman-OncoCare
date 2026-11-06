import { describe, it, expect, vi } from 'vitest'
import { screen } from '@testing-library/react'

vi.mock('../App', () => ({ default: () => <div>app shell</div> }))

// The app reads its tab from the URL, so /schedule must reach <App>. It used to
// be registered at exactly "/", which bounced every sidebar click to the
// dashboard.
describe('routes', () => {
  it('keeps a signed-in user on a tab URL', async () => {
    document.body.innerHTML = '<div id="root"></div>'
    localStorage.setItem('care_token', 'token')
    window.history.pushState({}, '', '/schedule')

    await import('../main')

    expect(await screen.findByText('app shell')).toBeInTheDocument()
    expect(window.location.pathname).toBe('/schedule')
    localStorage.clear()
  })
})
