// Testy UI losowania parametrów w formularzach RSA i DH (#97).
//
// Backend jest zastąpiony mockiem `fetch` zgodnym z backend/README.md (#96):
//   POST /api/v1/rsa/demo/parameters -> {"p":...,"q":...,"e":...}
//   POST /api/v1/dh/demo/parameters  -> {"prime":...,"generator":...}
// Błędy: {"error":{"code":"...","message":"..."}}, przy 429/503 nagłówek Retry-After.
import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { DhExchange } from '../src/DhExchange'
import { RsaView } from '../src/RsaView'

const RSA_PARAMETERS = '/api/v1/rsa/demo/parameters'
const DH_PARAMETERS = '/api/v1/dh/demo/parameters'
const KEYGEN = '/api/v1/rsa/demo/keygen'
const DH_SESSIONS = '/api/v2/dh/sessions'
const epoch = 'a'.repeat(32)

type Handler = (init: RequestInit) => Promise<Response>
let handlers: Record<string, Handler>
let fetchMock: ReturnType<typeof vi.fn>

function json(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', 'X-Backend-Epoch': epoch, ...headers },
  })
}

function apiError(code: string, status: number, message: string, headers: Record<string, string> = {}) {
  return json({ error: { code, message } }, status, headers)
}

// Odpowiedź, którą test zwalnia sam – do sprawdzania spóźnionych odpowiedzi.
function deferred() {
  let resolve: (response: Response) => void = () => {}
  const promise = new Promise<Response>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

function requests(method: string, url: string): RequestInit[] {
  return fetchMock.mock.calls
    .filter(([callUrl, init]) => callUrl === url && ((init as RequestInit)?.method ?? 'GET') === method)
    .map(([, init]) => init as RequestInit)
}

function value(label: string, scope: HTMLElement = document.body): string {
  return (within(scope).getByLabelText(label) as HTMLInputElement).value
}

beforeEach(() => {
  sessionStorage.clear()
  handlers = {
    'GET /api/v2/dh/nodes': () =>
      Promise.resolve(json({ alice: { online: true }, bob: { online: true }, mallory: { online: true } })),
  }
  fetchMock = vi.fn((url: string, init: RequestInit = {}) => {
    const handler = handlers[`${init.method ?? 'GET'} ${url}`]
    if (!handler) return Promise.reject(new TypeError(`brak atrapy: ${init.method} ${url}`))
    return handler(init)
  })
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  sessionStorage.clear()
})

function keygenForm(): HTMLElement {
  return screen.getByRole('form', { name: 'Generowanie kluczy' })
}

describe('RSA – losowanie p, q, e', () => {
  it('wypełnia pola, które bez edycji trafiają do keygen', async () => {
    const user = userEvent.setup()
    handlers[`POST ${RSA_PARAMETERS}`] = () => Promise.resolve(json({ p: 61261, q: 55799, e: 65537 }))
    handlers[`POST ${KEYGEN}`] = () =>
      Promise.resolve(json({ n: 3418302139, e: 65537, d: 1, phi: 3418185080 }))
    render(<RsaView />)
    const form = keygenForm()

    await user.click(within(form).getByRole('button', { name: 'Losuj parametry' }))
    await waitFor(() => expect(value('Liczba pierwsza (p)', form)).toBe('61261'))
    expect(value('Liczba pierwsza (q)', form)).toBe('55799')
    expect(value('Wykładnik publiczny (e)', form)).toBe('65537')
    // Losowanie samo niczego nie generuje.
    expect(requests('POST', KEYGEN)).toHaveLength(0)
    expect(requests('POST', RSA_PARAMETERS)[0].body).toBeUndefined()

    await user.click(within(form).getByRole('button', { name: 'Generuj klucze' }))
    await waitFor(() => expect(requests('POST', KEYGEN)).toHaveLength(1))
    expect(JSON.parse(requests('POST', KEYGEN)[0].body as string)).toEqual({ p: 61261, q: 55799, e: 65537 })
  })

  it('błąd losowania nie zmienia wpisanych wartości', async () => {
    const user = userEvent.setup()
    handlers[`POST ${RSA_PARAMETERS}`] = () =>
      Promise.resolve(apiError('PARAMETER_GENERATION_EXHAUSTED', 503,
        'Nie udało się wylosować parametrów w limicie prób.', { 'Retry-After': '1' }))
    render(<RsaView />)
    const form = keygenForm()

    await user.click(within(form).getByRole('button', { name: 'Losuj parametry' }))
    await within(form).findByText('Nie udało się wylosować parametrów. Spróbuj ponownie za 1 s.')
    expect(value('Liczba pierwsza (p)', form)).toBe('61')
    expect(value('Liczba pierwsza (q)', form)).toBe('53')
    expect(value('Wykładnik publiczny (e)', form)).toBe('17')
  })

  it('odpowiedź w złym formacie nie zmienia pól', async () => {
    const user = userEvent.setup()
    handlers[`POST ${RSA_PARAMETERS}`] = () => Promise.resolve(json({ p: 61261, q: '55799' }))
    render(<RsaView />)
    const form = keygenForm()

    await user.click(within(form).getByRole('button', { name: 'Losuj parametry' }))
    await within(form).findByText(/nieoczekiwanym formacie/)
    expect(value('Liczba pierwsza (p)', form)).toBe('61')
  })

  it('spóźniona odpowiedź nie nadpisuje ręcznej edycji', async () => {
    const user = userEvent.setup()
    const slow = deferred()
    handlers[`POST ${RSA_PARAMETERS}`] = () => slow.promise
    render(<RsaView />)
    const form = keygenForm()

    await user.click(within(form).getByRole('button', { name: 'Losuj parametry' }))
    await within(form).findByRole('button', { name: 'Losowanie…' })
    await user.clear(within(form).getByLabelText('Liczba pierwsza (p)'))
    await user.type(within(form).getByLabelText('Liczba pierwsza (p)'), '101')
    // Edycja przerwała losowanie – przycisk wraca do zwykłego stanu.
    within(form).getByRole('button', { name: 'Losuj parametry' })

    await act(async () => {
      slow.resolve(json({ p: 61261, q: 55799, e: 65537 }))
    })
    expect(value('Liczba pierwsza (p)', form)).toBe('101')
    expect(value('Liczba pierwsza (q)', form)).toBe('53')
    expect(value('Wykładnik publiczny (e)', form)).toBe('17')
  })

  it('Retry-After blokuje ponowne losowanie z komunikatem o czasie', async () => {
    const user = userEvent.setup()
    handlers[`POST ${RSA_PARAMETERS}`] = () =>
      Promise.resolve(apiError('RATE_LIMITED', 429, 'Nie można wykonać operacji.', { 'Retry-After': '5' }))
    render(<RsaView />)
    const form = keygenForm()

    await user.click(within(form).getByRole('button', { name: 'Losuj parametry' }))
    await within(form).findByText('Za dużo prób w krótkim czasie. Spróbuj ponownie za 5 s.')
    const button = within(form).getByRole('button', { name: 'Losuj parametry' }) as HTMLButtonElement
    expect(button.disabled).toBe(true)
    await user.click(button)
    expect(requests('POST', RSA_PARAMETERS)).toHaveLength(1)
  })
})

describe('DH – losowanie p, g', () => {
  it('wypełnia pola, nie rozpoczyna sesji, a start używa wylosowanych wartości', async () => {
    const user = userEvent.setup()
    handlers[`POST ${DH_PARAMETERS}`] = () => Promise.resolve(json({ prime: 65521, generator: 17 }))
    handlers[`POST ${DH_SESSIONS}`] = () =>
      Promise.resolve(apiError('RATE_LIMITED', 429, 'Nie można wykonać operacji.'))
    render(<DhExchange />)
    await waitFor(() => expect(requests('GET', '/api/v2/dh/nodes').length).toBeGreaterThan(0))

    await user.click(screen.getByRole('button', { name: 'Losuj parametry' }))
    await waitFor(() => expect(value('Liczba pierwsza (p)')).toBe('65521'))
    expect(value('Generator (g)')).toBe('17')
    expect(requests('POST', DH_SESSIONS)).toHaveLength(0)

    await user.click(screen.getByRole('button', { name: 'Rozpocznij sesję' }))
    await waitFor(() => expect(requests('POST', DH_SESSIONS)).toHaveLength(1))
    expect(JSON.parse(requests('POST', DH_SESSIONS)[0].body as string)).toMatchObject({
      prime: 65521,
      generator: 17,
    })
  })

  it('pola można dalej edytować ręcznie po losowaniu', async () => {
    const user = userEvent.setup()
    handlers[`POST ${DH_PARAMETERS}`] = () => Promise.resolve(json({ prime: 65521, generator: 17 }))
    render(<DhExchange />)

    await user.click(screen.getByRole('button', { name: 'Losuj parametry' }))
    await waitFor(() => expect(value('Generator (g)')).toBe('17'))
    await user.clear(screen.getByLabelText('Generator (g)'))
    await user.type(screen.getByLabelText('Generator (g)'), '3')
    expect(value('Generator (g)')).toBe('3')
  })

  it('Reset przerywa losowanie – spóźniona odpowiedź nie zmienia pól', async () => {
    const user = userEvent.setup()
    const slow = deferred()
    handlers[`POST ${DH_PARAMETERS}`] = () => slow.promise
    render(<DhExchange />)

    await user.click(screen.getByRole('button', { name: 'Losuj parametry' }))
    await screen.findByRole('button', { name: 'Losowanie…' })
    await user.click(screen.getByRole('button', { name: 'Reset' }))
    await screen.findByRole('button', { name: 'Losuj parametry' })

    await act(async () => {
      slow.resolve(json({ prime: 65521, generator: 17 }))
    })
    expect(value('Liczba pierwsza (p)')).toBe('23')
    expect(value('Generator (g)')).toBe('5')
  })

  it('błąd losowania nie zmienia wpisanych wartości', async () => {
    const user = userEvent.setup()
    handlers[`POST ${DH_PARAMETERS}`] = () =>
      Promise.resolve(apiError('CRYPTO_BUSY', 503, 'Nie można wykonać operacji.', { 'Retry-After': '2' }))
    render(<DhExchange />)
    await user.clear(screen.getByLabelText('Liczba pierwsza (p)'))
    await user.type(screen.getByLabelText('Liczba pierwsza (p)'), '29')

    await user.click(screen.getByRole('button', { name: 'Losuj parametry' }))
    await screen.findByText('Serwer jest chwilowo zajęty obliczeniami. Spróbuj ponownie za 2 s.')
    expect(value('Liczba pierwsza (p)')).toBe('29')
    expect(value('Generator (g)')).toBe('5')
  })
})