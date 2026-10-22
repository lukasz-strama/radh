import { useState } from 'react'
import type { FormEvent } from 'react'
import { ApiError, encryptRsa } from './api'
import type { RsaEncryptRequest } from './api'
import { validateRsaInput } from './validation'
import type { FieldErrors } from './validation'
import { Field } from './Field'

// Wynik szyfrowania razem z parametrami, które faktycznie zostały wysłane.
// (Pola formularza mogą się zmienić po kliknięciu, więc nie bierzemy ich z pól.)
type EncryptResult = {
  request: RsaEncryptRequest
  ciphertext: number
}

// Zakładka RSA: formularz szyfrowania i ekran wizualizacji.
export function RsaView() {
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({})
  const [apiError, setApiError] = useState<string | null>(null)
  const [result, setResult] = useState<EncryptResult | null>(null)
  const [isLoading, setIsLoading] = useState(false)

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

        {/* Panel sterowania. noValidate: walidację robimy sami, z polskimi komunikatami. */}
        <form className="panel" onSubmit={handleSubmit} noValidate>
          <Field name="message" label="Wiadomość (m)" error={fieldErrors.message} />
          <Field
            name="public_exponent"
            label="Wykładnik publiczny (e)"
            error={fieldErrors.public_exponent}
          />
          <Field name="modulus" label="Moduł (n)" error={fieldErrors.modulus} />

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
    </>
  )
}