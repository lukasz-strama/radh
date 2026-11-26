// Pełny cykl RSA (#100): szyfrowanie kluczem publicznym i deszyfrowanie kluczem
// prywatnym, na liczbie albo na tekście UTF-8. Każdą operację modularną liczy
// backend (CryptoCore); przeglądarka koduje tekst tylko po to, żeby pokazać bajty.
//
// Klucz prywatny (d) żyje wyłącznie w stanie Reacta – nie trafia do sessionStorage,
// localStorage ani adresu strony, więc znika razem z kartą.

import { useEffect, useImperativeHandle, useRef, useState } from 'react'
import type { FormEvent, Ref } from 'react'
import { ApiError, decryptRsa, decryptRsaText, encryptRsa, encryptRsaText } from './api'
import type {
  RsaDecryptRequest,
  RsaEncryptRequest,
  RsaTextDecryptRequest,
  RsaTextEncryptRequest,
} from './api'
import {
  RSA_TEXT_MAX_BYTES,
  utf8Length,
  validateRsaDecryptInput,
  validateRsaInput,
  validateRsaTextDecryptInput,
  validateRsaTextInput,
} from './validation'
import { Field } from './Field'
import { Button, Notice } from './ui'

type Mode = 'number' | 'text'

const MODE_LABEL: Record<Mode, string> = {
  number: 'Liczba',
  text: 'Tekst',
}

// Wyniki razem z danymi, które faktycznie zostały wysłane – pola mogą się
// zmienić po kliknięciu, więc wzory i tabele budujemy z żądania, nie z pól.
type EncryptResult =
  | { kind: 'number'; request: RsaEncryptRequest; ciphertext: number }
  | { kind: 'text'; request: RsaTextEncryptRequest; ciphertexts: number[] }

type DecryptResult =
  | { kind: 'number'; request: RsaDecryptRequest; message: number }
  | { kind: 'text'; request: RsaTextDecryptRequest; text: string }

type Errors = Record<string, string | undefined>

// Wpisanie kluczy z panelu generowania („Użyj klucza publicznego/prywatnego”).
export type RsaCycleHandle = {
  applyPublicKey: (key: { n: number; e: number }) => void
  applyPrivateKey: (key: { n: number; d: number }) => void
}

