// Laboratorium DH (#38): sesja dwóch niezależnych procesów, Alice i Boba.
// Frontend niczego nie liczy i nie wymyśla zdarzeń: pokazuje stan sesji z API (#37).
// Sekrety a i b nigdy nie przechodzą przez przeglądarkę.

import { useEffect, useRef, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import {
  ApiError,
  cancelActiveDhSession,
  cancelDhSession,
  fetchDhSession,
  startDhSession,
} from './api'
import type {
  DhEvent,
  DhNode,
  DhSession,
  EventType,
  MessageStatus,
  ParticipantStatus,
  Role,
  SessionStatus,
} from './api'
import { Field } from './Field'
import { validateDhParams } from './validation'
import type { DhField, DhFieldErrors } from './validation'

// Stan zakładki. Bez sesji nie pokazujemy żadnych wartości, żeby nie zostały stare.
type ViewState =
  | { status: 'empty' }
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'session'; session: DhSession }

// Nazwa uczestnika (też w dopełniaczu) i symbole we wzorach (Alice: a, A; Bob: b, B).
const ROLES: Record<
  Role,
  { name: string; nameOf: string; priv: string; pub: string; other: Role }
> = {
  alice: { name: 'Alice', nameOf: 'Alice', priv: 'a', pub: 'A', other: 'bob' },
  bob: { name: 'Bob', nameOf: 'Boba', priv: 'b', pub: 'B', other: 'alice' },
}

type Tone = 'neutral' | 'ok' | 'error'

const PARTICIPANT_STATUS: Record<ParticipantStatus, { label: string; tone: Tone }> = {
  waiting: { label: 'oczekuje', tone: 'neutral' },
  published: { label: 'wysłał wartość publiczną', tone: 'neutral' },
  received: { label: 'przetworzył wartość partnera', tone: 'ok' },
}

const SESSION_STATUS: Record<SessionStatus, { label: string; tone: Tone }> = {
  created: { label: 'utworzona', tone: 'neutral' },
  running: { label: 'w toku', tone: 'neutral' },
  completed: { label: 'zakończona', tone: 'ok' },
  cancelled: { label: 'anulowana', tone: 'error' },
}

const EVENT_TYPE: Record<EventType, string> = {
  session_created: 'utworzenie sesji',
  session_started: 'start sesji',
  public_value: 'wartość publiczna',
  message_processed: 'przetworzenie wiadomości',
  session_completed: 'koniec sesji',
  session_cancelled: 'anulowanie sesji',
}

const MESSAGE_STATUS: Record<MessageStatus, { label: string; tone: Tone }> = {
  queued: { label: 'w kolejce', tone: 'neutral' },
  processed: { label: 'przetworzona', tone: 'ok' },
}

// Co ile odpytujemy stan trwającej sesji.
const SESSION_POLL_MS = 1000

const DEFAULTS: Record<DhField, string> = {
  prime: '23',
  generator: '5',
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback
}

