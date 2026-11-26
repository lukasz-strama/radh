import { useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { ApiError, drawRsaParameters, generateRsaKeys } from './api'
import type { RsaKeygenRequest } from './api'
import { validateRsaKeyParams } from './validation'
import type { RsaKeyField, RsaKeyFieldErrors } from './validation'
import { Field } from './Field'
import { Button, Notice } from './ui'
import { useParameterDraw } from './useParameterDraw'
import { RsaCyclePanel } from './RsaCycle'
import type { RsaCycleHandle } from './RsaCycle'
import { RsaKeySteps } from './RsaKeySteps'
import type { RsaKeys } from './RsaKeySteps'

// Zakładka RSA: generowanie kluczy i pełny cykl – szyfrowanie oraz deszyfrowanie.
export function RsaView() {
  // Przyciski „Użyj klucza…” wpisują klucze do pól panelu cyklu.
  const cycle = useRef<RsaCycleHandle>(null)

  return (
    <>
      <h1>Szyfrowanie RSA</h1>

      {/* Dwa panele obok siebie; na wąskim ekranie jeden pod drugim. */}
      <div className="layout rsa-layout">
        <KeyGenPanel
          onUsePublicKey={(keys) => cycle.current?.applyPublicKey(keys)}
          onUsePrivateKey={(keys) => cycle.current?.applyPrivateKey(keys)}
        />
        <RsaCyclePanel ref={cycle} />
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
function KeyGenPanel({
  onUsePublicKey,
  onUsePrivateKey,
}: {
  onUsePublicKey: (keys: RsaKeys) => void
  onUsePrivateKey: (keys: RsaKeys) => void
}) {
  const [fieldErrors, setFieldErrors] = useState<RsaKeyFieldErrors>({})
  const [apiError, setApiError] = useState<string | null>(null)
  // Ostatnia wygenerowana para; null = brak (także po nowej próbie, zanim przyjdzie wynik).
  const [keys, setKeys] = useState<RsaKeys | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  // Numer ostatniego żądania – spóźniona odpowiedź po edycji pól jest ignorowana.
  const requestId = useRef(0)
  // Skąd pochodzą wartości w polach: z losowania czy z ręcznej edycji.
  const source = useRef<RsaKeys['source']>('manual')
  // Pola zostają niesterowane (wartości czyta FormData). Losowanie wpisuje nowe
  // wartości, montując pola od nowa (`key`) z nowym defaultValue. Pola sterowane
  // rozjeżdżały się z DOM, gdy wartość zmieniła się bez zdarzenia input (np. clear()
  // w Selenium) – kolejny render przywracał wtedy starą wartość.
  const [drawn, setDrawn] = useState({ values: KEY_DEFAULTS, version: 0 })
  const parameters = useParameterDraw(
    drawRsaParameters,
    (values) => validateRsaKeyParams(keyFields(values)).ok,
    (values) => {
      setDrawn((previous) => ({ values: keyFields(values), version: previous.version + 1 }))
      setFieldErrors({})
      source.current = 'drawn'
      // Stara para nie pasuje już do pól.
      setKeys(null)
    },
  )

  // Ręczna edycja ma pierwszeństwo: przerywa losowanie i trwające generowanie, a stary
  // wynik znika, żeby nie było widać wartości niepasujących do pól.
  function edit() {
    parameters.cancel()
    requestId.current += 1
    setIsLoading(false)
    setKeys(null)
    source.current = 'manual'
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    // Podczas losowania pola mogą się jeszcze zmienić – generujemy dopiero po nim.
    if (isLoading || parameters.isDrawing) return
    const id = ++requestId.current
    const keySource = source.current
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
      if (id !== requestId.current) return
      setKeys({ ...validation.data, ...response, source: keySource })
    } catch (error) {
      if (id !== requestId.current) return
      setApiError(
        error instanceof ApiError ? error.message : 'Wystąpił nieoczekiwany błąd.',
      )
    } finally {
      if (id === requestId.current) setIsLoading(false)
    }
  }

  return (
    <form className="panel" onSubmit={handleSubmit} noValidate aria-labelledby="rsa-keygen-title">
      <h2 id="rsa-keygen-title">Generowanie kluczy</h2>

      <Field
        name="p"
        label="Liczba pierwsza (p)"
        error={fieldErrors.p}
        key={`p-${drawn.version}`}
        defaultValue={drawn.values.p}
        onChange={edit}
      />
      <Field
        name="q"
        label="Liczba pierwsza (q)"
        error={fieldErrors.q}
        key={`q-${drawn.version}`}
        defaultValue={drawn.values.q}
        onChange={edit}
      />
      <Field
        name="e"
        label="Wykładnik publiczny (e)"
        error={fieldErrors.e}
        key={`e-${drawn.version}`}
        defaultValue={drawn.values.e}
        onChange={edit}
      />

      {/* Losowanie tylko wypełnia pola – klucze generuje się dopiero przyciskiem niżej. */}
      <Button
        variant="secondary"
        busy={parameters.isDrawing}
        busyLabel="Losowanie…"
        disabled={parameters.isBlocked || isLoading}
        onClick={parameters.draw}
      >
        Losuj parametry
      </Button>
      {parameters.error && <Notice tone="error">{parameters.error}</Notice>}

      <Button
        type="submit"
        busy={isLoading}
        busyLabel="Generowanie…"
        disabled={parameters.isDrawing}
      >
        Generuj klucze
      </Button>

      <RsaKeySteps keys={keys} />

      {/* Klucz publiczny (n, e) trafia do szyfrowania, prywatny (n, d) do deszyfrowania. */}
      <div className="rsa-key-buttons">
        <Button variant="secondary" disabled={!keys} onClick={() => keys && onUsePublicKey(keys)}>
          Użyj klucza publicznego
        </Button>
        <Button variant="secondary" disabled={!keys} onClick={() => keys && onUsePrivateKey(keys)}>
          Użyj klucza prywatnego
        </Button>
      </div>

      {keys && (
        <Notice tone="warning">
          Klucze 32-bitowe służą wyłącznie do nauki – da się je złamać w ułamku sekundy. Nie używaj
          ich do ochrony prawdziwych danych.
        </Notice>
      )}

      {apiError && <Notice tone="error">{apiError}</Notice>}
    </form>
  )
}

// Liczby z backendu w postaci pól formularza (jak przy ręcznym wpisaniu).
function keyFields(values: RsaKeygenRequest): Record<RsaKeyField, string> {
  return { p: String(values.p), q: String(values.q), e: String(values.e) }
}