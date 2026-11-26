// Testy UI pełnego cyklu RSA (#100): szyfrowanie i deszyfrowanie liczby oraz tekstu.
//
// Backend jest zastąpiony mockiem `fetch` zgodnym z backend/README.md (#99):
//   POST /api/v1/rsa/demo/keygen        -> {"n","e","d","phi"}
//   POST /api/v1/rsa/demo/encrypt       -> {"ciphertext"}
//   POST /api/v1/rsa/demo/decrypt       -> {"message"}
//   POST /api/v1/rsa/demo/text/encrypt  -> {"ciphertexts": [...]}
//   POST /api/v1/rsa/demo/text/decrypt  -> {"text"}
// Szyfrogramy w mocku liczy ten sam wzór (m^e mod n), żeby dane były spójne.
import { act, cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { RsaView } from '../src/RsaView'

const KEYGEN = '/api/v1/rsa/demo/keygen'
const ENCRYPT = '/api/v1/rsa/demo/encrypt'
const DECRYPT = '/api/v1/rsa/demo/decrypt'
const TEXT_ENCRYPT = '/api/v1/rsa/demo/text/encrypt'
const TEXT_DECRYPT = '/api/v1/rsa/demo/text/decrypt'

// Klucz z przykładu w backend/README.md: p = 61, q = 53, e = 17.
const N = 3233
const E = 17
const D = 2753

function modPow(base: number, exponent: number, modulus: number): number {
  let result = 1n
  let b = BigInt(base) % BigInt(modulus)
  let e = BigInt(exponent)
  const m = BigInt(modulus)
  while (e > 0n) {
    if (e & 1n) result = (result * b) % m
    b = (b * b) % m
    e >>= 1n
  }
  return Number(result)
}

type Handler = (body: Record<string, unknown>) => Promise<Response>
let handlers: Record<string, Handler>
let fetchMock: ReturnType<typeof vi.fn>

function json(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  })
}

function apiError(code: string, status: number, message: string, headers: Record<string, string> = {}) {
  return json({ error: { code, message } }, status, headers)
}

function bodies(url: string): Record<string, unknown>[] {
  return fetchMock.mock.calls
    .filter(([callUrl]) => callUrl === url)
    .map(([, init]) => JSON.parse((init as RequestInit).body as string))
}

// Backend liczący jak CryptoCore: każdy bajt UTF-8 szyfrowany osobno.
function realisticBackend(): Record<string, Handler> {
  return {
    [KEYGEN]: () => Promise.resolve(json({ n: N, e: E, d: D, phi: 3120 })),
    [ENCRYPT]: (body) =>
      Promise.resolve(json({ ciphertext: modPow(body.message as number, body.public_exponent as number, body.modulus as number) })),
    [DECRYPT]: (body) =>
      Promise.resolve(json({ message: modPow(body.ciphertext as number, body.private_exponent as number, body.modulus as number) })),
    [TEXT_ENCRYPT]: (body) => {
      const bytes = [...new TextEncoder().encode(body.text as string)]
      return Promise.resolve(json({
        ciphertexts: bytes.map((byte) => modPow(byte, body.public_exponent as number, body.modulus as number)),
      }))
    },
    [TEXT_DECRYPT]: (body) => {
      const bytes = (body.ciphertexts as number[]).map((c) =>
        modPow(c, body.private_exponent as number, body.modulus as number))
      return Promise.resolve(json({ text: new TextDecoder('utf-8', { fatal: true }).decode(new Uint8Array(bytes)) }))
    },
  }
}

