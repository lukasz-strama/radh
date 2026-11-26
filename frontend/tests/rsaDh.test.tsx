// Testy UI zakładki RSA + DH (#104): podpisana wymiana bez MITM i z MITM, izolacja
// poświadczeń od zakładki DH i unikalne identyfikatory przy obu zakładkach w DOM.
//
// Backend jest zastąpiony mockiem `fetch` zgodnym z backend/AUTHENTICATED_DH.md.
import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../src/App'
import { DhExchange } from '../src/DhExchange'
import { currentCredential, saveCredential } from '../src/dhCredentials'

const epoch = 'a'.repeat(32)
const authId = 'b'.repeat(32)
const classicId = 'd'.repeat(32)
const token = 'c'.repeat(43)
const authUrl = `/api/v2/dh/sessions/${authId}`
const HASH_ALICE = '1'.repeat(64)
const HASH_BOB = '2'.repeat(64)
const HASH_BOB_VIEW = '3'.repeat(64)

type Handler = (init: RequestInit) => Promise<Response>
let handlers: Record<string, Handler>
let fetchMock: ReturnType<typeof vi.fn>

function json(body: unknown, status = 200): Response {
  return new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', 'X-Backend-Epoch': epoch },
  })
}

const owned = { session_id: authId, backend_epoch: epoch }

// Sesja RSA + DH w danym stanie. verified: wynik weryfikacji podpisu Alice przez Boba
// (null – jeszcze bez weryfikacji); podpis Boba Alice weryfikuje zawsze pozytywnie.
function authSession({
  status = 'completed',
  mode = 'normal',
  verified = true as boolean | null,
  diagnostics = false,
}: { status?: string; mode?: string; verified?: boolean | null; diagnostics?: boolean } = {}) {
  const rejected = verified === false
  return {
    ...owned, prime: 23, generator: 5, mode, scenario: 'authenticated',
    diagnostics_enabled: diagnostics, status,
    failure_code: rejected ? 'SIGNATURE_VERIFICATION_FAILED' : null,
    created_at: '2026-11-26T12:00:00Z', expires_at: '2026-11-26T12:02:00Z',
    terminal_at: status === 'completed' || status === 'failed' ? '2026-11-26T12:00:30Z' : null,
    revision: 9,
    participants: rejected ? { alice: 'verified', bob: 'published' } : { alice: 'verified', bob: 'verified' },
    messages: [
      { sender: 'alice', recipient: 'bob', public_value: 8, status: 'processed' },
      { sender: 'bob', recipient: 'alice', public_value: 19, status: 'processed' },
    ],
    interceptions: [],
    authentication: {
      ...owned,
      trusted_keys: [
        { ...owned, owner: 'alice', modulus: 3233, public_exponent: 17 },
        { ...owned, owner: 'bob', modulus: 4757, public_exponent: 7 },
      ],
      signatures: [
        { ...owned, signer: 'alice', transcript_hash: HASH_ALICE, signature: 1234 },
        { ...owned, signer: 'bob', transcript_hash: HASH_BOB, signature: 4321 },
      ],
      verifications: [
        { ...owned, verifier: 'alice', signer: 'bob', verified: true,
          transcript_hash: HASH_BOB, published_transcript_hash: HASH_BOB },
        ...(verified === null ? [] : [{
          ...owned, verifier: 'bob', signer: 'alice', verified,
          transcript_hash: verified ? HASH_ALICE : HASH_BOB_VIEW, published_transcript_hash: HASH_ALICE,
        }]),
      ],
    },
  }
}

function events(list: object[] = []) {
  return () => Promise.resolve(json({ ...owned, events: list, next_after: list.length }))
}

const nodesOnline = () =>
  Promise.resolve(json({ alice: { online: true }, bob: { online: true }, mallory: { online: true } }))

function calls(method: string, url: string): RequestInit[] {
  return fetchMock.mock.calls
    .filter(([callUrl, init]) => callUrl === url && ((init as RequestInit)?.method ?? 'GET') === method)
    .map(([, init]) => init as RequestInit)
}

