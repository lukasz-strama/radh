import { useState } from 'react'
import type { FormEvent } from 'react'
import { ApiError, encryptRsa } from './api'
import { validateRsaInput } from './validation'
import type { FieldErrors, RsaField } from './validation'
import './App.css'

function App() {
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({})
  const [apiError, setApiError] = useState<string | null>(null)

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setApiError(null)

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

    try {
      const result = await encryptRsa(validation.data)
      // Wyświetlanie szyfrogramu – do zrobienia, gdy ustalimy format odpowiedzi.
      console.log('Odpowiedź backendu:', result)
    } catch (error) {
      setApiError(
        error instanceof ApiError ? error.message : 'Wystąpił nieoczekiwany błąd.',
      )
    }
  }

  return (
    <div className="app">
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

          <button type="submit">Szyfruj</button>

          {apiError && (
            <p className="api-error" role="alert">
              {apiError}
            </p>
          )}
        </form>
      </div>
    </div>
  )
}

type FieldProps = {
  name: RsaField
  label: string
  error?: string
}

// Pojedyncze pole liczbowe z etykietą i komunikatem błędu pod spodem.
function Field({ name, label, error }: FieldProps) {
  const errorId = `${name}-error`
  return (
    <label>
      {label}
      <input
        name={name}
        type="text"
        inputMode="numeric"
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? errorId : undefined}
      />
      {error && (
        <span className="field-error" id={errorId}>
          {error}
        </span>
      )}
    </label>
  )
}

export default App