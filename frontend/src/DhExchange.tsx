// Laboratorium DH (#38): sesja dwóch niezależnych procesów, Alice i Boba.
// Frontend niczego nie liczy i nie wymyśla zdarzeń: pokazuje stan sesji z API.
// Sekrety a i b nigdy nie przechodzą przez przeglądarkę.

import { useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { Field } from './Field'
import { validateDhParams } from './validation'
import type { DhField, DhFieldErrors } from './validation'

// Uczestnicy sesji. M3: dojdzie 'mallory'.
type Role = 'alice' | 'bob'

// Stan procesu węzła.
type NodeStatus = 'offline' | 'ready' | 'sent' | 'done' | 'error'

type SessionStatus = 'running' | 'completed' | 'failed'

type EventStatus = 'accepted' | 'rejected'

// Stan jednego węzła. Brak wartości = węzeł jeszcze jej nie zgłosił.
type DhNode = {
  status: NodeStatus
  publicValue?: number
  receivedValue?: number
  // Diagnostyka węzła, nie wiadomość protokołu.
  sharedKey?: number
}

// Wiadomość protokołu przekazana przez koordynatora.
type DhEvent = {
  seq: number
  from: Role
  to: Role
  type: string
  value: number
  status: EventStatus
}

type DhSession = {
  id: string
  p: number
  g: number
  status: SessionStatus
  nodes: Record<Role, DhNode>
  events: DhEvent[]
}

// Stan zakładki. Bez sesji nie pokazujemy żadnych wartości, żeby nie zostały stare.
type ViewState =
  | { status: 'empty' }
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'session'; session: DhSession }

// TYMCZASOWO, do czasu API sesji (#37): „Rozpocznij sesję” pokazuje tę przykładową
// sesję dla p = 23, g = 5, a = 6, b = 15. Docelowo stan i zdarzenia przyjdą z API.
const SAMPLE_SESSION: DhSession = {
  id: 'przyklad',
  p: 23,
  g: 5,
  status: 'completed',
  nodes: {
    alice: { status: 'done', publicValue: 8, receivedValue: 19, sharedKey: 2 },
    bob: { status: 'done', publicValue: 19, receivedValue: 8, sharedKey: 2 },
  },
  events: [
    { seq: 1, from: 'alice', to: 'bob', type: 'PUBLIC_VALUE', value: 8, status: 'accepted' },
    { seq: 2, from: 'bob', to: 'alice', type: 'PUBLIC_VALUE', value: 19, status: 'accepted' },
  ],
}

// Nazwa uczestnika (też w dopełniaczu) i symbole we wzorach (Alice: a, A; Bob: b, B).
const ROLES: Record<
  Role,
  { name: string; nameOf: string; priv: string; pub: string; other: Role }
> = {
  alice: { name: 'Alice', nameOf: 'Alice', priv: 'a', pub: 'A', other: 'bob' },
  bob: { name: 'Bob', nameOf: 'Boba', priv: 'b', pub: 'B', other: 'alice' },
}

type Tone = 'neutral' | 'ok' | 'error'

const NODE_STATUS: Record<NodeStatus, { label: string; tone: Tone }> = {
  offline: { label: 'niedostępny', tone: 'error' },
  ready: { label: 'gotowy', tone: 'neutral' },
  sent: { label: 'wysłał wartość publiczną', tone: 'neutral' },
  done: { label: 'obliczył sekret', tone: 'ok' },
  error: { label: 'błąd', tone: 'error' },
}

const SESSION_STATUS: Record<SessionStatus, { label: string; tone: Tone }> = {
  running: { label: 'w toku', tone: 'neutral' },
  completed: { label: 'zakończona', tone: 'ok' },
  failed: { label: 'nieudana', tone: 'error' },
}

const EVENT_STATUS: Record<EventStatus, { label: string; tone: Tone }> = {
  accepted: { label: 'przyjęta', tone: 'ok' },
  rejected: { label: 'odrzucona', tone: 'error' },
}

const DEFAULTS: Record<DhField, string> = {
  prime: '23',
  generator: '5',
}