export function RsaCyclePanel({ ref }: { ref?: Ref<RsaCycleHandle> }) {
  const [mode, setMode] = useState<Mode>('number')

  // Szyfrowanie: wiadomość (liczba albo tekst) i klucz publiczny (e, n).
  const [message, setMessage] = useState('')
  const [text, setText] = useState('')
  const [publicExponent, setPublicExponent] = useState('')
  const [modulus, setModulus] = useState('')
  const [encryptErrors, setEncryptErrors] = useState<Errors>({})
  const [encryptError, setEncryptError] = useState<string | null>(null)
  const [encrypted, setEncrypted] = useState<EncryptResult | null>(null)
  const [isEncrypting, setIsEncrypting] = useState(false)
  const encryptId = useRef(0)
  const encryptBlock = useRetryBlock(() => setEncryptError(null))

  // Deszyfrowanie: szyfrogram (liczba albo lista) i klucz prywatny (d, n).
  const [ciphertext, setCiphertext] = useState('')
  const [ciphertexts, setCiphertexts] = useState('')
  const [privateExponent, setPrivateExponent] = useState('')
  const [privateModulus, setPrivateModulus] = useState('')
  const [decryptErrors, setDecryptErrors] = useState<Errors>({})
  const [decryptError, setDecryptError] = useState<string | null>(null)
  const [decrypted, setDecrypted] = useState<DecryptResult | null>(null)
  const [isDecrypting, setIsDecrypting] = useState(false)
  const decryptId = useRef(0)
  // Rośnie przy każdej ręcznej zmianie i próbie deszyfrowania – po nim widać, czy
  // w trakcie szyfrowania ktoś pracował w panelu deszyfrowania.
  const decryptTouched = useRef(0)
  const decryptBlock = useRetryBlock(() => setDecryptError(null))

  // Unieważnia trwające żądanie danej strony cyklu, żeby spóźniona odpowiedź nie
  // nadpisała nowszych danych. Komunikat blokady Retry-After zostaje do jej końca
  // (jak przy losowaniu parametrów, #114) – wyjaśnia, czemu przycisk jest wyłączony.
  function stopEncryption() {
    encryptId.current += 1
    setIsEncrypting(false)
    if (!encryptBlock.blocked) setEncryptError(null)
  }

  function stopDecryption() {
    decryptId.current += 1
    setIsDecrypting(false)
    if (!decryptBlock.blocked) setDecryptError(null)
  }

  // Jak wyżej, a do tego usuwa stary wynik (nowy klucz, zmiana trybu).
  function clearEncryption() {
    stopEncryption()
    setEncrypted(null)
  }

  function clearDecryption() {
    stopDecryption()
    setDecrypted(null)
  }

  // Ręczna edycja pola ma pierwszeństwo przed trwającym żądaniem.
  function editEncryption(set: (value: string) => void) {
    return (value: string) => {
      stopEncryption()
      set(value)
    }
  }

  function editDecryption(set: (value: string) => void) {
    return (value: string) => {
      decryptTouched.current += 1
      stopDecryption()
      set(value)
    }
  }

  useImperativeHandle(ref, () => ({
    applyPublicKey(key) {
      setPublicExponent(String(key.e))
      setModulus(String(key.n))
      clearEncryption()
      setEncryptErrors(({ message, text }) => ({ message, text }))
    },
    applyPrivateKey(key) {
      setPrivateExponent(String(key.d))
      setPrivateModulus(String(key.n))
      clearDecryption()
      setDecryptErrors(({ ciphertext, ciphertexts }) => ({ ciphertext, ciphertexts }))
    },
  }))

  function changeMode(next: Mode) {
    setMode(next)
    clearEncryption()
    clearDecryption()
    setEncryptErrors({})
    setDecryptErrors({})
  }

  async function handleEncrypt(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (isEncrypting || encryptBlock.blocked) return
    const id = ++encryptId.current
    const touched = decryptTouched.current
    setEncryptError(null)
    setEncrypted(null)

    const validation =
      mode === 'number'
        ? validateRsaInput({ message, public_exponent: publicExponent, modulus })
        : validateRsaTextInput({ text, public_exponent: publicExponent, modulus })
    if (!validation.ok) {
      setEncryptErrors(validation.errors)
      return
    }
    setEncryptErrors({})

    setIsEncrypting(true)
    try {
      let result: EncryptResult
      if ('text' in validation.data) {
        const request = validation.data
        result = { kind: 'text', request, ciphertexts: await encryptRsaText(request) }
      } else {
        const request = validation.data
        result = { kind: 'number', request, ciphertext: (await encryptRsa(request)).ciphertext }
      }
      if (id !== encryptId.current) return
      setEncrypted(result)
      // Szyfrogram od razu czeka w polu deszyfrowania – bez ręcznego przepisywania.
      // Jeśli w trakcie szyfrowania ktoś pracował w panelu deszyfrowania, zostawiamy
      // jego dane w spokoju.
      if (decryptTouched.current !== touched) return
      clearDecryption()
      if (result.kind === 'number') {
        setCiphertext(String(result.ciphertext))
        setDecryptErrors((errors) => ({ ...errors, ciphertext: undefined }))
      } else {
        setCiphertexts(result.ciphertexts.join(', '))
        setDecryptErrors((errors) => ({ ...errors, ciphertexts: undefined }))
      }
    } catch (error) {
      if (id !== encryptId.current) return
      setEncryptError(errorMessage(error))
      encryptBlock.blockFor(error)
    } finally {
      if (id === encryptId.current) setIsEncrypting(false)
    }
  }

  async function handleDecrypt(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (isDecrypting || decryptBlock.blocked) return
    const id = ++decryptId.current
    decryptTouched.current += 1
    setDecryptError(null)
    setDecrypted(null)

    const key = { private_exponent: privateExponent, private_modulus: privateModulus }
    const validation =
      mode === 'number'
        ? validateRsaDecryptInput({ ciphertext, ...key })
        : validateRsaTextDecryptInput({ ciphertexts, ...key })
    if (!validation.ok) {
      setDecryptErrors(validation.errors)
      return
    }
    setDecryptErrors({})

    setIsDecrypting(true)
    try {
      let result: DecryptResult
      if ('ciphertexts' in validation.data) {
        const request = validation.data
        result = { kind: 'text', request, text: await decryptRsaText(request) }
      } else {
        const request = validation.data
        result = { kind: 'number', request, message: await decryptRsa(request) }
      }
      if (id !== decryptId.current) return
      setDecrypted(result)
    } catch (error) {
      if (id !== decryptId.current) return
      setDecryptError(errorMessage(error))
      decryptBlock.blockFor(error)
    } finally {
      if (id === decryptId.current) setIsDecrypting(false)
    }
  }

  const textBytes = utf8Length(text)

  return (
    <section className="panel rsa-cycle" aria-labelledby="rsa-cycle-title">
      <h2 id="rsa-cycle-title">Szyfrowanie i deszyfrowanie</h2>

      {/* Tryb obowiązuje obie strony cyklu; w trakcie obliczeń się go nie zmienia. */}
      <fieldset className="rsa-mode" disabled={isEncrypting || isDecrypting}>
        <legend>Tryb</legend>
        {(['number', 'text'] as const).map((value) => (
          <label key={value}>
            <input
              type="radio"
              name="rsa-mode"
              value={value}
              checked={mode === value}
              onChange={() => changeMode(value)}
            />
            {MODE_LABEL[value]}
          </label>
        ))}
      </fieldset>

      {/* noValidate: walidację robimy sami, z polskimi komunikatami. */}
      <form className="rsa-step" onSubmit={handleEncrypt} noValidate aria-labelledby="rsa-encrypt-title">
        <h3 id="rsa-encrypt-title">Szyfrowanie</h3>
        {mode === 'number' ? (
          <Field
            name="message"
            label="Wiadomość (m)"
            error={encryptErrors.message}
            value={message}
            onChange={editEncryption(setMessage)}
          />
        ) : (
          <TextArea
            name="text"
            label="Tekst"
            error={encryptErrors.text}
            hint={`${textBytes} / ${RSA_TEXT_MAX_BYTES} bajtów UTF-8`}
            value={text}
            onChange={editEncryption(setText)}
          />
        )}
        <Field
          name="public_exponent"
          label="Wykładnik publiczny (e)"
          error={encryptErrors.public_exponent}
          value={publicExponent}
          onChange={editEncryption(setPublicExponent)}
        />
        <Field
          name="modulus"
          label="Moduł (n)"
          error={encryptErrors.modulus}
          value={modulus}
          onChange={editEncryption(setModulus)}
        />

        <Button type="submit" busy={isEncrypting} busyLabel="Szyfrowanie…" disabled={encryptBlock.blocked}>
          Szyfruj
        </Button>

        {encrypted && <EncryptResultView result={encrypted} />}
        {encryptError && <Notice tone="error">{encryptError}</Notice>}
      </form>

      <form className="rsa-step" onSubmit={handleDecrypt} noValidate aria-labelledby="rsa-decrypt-title">
        <h3 id="rsa-decrypt-title">Deszyfrowanie</h3>
        {mode === 'number' ? (
          <Field
            name="ciphertext"
            label="Szyfrogram (c)"
            error={decryptErrors.ciphertext}
            value={ciphertext}
            onChange={editDecryption(setCiphertext)}
          />
        ) : (
          <TextArea
            name="ciphertexts"
            label="Szyfrogramy (c₁, c₂, …)"
            error={decryptErrors.ciphertexts}
            hint="Liczby oddzielone przecinkami lub spacjami, po jednej na bajt."
            value={ciphertexts}
            onChange={editDecryption(setCiphertexts)}
          />
        )}
        <Field
          name="private_exponent"
          label="Wykładnik prywatny (d)"
          error={decryptErrors.private_exponent}
          value={privateExponent}
          onChange={editDecryption(setPrivateExponent)}
        />
        <Field
          name="private_modulus"
          label="Moduł (n)"
          error={decryptErrors.private_modulus}
          value={privateModulus}
          onChange={editDecryption(setPrivateModulus)}
        />

        <Button type="submit" busy={isDecrypting} busyLabel="Deszyfrowanie…" disabled={decryptBlock.blocked}>
          Odszyfruj
        </Button>

        {decrypted && <DecryptResultView result={decrypted} />}
        {decryptError && <Notice tone="error">{decryptError}</Notice>}
      </form>

      <Notice tone="warning">
        To edukacyjne RSA bez paddingu (textbook RSA). Te same bajty dają zawsze te same
        szyfrogramy – w „HELLO” oba „L” wyglądają tak samo – więc szyfrogram zdradza budowę
        tekstu. Prawdziwe RSA używa paddingu (np. OAEP) i kluczy co najmniej 2048-bitowych.
      </Notice>
    </section>
  )
}

