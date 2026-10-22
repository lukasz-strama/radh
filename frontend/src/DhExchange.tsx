// Widok wymiany kluczy Diffiego–Hellmana (PBI-010, #14).
// Frontend niczego nie liczy: wysyła parametry do backendu i wyświetla odpowiedź.

import { useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { ApiError, exchangeDh } from './api'
import { Field } from './Field'
import { validateDhInput } from './validation'
import type { DhField, DhFieldErrors } from './validation'

type Party = 'alice' | 'bob'

// Wartości jednej strony wymiany.
type DhPartyData = {
  privateKey: number
  publicValue: number
  sharedSecret: number
}

type DhExchangeData = {
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

// Stan zakładki. Przy błędzie nie pokazujemy żadnych wartości,
// żeby nie wyświetlić niepoprawnego wyniku.
type DhState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; data: DhExchangeData }

// Wartości startowe formularza: przykład z kryteriów akceptacji #14.
const DEFAULTS: Record<DhField, string> = {
  prime: '23',
  generator: '5',
  alice_secret: '6',
  bob_secret: '15',
}

export function DhExchange() {
  const [fieldErrors, setFieldErrors] = useState<DhFieldErrors>({})
  const [state, setState] = useState<DhState>({ status: 'idle' })
  const [step, setStep] = useState(0)
  const isLoading = state.status === 'loading'
  const isLast = step === STEPS.length - 1

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (isLoading) return
    setState({ status: 'idle' })

    // Zbieramy wartości z pól formularza (po atrybucie `name`).
    const form = new FormData(event.currentTarget)
    const validation = validateDhInput({
      prime: String(form.get('prime') ?? ''),
      generator: String(form.get('generator') ?? ''),
      alice_secret: String(form.get('alice_secret') ?? ''),
      bob_secret: String(form.get('bob_secret') ?? ''),
    })

    if (!validation.ok) {
      setFieldErrors(validation.errors)
      return
    }
    setFieldErrors({})

    // Stary wynik znika od razu, żeby nie mieszał się z nowymi parametrami.
    setState({ status: 'loading' })
    try {
      const request = validation.data
      const response = await exchangeDh(request)
      // p, g i sekrety pochodzą z wysłanego żądania, reszta wyłącznie z backendu.
      setState({
        status: 'ready',
        data: {
          p: request.prime,
          g: request.generator,
          alice: {
            privateKey: request.alice_secret,
            publicValue: response.alice_public,
            sharedSecret: response.alice_shared_key,
          },
          bob: {
            privateKey: request.bob_secret,
            publicValue: response.bob_public,
            sharedSecret: response.bob_shared_key,
          },
        },
      })
      setStep(0)
    } catch (error) {
      setState({
        status: 'error',
        message: error instanceof ApiError ? error.message : 'Wystąpił nieoczekiwany błąd.',
      })
    }
  }

  return (
    <div className="dh">
      <h1>RADH – wymiana kluczy Diffiego–Hellmana</h1>

      <div className="layout">
        <section className="dh-scene" aria-label="Wizualizacja wymiany">
          {state.status === 'ready' ? (
            <DhVisualization data={state.data} step={step} />
          ) : (
            <p className="dh-placeholder">
              {isLoading
                ? 'Obliczanie…'
                : 'Podaj parametry i kliknij „Oblicz”, aby zobaczyć wymianę kluczy.'}
            </p>
          )}
        </section>

        <aside className="panel" aria-label="Parametry i etapy">
          {/* noValidate: walidację robimy sami, z polskimi komunikatami. */}
          <form className="dh-form" onSubmit={handleSubmit} noValidate>
            <Field
              name="prime"
              label="Liczba pierwsza (p)"
              error={fieldErrors.prime}
              defaultValue={DEFAULTS.prime}
            />
            <Field
              name="generator"
              label="Generator (g)"
              error={fieldErrors.generator}
              defaultValue={DEFAULTS.generator}
            />
            <Field
              name="alice_secret"
              label="Klucz prywatny Alice (a)"
              error={fieldErrors.alice_secret}
              defaultValue={DEFAULTS.alice_secret}
            />
            <Field
              name="bob_secret"
              label="Klucz prywatny Boba (b)"
              error={fieldErrors.bob_secret}
              defaultValue={DEFAULTS.bob_secret}
            />

            <button type="submit" disabled={isLoading} aria-busy={isLoading}>
              {isLoading ? 'Obliczanie…' : 'Oblicz'}
            </button>

            {state.status === 'error' && (
              <p className="api-error" role="alert">
                {state.message}
              </p>
            )}
          </form>

          {state.status === 'ready' && (
            <div className="dh-steps">
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
            </div>
          )}
        </aside>
      </div>
    </div>
  )
}

type DhVisualizationProps = {
  data: DhExchangeData
  step: number
}

// Parametry wspólne, panele Alice i Boba oraz kanał publiczny.
function DhVisualization({ data, step }: DhVisualizationProps) {
  return (
    <>
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
    </>
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