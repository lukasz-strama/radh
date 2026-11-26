// Generowanie pary kluczy RSA krok po kroku (#106): p, q → n → φ(n) → e → d → klucze.
//
// Wszystkie wyniki (n, φ(n), d) pochodzą z odpowiedzi backendu (CryptoCore); tutaj
// tylko podstawiamy liczby do wzorów. Jedyne działanie liczone w przeglądarce to
// sprawdzenie e · d = k · φ(n) + 1 – pokazuje, że d z backendu spełnia definicję,
// i nie zastępuje algorytmu (d wyznacza backend rozszerzonym algorytmem Euklidesa).

import type { ReactNode } from 'react'
import { DataBadge } from './ui'
import type { DataKind } from './ui'

// Para kluczy z backendu razem z parametrami, które faktycznie zostały wysłane,
// i informacją, skąd te parametry pochodziły.
export type RsaKeys = {
  p: number
  q: number
  e: number
  n: number
  phi: number
  d: number
  source: 'manual' | 'drawn'
}

// Teksty kroków w jednym miejscu, żeby łatwo było je poprawić merytorycznie.
const STEP_TEXT = {
  primes:
    'Dwie różne liczby pierwsze. Zostają tajne: kto zna p i q, policzy φ(n), a z niego d.',
  modulus:
    'Moduł obu kluczy, jawny. Bezpieczeństwo RSA opiera się na tym, że trudno rozłożyć n ' +
    'z powrotem na p i q – przy 32 bitach zajmuje to jednak ułamek sekundy.',
  phi:
    'Liczba liczb od 1 do n względnie pierwszych z n. Jest tajna, bo pozwala wyznaczyć d.',
  exponent:
    'Wykładnik publiczny. Musi być względnie pierwszy z φ(n), inaczej d by nie istniało. ' +
    'Warunek sprawdził backend.',
  privateExponent:
    'Wykładnik prywatny: odwrotność e modulo φ(n), czyli liczba, dla której e · d daje ' +
    'resztę 1 z dzielenia przez φ(n). Wyznacza ją backend.',
  keys:
    'Klucz publiczny (n, e) można dać każdemu – służy do szyfrowania. Klucz prywatny ' +
    '(n, d) zostaje u właściciela – służy do deszyfrowania.',
} as const

const SOURCE_LABEL: Record<RsaKeys['source'], string> = {
  manual: 'wpisane ręcznie',
  drawn: 'wylosowane',
}

// Bez wyniku w miejscu wartości jest „?”, a wzory zostają bez podstawionych liczb.
export function RsaKeySteps({ keys }: { keys: RsaKeys | null }) {
  const show = (value: number | undefined) => (value === undefined ? '?' : String(value))

  return (
    <ol className="result rsa-keys" aria-label="Kroki generowania kluczy">
      <Step
        title="Liczby pierwsze p i q"
        kind="private"
        value={<span>{keys ? `${keys.p}, ${keys.q}` : '?'}</span>}
        text={STEP_TEXT.primes}
      >
        {keys && <p className="rsa-key-step-source">Parametry {SOURCE_LABEL[keys.source]}.</p>}
      </Step>

      <Step title="Moduł n" kind="public" value={<output>{show(keys?.n)}</output>} text={STEP_TEXT.modulus}>
        <p className="formula">
          n = p · q
          {keys && (
            <>
              {' '}
              = <span className="rsa-nowrap">{keys.p} · {keys.q}</span>
            </>
          )}
        </p>
      </Step>

      <Step
        title="Funkcja Eulera φ(n)"
        kind="private"
        value={<output>{show(keys?.phi)}</output>}
        text={STEP_TEXT.phi}
      >
        <p className="formula">
          φ(n) = (p − 1)(q − 1)
          {keys && (
            <>
              {' '}
              = <span className="rsa-nowrap">{keys.p - 1} · {keys.q - 1}</span>
            </>
          )}
        </p>
      </Step>

      <Step title="Wykładnik publiczny e" kind="public" value={<span>{show(keys?.e)}</span>} text={STEP_TEXT.exponent}>
        <p className="formula">1 &lt; e &lt; φ(n), NWD(e, φ(n)) = 1</p>
        {keys && (
          <p className="formula">
            NWD({keys.e}, {keys.phi}) = 1
          </p>
        )}
      </Step>

      <Step
        title="Wykładnik prywatny d"
        kind="private"
        value={<output>{show(keys?.d)}</output>}
        text={STEP_TEXT.privateExponent}
      >
        <p className="formula">
          d = e<sup>−1</sup> mod φ(n), czyli e · d ≡ 1 (mod φ(n))
        </p>
        {keys && <InverseCheck keys={keys} />}
      </Step>

      <li className="rsa-key-step">
        <h3 className="rsa-key-step-title">Para kluczy</h3>
        <dl className="rsa-key-pair">
          <div>
            <dt>
              Klucz publiczny (n, e) <DataBadge kind="public" />
            </dt>
            <dd>
              <output>{`(${show(keys?.n)}, ${show(keys?.e)})`}</output>
            </dd>
          </div>
          <div>
            <dt>
              Klucz prywatny (n, d) <DataBadge kind="private" />
            </dt>
            <dd>
              <output>{`(${show(keys?.n)}, ${show(keys?.d)})`}</output>
            </dd>
          </div>
        </dl>
        <p className="rsa-key-step-text">{STEP_TEXT.keys}</p>
      </li>
    </ol>
  )
}

function Step({
  title,
  kind,
  value,
  text,
  children,
}: {
  title: string
  kind: DataKind
  value: ReactNode
  text: string
  children?: ReactNode
}) {
  return (
    <li className="rsa-key-step">
      <div className="rsa-key-step-head">
        <h3 className="rsa-key-step-title">
          {title} <DataBadge kind={kind} />
        </h3>
        <span className="rsa-key-step-value">{value}</span>
      </div>
      {children}
      <p className="rsa-key-step-text">{text}</p>
    </li>
  )
}

// e · d = k · φ(n) + 1 – iloczyn może przekroczyć 2^53, więc liczymy na BigInt.
function InverseCheck({ keys }: { keys: RsaKeys }) {
  const product = BigInt(keys.e) * BigInt(keys.d)
  const phi = BigInt(keys.phi)
  const quotient = product / phi
  const remainder = product % phi
  return (
    <p className="formula">
      e · d = <span className="rsa-nowrap">{keys.e} · {keys.d}</span> ={' '}
      <span className="rsa-nowrap">{product.toString()}</span> ={' '}
      <span className="rsa-nowrap">
        {quotient.toString()} · {keys.phi} + {remainder.toString()}
      </span>
    </p>
  )
}