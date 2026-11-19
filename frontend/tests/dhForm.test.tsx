// QA UI: formularz DH — walidacja pól, dostępność węzłów i znane defekty (it.fails).
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { DhExchange } from '../src/DhExchange'
import { startDhSession } from '../src/api'
import { pendingCreation } from '../src/dhCredentials'
import { validateDhParams } from '../src/validation'

const epoch = 'a'.repeat(32)
let online = { alice: true, bob: true, mallory: true }
let fetchMock: ReturnType<typeof vi.fn>

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'X-Backend-Epoch': epoch } })
}

function nodesResponse() {
  return json({ alice: { online: online.alice }, bob: { online: online.bob }, mallory: { online: online.mallory } })
}

beforeEach(() => {
  sessionStorage.clear()
  online = { alice: true, bob: true, mallory: true }
  fetchMock = vi.fn((url: string) => {
    if (url === '/api/v2/dh/nodes') return Promise.resolve(nodesResponse())
    return Promise.resolve(json({ error: { code: 'INVALID_PRIME', message: 'Niepoprawne parametry sesji DH.' } }, 422))
  })
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  sessionStorage.clear()
})

describe('walidacja parametrów DH', () => {
  it.each([
    [{ prime: '', generator: '5' }, 'prime', 'To pole jest wymagane.'],
    [{ prime: '2', generator: '1' }, 'prime', 'Liczba pierwsza p musi być co najmniej równa 3.'],
    [{ prime: '4294967296', generator: '5' }, 'prime', 'Maksymalna wartość to 4294967295.'],
    [{ prime: '23', generator: '' }, 'generator', 'To pole jest wymagane.'],
  ])('%j → błąd pola %s', (raw, field, message) => {
    const result = validateDhParams(raw)
    expect(result.ok).toBe(false)
    if (!result.ok) expect(result.errors[field as 'prime' | 'generator']).toBe(message)
  })

  it('generator musi być mniejszy od p, a pierwszość sprawdza backend', () => {
    const tooBig = validateDhParams({ prime: '23', generator: '23' })
    expect(tooBig.ok).toBe(false)
    expect(validateDhParams({ prime: '24', generator: '5' })).toEqual({ ok: true, data: { prime: 24, generator: 5 } })
  })
})

describe('formularz DH', () => {
  it('błędy pól są powiązane z polem (aria-invalid, aria-describedby) i nie wysyłają żądania', async () => {
    const user = userEvent.setup()
    render(<DhExchange />)
    const prime = screen.getByLabelText('Liczba pierwsza (p)')
    await user.clear(prime)
    await user.click(screen.getByRole('button', { name: 'Rozpocznij sesję' }))
    expect(prime.getAttribute('aria-invalid')).toBe('true')
    expect(document.getElementById(prime.getAttribute('aria-describedby') as string)?.textContent).toContain(
      'To pole jest wymagane.')
    expect(fetchMock.mock.calls.filter(([url]) => url !== '/api/v2/dh/nodes')).toEqual([])
  })

  it('niedostępna Mallory blokuje tylko scenariusz MITM, z podpowiedzią przy przycisku', async () => {
    online = { alice: true, bob: true, mallory: false }
    const user = userEvent.setup()
    render(<DhExchange />)
    const button = screen.getByRole('button', { name: 'Rozpocznij sesję' })
    await waitFor(() => expect(screen.getAllByText('dostępny')).toHaveLength(2))
    expect((button as HTMLButtonElement).disabled).toBe(false)
    await user.click(screen.getByLabelText('Atak MITM'))
    expect((button as HTMLButtonElement).disabled).toBe(true)
    expect(screen.getByText('Uruchom proces Mallory, żeby rozpocząć sesję.').getAttribute('id')).toBe('dh-nodes-hint')
    expect(button.getAttribute('aria-describedby')).toBe('dh-nodes-hint')
  })

  it('odrzucenie przez backend pokazuje komunikat role=alert', async () => {
    const user = userEvent.setup()
    render(<DhExchange />)
    await user.clear(screen.getByLabelText('Liczba pierwsza (p)'))
    await user.type(screen.getByLabelText('Liczba pierwsza (p)'), '24')
    await user.click(screen.getByRole('button', { name: 'Rozpocznij sesję' }))
    expect((await screen.findByRole('alert')).textContent).toContain('Niepoprawne parametry sesji DH.')
  })
})

describe('znane defekty (it.fails — po naprawie zamienić na it)', () => {
  // BUG-UI-02: ostateczne odrzucenie tworzenia (422) zostawia klucz próby w sessionStorage,
  // więc poprawione parametry dają „Poprzednia próba utworzenia wymaga porzucenia…”.
  it.fails('BUG-UI-02: po 422 nie zostaje zapisana próba tworzenia', async () => {
    await expect(startDhSession({ prime: 24, generator: 5 }, 'normal')).rejects.toThrow(
      'Niepoprawne parametry sesji DH.')
    expect(pendingCreation()).toBeNull()
  })

  it.fails('BUG-UI-02: poprawione p po 422 tworzy sesję bez Reset', async () => {
    await expect(startDhSession({ prime: 24, generator: 5 }, 'normal')).rejects.toThrow()
    await expect(startDhSession({ prime: 23, generator: 5 }, 'normal')).rejects.not.toThrow(
      'Poprzednia próba utworzenia wymaga porzucenia')
  })
})
