// Testy UI generowania kluczy RSA krok po kroku (#106).
//
// Backend jest zastąpiony mockiem `fetch` zgodnym z backend/README.md:
//   POST /api/v1/rsa/demo/keygen     -> {"n","e","d","phi"}
//   POST /api/v1/rsa/demo/parameters -> {"p","q","e"}
import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { RsaView } from '../src/RsaView'

const KEYGEN = '/api/v1/rsa/demo/keygen'
const PARAMETERS = '/api/v1/rsa/demo/parameters'

type Handler = () => Promise<Response>
let handlers: Record<string, Handler>

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } })
}

beforeEach(() => {
  handlers = {
    [KEYGEN]: () => Promise.resolve(json({ n: 3233, e: 17, d: 2753, phi: 3120 })),
  }
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string) => handlers[url]?.() ?? Promise.reject(new TypeError(`brak atrapy: ${url}`))),
  )
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

const keygen = () => within(screen.getByRole('form', { name: 'Generowanie kluczy' }))
const steps = () => within(screen.getByRole('list', { name: 'Kroki generowania kluczy' }))
const outputs = () =>
  Array.from(screen.getByRole('list', { name: 'Kroki generowania kluczy' }).querySelectorAll('output')).map(
    (output) => output.textContent,
  )
const text = () => screen.getByRole('list', { name: 'Kroki generowania kluczy' }).textContent ?? ''

describe('generowanie kluczy krok po kroku', () => {
  it('przed generowaniem pokazuje same wzory i „?”', () => {
    render(<RsaView />)
    expect(outputs()).toEqual(['?', '?', '?', '(?, ?)', '(?, ?)'])
    expect(steps().getAllByRole('listitem')).toHaveLength(6)
    expect(text()).toContain('n = p · q')
    expect(text()).not.toContain('61 · 53')
  })

  it('dla 61, 53, 17 pokazuje całą sekwencję z podstawionymi wartościami', async () => {
    const user = userEvent.setup()
    render(<RsaView />)
    await user.click(keygen().getByRole('button', { name: 'Generuj klucze' }))
    await waitFor(() => expect(outputs()).toEqual(['3233', '3120', '2753', '(3233, 17)', '(3233, 2753)']))

    const all = text()
    expect(all).toContain('61, 53')
    expect(all).toContain('n = p · q = 61 · 53')
    expect(all).toContain('φ(n) = (p − 1)(q − 1) = 60 · 52')
    expect(all).toContain('NWD(17, 3120) = 1')
    expect(all).toContain('e · d = 17 · 2753 = 46801 = 15 · 3120 + 1')
    expect(all).toContain('Parametry wpisane ręcznie.')

    // Kolejność kroków: p, q → n → φ(n) → e → d → klucze.
    const titles = steps()
      .getAllByRole('heading')
      .map((heading) => heading.textContent)
    expect(titles).toEqual([
      'Liczby pierwsze p i q tajne',
      'Moduł n jawne',
      'Funkcja Eulera φ(n) tajne',
      'Wykładnik publiczny e jawne',
      'Wykładnik prywatny d tajne',
      'Para kluczy',
    ])
  })

  it('zmiana pola usuwa nieaktualny wynik', async () => {
    const user = userEvent.setup()
    render(<RsaView />)
    await user.click(keygen().getByRole('button', { name: 'Generuj klucze' }))
    await waitFor(() => expect(outputs()[0]).toBe('3233'))

    await user.type(keygen().getByLabelText('Wykładnik publiczny (e)'), '1')
    expect(outputs()).toEqual(['?', '?', '?', '(?, ?)', '(?, ?)'])
    expect((keygen().getByRole('button', { name: 'Użyj klucza publicznego' }) as HTMLButtonElement).disabled).toBe(true)
  })

  it('spóźniona odpowiedź po zmianie pola nie wraca', async () => {
    const user = userEvent.setup()
    let release: (response: Response) => void = () => {}
    handlers[KEYGEN] = () => new Promise((resolve) => (release = resolve))
    render(<RsaView />)
    await user.click(keygen().getByRole('button', { name: 'Generuj klucze' }))
    await keygen().findByRole('button', { name: 'Generowanie…' })

    await user.type(keygen().getByLabelText('Liczba pierwsza (q)'), '9')
    keygen().getByRole('button', { name: 'Generuj klucze' })
    await act(async () => release(json({ n: 3233, e: 17, d: 2753, phi: 3120 })))
    expect(outputs()[0]).toBe('?')
  })

  it('losowanie czyści stary wynik, a nowy pokazuje wylosowane wartości', async () => {
    const user = userEvent.setup()
    handlers[PARAMETERS] = () => Promise.resolve(json({ p: 257, q: 263, e: 65537 }))
    render(<RsaView />)
    await user.click(keygen().getByRole('button', { name: 'Generuj klucze' }))
    await waitFor(() => expect(outputs()[0]).toBe('3233'))

    await user.click(keygen().getByRole('button', { name: 'Losuj parametry' }))
    await waitFor(() => expect((keygen().getByLabelText('Liczba pierwsza (p)') as HTMLInputElement).value).toBe('257'))
    expect(outputs()[0]).toBe('?')

    handlers[KEYGEN] = () => Promise.resolve(json({ n: 67591, e: 65537, d: 63489, phi: 67072 }))
    await user.click(keygen().getByRole('button', { name: 'Generuj klucze' }))
    await waitFor(() => expect(outputs()[0]).toBe('67591'))
    const all = text()
    expect(all).toContain('n = p · q = 257 · 263')
    expect(all).toContain('φ(n) = (p − 1)(q − 1) = 256 · 262')
    expect(all).toContain('Parametry wylosowane.')
    // Iloczyn przekracza 2^32 – sprawdzamy, że liczymy go dokładnie.
    expect(all).toContain('e · d = 65537 · 63489 = 4160878593 = 62036 · 67072 + 1')
  })
})