function EncryptResultView({ result }: { result: EncryptResult }) {
  if (result.kind === 'number') {
    const { request } = result
    return (
      <div className="result result--ok" role="status">
        <h4>Szyfrogram</h4>
        <p className="formula">
          c = m<sup>e</sup> mod n
        </p>
        <p className="formula">
          c = {request.message}
          <sup>{request.public_exponent}</sup> mod {request.modulus} ={' '}
          <output>{result.ciphertext}</output>
        </p>
      </div>
    )
  }
  const { request, ciphertexts } = result
  return (
    <div className="result result--ok" role="status">
      <h4>Szyfrogram</h4>
      <p>
        „{request.text}” → {plural(ciphertexts.length, 'bajt', 'bajty', 'bajtów')} UTF-8 →{' '}
        {plural(ciphertexts.length, 'szyfrogram', 'szyfrogramy', 'szyfrogramów')}
      </p>
      <p className="formula">
        c<sub>i</sub> = m<sub>i</sub>
        <sup>e</sup> mod n, <span className="rsa-nowrap">e = {request.public_exponent},</span>{' '}
        <span className="rsa-nowrap">n = {request.modulus}</span>
      </p>
      <ByteTable text={request.text} ciphertexts={ciphertexts} direction="encrypt" />
    </div>
  )
}