export function DhExchange() {
  const [fieldErrors, setFieldErrors] = useState<DhFieldErrors>({})
  const [view, setView] = useState<ViewState>({ status: 'empty' })
  const isLoading = view.status === 'loading'

  function handleStart(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (isLoading) return
    setView({ status: 'empty' })

    const form = new FormData(event.currentTarget)
    const validation = validateDhParams({
      prime: String(form.get('prime') ?? ''),
      generator: String(form.get('generator') ?? ''),
    })

    if (!validation.ok) {
      setFieldErrors(validation.errors)
      return
    }
    setFieldErrors({})

    // TYMCZASOWO: zamiast rozpoczęcia sesji przez API.
    setView({ status: 'session', session: SAMPLE_SESSION })
  }

  function handleReset() {
    setFieldErrors({})
    setView({ status: 'empty' })
  }

  return (
    <div className="dh">
      <h1>RADH – wymiana kluczy Diffiego–Hellmana</h1>

      <div className="layout">
        <section className="dh-scene" aria-label="Przebieg sesji">
          {view.status === 'session' ? (
            <SessionView session={view.session} />
          ) : (
            <p className="dh-placeholder">
              {isLoading
                ? 'Uruchamianie sesji…'
                : 'Podaj parametry publiczne i kliknij „Rozpocznij sesję”.'}
            </p>
          )}
        </section>

        <aside className="panel" aria-label="Parametry sesji">
          {/* noValidate: walidację robimy sami, z polskimi komunikatami. */}
          <form className="dh-form" onSubmit={handleStart} noValidate>
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
            <p className="dh-note">
              Klucze prywatne losują procesy Alice i Boba. Przeglądarka ich nie zna.
            </p>

            <div className="dh-buttons">
              <button type="submit" disabled={isLoading} aria-busy={isLoading}>
                {isLoading ? 'Uruchamianie…' : 'Rozpocznij sesję'}
              </button>
              <button type="button" onClick={handleReset} disabled={isLoading}>
                Reset
              </button>
            </div>

            {view.status === 'error' && (
              <p className="api-error" role="alert">
                {view.message}
              </p>
            )}
          </form>
        </aside>
      </div>
    </div>
  )
}

// Parametry, węzły, wynik i dziennik jednej sesji.
function SessionView({ session }: { session: DhSession }) {
  const sessionStatus = SESSION_STATUS[session.status]

  return (
    <>
      <section className="dh-shared" aria-labelledby="dh-shared-title">
        <div className="dh-shared-header">
          <h2 id="dh-shared-title">Parametry wspólne</h2>
          <Badge tone={sessionStatus.tone}>sesja {sessionStatus.label}</Badge>
        </div>
        <p className="formula">
          p = <output>{session.p}</output>
        </p>
        <p className="formula">
          g = <output>{session.g}</output>
        </p>
      </section>

      <div className="dh-parties">
        <NodePanel role="alice" session={session} />

        {/* Środek: wiadomości idą przez koordynatora. M3: tu stanie Mallory. */}
        <div className="dh-channel">
          <span className="dh-channel-label">koordynator</span>
        </div>

        <NodePanel role="bob" session={session} />
      </div>

      <SessionResult session={session} />

      <EventLog events={session.events} />
    </>
  )
}

// Panel jednego węzła: status, tajny klucz (bez wartości), wartości publiczne, sekret.
function NodePanel({ role, session }: { role: Role; session: DhSession }) {
  const { name, nameOf, priv, pub, other } = ROLES[role]
  const node = session.nodes[role]
  const status = NODE_STATUS[node.status]
  const otherPub = ROLES[other].pub
  const titleId = `dh-${role}-title`

  return (
    <section className={`dh-party dh-party--${role}`} aria-labelledby={titleId}>
      <div className="dh-party-header">
        <h2 id={titleId}>{name}</h2>
        <Badge tone={status.tone}>{status.label}</Badge>
      </div>

      <DhValue kind="private" label="Klucz prywatny" withValue={false}>
        <span className="formula">{priv}</span> – zna go tylko proces {nameOf}
      </DhValue>

      <DhValue kind="public" label="Wartość publiczna" value={node.publicValue}>
        {pub} = g<sup>{priv}</sup> mod p
      </DhValue>

      <DhValue kind="public" label="Otrzymana wartość" value={node.receivedValue}>
        {otherPub}
      </DhValue>

      <DhValue kind="private" label="Wspólny sekret" value={node.sharedKey}>
        K = {otherPub}
        <sup>{priv}</sup> mod p
      </DhValue>
    </section>
  )
}

