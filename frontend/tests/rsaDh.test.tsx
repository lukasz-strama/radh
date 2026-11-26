// Testy UI zakładki RSA + DH (#104): podpisana wymiana bez MITM i z MITM, izolacja
// poświadczeń od zakładki DH, walidacja stanu uwierzytelnienia i unikalne identyfikatory.
//
// Backend jest zastąpiony mockiem `fetch` zgodnym z backend/AUTHENTICATED_DH.md
// i modelami sesji v2 (messages: intercepted → queued → processed,
// interceptions: pending → forwarded → processed; processed = ACK odbiorcy).
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
// Skróty transkryptów podpisanych przez Alice i Boba oraz skrót, który Bob buduje
// ze swojego widoku po podmianie MITM.
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

const TRUSTED_KEYS = [
  { ...owned, owner: 'alice', modulus: 3233, public_exponent: 17 },
  { ...owned, owner: 'bob', modulus: 4757, public_exponent: 7 },
]
const SIGNATURES = [
  { ...owned, signer: 'alice', transcript_hash: HASH_ALICE, signature: 1234 },
  { ...owned, signer: 'bob', transcript_hash: HASH_BOB, signature: 4321 },
]
const POSITIVE_VERIFICATIONS = [
  { ...owned, verifier: 'alice', signer: 'bob', verified: true,
    transcript_hash: HASH_BOB, published_transcript_hash: HASH_BOB },
  { ...owned, verifier: 'bob', signer: 'alice', verified: true,
    transcript_hash: HASH_ALICE, published_transcript_hash: HASH_ALICE },
]

// Głęboka kopia: przypadki walidacji psują dane sesji, a wspólne tablice
// (klucze, podpisy, weryfikacje) nie mogą się zmieniać między testami.
function base(overrides: Record<string, unknown>) {
  return structuredClone({
    ...owned, prime: 23, generator: 5, mode: 'normal', scenario: 'authenticated',
    diagnostics_enabled: true, failure_code: null,
    created_at: '2026-11-26T12:00:00Z', expires_at: '2026-11-26T12:02:00Z',
    terminal_at: null, revision: 1,
    participants: { alice: 'waiting', bob: 'waiting' },
    messages: [], interceptions: [],
    authentication: { ...owned, trusted_keys: [], signatures: [], verifications: [] },
    ...overrides,
  })
}

// Sesja tuż po utworzeniu: bez kluczy, podpisów i wiadomości.
const createdSession = (status = 'created') => base({ status, diagnostics_enabled: false })

// Podpisana wymiana bez MITM. acked: obie wiadomości DH potwierdzone, sesja zakończona;
// bez ACK oba podpisy są już zweryfikowane, ale sesja trwa.
function signedSession(acked: boolean) {
  const status = acked ? 'processed' : 'queued'
  return base({
    status: acked ? 'completed' : 'running',
    terminal_at: acked ? '2026-11-26T12:00:30Z' : null,
    revision: acked ? 14 : 12,
    participants: { alice: 'verified', bob: 'verified' },
    messages: [
      { message_id: 'alice-public', sender: 'alice', recipient: 'bob', type: 'public_value', public_value: 8, status },
      { message_id: 'bob-public', sender: 'bob', recipient: 'alice', type: 'public_value', public_value: 19, status },
    ],
    authentication: { ...owned, trusted_keys: TRUSTED_KEYS, signatures: SIGNATURES, verifications: POSITIVE_VERIFICATIONS },
  })
}