export function DhExchange() {
  const [fieldErrors, setFieldErrors] = useState<DhFieldErrors>({})
  const [view, setView] = useState<ViewState>({ status: 'empty' })
  // Numer bieżącego żądania. Reset albo nowy start go zwiększa, więc spóźniona
  // odpowiedź starego żądania jest ignorowana i nie nadpisze nowszego stanu.
  const requestId = useRef(0)
  const isLoading = view.status === 'loading'

  // Sesję odpytujemy tylko, dopóki trwa. Zakończona albo anulowana nie zmieni się już.
  const activeId =
    view.status === 'session' &&
    (view.session.status === 'created' || view.session.status === 'running')
      ? view.session.id
      : null

  // Odpytywanie trwającej sesji. Kolejne zapytanie idzie dopiero po odpowiedzi na
  // poprzednie, więc się nie nakładają. Reset, nowy start albo koniec sesji je zatrzymuje.
  useEffect(() => {
    if (!activeId) return
    const sessionId = activeId
    const id = requestId.current
    let active = true
    let timer: number | undefined

    async function tick() {
      try {
        const session = await fetchDhSession(sessionId)
        if (!active || id !== requestId.current) return
        setView({ status: 'session', session })
        if (session.status === 'created' || session.status === 'running') {
          timer = window.setTimeout(tick, SESSION_POLL_MS)
        }
      } catch (error) {
        if (!active || id !== requestId.current) return
        // Bez aktualnego stanu nie pokazujemy starego: zamiast sesji tylko błąd.
        setView({
          status: 'error',
          message: `Utracono stan sesji: ${errorMessage(error, 'nieoczekiwany błąd.')}`,
        })
      }
    }

    timer = window.setTimeout(tick, SESSION_POLL_MS)
    return () => {
      active = false
      window.clearTimeout(timer)
    }
  }, [activeId])

  async function handleStart(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (isLoading) return
    const id = ++requestId.current
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

    setView({ status: 'loading' })
    try {
      const session = await startDhSession(validation.data)
      if (id !== requestId.current) return
      setView({ status: 'session', session })
    } catch (error) {
      if (id !== requestId.current) return
      setView({ status: 'error', message: errorMessage(error, 'Wystąpił nieoczekiwany błąd.') })
    }
  }

  // Reset anuluje trwającą sesję u koordynatora (także pozostałą po odświeżeniu strony)
  // i porzuca czekające żądania. Nowa sesja zawsze dostaje nowe ID.
  async function handleReset() {
    const id = ++requestId.current
    const ownId = activeId
    setFieldErrors({})
    setView({ status: 'empty' })
    try {
      if (ownId) await cancelDhSession(ownId)
      else await cancelActiveDhSession()
    } catch (error) {
      if (id !== requestId.current) return
      setView({
        status: 'error',
        message: `Nie udało się anulować sesji: ${errorMessage(error, 'nieoczekiwany błąd.')}`,
      })
    }
  }

  const session = view.status === 'session' ? view.session : null

  return (
    <div className="dh">
      <h1>RADH – wymiana kluczy Diffiego–Hellmana</h1>

      <div className="layout">
        <section className="dh-scene" aria-label="Przebieg sesji">
          {session ? (
            <SessionHeader session={session} />
          ) : (
            <p className="dh-placeholder">
              {isLoading
                ? 'Uruchamianie sesji…'
                : 'Podaj parametry publiczne i kliknij „Rozpocznij sesję”.'}
            </p>
          )}

          {/* Węzły widać zawsze; bez sesji bez wartości. */}
          <div className="dh-parties">
            <NodePanel role="alice" node={session?.nodes.alice} />

            {/* Środek: wiadomości idą przez koordynatora. M3: tu stanie Mallory. */}
            <div className="dh-channel">
              <span className="dh-channel-label">koordynator</span>
            </div>

            <NodePanel role="bob" node={session?.nodes.bob} />
          </div>

          {session && <WaitingHint session={session} />}
          {session && <SessionResult session={session} />}
          {session && <EventLog events={session.events} />}
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
              <button type="button" onClick={handleReset}>
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

// Parametry wspólne i status sesji.
function SessionHeader({ session }: { session: DhSession }) {
  const status = SESSION_STATUS[session.status]
  return (
    <section className="dh-shared" aria-labelledby="dh-shared-title">
      <div className="dh-shared-header">
        <h2 id="dh-shared-title">Parametry wspólne</h2>
        <Badge tone={status.tone}>sesja {status.label}</Badge>
      </div>
      <p className="formula">
        p = <output>{session.p}</output>
      </p>
      <p className="formula">
        g = <output>{session.g}</output>
      </p>
    </section>
  )
}

// Koordynator nie wie, czy procesy węzłów działają (#37 nie ma heartbeatów).
// Gdy sesja trwa, a ktoś jeszcze nie wysłał wartości, podpowiadamy, co sprawdzić.
function WaitingHint({ session }: { session: DhSession }) {
  if (session.status !== 'running') return null
  const waiting = (['alice', 'bob'] as const).filter(
    (role) => session.nodes[role].status === 'waiting',
  )
  if (waiting.length === 0) return null
  const names = waiting.map((role) => ROLES[role].nameOf).join(' i ')
  return (
    <p className="dh-note" role="status">
      Czekamy na wartość publiczną od {names}. Jeśli się nie pojawia, sprawdź, czy proces
      węzła jest uruchomiony (<code>python -m backend.dh_transport --role …</code>).
    </p>
  )
}

// Panel jednego węzła: status, tajny klucz (bez wartości), wartości publiczne, sekret.
function NodePanel({ role, node }: { role: Role; node: DhNode | undefined }) {
  const { name, nameOf, priv, pub, other } = ROLES[role]
  const status = node && PARTICIPANT_STATUS[node.status]
  const otherPub = ROLES[other].pub
  const titleId = `dh-${role}-title`

  return (
    <section className={`dh-party dh-party--${role}`} aria-labelledby={titleId}>
      <div className="dh-party-header">
        <h2 id={titleId}>{name}</h2>
        {status && <Badge tone={status.tone}>{status.label}</Badge>}
      </div>

      <DhValue kind="private" label="Klucz prywatny" withValue={false}>
        <span className="formula">{priv}</span> – zna go tylko proces {nameOf}
      </DhValue>

      <DhValue kind="public" label="Wartość publiczna" value={node?.publicValue}>
        {pub} = g<sup>{priv}</sup> mod p
      </DhValue>

      <DhValue kind="public" label="Otrzymana wartość" value={node?.receivedValue}>
        {otherPub}
      </DhValue>

      {/* Bez diagnostyki K zostaje w procesie: po przetworzeniu wartości partnera
          wiemy tylko, że węzeł je obliczył, więc zamiast „?” mówimy to wprost. */}
      {node?.status === 'received' && node.sharedKey === undefined ? (
        <DhValue kind="private" label="Wspólny sekret" withValue={false}>
          <span className="formula">K</span> – obliczony, zna go tylko proces {nameOf}
        </DhValue>
      ) : (
        <DhValue kind="private" label="Wspólny sekret" value={node?.sharedKey}>
          K = {otherPub}
          <sup>{priv}</sup> mod p
        </DhValue>
      )}
    </section>
  )
}

type DhValueProps = {
  kind: 'private' | 'public'
  label: string
  // undefined: wartości jeszcze nie ma (pokazujemy „?”).
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
// API #37 nie udostępnia jeszcze K, więc do czasu uzgodnienia diagnostyki sekcja się nie pokazuje.
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
        K nie jest przesyłane – pokazujemy je tylko na potrzeby demonstracji.
      </p>
    </section>
  )
}

// Uporządkowany dziennik zdarzeń koordynatora.
function EventLog({ events }: { events: DhEvent[] }) {
  return (
    <section className="dh-log" aria-labelledby="dh-log-title">
      <h2 id="dh-log-title">Dziennik zdarzeń</h2>
      {events.length === 0 ? (
        <p className="dh-note">Brak zdarzeń w tej sesji.</p>
      ) : (
        <div className="dh-log-scroll">
          <table>
            <thead>
              <tr>
                <th scope="col">Nr</th>
                <th scope="col">Zdarzenie</th>
                <th scope="col">Nadawca → odbiorca</th>
                <th scope="col">Wartość</th>
                <th scope="col">Status</th>
              </tr>
            </thead>
            <tbody>
              {events.map((event) => (
                <EventRow key={event.seq} event={event} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

// Wiersz dziennika. Zdarzenia sesji (utworzenie, start, koniec) nie mają nadawcy
// ani wartości, więc w tych kolumnach jest kreska.
function EventRow({ event }: { event: DhEvent }) {
  const status = MESSAGE_STATUS[event.status]
  return (
    <tr>
      <td>{event.seq}</td>
      <td>{EVENT_TYPE[event.type]}</td>
      <td>
        {event.from && event.to ? (
          <>
            <RoleName role={event.from} /> → <RoleName role={event.to} />
          </>
        ) : (
          '–'
        )}
      </td>
      <td className="formula">{event.value ?? '–'}</td>
      <td>{event.from ? <Badge tone={status.tone}>{status.label}</Badge> : '–'}</td>
    </tr>
  )
}

function RoleName({ role }: { role: Role }) {
  return <span className={`dh-role dh-role--${role}`}>{ROLES[role].name}</span>
}

function Badge({ tone, children }: { tone: Tone; children: ReactNode }) {
  return <span className={`dh-badge dh-badge--${tone}`}>{children}</span>
}