type DhValueProps = {
  kind: 'private' | 'public'
  label: string
  // undefined: węzeł jeszcze nie zgłosił wartości (pokazujemy „?”).
  value?: number
  // false: pole bez wartości liczbowej (klucz prywatny).
  withValue?: boolean
  children: ReactNode
}

// Jedna wartość z oznaczeniem, czy jest tajna, czy jawna.
function DhValue({ kind, label, value, withValue = true, children }: DhValueProps) {
  const pending = withValue && value === undefined
  return (
    <div className={`dh-value dh-value--${kind}${pending ? ' dh-value--pending' : ''}`}>
      <div className="dh-value-header">
        <span>{label}</span>
        <span className="dh-value-badge">{kind === 'private' ? 'tajne' : 'jawne'}</span>
      </div>
      <p className={withValue ? 'formula' : undefined}>
        {children}
        {withValue && (
          <>
            {' '}
            = <output>{value ?? '?'}</output>
          </>
        )}
      </p>
    </div>
  )
}

// Porównanie sekretów obu stron. Pokazujemy dopiero, gdy oba węzły je zgłosiły.
function SessionResult({ session }: { session: DhSession }) {
  const kA = session.nodes.alice.sharedKey
  const kB = session.nodes.bob.sharedKey
  if (kA === undefined || kB === undefined) return null

  const match = kA === kB
  return (
    <section
      className={`dh-result dh-result--${match ? 'ok' : 'error'}`}
      aria-labelledby="dh-result-title"
    >
      <h2 id="dh-result-title">
        {match ? 'Sekrety zgodne' : 'Sekrety niezgodne'}
      </h2>
      <p className="formula">
        K<sub>A</sub> = <output>{kA}</output>, K<sub>B</sub> = <output>{kB}</output>
      </p>
      {match && (
        <p>
          Obie strony doszły do tej samej liczby, choć żadna nie poznała klucza
          prywatnego drugiej: B<sup>a</sup> = (g<sup>b</sup>)<sup>a</sup> = g<sup>ab</sup> =
          (g<sup>a</sup>)<sup>b</sup> = A<sup>b</sup> (mod p).
        </p>
      )}
      <p className="dh-note">
        Wartości K pochodzą z diagnostyki węzłów, nie z wiadomości protokołu.
      </p>
    </section>
  )
}

// Uporządkowany dziennik wiadomości przekazanych przez koordynatora.
function EventLog({ events }: { events: DhEvent[] }) {
  return (
    <section className="dh-log" aria-labelledby="dh-log-title">
      <h2 id="dh-log-title">Dziennik wiadomości</h2>
      {events.length === 0 ? (
        <p className="dh-note">Brak wiadomości w tej sesji.</p>
      ) : (
        <div className="dh-log-scroll">
          <table>
            <thead>
              <tr>
                <th scope="col">Nr</th>
                <th scope="col">Nadawca → odbiorca</th>
                <th scope="col">Typ</th>
                <th scope="col">Wartość</th>
                <th scope="col">Status</th>
              </tr>
            </thead>
            <tbody>
              {events.map((event) => {
                const status = EVENT_STATUS[event.status]
                return (
                  <tr key={event.seq}>
                    <td>{event.seq}</td>
                    <td>
                      <span className={`dh-role dh-role--${event.from}`}>
                        {ROLES[event.from].name}
                      </span>{' '}
                      →{' '}
                      <span className={`dh-role dh-role--${event.to}`}>
                        {ROLES[event.to].name}
                      </span>
                    </td>
                    <td className="formula">{event.type}</td>
                    <td className="formula">{event.value}</td>
                    <td>
                      <Badge tone={status.tone}>{status.label}</Badge>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

function Badge({ tone, children }: { tone: Tone; children: ReactNode }) {
  return <span className={`dh-badge dh-badge--${tone}`}>{children}</span>
}