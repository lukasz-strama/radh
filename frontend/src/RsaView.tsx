import { useRef, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { ApiError, drawRsaParameters, generateRsaKeys } from './api'
import type { RsaKeygenRequest } from './api'
import { validateRsaKeyParams } from './validation'
import type { RsaKeyField, RsaKeyFieldErrors } from './validation'
import { Field } from './Field'
import { Button, DataBadge, Notice } from './ui'
import { useParameterDraw } from './useParameterDraw'
import { RsaCyclePanel } from './RsaCycle'
import type { RsaCycleHandle } from './RsaCycle'

// Para kluczy z backendu razem z parametrami, które faktycznie zostały wysłane.
type RsaKeys = {
  p: number
  q: number
  e: number
  n: number
  phi: number
  d: number
}

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
    },
  )

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    // Podczas losowania pola mogą się jeszcze zmienić – generujemy dopiero po nim.
    if (isLoading || parameters.isDrawing) return
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

      {/* Ręczna edycja ma pierwszeństwo: przerywa trwające losowanie, żeby go nie nadpisało. */}
      <Field
        name="p"
        label="Liczba pierwsza (p)"
        error={fieldErrors.p}
        key={`p-${drawn.version}`}
        defaultValue={drawn.values.p}
        onChange={parameters.cancel}
      />
      <Field
        name="q"
        label="Liczba pierwsza (q)"
        error={fieldErrors.q}
        key={`q-${drawn.version}`}
        defaultValue={drawn.values.q}
        onChange={parameters.cancel}
      />
      <Field
        name="e"
        label="Wykładnik publiczny (e)"
        error={fieldErrors.e}
        key={`e-${drawn.version}`}
        defaultValue={drawn.values.e}
        onChange={parameters.cancel}
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

      <KeyResult keys={keys} />

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
            Klucz publiczny <DataBadge kind="public" />
          </>
        }
        value={`(${show(keys?.n)}, ${show(keys?.e)})`}
        formula={<>(n, e)</>}
      />
      <KeyRow
        label={
          <>
            Klucz prywatny <DataBadge kind="private" />
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