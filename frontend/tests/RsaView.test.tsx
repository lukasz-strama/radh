// Testy zachowania UI zakładki RSA: generowanie kluczy i użycie klucza publicznego (#57, #58).
//
// Backend jest zastąpiony mockiem `fetch`, który odpowiada zgodnie z kontraktem
// z backend/README.md:
//   POST /api/v1/rsa/demo/keygen  -> {"n":3233,"e":17,"d":2753,"phi":3120}
//   POST /api/v1/rsa/demo/encrypt -> {"ciphertext":2790}
// Błędy: {"error":{"code":"...","message":"..."}}.
import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { RsaView } from '../src/RsaView'

const KEYGEN_URL = '/api/v1/rsa/demo/keygen'
const ENCRYPT_URL = '/api/v1/rsa/demo/encrypt'

type MockReply = { status: number; body: unknown } | Error

// Kolejki odpowiedzi dla każdego adresu; ostatnia odpowiedź jest powtarzana.
let replies: Record<string, MockReply[]>
let fetchMock: ReturnType<typeof vi.fn>

function reply(url: string, ...responses: MockReply[]) {
  replies[url] = responses
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function callsTo(url: string) {
  return fetchMock.mock.calls.filter(([calledUrl]) => calledUrl === url)
}

function bodyOf(call: unknown[]) {
  return JSON.parse((call[1] as RequestInit).body as string)
}

beforeEach(() => {
  replies = {}
  fetchMock = vi.fn(async (url: string) => {
    const queue = replies[url]
    if (!queue || queue.length === 0) throw new Error(`Nieoczekiwane żądanie: ${url}`)
    const next = queue.length > 1 ? queue.shift()! : queue[0]
    if (next instanceof Error) throw next
    return jsonResponse(next.status, next.body)
  })
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

function keygenForm() {
  return within(screen.getByRole('form', { name: 'Generowanie kluczy' }))
}

function encryptForm() {
  return within(screen.getByRole('form', { name: 'Szyfrowanie' }))
}

async function fillKeygen(user: ReturnType<typeof userEvent.setup>, p: string, q: string, e: string) {
  const form = keygenForm()
  for (const [label, value] of [
    ['Liczba pierwsza (p)', p],
    ['Liczba pierwsza (q)', q],
    ['Wykładnik publiczny (e)', e],
  ]) {
    const input = form.getByLabelText(label)
    await user.clear(input)
    await user.type(input, value)
  }
  await user.click(form.getByRole('button', { name: 'Generuj klucze' }))
}

const KEYS_61_53_17 = { n: 3233, e: 17, d: 2753, phi: 3120 }

describe('RSA: generowanie kluczy i użycie klucza publicznego', () => {
  it('p=61, q=53, e=17 pokazuje n=3233, phi=3120, d=2753, a szyfrowanie m=65 daje c=2790', async () => {
    reply(KEYGEN_URL, { status: 200, body: KEYS_61_53_17 })
    reply(ENCRYPT_URL, { status: 200, body: { ciphertext: 2790 } })
    const user = userEvent.setup()
    render(<RsaView />)

    await fillKeygen(user, '61', '53', '17')

    // Wartości pochodzą z backendu (C), a UI je tylko wyświetla.
    const keygen = keygenForm()
    expect(await keygen.findByText('3233')).toBeTruthy()
    expect(keygen.getByText('3120')).toBeTruthy()
    expect(keygen.getByText('2753')).toBeTruthy()
    expect(keygen.getByText('(3233, 17)')).toBeTruthy() // klucz publiczny (n, e)
    expect(keygen.getByText('(3233, 2753)')).toBeTruthy() // klucz prywatny (n, d)

    expect(callsTo(KEYGEN_URL)).toHaveLength(1)
    expect(bodyOf(callsTo(KEYGEN_URL)[0])).toEqual({ p: 61, q: 53, e: 17 })
    expect((callsTo(KEYGEN_URL)[0][1] as RequestInit).method).toBe('POST')

    // „Użyj klucza publicznego” wpisuje (n, e) do istniejącego formularza szyfrowania.
    await user.click(keygen.getByRole('button', { name: 'Użyj klucza publicznego' }))
    const encrypt = encryptForm()
    expect((encrypt.getByLabelText('Wykładnik publiczny (e)') as HTMLInputElement).value).toBe('17')
    expect((encrypt.getByLabelText('Moduł (n)') as HTMLInputElement).value).toBe('3233')

    await user.type(encrypt.getByLabelText('Wiadomość (m)'), '65')
    await user.click(encrypt.getByRole('button', { name: 'Szyfruj' }))

    // Szyfrogram jest w <output> panelu szyfrowania.
    expect(await encrypt.findByText('2790', { selector: 'output' })).toBeTruthy()
    expect(callsTo(ENCRYPT_URL)).toHaveLength(1)
    expect(bodyOf(callsTo(ENCRYPT_URL)[0])).toEqual({
      message: 65,
      public_exponent: 17,
      modulus: 3233,
    })
  })

  it('błąd API (422 INVALID_P) pokazuje komunikat i usuwa poprzedni wynik', async () => {
    reply(
      KEYGEN_URL,
      { status: 200, body: KEYS_61_53_17 },
      {
        status: 422,
        body: { error: { code: 'INVALID_P', message: 'Parametr p musi być liczbą pierwszą.' } },
      },
    )
    const user = userEvent.setup()
    render(<RsaView />)

    await fillKeygen(user, '61', '53', '17')
    const keygen = keygenForm()
    expect(await keygen.findByText('2753')).toBeTruthy()

    // Druga próba: 60 nie jest liczbą pierwszą - odrzuca ją dopiero backend (C).
    await fillKeygen(user, '60', '53', '17')

    const alert = await keygen.findByRole('alert')
    expect(alert.textContent).toContain('Parametr p musi być liczbą pierwszą.')
    expect(keygen.queryByText('2753')).toBeNull()
    expect(keygen.queryByText('3233')).toBeNull()
    expect(keygen.getByRole('button', { name: 'Użyj klucza publicznego' })).toHaveProperty(
      'disabled',
      true,
    )
    expect(callsTo(KEYGEN_URL)).toHaveLength(2)
  })

  it('brak połączenia z backendem pokazuje błąd i nie zostawia wyniku', async () => {
    reply(KEYGEN_URL, { status: 200, body: KEYS_61_53_17 }, new TypeError('Failed to fetch'))
    const user = userEvent.setup()
    render(<RsaView />)

    await fillKeygen(user, '61', '53', '17')
    const keygen = keygenForm()
    expect(await keygen.findByText('2753')).toBeTruthy()

    await fillKeygen(user, '61', '53', '17')
    expect(await keygen.findByRole('alert')).toBeTruthy()
    expect(keygen.queryByText('2753')).toBeNull()
  })

  it('niepoprawne dane w formularzu nie wysyłają żądania i usuwają poprzedni wynik', async () => {
    reply(KEYGEN_URL, { status: 200, body: KEYS_61_53_17 })
    const user = userEvent.setup()
    render(<RsaView />)

    await fillKeygen(user, '61', '53', '17')
    const keygen = keygenForm()
    expect(await keygen.findByText('2753')).toBeTruthy()

    await fillKeygen(user, 'abc', '53', '17')
    expect(keygen.queryByText('2753')).toBeNull()
    expect(callsTo(KEYGEN_URL)).toHaveLength(1) // drugie żądanie nie poszło
  })

  it('po wygenerowaniu pokazuje ostrzeżenie o edukacyjnym charakterze 32-bitowych kluczy', async () => {
    reply(KEYGEN_URL, { status: 200, body: KEYS_61_53_17 })
    const user = userEvent.setup()
    render(<RsaView />)

    // Przed wygenerowaniem nie ma wyniku, więc nie ma też ostrzeżenia.
    expect(keygenForm().queryByText(/wyłącznie do nauki/i)).toBeNull()

    await fillKeygen(user, '61', '53', '17')
    expect(await keygenForm().findByText(/wyłącznie do nauki/i)).toBeTruthy()
  })
})

describe('RSA: regresja dotychczasowego szyfrowania', () => {
  it('szyfrowanie bez generowania kluczy nadal działa (65, 17, 3233 -> 2790)', async () => {
    reply(ENCRYPT_URL, { status: 200, body: { ciphertext: 2790 } })
    const user = userEvent.setup()
    render(<RsaView />)

    const encrypt = encryptForm()
    await user.type(encrypt.getByLabelText('Wiadomość (m)'), '65')
    await user.type(encrypt.getByLabelText('Wykładnik publiczny (e)'), '17')
    await user.type(encrypt.getByLabelText('Moduł (n)'), '3233')
    await user.click(encrypt.getByRole('button', { name: 'Szyfruj' }))

    expect(await encrypt.findByText('2790', { selector: 'output' })).toBeTruthy()
    expect(callsTo(KEYGEN_URL)).toHaveLength(0)
  })
})