function DecryptResultView({ result }: { result: DecryptResult }) {
  if (result.kind === 'number') {
    const { request } = result
    return (
      <div className="result result--ok" role="status">
        <h4>Odzyskana wiadomość</h4>
        <p className="formula">
          m = c<sup>d</sup> mod n
        </p>
        <p className="formula">
          m = {request.ciphertext}
          <sup>{request.private_exponent}</sup> mod {request.modulus} ={' '}
          <output>{result.message}</output>
        </p>
      </div>
    )
  }
  const { request, text } = result
  return (
    <div className="result result--ok" role="status">
      <h4>Odzyskany tekst</h4>
      <p className="formula">
        m<sub>i</sub> = c<sub>i</sub>
        <sup>d</sup> mod n, <span className="rsa-nowrap">d = {request.private_exponent},</span>{' '}
        <span className="rsa-nowrap">n = {request.modulus}</span>
      </p>
      <ByteTable text={text} ciphertexts={request.ciphertexts} direction="decrypt" />
      <p>
        Tekst: „<output>{text}</output>”
      </p>
    </div>
  )
}

// Tabela znak → bajty UTF-8 → szyfrogramy (przy deszyfrowaniu w odwrotnej kolejności).
// Jeden wiersz to jeden znak; znak spoza ASCII zajmuje kilka bajtów, więc ma kilka
// szyfrogramów. Bajty po deszyfrowaniu to bajty odzyskanego tekstu – backend dekoduje
// UTF-8 ściśle, więc ich liczba zawsze zgadza się z liczbą szyfrogramów.
function ByteTable({
  text,
  ciphertexts,
  direction,
}: {
  text: string
  ciphertexts: number[]
  direction: 'encrypt' | 'decrypt'
}) {
  const rows = byteRows(text, ciphertexts)
  const columns =
    direction === 'encrypt'
      ? ['Znak', 'Bajty UTF-8 (m)', 'Szyfrogram (c)']
      : ['Szyfrogram (c)', 'Bajty UTF-8 (m)', 'Znak']

  return (
    <div className="rsa-bytes" role="region" tabIndex={0} aria-label="Bajty i szyfrogramy">
      <table>
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column} scope="col">
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => {
            const cells = [
              <td key="char" className="rsa-char">
                {visibleChar(row.char)}
              </td>,
              <td key="bytes">{row.bytes.join(' ')}</td>,
              <td key="cipher">{row.ciphertexts.join(' ')}</td>,
            ]
            return <tr key={index}>{direction === 'encrypt' ? cells : cells.reverse()}</tr>
          })}
        </tbody>
      </table>
    </div>
  )
}

