import { useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { ApiError, encryptRsa, generateRsaKeys } from './api'
import type { RsaEncryptRequest } from './api'
import { validateRsaInput, validateRsaKeyParams } from './validation'
import type { FieldErrors, RsaKeyField, RsaKeyFieldErrors } from './validation'
import { Field } from './Field'

// Wynik szyfrowania razem z parametrami, które faktycznie zostały wysłane.
// (Pola formularza mogą się zmienić po kliknięciu, więc nie bierzemy ich z pól.)
type EncryptResult = {
  request: RsaEncryptRequest
  ciphertext: number
}

// Para kluczy z backendu razem z parametrami, które faktycznie zostały wysłane.
type RsaKeys = {
  p: number
  q: number
  e: number
  n: number
  phi: number
  d: number
}

// Zakładka RSA: generowanie kluczy, formularz szyfrowania i ekran wizualizacji.
export function RsaView() {
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({})
  const [apiError, setApiError] = useState<string | null>(null)
  const [result, setResult] = useState<EncryptResult | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  // e i n trzymamy w stanie, żeby „Użyj klucza publicznego” mógł je wpisać.
  const [publicExponent, setPublicExponent] = useState('')
  const [modulus, setModulus] = useState('')

  // Wpisuje klucz publiczny (n, e) do formularza szyfrowania. Stary szyfrogram
  // dotyczył innego klucza, więc go usuwamy razem z błędami pól e i n.
  function applyPublicKey(keys: RsaKeys) {
    setPublicExponent(String(keys.e))
    setModulus(String(keys.n))
    setResult(null)
    setApiError(null)
    setFieldErrors(({ message }) => ({ message }))
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (isLoading) return
    setApiError(null)
    setResult(null)

    // Zbieramy wartości z pól formularza (po atrybucie `name`).
    const form = new FormData(event.currentTarget)
    const validation = validateRsaInput({
      message: String(form.get('message') ?? ''),
      public_exponent: String(form.get('public_exponent') ?? ''),
      modulus: String(form.get('modulus') ?? ''),
    })

    if (!validation.ok) {
      setFieldErrors(validation.errors)
      return
    }
    setFieldErrors({})

    setIsLoading(true)
    try {
      // Szyfrogram pochodzi wyłącznie z odpowiedzi backendu.
      const response = await encryptRsa(validation.data)
      setResult({ request: validation.data, ciphertext: response.ciphertext })
    } catch (error) {
      setApiError(
        error instanceof ApiError ? error.message : 'Wystąpił nieoczekiwany błąd.',
      )
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <>
      <h1>RADH – szyfrowanie RSA</h1>

      <div className="layout">
        {/* Ekran: tu później trafi wizualizacja (Alice, Bob, Mallory, pakiety) */}
        <section className="screen" aria-label="Ekran wizualizacji"></section>

        <div className="rsa-side">
          <KeyGenPanel onUsePublicKey={applyPublicKey} />

          {/* Panel szyfrowania. noValidate: walidację robimy sami, z polskimi komunikatami. */}
          <form
            className="panel"
            onSubmit={handleSubmit}
            noValidate
            aria-labelledby="rsa-encrypt-title"
          >
            <h2 id="rsa-encrypt-title">Szyfrowanie</h2>
            <Field name="message" label="Wiadomość (m)" error={fieldErrors.message} />
            <Field
              name="public_exponent"
              label="Wykładnik publiczny (e)"
              error={fieldErrors.public_exponent}
              value={publicExponent}
              onChange={setPublicExponent}
            />
            <Field
              name="modulus"
              label="Moduł (n)"
              error={fieldErrors.modulus}
              value={modulus}
              onChange={setModulus}
            />

            <button type="submit" disabled={isLoading} aria-busy={isLoading}>
              {isLoading ? 'Szyfrowanie…' : 'Szyfruj'}
            </button>

            {result && (
              <div className="result" role="status">
                <p>
                  Szyfrogram (c): <output>{result.ciphertext}</output>
                </p>
                <p className="formula">
                  c = m<sup>e</sup> mod n
                </p>
                <p className="formula">
                  c = {result.request.message}
                  <sup>{result.request.public_exponent}</sup> mod {result.request.modulus} ={' '}
                  {result.ciphertext}
                </p>
              </div>
            )}

            {apiError && (
              <p className="api-error" role="alert">
                {apiError}
              </p>
            )}
          </form>
        </div>
      </div>
    </>
  )
}

const KEY_DEFAULTS: Record<RsaKeyField, string> = {
  p: '61',
  q: '53',
  e: '17',
}

// Panel generowania pary kluczy. Wszystkie wartości (n, φ(n), d) liczy backend;
// tutaj tylko formularz, walidacja i czytelne oznaczenia wyniku.
function KeyGenPanel({ onUsePublicKey }: { onUsePublicKey: (keys: RsaKeys) => void }) {
  const [fieldErrors, setFieldErrors] = useState<RsaKeyFieldErrors>({})
  const [apiError, setApiError] = useState<string | null>(null)
  // Ostatnia wygenerowana para; null = brak (także po nowej próbie, zanim przyjdzie wynik).
  const [keys, setKeys] = useState<RsaKeys | null>(null)
  const [isLoading, setIsLoading] = useState(false)

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (isLoading) return
    setApiError(null)
    setKeys(null)

    const form = new FormData(event.currentTarget)
    const validation = validateRsaKeyParams({
      p: String(form.get('p') ?? ''),
      q: String(form.get('q') ?? ''),
      e: String(form.get('e') ?? ''),
    })

    if (!validation.ok) {
      setFieldErrors(validation.errors)
      return
    }
    setFieldErrors({})

    setIsLoading(true)
    try {
      // n, φ(n) i d pochodzą wyłącznie z odpowiedzi backendu (CryptoCore).
      const response = await generateRsaKeys(validation.data)
      setKeys({ ...validation.data, ...response })
    } catch (error) {
      setApiError(
        error instanceof ApiError ? error.message : 'Wystąpił nieoczekiwany błąd.',
      )
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <form className="panel" onSubmit={handleSubmit} noValidate aria-labelledby="rsa-keygen-title">
      <h2 id="rsa-keygen-title">Generowanie kluczy</h2>

      <Field
        name="p"
        label="Liczba pierwsza (p)"
        error={fieldErrors.p}
        defaultValue={KEY_DEFAULTS.p}
      />
      <Field
        name="q"
        label="Liczba pierwsza (q)"
        error={fieldErrors.q}
        defaultValue={KEY_DEFAULTS.q}
      />
      <Field
        name="e"
        label="Wykładnik publiczny (e)"
        error={fieldErrors.e}
        defaultValue={KEY_DEFAULTS.e}
      />

      <button type="submit" disabled={isLoading} aria-busy={isLoading}>
        {isLoading ? 'Generowanie…' : 'Generuj klucze'}
      </button>

      <KeyResult keys={keys} />

      <button type="button" disabled={!keys} onClick={() => keys && onUsePublicKey(keys)}>
        Użyj klucza publicznego
      </button>

      <p className="rsa-warning">
        Klucze 32-bitowe służą wyłącznie do nauki – da się je złamać w ułamku sekundy. Nie używaj
        ich do ochrony prawdziwych danych.
      </p>

      {apiError && (
        <p className="api-error" role="alert">
          {apiError}
        </p>
      )}
    </form>
  )
}

// Wynik generowania z oznaczeniami: nazwa i wartość w jednym wierszu, wzór pod spodem.
// Bez wyniku w miejscu wartości jest „?”.
function KeyResult({ keys }: { keys: RsaKeys | null }) {
  const show = (value: number | undefined) => (value === undefined ? '?' : String(value))
  return (
    <dl className="result rsa-keys">
      <KeyRow label="Moduł" value={show(keys?.n)} formula={<>n = p · q</>} />
      <KeyRow label="Funkcja Eulera" value={show(keys?.phi)} formula={<>φ(n) = (p − 1)(q − 1)</>} />
      <KeyRow
        label="Wykładnik prywatny"
        value={show(keys?.d)}
        formula={
          <>
            d = e<sup>−1</sup> mod φ(n)
          </>
        }
      />
      <KeyRow
        label={
          <>
            Klucz publiczny <span className="rsa-key-badge">jawny</span>
          </>
        }
        value={`(${show(keys?.n)}, ${show(keys?.e)})`}
        formula={<>(n, e)</>}
      />
      <KeyRow
        label={
          <>
            Klucz prywatny <span className="rsa-key-badge rsa-key-badge--private">tajny</span>
          </>
        }
        value={`(${show(keys?.n)}, ${show(keys?.d)})`}
        formula={<>(n, d)</>}
      />
    </dl>
  )
}

function KeyRow({
  label,
  value,
  formula,
}: {
  label: ReactNode
  value: string
  formula: ReactNode
}) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>
        <output>{value}</output>
      </dd>
      <dd className="formula rsa-key-formula">{formula}</dd>
    </div>
  )
}