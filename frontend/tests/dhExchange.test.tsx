// Testy zachowania UI zakładki DH przy błędach startu (#70, uwagi do #90):
// spóźniona odpowiedź nie nadpisuje nowszego stanu, a Retry-After blokuje
// każdy przycisk startu, także ponowienie istniejącej sesji.
//
// Backend jest zastąpiony mockiem `fetch` zgodnym z API v2
// (docs/architecture/multi-session.md, backend/MULTI_SESSION.md).
import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { DhExchange } from '../src/DhExchange'
import { saveCredential } from '../src/dhCredentials'

const epoch = 'a'.repeat(32)
const id = 'b'.repeat(32)
const token = 'c'.repeat(43)
const sessionUrl = `/api/v2/dh/sessions/${id}`

type Handler = (init: RequestInit) => Promise<Response>
let handlers: Record<string, Handler>
let fetchMock: ReturnType<typeof vi.fn>

function json(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', 'X-Backend-Epoch': epoch, ...headers },
  })
}

function apiError(code: string, status: number, headers: Record<string, string> = {}): Response {
  return json({ error: { code, message: 'Nie można wykonać operacji.' } }, status, headers)
}

function session(status: string) {
  return {
    session_id: id, backend_epoch: epoch, prime: 23, generator: 5,
    mode: 'normal', diagnostics_enabled: false, status, failure_code: null,
    created_at: '2026-11-19T12:00:00Z', expires_at: '2026-11-19T12:02:00Z',
    terminal_at: null, revision: 1, participants: { alice: 'waiting', bob: 'waiting' },
    messages: [], interceptions: [],
  }
}

const nodesOnline = () =>
  Promise.resolve(json({ alice: { online: true }, bob: { online: true }, mallory: { online: true } }))
const history = () =>
  Promise.resolve(json({ session_id: id, backend_epoch: epoch, events: [], next_after: 0 }))

function calls(method: string, url: string): number {
  return fetchMock.mock.calls.filter(
    ([callUrl, init]) => callUrl === url && ((init as RequestInit)?.method ?? 'GET') === method,
  ).length
}

beforeEach(() => {
  sessionStorage.clear()
  handlers = {}
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

describe('zakładka DH – błędy startu', () => {
  it('spóźniony błąd odczytu zachowanej sesji nie nadpisuje widoku po Resecie', async () => {
    const user = userEvent.setup()
    // Odczyt zachowanej sesji po nieudanym starcie zawiśnie do końca testu.
    let failKeptRead: (error: Error) => void = () => {}
    handlers = {
      'GET /api/v2/dh/nodes': nodesOnline,
      'POST /api/v2/dh/sessions': () =>
        Promise.resolve(json({ session: session('created'), session_token: token }, 201)),
      [`POST ${sessionUrl}/start`]: () => Promise.resolve(apiError('NODE_UNAVAILABLE', 409)),
      [`GET ${sessionUrl}`]: () =>
        new Promise<Response>((_, reject) => {
          failKeptRead = reject
        }),
      [`DELETE ${sessionUrl}`]: () => Promise.resolve(json(null, 204)),
      [`POST ${sessionUrl}/cancel`]: () => Promise.resolve(json(session('cancelled'))),
    }
    render(<DhExchange />)
    await waitFor(() => expect(calls('GET', '/api/v2/dh/nodes')).toBeGreaterThan(0))

    await user.click(screen.getByRole('button', { name: 'Rozpocznij sesję' }))
    await waitFor(() => expect(calls('GET', sessionUrl)).toBe(1))

    // Użytkownik nie czeka i resetuje; Reset kończy się, zanim odczyt zawiedzie.
    await user.click(screen.getByRole('button', { name: 'Reset' }))
    await waitFor(() => expect(calls('DELETE', sessionUrl)).toBe(1))
    await screen.findByText(/Podaj parametry publiczne/)

    await act(async () => {
      failKeptRead(new TypeError('Failed to fetch'))
    })

    expect(screen.queryByText(/Podaj parametry publiczne/)).not.toBeNull()
    expect(screen.queryByText(/Nie wszystkie potrzebne procesy/)).toBeNull()
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('Retry-After blokuje też ponowienie startu istniejącej sesji', async () => {
    const user = userEvent.setup()
    saveCredential({ id, token, epoch })
    handlers = {
      'GET /api/v2/dh/nodes': nodesOnline,
      [`GET ${sessionUrl}`]: () => Promise.resolve(json(session('created'))),
      [`GET ${sessionUrl}/events?after=0&limit=32`]: history,
      [`POST ${sessionUrl}/start`]: () =>
        Promise.resolve(apiError('RATE_LIMITED', 429, { 'Retry-After': '5' })),
    }
    render(<DhExchange />)

    const resume = await screen.findByRole('button', { name: 'Uruchom własną sesję' })
    await user.click(resume)
    await screen.findByText('Za dużo prób w krótkim czasie. Spróbuj ponownie za 5 s.')

    const blocked = await screen.findByRole('button', { name: 'Uruchom własną sesję' })
    expect((blocked as HTMLButtonElement).disabled).toBe(true)
    await user.click(blocked)
    expect(calls('POST', `${sessionUrl}/start`)).toBe(1)
  })
})