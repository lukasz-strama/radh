// Jednostki klienta API i poświadczeń. Fetch jest atrapą, bez React i serwera.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  ApiError, cancelDhSession, currentCredential, deleteDhSession, encryptRsa,
  fetchDhDiagnostics, fetchDhNodes, fetchDhSession, generateRsaKeys,
  resetOwnDhSession, resumeDhSession, startDhSession,
} from '../src/api'
import {
  forgetCredential, newCreationKey, pendingCreation, saveCredential, savePendingCreation,
} from '../src/dhCredentials'

const epoch = 'a'.repeat(32)
const id = 'b'.repeat(32)
const token = 'c'.repeat(43)
const own = { id, token, epoch }
const url = '/api/v2/dh/sessions'
let fetchMock: ReturnType<typeof vi.fn>

function session(status = 'running', overrides: object = {}) {
  return {
    session_id: id, backend_epoch: epoch, prime: 23, generator: 5,
    mode: 'normal', diagnostics_enabled: false, status, failure_code: null,
    created_at: '2026-11-18T12:00:00Z', expires_at: '2026-11-18T12:10:00Z',
    terminal_at: null, revision: 1, participants: { alice: 'waiting', bob: 'waiting' },
    messages: [], interceptions: [], ...overrides,
  }
}

function response(body: unknown, status = 200, returnedEpoch = epoch, headers = {}) {
  return new Response(status === 204 ? null : JSON.stringify(body), {
    status, headers: { 'X-Backend-Epoch': returnedEpoch, ...headers },
  })
}

function nodes() {
  return response({ alice: { online: true }, bob: { online: true }, mallory: { online: true } })
}

function history() {
  return response({ session_id: id, backend_epoch: epoch, events: [], next_after: 0 })
}

beforeEach(() => {
  sessionStorage.clear()
  fetchMock = vi.fn()
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
  sessionStorage.clear()
})

describe('poświadczenia własnej karty', () => {
  it('przechowuje poświadczenie w sessionStorage i usuwa wyłącznie oczekiwane', () => {
    saveCredential(own)
    expect(currentCredential()).toEqual(own)
    expect(localStorage.length).toBe(0)
    forgetCredential({ ...own, token: 'd'.repeat(43) })
    expect(currentCredential()).toEqual(own)
    forgetCredential(own)
    expect(currentCredential()).toBeNull()
  })

  it('generuje klucz z 32 losowych bajtów base64url', () => {
    const first = newCreationKey()
    expect(first).toMatch(/^[A-Za-z0-9_-]{43}$/)
    expect(newCreationKey()).not.toBe(first)
  })

  it('odrzuca uszkodzone poświadczenie zapisane w karcie', () => {
    sessionStorage.setItem('radh.dh.v2.session', JSON.stringify({ ...own, id: '../other' }))
    expect(currentCredential()).toBeNull()
  })
})

