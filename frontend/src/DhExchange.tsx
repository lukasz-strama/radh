// Widok wymiany kluczy Diffiego–Hellmana (PBI-010, #14).
// Frontend niczego nie liczy: wyświetla wartości, które dostaje.

import { useState } from 'react'
import type { ReactNode } from 'react'

type Party = 'alice' | 'bob'

// Wartości jednej strony wymiany.
export type DhPartyData = {
  privateKey: number
  publicValue: number
  sharedSecret: number
}

export type DhExchangeData = {
  p: number
  g: number
  alice: DhPartyData
  bob: DhPartyData
}

// Nazwa strony i symbole używane we wzorach (Alice: a, A; Bob: b, B).
const PARTIES: Record<Party, { name: string; priv: string; pub: string; other: Party }> = {
  alice: { name: 'Alice', priv: 'a', pub: 'A', other: 'bob' },
  bob: { name: 'Bob', priv: 'b', pub: 'B', other: 'alice' },
}

// Etapy wymiany w kolejności wyświetlania.
const STEPS = [
  {
    title: 'Parametry wspólne',
    description:
      'Alice i Bob jawnie uzgadniają liczbę pierwszą p i generator g. Może je znać każdy, także podsłuchujący.',
  },
  {
    title: 'Klucze prywatne',
    description:
      'Każda strona losuje swój klucz prywatny: Alice a, Bob b. Nikomu go nie wysyłają.',
  },
  {
    title: 'Wartości publiczne',
    description:
      'Każda strona podnosi g do potęgi swojego klucza prywatnego modulo p. Wynik, A albo B, można pokazać wszystkim.',
  },
  {
    title: 'Wymiana',
    description:
      'Alice wysyła A do Boba, a Bob wysyła B do Alice przez kanał publiczny. Podsłuchujący widzi obie wartości.',
  },
  {
    title: 'Wspólny sekret',
    description:
      'Każda strona podnosi otrzymaną wartość do potęgi swojego klucza prywatnego. Obu wychodzi to samo K, bo (gᵇ)ᵃ = (gᵃ)ᵇ mod p.',
  },
]

// Od którego etapu (indeks w STEPS) widać daną wartość.
const STEP_PRIVATE = 1
const STEP_PUBLIC = 2
const STEP_EXCHANGE = 3
const STEP_SECRET = 4

// Stan danych do wizualizacji. Przy błędzie nie pokazujemy żadnych wartości,
// żeby nie wyświetlić niepoprawnego wyniku.
export type DhState =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; data: DhExchangeData }

type DhExchangeProps = {
  state: DhState
  onRetry?: () => void
}

export function DhExchange({ state, onRetry }: DhExchangeProps) {
  return (
    <div className="dh">
      <h1>RADH – wymiana kluczy Diffiego–Hellmana</h1>

      {state.status === 'loading' && (
        <p className="dh-status" role="status">
          Pobieranie danych z backendu…
        </p>
      )}

      {state.status === 'error' && (
        <div className="api-error dh-error" role="alert">
          <p>{state.message}</p>
          {onRetry && (
            <button type="button" onClick={onRetry}>
              Spróbuj ponownie
            </button>
          )}
        </div>
      )}

      {/* Nowe dane montują wizualizację od nowa, więc etapy zaczynają się od 1 */}
      {state.status === 'ready' && <DhWalkthrough data={state.data} />}
    </div>
  )
}

type DhWalkthroughProps = {
  data: DhExchangeData
}

