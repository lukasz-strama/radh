// QA UI: nawigacja zakładkami (wzorzec ARIA „tabs”) i zachowanie stanu ukrytych paneli.
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../src/App'

beforeEach(() => {
  sessionStorage.clear()
  // Zakładka DH odpytuje węzły; tu wystarczy, że backend nie odpowiada.
  vi.stubGlobal('fetch', vi.fn(() => Promise.reject(new TypeError('offline'))))
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('zakładki', () => {
  it('strzałki, Home i End przełączają widok i przenoszą fokus; Tab wchodzi tylko na aktywną', async () => {
    const user = userEvent.setup()
    render(<App />)
    const rsa = screen.getByRole('tab', { name: 'RSA' })
    const dh = screen.getByRole('tab', { name: 'Diffie–Hellman' })
    expect(rsa.getAttribute('aria-selected')).toBe('true')
    expect(rsa.tabIndex).toBe(0)
    expect(dh.tabIndex).toBe(-1)

    await user.tab()
    expect(document.activeElement).toBe(rsa)
    await user.keyboard('{ArrowRight}')
    expect(document.activeElement).toBe(dh)
    expect(dh.getAttribute('aria-selected')).toBe('true')
    expect((screen.getByRole('tabpanel', { name: 'Diffie–Hellman' }) as HTMLElement).hidden).toBe(false)
    expect((document.getElementById('view-rsa') as HTMLElement).hidden).toBe(true)

    const rsadh = screen.getByRole('tab', { name: 'RSA + DH' })
    await user.keyboard('{ArrowRight}')
    expect(document.activeElement).toBe(rsadh)
    await user.keyboard('{ArrowRight}') // zawija do pierwszej
    expect(document.activeElement).toBe(rsa)
    await user.keyboard('{End}')
    expect(document.activeElement).toBe(rsadh)
    await user.keyboard('{Home}')
    expect(document.activeElement).toBe(rsa)
    await user.keyboard('{ArrowLeft}')
    expect(document.activeElement).toBe(rsadh)
  })

  it('panele są powiązane z zakładkami (aria-controls / aria-labelledby)', () => {
    render(<App />)
    for (const tab of screen.getAllByRole('tab', { hidden: true })) {
      const panel = document.getElementById(tab.getAttribute('aria-controls') as string)
      expect(panel.getAttribute('role')).toBe('tabpanel')
      expect(panel.getAttribute('aria-labelledby')).toBe(tab.id)
    }
  })

  it('przełączenie zakładki nie gubi wpisanych danych', async () => {
    const user = userEvent.setup()
    render(<App />)
    const message = screen.getByLabelText('Wiadomość (m)')
    await user.type(message, '65')
    await user.click(screen.getByRole('tab', { name: 'Diffie–Hellman' }))
    await user.click(screen.getByRole('tab', { name: 'RSA' }))
    expect((screen.getByLabelText('Wiadomość (m)') as HTMLInputElement).value).toBe('65')
  })
})