// Dzieli tekst na znaki i przypisuje każdemu jego bajty UTF-8 oraz ich szyfrogramy.
function byteRows(text: string, ciphertexts: number[]) {
  const encoder = new TextEncoder()
  const rows: { char: string; bytes: number[]; ciphertexts: number[] }[] = []
  let offset = 0
  for (const char of text) {
    const bytes = [...encoder.encode(char)]
    rows.push({ char, bytes, ciphertexts: ciphertexts.slice(offset, offset + bytes.length) })
    offset += bytes.length
  }
  return rows
}

// Białe i sterujące znaki pokazujemy symbolem, żeby wiersz nie był pusty.
function visibleChar(char: string): string {
  if (char === ' ') return '␣'
  if (char === '\n') return '↵'
  if (char === '\t') return '⇥'
  const code = char.codePointAt(0) ?? 0
  if (code < 0x20 || code === 0x7f) return `U+${code.toString(16).toUpperCase().padStart(4, '0')}`
  return char
}

// 1 bajt, 2 bajty, 5 bajtów, 22 bajty, 12 bajtów.
function plural(count: number, one: string, few: string, many: string): string {
  const tens = count % 100
  const units = count % 10
  const word =
    count === 1 ? one : units >= 2 && units <= 4 && (tens < 12 || tens > 14) ? few : many
  return `${count} ${word}`
}

function errorMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : 'Wystąpił nieoczekiwany błąd.'
}

// Po 429/503 z Retry-After przycisk czeka podany czas, żeby nie dokładać odrzucanych
// prób. Po końcu blokady komunikat z czasem („za N s”) jest już nieaktualny.
function useRetryBlock(onEnd: () => void) {
  const [blocked, setBlocked] = useState(false)
  const timer = useRef<number | undefined>(undefined)
  useEffect(() => () => window.clearTimeout(timer.current), [])

  function blockFor(error: unknown) {
    if (!(error instanceof ApiError) || error.retryAfter <= 0) return
    if (error.status !== 429 && error.status !== 503) return
    window.clearTimeout(timer.current)
    setBlocked(true)
    timer.current = window.setTimeout(() => {
      setBlocked(false)
      onEnd()
    }, error.retryAfter * 1000)
  }

  return { blocked, blockFor }
}

// Wieloliniowe pole tekstowe z etykietą, podpowiedzią i komunikatem błędu.
function TextArea({
  name,
  label,
  error,
  hint,
  value,
  onChange,
}: {
  name: string
  label: string
  error?: string
  hint?: string
  value: string
  onChange: (value: string) => void
}) {
  const hintId = `${name}-hint`
  const errorId = `${name}-error`
  const describedBy = [hint && hintId, error && errorId].filter(Boolean).join(' ')
  // Podpowiedź i błąd leżą poza <label>, żeby nie weszły do nazwy pola.
  return (
    <div className="rsa-textarea">
      <label>
        {label}
        <textarea
          name={name}
          rows={3}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy || undefined}
        />
      </label>
      {hint && (
        <span className="hint" id={hintId}>
          {hint}
        </span>
      )}
      {error && (
        <span className="field-error" id={errorId}>
          {error}
        </span>
      )}
    </div>
  )
}