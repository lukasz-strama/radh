// Laboratorium DH (#38): sesja dwóch niezależnych procesów, Alice i Boba.
// Frontend niczego nie liczy i nie wymyśla zdarzeń: pokazuje stan sesji z API.
// Sekrety a i b nigdy nie przechodzą przez przeglądarkę.

import { useEffect, useRef, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { ApiError, fetchDhNodes, startDhSession } from './api'
import type {
  DhEvent,
  DhNode,
  DhSession,
  EventStatus,
  NodeAvailability,
  NodeStatus,
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

// Dostępność węzłów przed sesją.
type NodesState =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; nodes: Record<Role, NodeAvailability> }

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
  idle: { label: 'gotowy', tone: 'neutral' },
  public_ready: { label: 'obliczył wartość publiczną', tone: 'neutral' },
  complete: { label: 'obliczył sekret', tone: 'ok' },
  error: { label: 'błąd', tone: 'error' },
}

const AVAILABILITY: Record<NodeAvailability, { label: string; tone: Tone }> = {
  online: { label: 'dostępny', tone: 'ok' },
  offline: { label: 'niedostępny', tone: 'error' },
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

// Pyta koordynatora o dostępność węzłów; błąd zamienia na stan do wyświetlenia.
async function checkNodes(): Promise<NodesState> {
  try {
    return { status: 'ready', nodes: await fetchDhNodes() }
  } catch (error) {
    return {
      status: 'error',
      message: error instanceof ApiError ? error.message : 'Nie udało się sprawdzić węzłów.',
    }
  }
}

const DEFAULTS: Record<DhField, string> = {
  prime: '23',
  generator: '5',
}

export function DhExchange() {
  const [fieldErrors, setFieldErrors] = useState<DhFieldErrors>({})
  const [view, setView] = useState<ViewState>({ status: 'empty' })
  // Numer bieżącego żądania. Reset albo nowy start go zwiększa, więc spóźniona
  // odpowiedź starego żądania jest ignorowana i nie nadpisze nowszego stanu.
  const requestId = useRef(0)
  const [nodes, setNodes] = useState<NodesState>({ status: 'loading' })
  const isLoading = view.status === 'loading'
  const nodesReady =
    nodes.status === 'ready' && nodes.nodes.alice === 'online' && nodes.nodes.bob === 'online'

  // Dostępność węzłów sprawdzamy przy otwarciu widoku i po resecie.
  // (Odświeżanie w odstępach czasu dojdzie razem z pollingiem.)
  useEffect(() => {
    let active = true
    void checkNodes().then((state) => {
      if (active) setNodes(state)
    })
    return () => {
      active = false
    }
  }, [])

  async function handleStart(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (isLoading || !nodesReady) return
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
      setView({
        status: 'error',
        message: error instanceof ApiError ? error.message : 'Wystąpił nieoczekiwany błąd.',
      })
    }
  }

  // Reset działa też w trakcie uruchamiania: porzuca czekające żądanie.
  function handleReset() {
    requestId.current++
    setFieldErrors({})
    setView({ status: 'empty' })
    setNodes({ status: 'loading' })
    void checkNodes().then(setNodes)
  }

  return (
    <div className="dh">
      <h1>RADH – wymiana kluczy Diffiego–Hellmana</h1>

      <div className="layout">
        <section className="dh-scene" aria-label="Przebieg sesji">
          {/* Węzły widać zawsze: przed sesją z dostępnością, w sesji z fazą. */}
          <Scene session={view.status === 'session' ? view.session : null} nodes={nodes}>
            {view.status !== 'session' && (
              <p className="dh-placeholder">
                {isLoading
                  ? 'Uruchamianie sesji…'
                  : 'Podaj parametry publiczne i kliknij „Rozpocznij sesję”.'}
              </p>
            )}
          </Scene>
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
              <button
                type="submit"
                disabled={isLoading || !nodesReady}
                aria-busy={isLoading}
                aria-describedby={nodesReady ? undefined : 'dh-nodes-hint'}
              >
                {isLoading ? 'Uruchamianie…' : 'Rozpocznij sesję'}
              </button>
              <button type="button" onClick={handleReset}>
                Reset
              </button>
            </div>

            <NodesHint nodes={nodes} />

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

type SceneProps = {
  session: DhSession | null
  nodes: NodesState
  children?: ReactNode
}

// Parametry, węzły, wynik i dziennik. Bez sesji: same węzły z dostępnością.
function Scene({ session, nodes, children }: SceneProps) {
  const sessionStatus = session && SESSION_STATUS[session.status]

  return (
    <>
      {session && sessionStatus ? (
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
      ) : (
        children
      )}

      <div className="dh-parties">
        <NodePanel role="alice" node={session?.nodes.alice} nodes={nodes} />

        {/* Środek: wiadomości idą przez koordynatora. M3: tu stanie Mallory. */}
        <div className="dh-channel">
          <span className="dh-channel-label">koordynator</span>
        </div>

        <NodePanel role="bob" node={session?.nodes.bob} nodes={nodes} />
      </div>

      {session && <SessionResult session={session} />}

      {session && <EventLog events={session.events} />}
    </>
  )
}

// Plakietka węzła: w sesji jego faza, poza sesją dostępność procesu.
function nodeBadge(role: Role, node: DhNode | undefined, nodes: NodesState) {
  if (node) return NODE_STATUS[node.status]
  if (nodes.status === 'ready') return AVAILABILITY[nodes.nodes[role]]
  if (nodes.status === 'error') return { label: 'nieznany', tone: 'error' as const }
  return { label: 'sprawdzanie…', tone: 'neutral' as const }
}

// Komunikat pod przyciskiem, gdy nie da się rozpocząć sesji z powodu węzłów.
function NodesHint({ nodes }: { nodes: NodesState }) {
  let text: string | null = null
  if (nodes.status === 'loading') text = 'Sprawdzanie dostępności węzłów…'
  if (nodes.status === 'error') text = nodes.message
  if (nodes.status === 'ready') {
    const offline = (['alice', 'bob'] as const).filter((role) => nodes.nodes[role] === 'offline')
    if (offline.length > 0) {
      const names = offline.map((role) => ROLES[role].nameOf).join(' i ')
      text = `Uruchom proces ${names}, żeby rozpocząć sesję.`
    }
  }
  if (!text) return null
  return (
    <p className="dh-note" id="dh-nodes-hint">
      {text}
    </p>
  )
}

type NodePanelProps = {
  role: Role
  // Stan węzła w sesji; bez sesji undefined.
  node: DhNode | undefined
  nodes: NodesState
}

// Panel jednego węzła: status, tajny klucz (bez wartości), wartości publiczne, sekret.
function NodePanel({ role, node, nodes }: NodePanelProps) {
  const { name, nameOf, priv, pub, other } = ROLES[role]
  const status = nodeBadge(role, node, nodes)
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

      <DhValue kind="public" label="Wartość publiczna" value={node?.publicValue}>
        {pub} = g<sup>{priv}</sup> mod p
      </DhValue>

      <DhValue kind="public" label="Otrzymana wartość" value={node?.receivedValue}>
        {otherPub}
      </DhValue>

      <DhValue kind="private" label="Wspólny sekret" value={node?.sharedKey}>
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
        K nie jest przesyłane – pokazujemy je tylko na potrzeby demonstracji.
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