beforeEach(() => {
  sessionStorage.clear()
  localStorage.clear()
  handlers = realisticBackend()
  fetchMock = vi.fn((url: string, init: RequestInit = {}) => {
    const handler = handlers[url]
    if (!handler) return Promise.reject(new TypeError(`brak atrapy: ${url}`))
    return handler(init.body ? JSON.parse(init.body as string) : {})
  })
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

const keygen = () => within(screen.getByRole('form', { name: 'Generowanie kluczy' }))
const encrypt = () => within(screen.getByRole('form', { name: 'Szyfrowanie' }))
const decrypt = () => within(screen.getByRole('form', { name: 'Deszyfrowanie' }))

function inputValue(scope: ReturnType<typeof within>, label: string): string {
  return (scope.getByLabelText(label) as HTMLInputElement | HTMLTextAreaElement).value
}

// Generuje domyślne klucze i wpisuje oba do panelu cyklu.
async function generateAndUseKeys(user: ReturnType<typeof userEvent.setup>) {
  await user.click(keygen().getByRole('button', { name: 'Generuj klucze' }))
  await keygen().findByText('2753')
  await user.click(keygen().getByRole('button', { name: 'Użyj klucza publicznego' }))
  await user.click(keygen().getByRole('button', { name: 'Użyj klucza prywatnego' }))
}

function tableRows(scope: ReturnType<typeof within>): string[][] {
  const table = scope.getByRole('table')
  return within(table)
    .getAllByRole('row')
    .slice(1)
    .map((row) => within(row).getAllByRole('cell').map((cell) => cell.textContent ?? ''))
}

describe('pełny cykl RSA', () => {
  it('tekst „HELLO”: klucze z generatora, szyfrowanie i odzyskanie bez przepisywania', async () => {
    const user = userEvent.setup()
    render(<RsaView />)
    await generateAndUseKeys(user)
    expect(inputValue(decrypt(), 'Wykładnik prywatny (d)')).toBe('2753')
    expect(inputValue(decrypt(), 'Moduł (n)')).toBe('3233')

    await user.click(screen.getByRole('radio', { name: 'Tekst' }))
    await user.type(encrypt().getByLabelText('Tekst'), 'HELLO')
    expect(encrypt().getByText('5 / 128 bajtów UTF-8')).toBeTruthy()
    await user.click(encrypt().getByRole('button', { name: 'Szyfruj' }))

    await encrypt().findByRole('table')
    expect(bodies(TEXT_ENCRYPT)).toEqual([{ text: 'HELLO', public_exponent: E, modulus: N }])
    expect(tableRows(encrypt())).toEqual([
      ['H', '72', '3000'],
      ['E', '69', '28'],
      ['L', '76', '2726'],
      ['L', '76', '2726'],
      ['O', '79', '1307'],
    ])
    // Szyfrogramy czekają w polu deszyfrowania.
    expect(inputValue(decrypt(), 'Szyfrogramy (c₁, c₂, …)')).toBe('3000, 28, 2726, 2726, 1307')

    await user.click(decrypt().getByRole('button', { name: 'Odszyfruj' }))
    await decrypt().findByText('HELLO', { selector: 'output' })
    expect(bodies(TEXT_DECRYPT)).toEqual([
      { ciphertexts: [3000, 28, 2726, 2726, 1307], private_exponent: D, modulus: N },
    ])
    expect(tableRows(decrypt())).toEqual([
      ['3000', '72', 'H'],
      ['28', '69', 'E'],
      ['2726', '76', 'L'],
      ['2726', '76', 'L'],
      ['1307', '79', 'O'],
    ])
  })

  it('polski tekst przechodzi cały cykl; widać bajty wielobajtowych znaków', async () => {
    const user = userEvent.setup()
    render(<RsaView />)
    await generateAndUseKeys(user)
    await user.click(screen.getByRole('radio', { name: 'Tekst' }))
    const text = 'Zażółć gęślą jaźń'
    await user.type(encrypt().getByLabelText('Tekst'), text)
    expect(encrypt().getByText('26 / 128 bajtów UTF-8')).toBeTruthy()
    await user.click(encrypt().getByRole('button', { name: 'Szyfruj' }))

    await encrypt().findByRole('table')
    const rows = tableRows(encrypt())
    expect(rows).toHaveLength([...text].length)
    expect(rows[2]).toEqual(['ż', '197 188', `${modPow(197, E, N)} ${modPow(188, E, N)}`])
    expect(rows[6]).toEqual(['␣', '32', String(modPow(32, E, N))])
    expect(encrypt().getByText(/26 bajtów UTF-8 → 26 szyfrogramów/)).toBeTruthy()

    await user.click(decrypt().getByRole('button', { name: 'Odszyfruj' }))
    await decrypt().findByText(text, { selector: 'output' })
    expect(tableRows(decrypt())[2]).toEqual([`${modPow(197, E, N)} ${modPow(188, E, N)}`, '197 188', 'ż'])
  })

  it('tryb liczbowy: 65 → 2790 → 65', async () => {
    const user = userEvent.setup()
    render(<RsaView />)
    await generateAndUseKeys(user)
    await user.type(encrypt().getByLabelText('Wiadomość (m)'), '65')
    await user.click(encrypt().getByRole('button', { name: 'Szyfruj' }))
    expect(await encrypt().findByText('2790', { selector: 'output' })).toBeTruthy()
    expect(inputValue(decrypt(), 'Szyfrogram (c)')).toBe('2790')

    await user.click(decrypt().getByRole('button', { name: 'Odszyfruj' }))
    expect(await decrypt().findByText('65', { selector: 'output' })).toBeTruthy()
    expect(bodies(DECRYPT)).toEqual([{ ciphertext: 2790, private_exponent: D, modulus: N }])
    const result = screen.getByRole('form', { name: 'Deszyfrowanie' }).querySelector('.result')
    expect(result?.textContent).toContain('m = 27902753 mod 3233 = 65')
  })

  it('pokazuje ostrzeżenie o RSA bez paddingu', () => {
    render(<RsaView />)
    expect(screen.getByText(/bez paddingu/)).toBeTruthy()
  })

  it('klucz prywatny nie trafia do trwałej pamięci przeglądarki', async () => {
    const user = userEvent.setup()
    render(<RsaView />)
    await generateAndUseKeys(user)
    await user.type(encrypt().getByLabelText('Wiadomość (m)'), '65')
    await user.click(encrypt().getByRole('button', { name: 'Szyfruj' }))
    await user.click(await decrypt().findByRole('button', { name: 'Odszyfruj' }))
    await decrypt().findByText('65', { selector: 'output' })

    const stored = [sessionStorage, localStorage].flatMap((storage) =>
      Object.keys(storage).map((key) => `${key}=${storage.getItem(key)}`))
    expect(stored.filter((entry) => entry.includes(String(D)))).toEqual([])
    expect(window.location.href).not.toContain(String(D))
  })
})

describe('błędy i limity', () => {
  it('tekst dłuższy niż 128 bajtów UTF-8 nie idzie do backendu', async () => {
    const user = userEvent.setup()
    render(<RsaView />)
    await generateAndUseKeys(user)
    await user.click(screen.getByRole('radio', { name: 'Tekst' }))
    await user.type(encrypt().getByLabelText('Tekst'), 'ż'.repeat(65))
    await user.click(encrypt().getByRole('button', { name: 'Szyfruj' }))
    expect(encrypt().getByText('Tekst może mieć najwyżej 128 bajtów UTF-8.')).toBeTruthy()
    expect(bodies(TEXT_ENCRYPT)).toHaveLength(0)
  })

  it('tryb tekstowy wymaga modułu większego od 255', async () => {
    const user = userEvent.setup()
    render(<RsaView />)
    await user.click(screen.getByRole('radio', { name: 'Tekst' }))
    await user.type(encrypt().getByLabelText('Tekst'), 'A')
    await user.type(encrypt().getByLabelText('Wykładnik publiczny (e)'), '7')
    await user.type(encrypt().getByLabelText('Moduł (n)'), '143')
    await user.click(encrypt().getByRole('button', { name: 'Szyfruj' }))
    expect(encrypt().getByText(/moduł n musi być większy od 255/)).toBeTruthy()
    expect(bodies(TEXT_ENCRYPT)).toHaveLength(0)
  })

  it('błędny szyfrogram na liście wskazuje jego numer', async () => {
    const user = userEvent.setup()
    render(<RsaView />)
    await generateAndUseKeys(user)
    await user.click(screen.getByRole('radio', { name: 'Tekst' }))
    await user.type(decrypt().getByLabelText('Szyfrogramy (c₁, c₂, …)'), '3000, x1, 28')
    await user.click(decrypt().getByRole('button', { name: 'Odszyfruj' }))
    expect(decrypt().getByText(/Szyfrogram nr 2: Podaj nieujemną liczbę/)).toBeTruthy()

    await user.clear(decrypt().getByLabelText('Szyfrogramy (c₁, c₂, …)'))
    await user.type(decrypt().getByLabelText('Szyfrogramy (c₁, c₂, …)'), '3000 4000')
    await user.click(decrypt().getByRole('button', { name: 'Odszyfruj' }))
    expect(decrypt().getByText('Szyfrogram nr 2 musi być mniejszy od modułu n.')).toBeTruthy()
    expect(bodies(TEXT_DECRYPT)).toHaveLength(0)
  })

  it('szyfrogram liczbowy musi być mniejszy od n', async () => {
    const user = userEvent.setup()
    render(<RsaView />)
    await generateAndUseKeys(user)
    await user.type(decrypt().getByLabelText('Szyfrogram (c)'), '5000')
    await user.click(decrypt().getByRole('button', { name: 'Odszyfruj' }))
    expect(decrypt().getByText('Szyfrogram c musi być mniejszy od modułu n.')).toBeTruthy()
    expect(bodies(DECRYPT)).toHaveLength(0)
  })

  it('błąd z backendu (zły klucz, niepoprawne UTF-8) pokazuje jego komunikat', async () => {
    const user = userEvent.setup()
    handlers[TEXT_DECRYPT] = () =>
      Promise.resolve(apiError('INVALID_UTF8', 422, 'Odszyfrowane bajty nie tworzą poprawnego UTF-8.'))
    render(<RsaView />)
    await generateAndUseKeys(user)
    await user.click(screen.getByRole('radio', { name: 'Tekst' }))
    await user.type(decrypt().getByLabelText('Szyfrogramy (c₁, c₂, …)'), '3000')
    await user.click(decrypt().getByRole('button', { name: 'Odszyfruj' }))
    const alert = await decrypt().findByRole('alert')
    expect(alert.textContent).toBe('Odszyfrowane bajty nie tworzą poprawnego UTF-8.')
  })

  it('limit żądań: czytelny komunikat z czasem i blokada przycisku', async () => {
    const user = userEvent.setup()
    handlers[TEXT_ENCRYPT] = () =>
      Promise.resolve(apiError('RATE_LIMITED', 429, 'Nie można wykonać operacji.', { 'Retry-After': '1' }))
    render(<RsaView />)
    await generateAndUseKeys(user)
    await user.click(screen.getByRole('radio', { name: 'Tekst' }))
    await user.type(encrypt().getByLabelText('Tekst'), 'HELLO')
    await user.click(encrypt().getByRole('button', { name: 'Szyfruj' }))

    const message = 'Za dużo prób w krótkim czasie. Spróbuj ponownie za 1 s.'
    expect((await encrypt().findByRole('alert')).textContent).toBe(message)
    const button = encrypt().getByRole('button', { name: 'Szyfruj' }) as HTMLButtonElement
    expect(button.disabled).toBe(true)
    // Po upływie Retry-After przycisk wraca, a nieaktualny komunikat znika.
    await waitFor(() => expect(button.disabled).toBe(false), { timeout: 2500 })
    expect(encrypt().queryByRole('alert')).toBeNull()
  })

  it('spóźniony szyfrogram nie wraca po zmianie klucza', async () => {
    const user = userEvent.setup()
    let release: (response: Response) => void = () => {}
    handlers[ENCRYPT] = () => new Promise((resolve) => (release = resolve))
    render(<RsaView />)
    await generateAndUseKeys(user)
    await user.type(encrypt().getByLabelText('Wiadomość (m)'), '65')
    await user.click(encrypt().getByRole('button', { name: 'Szyfruj' }))
    await encrypt().findByRole('button', { name: 'Szyfrowanie…' })

    await user.click(keygen().getByRole('button', { name: 'Użyj klucza publicznego' }))
    await act(async () => release(json({ ciphertext: 2790 })))
    expect(encrypt().queryByRole('status')).toBeNull()
    expect(inputValue(decrypt(), 'Szyfrogram (c)')).toBe('')
  })

  it('zmiana trybu czyści wyniki, a klucze zostają', async () => {
    const user = userEvent.setup()
    render(<RsaView />)
    await generateAndUseKeys(user)
    await user.type(encrypt().getByLabelText('Wiadomość (m)'), '65')
    await user.click(encrypt().getByRole('button', { name: 'Szyfruj' }))
    await encrypt().findByText('2790', { selector: 'output' })

    await user.click(screen.getByRole('radio', { name: 'Tekst' }))
    expect(encrypt().queryByRole('status')).toBeNull()
    expect(inputValue(encrypt(), 'Moduł (n)')).toBe('3233')
    expect(inputValue(decrypt(), 'Wykładnik prywatny (d)')).toBe('2753')
    await user.click(screen.getByRole('radio', { name: 'Liczba' }))
    expect(inputValue(encrypt(), 'Wiadomość (m)')).toBe('65')
  })
})

describe('poprawki z review', () => {
  // Odpowiedź zwalniana przez test – do sprawdzania spóźnionych odpowiedzi.
  function hold(url: string) {
    let release: (response: Response) => void = () => {}
    handlers[url] = () => new Promise((resolve) => (release = resolve))
    return (response: Response) => release(response)
  }

  it('ręczna edycja pola szyfrowania unieważnia trwające żądanie', async () => {
    const user = userEvent.setup()
    const release = hold(ENCRYPT)
    render(<RsaView />)
    await generateAndUseKeys(user)
    await user.type(encrypt().getByLabelText('Wiadomość (m)'), '65')
    await user.click(encrypt().getByRole('button', { name: 'Szyfruj' }))
    await encrypt().findByRole('button', { name: 'Szyfrowanie…' })

    await user.type(encrypt().getByLabelText('Wiadomość (m)'), '6')
    encrypt().getByRole('button', { name: 'Szyfruj' })
    await act(async () => release(json({ ciphertext: 2790 })))
    expect(encrypt().queryByRole('status')).toBeNull()
    expect(inputValue(decrypt(), 'Szyfrogram (c)')).toBe('')
  })

  it('ręczna edycja pola deszyfrowania unieważnia trwające żądanie', async () => {
    const user = userEvent.setup()
    const release = hold(DECRYPT)
    render(<RsaView />)
    await generateAndUseKeys(user)
    await user.type(decrypt().getByLabelText('Szyfrogram (c)'), '2790')
    await user.click(decrypt().getByRole('button', { name: 'Odszyfruj' }))
    await decrypt().findByRole('button', { name: 'Deszyfrowanie…' })

    await user.type(decrypt().getByLabelText('Wykładnik prywatny (d)'), '1')
    await act(async () => release(json({ message: 65 })))
    expect(decrypt().queryByRole('status')).toBeNull()
  })

  it('koniec szyfrowania nie nadpisuje szyfrogramu wpisanego ręcznie w trakcie', async () => {
    const user = userEvent.setup()
    const release = hold(ENCRYPT)
    render(<RsaView />)
    await generateAndUseKeys(user)
    await user.type(encrypt().getByLabelText('Wiadomość (m)'), '65')
    await user.click(encrypt().getByRole('button', { name: 'Szyfruj' }))
    await encrypt().findByRole('button', { name: 'Szyfrowanie…' })

    await user.type(decrypt().getByLabelText('Szyfrogram (c)'), '1234')
    await act(async () => release(json({ ciphertext: 2790 })))
    expect(await encrypt().findByText('2790', { selector: 'output' })).toBeTruthy()
    expect(inputValue(decrypt(), 'Szyfrogram (c)')).toBe('1234')
  })

  it('komunikat Retry-After zostaje do końca blokady mimo zmiany klucza i edycji', async () => {
    const user = userEvent.setup()
    handlers[ENCRYPT] = () =>
      Promise.resolve(apiError('RATE_LIMITED', 429, 'Nie można wykonać operacji.', { 'Retry-After': '1' }))
    render(<RsaView />)
    await generateAndUseKeys(user)
    await user.type(encrypt().getByLabelText('Wiadomość (m)'), '65')
    await user.click(encrypt().getByRole('button', { name: 'Szyfruj' }))
    const message = 'Za dużo prób w krótkim czasie. Spróbuj ponownie za 1 s.'
    expect((await encrypt().findByRole('alert')).textContent).toBe(message)

    await user.click(keygen().getByRole('button', { name: 'Użyj klucza publicznego' }))
    await user.type(encrypt().getByLabelText('Wiadomość (m)'), '6')
    expect(encrypt().getByRole('alert').textContent).toBe(message)
    await waitFor(() => expect(encrypt().queryByRole('alert')).toBeNull(), { timeout: 2500 })
  })

  it('wynik spoza zakresu modułu jest odrzucany', async () => {
    const user = userEvent.setup()
    handlers[ENCRYPT] = () => Promise.resolve(json({ ciphertext: 5000 }))
    handlers[DECRYPT] = () => Promise.resolve(json({ message: 3233 }))
    handlers[TEXT_ENCRYPT] = () => Promise.resolve(json({ ciphertexts: [3000, 28, 4000, 2726, 1307] }))
    render(<RsaView />)
    await generateAndUseKeys(user)

    await user.type(encrypt().getByLabelText('Wiadomość (m)'), '65')
    await user.click(encrypt().getByRole('button', { name: 'Szyfruj' }))
    expect((await encrypt().findByRole('alert')).textContent).toMatch(/nieoczekiwanym formacie/)

    await user.type(decrypt().getByLabelText('Szyfrogram (c)'), '2790')
    await user.click(decrypt().getByRole('button', { name: 'Odszyfruj' }))
    expect((await decrypt().findByRole('alert')).textContent).toMatch(/nieoczekiwanym formacie/)

    await user.click(screen.getByRole('radio', { name: 'Tekst' }))
    await user.type(encrypt().getByLabelText('Tekst'), 'HELLO')
    await user.click(encrypt().getByRole('button', { name: 'Szyfruj' }))
    expect((await encrypt().findByRole('alert')).textContent).toMatch(/nieoczekiwanym formacie/)
    expect(encrypt().queryByRole('table')).toBeNull()
  })
})