describe('API v2', () => {
  it('tworzy sesję z kluczem i epoch, a startuje ją z tokenem właściciela', async () => {
    fetchMock.mockResolvedValueOnce(nodes())
      .mockResolvedValueOnce(response({ session: session('created'), session_token: token }, 201))
      .mockResolvedValueOnce(response(session()))
    const result = await startDhSession({ prime: 23, generator: 5 }, 'normal', true)
    expect(result.id).toBe(id)
    expect(currentCredential()).toEqual(own)
    expect(pendingCreation()).toBeNull()
    const create = fetchMock.mock.calls[1]
    expect(create[0]).toBe(url)
    expect(create[1].headers['Idempotency-Key']).toMatch(/^[A-Za-z0-9_-]{43}$/)
    expect(create[1].headers['X-Backend-Epoch']).toBe(epoch)
    expect(JSON.parse(create[1].body)).toEqual({
      prime: 23, generator: 5, mode: 'normal', diagnostics_enabled: true,
    })
    expect(fetchMock.mock.calls[2][1].headers.Authorization).toBe('Bearer ' + token)
  })

  it('ponawia niepotwierdzone tworzenie z tym samym kluczem po kliknięciu', async () => {
    fetchMock.mockResolvedValueOnce(nodes()).mockRejectedValueOnce(new Error('network'))
    await expect(startDhSession({ prime: 23, generator: 5 }, 'normal')).rejects.toBeInstanceOf(ApiError)
    const key = pendingCreation()?.key
    fetchMock.mockResolvedValueOnce(nodes())
      .mockResolvedValueOnce(response({ session: session('created'), session_token: token }, 201))
      .mockResolvedValueOnce(response(session()))
    await startDhSession({ prime: 23, generator: 5 }, 'normal')
    expect(fetchMock.mock.calls[3][1].headers['Idempotency-Key']).toBe(key)
  })

  it.each(['expired', 'changed-epoch', 'changed-params'])('nie powtarza create po %s', async (reason) => {
    savePendingCreation({
      key: 'k'.repeat(43), epoch: reason === 'changed-epoch' ? 'f'.repeat(32) : epoch,
      createdAt: Date.now() - (reason === 'expired' ? 60_001 : 0),
      params: { prime: 23, generator: reason === 'changed-params' ? 2 : 5, mode: 'normal', diagnostics_enabled: false },
    })
    fetchMock.mockResolvedValueOnce(nodes())
    await expect(startDhSession({ prime: 23, generator: 5 }, 'normal')).rejects.toMatchObject({ code: 'CREATE_RETRY_EXPIRED' })
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('zachowuje token po błędzie startu, żeby umożliwić reset lub ponowienie', async () => {
    fetchMock.mockResolvedValueOnce(nodes())
      .mockResolvedValueOnce(response({ session: session('created'), session_token: token }, 201))
      .mockResolvedValueOnce(response({ error: { code: 'NODE_UNAVAILABLE', message: 'Brak węzła.' } }, 409))
    await expect(startDhSession({ prime: 23, generator: 5 }, 'normal')).rejects.toMatchObject({ code: 'NODE_UNAVAILABLE' })
    expect(currentCredential()).toEqual(own)
    expect(fetchMock).toHaveBeenCalledTimes(3)
  })

  it('pobiera stan i zdarzenia wyłącznie własnej sesji', async () => {
    saveCredential(own)
    fetchMock.mockResolvedValueOnce(response(session())).mockResolvedValueOnce(history())
    expect((await fetchDhSession(id)).epoch).toBe(epoch)
    expect(fetchMock.mock.calls.map(([path]) => path)).toEqual([
      url + '/' + id, url + '/' + id + '/events?after=0&limit=32',
    ])
    for (const [, options] of fetchMock.mock.calls) {
      expect(options.headers.Authorization).toBe('Bearer ' + token)
    }
    await expect(fetchDhSession('e'.repeat(32))).rejects.toMatchObject({ code: 'UNAUTHORIZED' })
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it.each([404, 410])('usuwa własne poświadczenie po HTTP %s', async (status) => {
    saveCredential(own)
    fetchMock.mockResolvedValueOnce(response({ error: { code: 'SESSION_NOT_FOUND', message: 'Brak sesji.' } }, status))
    await expect(fetchDhSession(id)).rejects.toMatchObject({ status })
    expect(currentCredential()).toBeNull()
  })

  it('wykrywa restart backendu i usuwa poświadczenie poprzedniego epoch', async () => {
    saveCredential(own)
    fetchMock.mockResolvedValueOnce(response(session(), 200, 'f'.repeat(32)))
    await expect(fetchDhSession(id)).rejects.toMatchObject({ code: 'BACKEND_EPOCH_MISMATCH' })
    expect(currentCredential()).toBeNull()
  })

  it('nie usuwa nowszego poświadczenia po spóźnionym błędzie starej sesji', async () => {
    saveCredential(own)
    let resolve!: (value: Response) => void
    fetchMock.mockImplementationOnce(() => new Promise<Response>((done) => { resolve = done }))
    const pending = fetchDhSession(id)
    const newer = { ...own, id: 'e'.repeat(32) }
    saveCredential(newer)
    resolve(response({ error: { code: 'SESSION_NOT_FOUND', message: 'Brak.' } }, 404))
    await expect(pending).rejects.toMatchObject({ status: 404 })
    expect(currentCredential()).toEqual(newer)
  })

  it('zachowuje token istniejącej expired i umożliwia DELETE', async () => {
    saveCredential(own)
    fetchMock.mockResolvedValueOnce(response(session('expired'))).mockResolvedValueOnce(history())
    expect((await fetchDhSession(id)).status).toBe('expired')
    expect(currentCredential()).toEqual(own)
    fetchMock.mockResolvedValueOnce(response(null, 204))
    await deleteDhSession(id)
    expect(currentCredential()).toBeNull()
  })

  it('reset usuwa tylko zapisaną sesję i nigdy nie odpytuje globalnej sesji', async () => {
    saveCredential(own)
    fetchMock.mockResolvedValueOnce(response(null, 204))
    await resetOwnDhSession()
    expect(fetchMock.mock.calls[0][0]).toBe(url + '/' + id)
    expect(fetchMock.mock.calls[0][1].method).toBe('DELETE')
    await resetOwnDhSession()
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('przekazuje Retry-After z błędu bez automatycznego ponowienia', async () => {
    saveCredential(own)
    fetchMock.mockResolvedValueOnce(response({ error: { code: 'RATE_LIMITED', message: 'Spróbuj później.' } }, 429, epoch, { 'Retry-After': '7' }))
    await expect(fetchDhDiagnostics(id)).rejects.toMatchObject({ status: 429, retryAfter: 7 })
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(currentCredential()).toEqual(own)
  })

  it('nie zapisuje wyniku tworzenia po przerwaniu operacji', async () => {
    const controller = new AbortController()
    fetchMock.mockResolvedValueOnce(nodes()).mockImplementationOnce(() => {
      controller.abort()
      return Promise.resolve(response({ session: session('created'), session_token: token }, 201))
    })
    await expect(startDhSession({ prime: 23, generator: 5 }, 'normal', false, controller.signal)).rejects.toMatchObject({ name: 'AbortError' })
    expect(currentCredential()).toBeNull()
  })

  it('odrzuca odpowiedź startu przypisaną do innego ID', async () => {
    saveCredential(own)
    fetchMock.mockResolvedValueOnce(response(session('running', { session_id: 'e'.repeat(32) })))
    await expect(resumeDhSession(id)).rejects.toBeInstanceOf(ApiError)
  })

  it('wysyła cancel z poświadczeniem własnej sesji', async () => {
    saveCredential(own)
    fetchMock.mockResolvedValueOnce(response(session('cancelled')))
    expect((await cancelDhSession(id)).status).toBe('cancelled')
    expect(fetchMock.mock.calls[0][1].headers.Authorization).toBe('Bearer ' + token)
  })

  it('odczytuje nowe presence bez last_seen', async () => {
    fetchMock.mockResolvedValueOnce(nodes())
    expect(await fetchDhNodes()).toEqual({
      alice: { online: true }, bob: { online: true }, mallory: { online: true }, backendEpoch: epoch,
    })
  })

  it('zachowuje format wywołań RSA', async () => {
    fetchMock.mockResolvedValueOnce(response({ ciphertext: 2790 }))
      .mockResolvedValueOnce(response({ n: 3233, e: 17, d: 2753, phi: 3120 }))
    expect(await encryptRsa({ message: 65, public_exponent: 17, modulus: 3233 })).toEqual({ ciphertext: 2790 })
    expect((await generateRsaKeys({ p: 61, q: 53, e: 17 })).d).toBe(2753)
    expect(fetchMock.mock.calls.map(([path]) => path)).toEqual(['/api/v1/rsa/demo/encrypt', '/api/v1/rsa/demo/keygen'])
  })
})


describe('błędy reverse proxy bez epoch', () => {
  it.each([429, 502, 503, 504])('zachowuje token po HTTP %s i przekazuje Retry-After', async (status) => {
    saveCredential(own)
    fetchMock.mockResolvedValueOnce(new Response('<html>proxy error</html>', {
      status, headers: { 'Retry-After': '9' },
    }))
    await expect(fetchDhDiagnostics(id)).rejects.toMatchObject({ status, retryAfter: 9 })
    expect(currentCredential()).toEqual(own)
  })

  it.each([null, 'invalid'])('odrzuca poprawną odpowiedź bez wymaganego epoch (%s), zachowując token', async (header) => {
    saveCredential(own)
    const headers = new Headers()
    if (header !== null) headers.set('X-Backend-Epoch', header)
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify(session()), { status: 200, headers }))
    await expect(fetchDhSession(id)).rejects.toMatchObject({ code: 'INVALID_RESPONSE' })
    expect(currentCredential()).toEqual(own)
  })

  it.each([404, 410])('nie usuwa tokenu po niepotwierdzonym HTTP %s proxy', async (status) => {
    saveCredential(own)
    fetchMock.mockResolvedValueOnce(new Response('{}', { status }))
    await expect(fetchDhSession(id)).rejects.toMatchObject({ code: 'INVALID_RESPONSE' })
    expect(currentCredential()).toEqual(own)
  })

  it('nie ufa kodowi restartu bez poprawnego nagłówka epoch', async () => {
    saveCredential(own)
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ error: {
      code: 'BACKEND_EPOCH_MISMATCH', message: 'Proxy',
    } }), { status: 503 }))
    await expect(fetchDhSession(id)).rejects.toMatchObject({ code: 'INVALID_RESPONSE' })
    expect(currentCredential()).toEqual(own)
  })
})