// Wizualizacja z panelem etapów.
function DhWalkthrough({ data }: DhWalkthroughProps) {
  const [step, setStep] = useState(0)
  const isLast = step === STEPS.length - 1

  return (
    <div className="layout">
      <section className="dh-scene" aria-label="Wizualizacja wymiany">
        {/* Parametry znane obu stronom (i każdemu, kto podsłuchuje) */}
        <section className="dh-shared" aria-labelledby="dh-shared-title">
          <h2 id="dh-shared-title">Parametry wspólne</h2>
          <p className="formula">
            p = <output>{data.p}</output>
          </p>
          <p className="formula">
            g = <output>{data.g}</output>
          </p>
        </section>

        <div className="dh-parties">
          <PartyPanel party="alice" data={data} step={step} />

          {/* Kanał publiczny: na etapie wymiany pokazuje przesyłane A i B */}
          <div className="dh-channel">
            <span className="dh-channel-label">kanał publiczny</span>
            {step >= STEP_EXCHANGE && (
              <>
                <Packet from="alice" value={data.alice.publicValue} />
                <Packet from="bob" value={data.bob.publicValue} />
              </>
            )}
          </div>

          <PartyPanel party="bob" data={data} step={step} />
        </div>
      </section>

      {/* Panel sterowania krokami */}
      <aside className="panel dh-controls" aria-label="Sterowanie etapami">
        <div aria-live="polite">
          <p className="dh-step-counter">
            Krok {step + 1} z {STEPS.length}
          </p>
          <h2>{STEPS[step].title}</h2>
          <p>{STEPS[step].description}</p>
        </div>

        <div className="dh-step-buttons">
          <button type="button" onClick={() => setStep(step - 1)} disabled={step === 0}>
            Wstecz
          </button>
          <button type="button" onClick={() => setStep(step + 1)} disabled={isLast}>
            Dalej
          </button>
        </div>
      </aside>
    </div>
  )
}

type PartyPanelProps = {
  party: Party
  data: DhExchangeData
  step: number
}

// Panel jednej strony wymiany: klucz prywatny, wartość publiczna, wspólny sekret.
function PartyPanel({ party, data, step }: PartyPanelProps) {
  const { name, priv, pub, other } = PARTIES[party]
  const own = data[party]
  const received = data[other].publicValue
  const otherPub = PARTIES[other].pub
  const titleId = `dh-${party}-title`

  return (
    <section className={`dh-party dh-party--${party}`} aria-labelledby={titleId}>
      <h2 id={titleId}>{name}</h2>

      <DhValue
        kind="private"
        label="Klucz prywatny"
        symbol={priv}
        visible={step >= STEP_PRIVATE}
      >
        {priv} = <output>{own.privateKey}</output>
      </DhValue>

      <DhValue
        kind="public"
        label="Wartość publiczna"
        symbol={pub}
        visible={step >= STEP_PUBLIC}
      >
        {pub} = g<sup>{priv}</sup> mod p = {data.g}
        <sup>{own.privateKey}</sup> mod {data.p} = <output>{own.publicValue}</output>
      </DhValue>

      <DhValue kind="private" label="Wspólny sekret" symbol="K" visible={step >= STEP_SECRET}>
        K = {otherPub}
        <sup>{priv}</sup> mod p = {received}
        <sup>{own.privateKey}</sup> mod {data.p} = <output>{own.sharedSecret}</output>
      </DhValue>
    </section>
  )
}

type DhValueProps = {
  kind: 'private' | 'public'
  label: string
  symbol: string
  visible: boolean
  children: ReactNode
}

// Jedna wartość z oznaczeniem, czy jest tajna, czy jawna.
// Przed swoim etapem pokazuje tylko „symbol = ?”, żeby układ nie skakał.
function DhValue({ kind, label, symbol, visible, children }: DhValueProps) {
  return (
    <div className={`dh-value dh-value--${kind}${visible ? '' : ' dh-value--pending'}`}>
      <div className="dh-value-header">
        <span>{label}</span>
        <span className="dh-value-badge">{kind === 'private' ? 'tajne' : 'jawne'}</span>
      </div>
      <p className="formula">{visible ? children : `${symbol} = ?`}</p>
    </div>
  )
}

type PacketProps = {
  from: Party
  value: number
}

// Wartość publiczna w drodze do drugiej strony.
// Strzałki: poziome obok siebie, pionowe w układzie jeden pod drugim (CSS).
function Packet({ from, value }: PacketProps) {
  const { name, pub, other } = PARTIES[from]
  const toBob = from === 'alice'
  return (
    <span
      className={`dh-packet dh-packet--${from}`}
      aria-label={`${pub} = ${value}, od ${name} do ${PARTIES[other].name}`}
    >
      {!toBob && <Arrow horizontal="←" vertical="↑" />}
      <span className="formula">
        {pub} = {value}
      </span>
      {toBob && <Arrow horizontal="→" vertical="↓" />}
    </span>
  )
}

function Arrow({ horizontal, vertical }: { horizontal: string; vertical: string }) {
  return (
    <span aria-hidden="true">
      <span className="dh-arrow-h">{horizontal}</span>
      <span className="dh-arrow-v">{vertical}</span>
    </span>
  )
}