// Podpisana wymiana z MITM po pierwszej negatywnej weryfikacji: Mallory przechwyciła A = 8
// i B = 19, Bobowi podstawiła Y = 15, Alice X = 4. Bob zbudował transkrypt z Y, więc
// podpis Alice odrzucił. Bez ACK: wiadomości zostają queued, przechwycenia forwarded,
// a uczestnicy nie przechodzą do verified.
function mitmRejectedSession() {
  return base({
    mode: 'mitm', status: 'failed', failure_code: 'SIGNATURE_VERIFICATION_FAILED',
    terminal_at: '2026-11-26T12:00:30Z', revision: 13,
    participants: { alice: 'published', bob: 'published' },
    messages: [
      { message_id: 'alice-public', sender: 'alice', recipient: 'bob', type: 'public_value', public_value: 15, status: 'queued' },
      { message_id: 'bob-public', sender: 'bob', recipient: 'alice', type: 'public_value', public_value: 4, status: 'queued' },
    ],
    interceptions: [
      { message_id: 'alice-public', original_sender: 'alice', recipient: 'bob', original_value: 8,
        delivered_value: 15, intercepted_by: 'mallory', actual_sender: 'mallory', status: 'forwarded' },
      { message_id: 'bob-public', original_sender: 'bob', recipient: 'alice', original_value: 19,
        delivered_value: 4, intercepted_by: 'mallory', actual_sender: 'mallory', status: 'forwarded' },
    ],
    authentication: {
      ...owned, trusted_keys: TRUSTED_KEYS, signatures: SIGNATURES,
      verifications: [
        { ...owned, verifier: 'bob', signer: 'alice', verified: false,
          transcript_hash: HASH_BOB_VIEW, published_transcript_hash: HASH_ALICE },
      ],
    },
  })
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

// Wartości z panelu węzła: etykieta → tekst <output> i dopisek pod wartością.
function partyValue(role: 'Alice' | 'Bob', label: RegExp) {
  const panel = screen.getByRole('region', { name: role })
  const value = within(panel).getByText(label).closest('.dh-value') as HTMLElement
  return {
    output: value.querySelector('output')?.textContent,
    note: value.querySelector('.hint')?.textContent,
  }
}

// Zapisuje poświadczenie RSA + DH i podaje stan sesji przy odczycie.
function ownSession(session: unknown, history: object[] = []) {
  saveCredential({ id: authId, token, epoch }, 'authenticated')
  handlers[`GET ${authUrl}`] = () => Promise.resolve(json(session))
  handlers[`GET ${authUrl}/events`] = events(history)
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
    handlers['POST /api/v2/dh/sessions'] = () =>
      Promise.resolve(json({ session: createdSession(), session_token: token }, 201))
    handlers[`POST ${authUrl}/start`] = () => Promise.resolve(json(createdSession('running')))
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
    ownSession(signedSession(true))
    handlers[`DELETE ${authUrl}`] = () => Promise.resolve(json(null, 204))
    render(<DhExchange scenario="authenticated" />)
    await screen.findByRole('heading', { name: 'Podpisy RSA' })

    await user.click(screen.getByRole('button', { name: 'Reset' }))
    await waitFor(() => expect(calls('DELETE', authUrl)).toHaveLength(1))
    expect(currentCredential('authenticated')).toBeNull()
    expect(currentCredential('classic')?.id).toBe(classicId)
    expect(calls('DELETE', `/api/v2/dh/sessions/${classicId}`)).toHaveLength(0)
  })

  it('podpisana wymiana bez MITM: klucze, podpisy, obie weryfikacje i zgodne K po zakończeniu', async () => {
    ownSession(signedSession(true))
    handlers[`GET ${authUrl}/diagnostics`] = () => Promise.resolve(json({ alice: 2, bob: 2 }))
    render(<DhExchange scenario="authenticated" />)

    const panel = within(await screen.findByRole('region', { name: 'Podpisy RSA' }))
    expect(panel.getByText('(3233, 17)')).toBeTruthy()
    expect(panel.getByText('(4757, 7)')).toBeTruthy()
    expect(panel.getByText('1234')).toBeTruthy()
    expect(panel.getByText(HASH_ALICE)).toBeTruthy()
    expect(panel.getAllByText('podpis poprawny')).toHaveLength(2)
    expect(panel.getByText(/Obie strony zweryfikowały podpis partnera/)).toBeTruthy()
    expect(partyValue('Bob', /Otrzymana wartość/)).toEqual({ output: '8', note: undefined })

    // K przychodzi z diagnostyki przy pierwszym odpytaniu sesji.
    expect(await screen.findByRole('heading', { name: 'Sekrety zgodne' }, { timeout: 3500 })).toBeTruthy()
    expect(partyValue('Alice', /Wspólny sekret/).output).toBe('2')
  })

  it('verified bez ACK nie pokazuje zaakceptowanego K, nawet gdy diagnostyka je zgłosi', async () => {
    ownSession(signedSession(false))
    handlers[`GET ${authUrl}/diagnostics`] = () => Promise.resolve(json({ alice: 2, bob: 2 }))
    render(<DhExchange scenario="authenticated" />)
    await screen.findByRole('region', { name: 'Podpisy RSA' })
    await waitFor(() => expect(calls('GET', `${authUrl}/diagnostics`).length).toBeGreaterThan(0), { timeout: 3500 })

    expect(screen.getAllByText('zweryfikował podpis partnera')).toHaveLength(2)
    for (const role of ['Alice', 'Bob'] as const) {
      const secret = partyValue(role, /Wspólny sekret/)
      expect(secret.output).toBeUndefined()
      expect(screen.getByRole('region', { name: role }).textContent).toContain(
        'zostanie zaakceptowany po weryfikacji obu podpisów i zakończeniu sesji',
      )
    }
    expect(partyValue('Bob', /Otrzymana wartość/)).toEqual({
      output: '8', note: 'dostarczona, podpis zweryfikowany – czeka na potwierdzenie',
    })
    expect(screen.queryByRole('heading', { name: /Sekrety/ })).toBeNull()
  })

  it('podpisana wymiana z MITM: dostarczone podmiany, błąd podpisu, przyczyna i brak K', async () => {
    ownSession(mitmRejectedSession(), [
      { sequence: 9, type: 'signature_rejected', created_at: '2026-11-26T12:00:20Z',
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

    // Ofiary dostały podmiany Mallory, ale ich nie przyjęły (brak ACK).
    expect(partyValue('Bob', /Otrzymana „od Alice”/)).toEqual({
      output: '15', note: 'dostarczona, nieprzyjęta – podpis partnera się nie zgadza',
    })
    expect(partyValue('Alice', /Otrzymana „od Boba”/)).toEqual({
      output: '4', note: 'dostarczona, nieprzyjęta – podpis partnera się nie zgadza',
    })
    const mallory = screen.getByRole('region', { name: 'Mallory' })
    expect(mallory.textContent).toContain('A = 8')
    expect(mallory.textContent).toContain('Y = gy mod p = 15')

    expect(screen.getAllByText(/niezaakceptowany: podpis partnera się nie zgadza/)).toHaveLength(2)
    expect(screen.getByText(/Podpis odrzucony – wymiana przerwana/)).toBeTruthy()
    expect(screen.queryByRole('heading', { name: /Sekrety/ })).toBeNull()
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

// Odpowiedzi niezgodne z backend/AUTHENTICATED_DH.md – widok ich nie pokazuje.
describe('walidacja stanu uwierzytelnienia', () => {
  type Session = ReturnType<typeof signedSession>
  const auth = (session: Session) => session.authentication as {
    trusted_keys: Record<string, unknown>[]
    signatures: Record<string, unknown>[]
    verifications: Record<string, unknown>[]
  }
  const cases: [string, (session: Session) => void][] = [
    ['moduł klucza ≤ 255', (s) => { auth(s).trusted_keys[0].modulus = 255 }],
    ['wykładnik e ≥ n', (s) => { auth(s).trusted_keys[1].public_exponent = 4757 }],
    ['wykładnik e ≤ 1', (s) => { auth(s).trusted_keys[0].public_exponent = 1 }],
    ['podpis ≥ moduł klucza podpisującego', (s) => { auth(s).signatures[0].signature = 3233 }],
    ['podpis bez obu kluczy', (s) => { auth(s).trusted_keys.pop() }],
    ['verified=true przy różnych skrótach', (s) => { auth(s).verifications[1].transcript_hash = HASH_BOB_VIEW }],
    ['opublikowany skrót inny niż w podpisie', (s) => {
      auth(s).verifications[0].published_transcript_hash = HASH_BOB_VIEW
      auth(s).verifications[0].transcript_hash = HASH_BOB_VIEW
    }],
    ['weryfikacja bez obu podpisów', (s) => { auth(s).signatures.pop() }],
    ['brak stanu authentication w RSA + DH', (s) => { delete (s as Partial<Session>).authentication }],
    ['status received w RSA + DH', (s) => { s.participants.alice = 'received' }],
  ]

  it.each(cases)('%s', async (_, spoil) => {
    const session = signedSession(true)
    spoil(session)
    ownSession(session)
    render(<DhExchange scenario="authenticated" />)
    expect(await screen.findByText(/nieoczekiwanym formacie/)).toBeTruthy()
    expect(screen.queryByRole('region', { name: 'Podpisy RSA' })).toBeNull()
  })

  it('zwykła wymiana nie może mieć danych uwierzytelnienia', async () => {
    const session = { ...signedSession(true), scenario: 'classic', participants: { alice: 'received', bob: 'received' } }
    saveCredential({ id: authId, token, epoch })
    handlers[`GET ${authUrl}`] = () => Promise.resolve(json(session))
    handlers[`GET ${authUrl}/events`] = events()
    render(<DhExchange />)
    expect(await screen.findByText(/nieoczekiwanym formacie/)).toBeTruthy()
  })
})