beforeEach(() => {
  sessionStorage.clear()
  handlers = { 'GET /api/v2/dh/nodes': nodesOnline }
  fetchMock = vi.fn((url: string, init: RequestInit = {}) => {
    const handler = handlers[`${init.method ?? 'GET'} ${url.split('?')[0]}`]
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

describe('zakładka RSA + DH', () => {
  it('start tworzy sesję authenticated z własnym poświadczeniem, obok sesji zakładki DH', async () => {
    const user = userEvent.setup()
    saveCredential({ id: classicId, token, epoch })
    handlers['GET /api/v2/dh/sessions/' + classicId] = () => Promise.resolve(json({}))
    handlers['POST /api/v2/dh/sessions'] = () =>
      Promise.resolve(json({ session: authSession({ status: 'created', verified: null }), session_token: token }, 201))
    handlers[`POST ${authUrl}/start`] = () => Promise.resolve(json(authSession({ status: 'running', verified: null })))
    render(<DhExchange scenario="authenticated" />)
    await screen.findByRole('radio', { name: 'Podpisana wymiana + MITM' })

    await user.click(screen.getByRole('button', { name: 'Rozpocznij sesję' }))
    await waitFor(() => expect(calls('POST', `${authUrl}/start`)).toHaveLength(1))
    expect(JSON.parse(calls('POST', '/api/v2/dh/sessions')[0].body as string)).toMatchObject({
      prime: 23, generator: 5, mode: 'normal', scenario: 'authenticated',
    })
    expect(currentCredential('authenticated')?.id).toBe(authId)
    expect(currentCredential('classic')?.id).toBe(classicId)
  })

  it('Reset usuwa tylko sesję zakładki RSA + DH', async () => {
    const user = userEvent.setup()
    saveCredential({ id: classicId, token, epoch })
    saveCredential({ id: authId, token, epoch }, 'authenticated')
    handlers[`GET ${authUrl}`] = () => Promise.resolve(json(authSession()))
    handlers[`GET ${authUrl}/events`] = events()
    handlers[`DELETE ${authUrl}`] = () => Promise.resolve(json(null, 204))
    render(<DhExchange scenario="authenticated" />)
    await screen.findByRole('heading', { name: 'Podpisy RSA' })

    await user.click(screen.getByRole('button', { name: 'Reset' }))
    await waitFor(() => expect(calls('DELETE', authUrl)).toHaveLength(1))
    expect(currentCredential('authenticated')).toBeNull()
    expect(currentCredential('classic')?.id).toBe(classicId)
    expect(calls('DELETE', `/api/v2/dh/sessions/${classicId}`)).toHaveLength(0)
  })

  it('podpisana wymiana bez MITM: klucze, podpisy, obie weryfikacje i zgodne K', async () => {
    saveCredential({ id: authId, token, epoch }, 'authenticated')
    handlers[`GET ${authUrl}`] = () => Promise.resolve(json(authSession({ diagnostics: true })))
    handlers[`GET ${authUrl}/events`] = events()
    handlers[`GET ${authUrl}/diagnostics`] = () => Promise.resolve(json({ alice: 2, bob: 2 }))
    render(<DhExchange scenario="authenticated" />)

    const panel = within(await screen.findByRole('region', { name: 'Podpisy RSA' }))
    expect(panel.getByText('(3233, 17)')).toBeTruthy()
    expect(panel.getByText('(4757, 7)')).toBeTruthy()
    expect(panel.getByText('1234')).toBeTruthy()
    expect(panel.getByText(HASH_ALICE)).toBeTruthy()
    expect(panel.getAllByText('podpis poprawny')).toHaveLength(2)
    expect(panel.getByText(/Obie strony zweryfikowały podpis partnera/)).toBeTruthy()
    expect(screen.getAllByText('zweryfikował podpis partnera')).toHaveLength(2)

    // K przychodzi z diagnostyki przy pierwszym odpytaniu sesji.
    expect(await screen.findByRole('heading', { name: 'Sekrety zgodne' }, { timeout: 3500 })).toBeTruthy()
  })

  it('podpisana wymiana z MITM: błąd podpisu, przyczyna i brak zaakceptowanego K', async () => {
    saveCredential({ id: authId, token, epoch }, 'authenticated')
    handlers[`GET ${authUrl}`] = () =>
      Promise.resolve(json(authSession({ status: 'failed', mode: 'mitm', verified: false, diagnostics: true })))
    handlers[`GET ${authUrl}/events`] = events([
      { sequence: 1, type: 'signature_rejected', created_at: '2026-11-26T12:00:20Z',
        sender: 'bob', recipient: 'alice', public_value: null, message_id: null,
        status: 'processed', verified: false },
    ])
    render(<DhExchange scenario="authenticated" />)

    const panel = within(await screen.findByRole('region', { name: 'Podpisy RSA' }))
    expect(panel.getByText('podpis odrzucony')).toBeTruthy()
    const reason = panel.getByRole('heading', { name: 'Przyczyna odrzucenia' }).parentElement as HTMLElement
    expect(reason.textContent).toContain('Weryfikacja Boba: podpis Alice odrzucony.')
    expect(reason.textContent).toContain(`${HASH_BOB_VIEW.slice(0, 12)}…`)
    expect(reason.textContent).toContain(`${HASH_ALICE.slice(0, 12)}…`)
    expect(screen.getAllByText(/niezaakceptowany: podpis partnera się nie zgadza/)).toHaveLength(2)
    expect(screen.getByText(/Podpis odrzucony – wymiana przerwana/)).toBeTruthy()
    expect(screen.queryByRole('heading', { name: /Sekrety/ })).toBeNull()
    // Wynik weryfikacji widać też w dzienniku.
    const log = within(screen.getByRole('region', { name: /Dziennik zdarzeń/ }))
    expect(log.getByText('podpis odrzucony')).toBeTruthy()
  })

  it('obie zakładki DH w DOM nie dublują identyfikatorów', async () => {
    render(<App />)
    await waitFor(() => expect(calls('GET', '/api/v2/dh/nodes').length).toBeGreaterThanOrEqual(2))
    const ids = Array.from(document.querySelectorAll('[id]'), (element) => element.id)
    expect(ids.filter((value, index) => ids.indexOf(value) !== index)).toEqual([])
    expect(screen.getByRole('tab', { name: 'RSA + DH' })).toBeTruthy()
  })
})