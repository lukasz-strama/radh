// Laboratorium DH (#38, #42): sesja niezależnych procesów Alice i Boba, a w scenariuszu
// ataku także Mallory. Frontend niczego nie liczy i nie wymyśla zdarzeń: pokazuje stan
// sesji z API (#37, #41). Sekrety prywatne nigdy nie przechodzą przez przeglądarkę.

import { useEffect, useRef, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import {
  ApiError,
  cancelActiveDhSession,
  cancelDhSession,
  fetchDhDiagnostics,
  fetchDhMalloryDiagnostics,
  fetchDhNodes,
  fetchDhSession,
  startDhSession,
} from './api'
import type {
  DhEvent,
  DhInterception,
  DhMallory,
  DhMode,
  DhNode,
  DhSession,
  EventType,
  MessageStatus,
  NodeAvailability,
  NodeRole,
  NodesAvailability,
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

// Dostępność węzłów z heartbeatów.
type NodesState =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; nodes: NodesAvailability }

// K z diagnostyki: Alice, Bob i (w MITM) oba sekrety Mallory.
type Diagnostics = {
  alice: number | null
  bob: number | null
  withAlice: number | null
  withBob: number | null
}

// Nazwa uczestnika (też w dopełniaczu) i symbole we wzorach (Alice: a, A; Bob: b, B).
// fake: wartość Mallory, którą ofiara dostaje w MITM zamiast wartości partnera.
const ROLES: Record<
  Role,
  { name: string; nameOf: string; priv: string; pub: string; fake: string; other: Role }
> = {
  alice: { name: 'Alice', nameOf: 'Alice', priv: 'a', pub: 'A', fake: 'X', other: 'bob' },
  bob: { name: 'Bob', nameOf: 'Boba', priv: 'b', pub: 'B', fake: 'Y', other: 'alice' },
}

const NODE_NAME: Record<NodeRole, { name: string; nameOf: string }> = {
  alice: ROLES.alice,
  bob: ROLES.bob,
  mallory: { name: 'Mallory', nameOf: 'Mallory' },
}

type Tone = 'neutral' | 'ok' | 'error'

const PARTICIPANT_STATUS: Record<ParticipantStatus, { label: string; tone: Tone }> = {
  waiting: { label: 'oczekuje', tone: 'neutral' },
  published: { label: 'wysłał wartość publiczną', tone: 'neutral' },
  received: { label: 'przetworzył wartość partnera', tone: 'ok' },
}

const MODE_LABEL: Record<DhMode, string> = {
  normal: 'Zwykła wymiana',
  mitm: 'Atak MITM',
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
  message_intercepted: 'przechwycenie',
  message_forwarded: 'podmiana',
  message_processed: 'przetworzenie wiadomości',
  session_completed: 'koniec sesji',
  session_cancelled: 'anulowanie sesji',
}

const MESSAGE_STATUS: Record<MessageStatus, { label: string; tone: Tone }> = {
  intercepted: { label: 'przechwycona', tone: 'error' },
  queued: { label: 'w kolejce', tone: 'neutral' },
  processed: { label: 'przetworzona', tone: 'ok' },
}

// Co ile odpytujemy stan sesji i dostępność węzłów.
const SESSION_POLL_MS = 1000
const NODES_POLL_MS = 3000
// Ostatni ACK może zakończyć sesję, zanim węzły zgłoszą K, więc diagnostykę
// czytamy jeszcze przez tyle po zakończeniu (albo krócej, gdy przyjdą wszystkie wartości).
const DIAGNOSTICS_GRACE_MS = 10_000

// Pyta koordynatora o dostępność węzłów; błąd zamienia na stan do wyświetlenia.
async function checkNodes(): Promise<NodesState> {
  try {
    return { status: 'ready', nodes: await fetchDhNodes() }
  } catch (error) {
    return { status: 'error', message: errorMessage(error, 'nieoczekiwany błąd.') }
  }
}

const NO_DIAGNOSTICS: Diagnostics = { alice: null, bob: null, withAlice: null, withBob: null }

// Dokłada K z diagnostyki do stanu sesji; null zostaje jako brak wartości.
function withDiagnostics(session: DhSession, diagnostics: Diagnostics): DhSession {
  const node = (role: Role): DhNode => ({
    ...session.nodes[role],
    sharedKey: diagnostics[role] ?? undefined,
  })
  const mallory: DhMallory | null = session.mallory && {
    ...session.mallory,
    withAlice: diagnostics.withAlice ?? undefined,
    withBob: diagnostics.withBob ?? undefined,
  }
  return { ...session, nodes: { alice: node('alice'), bob: node('bob') }, mallory }
}

// Czy mamy już wszystkie K, jakie sesja może zgłosić (w MITM także oba od Mallory).
function allKeysKnown(mode: DhMode, diagnostics: Diagnostics): boolean {
  const victims = diagnostics.alice !== null && diagnostics.bob !== null
  if (mode === 'normal') return victims
  return victims && diagnostics.withAlice !== null && diagnostics.withBob !== null
}

// Węzły potrzebne w danym scenariuszu.
function requiredNodes(mode: DhMode): NodeRole[] {
  return mode === 'mitm' ? ['alice', 'bob', 'mallory'] : ['alice', 'bob']
}

// Węzły, o których heartbeat mówi, że nie działają. Brak Mallory w odpowiedzi
// (backend bez MITM) nie blokuje – start i tak zwróci czytelny błąd.
function offlineNodes(nodes: NodesState, mode: DhMode): NodeRole[] {
  if (nodes.status !== 'ready') return []
  return requiredNodes(mode).filter((role) => nodes.nodes[role]?.online === false)
}

// Polecenie uruchomienia węzła (bez trybu testowego i diagnostyki).
function runCommand(role: NodeRole): string {
  return `python -m backend.dh_transport --role ${role}`
}

function joinNames(roles: NodeRole[]): string {
  const names = roles.map((role) => NODE_NAME[role].nameOf)
  return names.length <= 1
    ? names.join('')
    : `${names.slice(0, -1).join(', ')} i ${names[names.length - 1]}`
}

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
  const [mode, setMode] = useState<DhMode>('normal')
  // Ostatnia zakończona sesja każdego scenariusza – do porównania obok siebie.
  // Sesje idą po kolei (koordynator obsługuje jedną naraz), a porównanie zostaje po resecie.
  const [lastByMode, setLastByMode] = useState<Partial<Record<DhMode, DhSession>>>({})
  // Numer bieżącego żądania. Reset albo nowy start go zwiększa, więc spóźniona
  // odpowiedź starego żądania jest ignorowana i nie nadpisze nowszego stanu.
  const requestId = useRef(0)
  const [nodes, setNodes] = useState<NodesState>({ status: 'loading' })
  const isLoading = view.status === 'loading'
  // Start blokujemy tylko, gdy wiadomo, że któryś potrzebny węzeł nie działa. Gdy
  // dostępności nie da się sprawdzić, nie blokujemy – sesja i tak pokaże, czy węzły odpowiadają.
  const nodesOffline = offlineNodes(nodes, mode).length > 0

  const sessionId = view.status === 'session' ? view.session.id : null
  const activeId =
    view.status === 'session' &&
    (view.session.status === 'created' || view.session.status === 'running')
      ? view.session.id
      : null

  // Dostępność węzłów sprawdzamy od razu i potem co NODES_POLL_MS.
  useEffect(() => {
    let active = true
    let timer: number | undefined
    async function tick() {
      const state = await checkNodes()
      if (!active) return
      setNodes(state)
      timer = window.setTimeout(tick, NODES_POLL_MS)
    }
    void tick()
    return () => {
      active = false
      window.clearTimeout(timer)
    }
  }, [])

  // Odpytywanie sesji i jej diagnostyki. Kolejne zapytanie idzie dopiero po odpowiedzi
  // na poprzednie. Działa, dopóki sesja trwa, a po zakończeniu jeszcze do
  // DIAGNOSTICS_GRACE_MS lub do otrzymania K od obu stron. Reset i nowy start je zatrzymują.
  useEffect(() => {
    if (!sessionId) return
    const id = requestId.current
    let active = true
    let timer: number | undefined
    let diagnostics: Diagnostics = NO_DIAGNOSTICS
    let completedAt: number | null = null

    async function tick() {
      let session: DhSession
      try {
        session = await fetchDhSession(sessionId as string)
      } catch (error) {
        if (!active || id !== requestId.current) return
        // Bez aktualnego stanu nie pokazujemy starego: zamiast sesji tylko błąd.
        setView({
          status: 'error',
          message: `Utracono stan sesji: ${errorMessage(error, 'nieoczekiwany błąd.')}`,
        })
        return
      }
      if (!active || id !== requestId.current) return

      // Błąd diagnostyki nie psuje sesji: K jest dodatkiem, zostają poprzednie wartości.
      if (session.status === 'running' || session.status === 'completed') {
        try {
          diagnostics = { ...diagnostics, ...(await fetchDhDiagnostics(session.id)) }
        } catch {
          // ignorujemy, spróbujemy przy następnym odczycie
        }
        if (session.mode === 'mitm') {
          try {
            diagnostics = { ...diagnostics, ...(await fetchDhMalloryDiagnostics(session.id)) }
          } catch {
            // jak wyżej
          }
        }
        if (!active || id !== requestId.current) return
      }

      const shown = withDiagnostics(session, diagnostics)
      setView({ status: 'session', session: shown })
      if (shown.status === 'completed') {
        setLastByMode((previous) => ({ ...previous, [shown.mode]: shown }))
      }

      if (session.status === 'completed' && completedAt === null) completedAt = Date.now()
      const keepPolling =
        session.status === 'created' ||
        session.status === 'running' ||
        (session.status === 'completed' &&
          !allKeysKnown(session.mode, diagnostics) &&
          Date.now() - (completedAt ?? 0) < DIAGNOSTICS_GRACE_MS)
      if (keepPolling) timer = window.setTimeout(tick, SESSION_POLL_MS)
    }

    timer = window.setTimeout(tick, SESSION_POLL_MS)
    return () => {
      active = false
      window.clearTimeout(timer)
    }
  }, [sessionId])

  async function handleStart(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (isLoading || nodesOffline) return
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
      const session = await startDhSession(validation.data, mode)
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
  // W sesji liczy się jej tryb, przed startem – wybrany scenariusz.
  const shownMode = session?.mode ?? mode

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
          <div className={`dh-parties dh-parties--${shownMode}`}>
            <NodePanel
              role="alice"
              mode={shownMode}
              node={session?.nodes.alice}
              nodes={nodes}
            />

            {/* Środek: przy zwykłej wymianie wiadomości idą przez koordynatora,
                przy ataku przechwytuje je Mallory. */}
            {shownMode === 'mitm' ? (
              <MalloryPanel
                mallory={session?.mallory ?? undefined}
                completed={session?.status === 'completed'}
                nodes={nodes}
              />
            ) : (
              <div className="dh-channel">
                <span className="dh-channel-label">koordynator</span>
              </div>
            )}

            <NodePanel role="bob" mode={shownMode} node={session?.nodes.bob} nodes={nodes} />
          </div>

          {shownMode === 'mitm' && <MitmExplanation />}

          {session && <WaitingHint session={session} nodes={nodes} />}
          {session && <SessionResult session={session} />}
          <ScenarioComparison sessions={lastByMode} />
          {session && (
            <EventLog
              events={session.events}
              interceptions={session.mallory?.interceptions ?? []}
            />
          )}
        </section>

        <aside className="panel" aria-label="Parametry sesji">
          {/* noValidate: walidację robimy sami, z polskimi komunikatami. */}
          <form className="dh-form" onSubmit={handleStart} noValidate>
            {/* Scenariusz wybiera się przed startem sesji. */}
            <fieldset className="dh-mode" disabled={isLoading}>
              <legend>Scenariusz</legend>
              {(['normal', 'mitm'] as const).map((value) => (
                <label key={value}>
                  <input
                    type="radio"
                    name="mode"
                    value={value}
                    checked={mode === value}
                    onChange={() => setMode(value)}
                  />
                  {MODE_LABEL[value]}
                </label>
              ))}
            </fieldset>

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
              Klucze prywatne losują procesy{' '}
              {mode === 'mitm' ? 'Alice, Boba i Mallory' : 'Alice i Boba'}. Przeglądarka ich
              nie zna.
            </p>

            <div className="dh-buttons">
              <button
                type="submit"
                disabled={isLoading || nodesOffline}
                aria-busy={isLoading}
                aria-describedby={
                  nodesOffline || nodes.status === 'error' ? 'dh-nodes-hint' : undefined
                }
              >
                {isLoading ? 'Uruchamianie…' : 'Rozpocznij sesję'}
              </button>
              <button type="button" onClick={handleReset}>
                Reset
              </button>
            </div>

            <NodesHint nodes={nodes} mode={mode} />

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
        <span className="dh-badges">
          <Badge tone={session.mode === 'mitm' ? 'error' : 'neutral'}>
            {MODE_LABEL[session.mode]}
          </Badge>
          <Badge tone={status.tone}>sesja {status.label}</Badge>
        </span>
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

// Sesja trwa, a ktoś jeszcze nie wysłał wartości (albo Mallory nie odesłała podmiany):
// mówimy, na kogo czekamy, a jeśli heartbeat mówi, że proces nie działa, podpowiadamy,
// jak go uruchomić.
function WaitingHint({ session, nodes }: { session: DhSession; nodes: NodesState }) {
  if (session.status !== 'running') return null
  const waiting: NodeRole[] = (['alice', 'bob'] as const).filter(
    (role) => session.nodes[role].status === 'waiting',
  )
  const malloryPending = session.mallory?.interceptions.some((i) => i.status === 'pending')
  if (waiting.length === 0 && !malloryPending) return null
  const offline = offlineNodes(nodes, session.mode).filter(
    (role) => waiting.includes(role) || (role === 'mallory' && malloryPending),
  )
  return (
    <p className="dh-note" role="status">
      {waiting.length > 0 && `Czekamy na wartość publiczną od ${joinNames(waiting)}.`}
      {waiting.length > 0 && malloryPending && ' '}
      {malloryPending && 'Czekamy, aż Mallory odeśle podmienioną wartość.'}
      {offline.length > 0 && (
        <>
          {' '}
          Proces {joinNames(offline)} nie odpowiada – uruchom go:{' '}
          <code>{runCommand(offline[0])}</code>.
        </>
      )}
    </p>
  )
}

// Komunikat pod przyciskami o dostępności węzłów potrzebnych w wybranym scenariuszu.
function NodesHint({ nodes, mode }: { nodes: NodesState; mode: DhMode }) {
  let text: string | null = null
  if (nodes.status === 'error') text = `Nie udało się sprawdzić dostępności węzłów: ${nodes.message}`
  const offline = offlineNodes(nodes, mode)
  if (offline.length > 0) text = `Uruchom proces ${joinNames(offline)}, żeby rozpocząć sesję.`
  if (!text) return null
  return (
    <p className="dh-note" id="dh-nodes-hint">
      {text}
    </p>
  )
}

// Plakietka dostępności procesu (poza sesją).
function availabilityBadge(
  availability: NodeAvailability | undefined,
  nodes: NodesState,
): { label: string; tone: Tone } | null {
  if (nodes.status === 'loading') return { label: 'sprawdzanie…', tone: 'neutral' }
  if (!availability) return null
  if (availability.online) return { label: 'dostępny', tone: 'ok' }
  return availability.lastSeen === null
    ? { label: 'nie zgłosił się', tone: 'error' }
    : { label: 'niedostępny', tone: 'error' }
}

// Plakietka węzła: w sesji jego postęp, poza sesją dostępność procesu.
function nodeBadge(
  role: Role,
  node: DhNode | undefined,
  nodes: NodesState,
): { label: string; tone: Tone } | null {
  if (node) return PARTICIPANT_STATUS[node.status]
  return availabilityBadge(nodes.status === 'ready' ? nodes.nodes[role] : undefined, nodes)
}

// Panel jednego węzła: status, tajny klucz (bez wartości), wartości publiczne, sekret.
type NodePanelProps = {
  role: Role
  mode: DhMode
  // Stan uczestnika w sesji; bez sesji undefined.
  node: DhNode | undefined
  nodes: NodesState
}

function NodePanel({ role, mode, node, nodes }: NodePanelProps) {
  const { name, nameOf, priv, pub, fake, other } = ROLES[role]
  const status = nodeBadge(role, node, nodes)
  // W MITM ofiara dostaje wartość Mallory, choć myśli, że to wartość partnera.
  const received = mode === 'mitm' ? fake : ROLES[other].pub
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

      <DhValue
        kind="public"
        label={mode === 'mitm' ? `Otrzymana „od ${ROLES[other].nameOf}”` : 'Otrzymana wartość'}
        value={node?.receivedValue}
      >
        {received}
      </DhValue>

      {/* Bez diagnostyki K zostaje w procesie: po przetworzeniu wartości partnera
          wiemy tylko, że węzeł je obliczył, więc zamiast „?” mówimy to wprost.
          Gdy diagnostyka przyjdzie (także po zakończeniu sesji), pokazujemy liczbę. */}
      {node?.status === 'received' && node.sharedKey === undefined ? (
        <DhValue kind="private" label="Wspólny sekret" withValue={false}>
          <span className="formula">K</span> – obliczony, zna go tylko proces {nameOf}
        </DhValue>
      ) : (
        <DhValue kind="private" label="Wspólny sekret" value={node?.sharedKey}>
          K = {received}
          <sup>{priv}</sup> mod p
        </DhValue>
      )}
    </section>
  )
}

// Panel Mallory: dwa własne sekrety, przechwycone wartości, podstawione wartości
// i dwa sekrety uzgodnione osobno z Alice i z Bobem. Wszystko z rekordów przechwyceń
// i diagnostyki Mallory (#41); bez sesji same wzory.
type MalloryPanelProps = {
  mallory: DhMallory | undefined
  completed: boolean
  nodes: NodesState
}

// Postęp Mallory w sesji: ile wartości przechwyciła i ile już podmieniła.
function malloryBadge(mallory: DhMallory): { label: string; tone: Tone } {
  const { interceptions } = mallory
  const forwarded = interceptions.filter((i) => i.status !== 'pending').length
  if (interceptions.length === 0) return { label: 'czeka na wiadomości', tone: 'neutral' }
  if (forwarded < interceptions.length) {
    return { label: `przechwyciła ${interceptions.length}/2`, tone: 'neutral' }
  }
  return { label: `podmieniła ${forwarded}/2`, tone: forwarded === 2 ? 'error' : 'neutral' }
}

function MalloryPanel({ mallory, completed, nodes }: MalloryPanelProps) {
  const status = mallory
    ? malloryBadge(mallory)
    : availabilityBadge(nodes.status === 'ready' ? nodes.nodes.mallory : undefined, nodes)
  // Mallory liczy K z ofiarą, gdy obsłuży jej wiadomość (odeśle podmianę).
  const handled = (role: Role) =>
    mallory?.interceptions.some((i) => i.originalSender === role && i.status !== 'pending') ??
    false

  return (
    <section className="dh-party dh-party--mallory" aria-labelledby="dh-mallory-title">
      <div className="dh-party-header">
        <h2 id="dh-mallory-title">Mallory</h2>
        {status && <Badge tone={status.tone}>{status.label}</Badge>}
      </div>

      <DhValue kind="private" label="Klucze prywatne" withValue={false}>
        <span className="formula">x</span>, <span className="formula">y</span> – zna je
        tylko proces Mallory
      </DhValue>

      <DhValue kind="public" label="Przechwycona od Alice" value={mallory?.fromAlice}>
        A
      </DhValue>

      <DhValue kind="public" label="Podstawiona Bobowi" value={mallory?.toBob}>
        Y = g<sup>y</sup> mod p
      </DhValue>

      <DhValue kind="public" label="Przechwycona od Boba" value={mallory?.fromBob}>
        B
      </DhValue>

      <DhValue kind="public" label="Podstawiona Alice" value={mallory?.toAlice}>
        X = g<sup>x</sup> mod p
      </DhValue>

      <MalloryKey
        label="Sekret z Alice"
        value={mallory?.withAlice}
        computed={completed && handled('alice')}
      >
        K<sub>MA</sub> = A<sup>x</sup> mod p
      </MalloryKey>

      <MalloryKey
        label="Sekret z Bobem"
        value={mallory?.withBob}
        computed={completed && handled('bob')}
      >
        K<sub>MB</sub> = B<sup>y</sup> mod p
      </MalloryKey>
    </section>
  )
}

// Sekret Mallory. Jak w panelu węzła: bez diagnostyki mówimy wprost, że K jest
// obliczony, ale zostaje w procesie.
function MalloryKey({
  label,
  value,
  computed,
  children,
}: {
  label: string
  value: number | undefined
  computed: boolean
  children: ReactNode
}) {
  if (computed && value === undefined) {
    return (
      <DhValue kind="private" label={label} withValue={false}>
        <span className="formula">K</span> – obliczony, zna go tylko proces Mallory
      </DhValue>
    )
  }
  return (
    <DhValue kind="private" label={label} value={value}>
      {children}
    </DhValue>
  )
}

// Stałe wyjaśnienie scenariusza ataku: nie zależy od danych sesji.
function MitmExplanation() {
  return (
    <section className="dh-explain" aria-labelledby="dh-explain-title">
      <h2 id="dh-explain-title">Dlaczego atak się udaje</h2>
      <p>
        Alice i Bob dostają same liczby. Nic w wartości publicznej nie mówi, kto ją
        naprawdę wysłał.
      </p>
      <p>
        Mallory przechwytuje A i B, a w zamian wysyła własne X i Y. Z każdą ofiarą wykonuje
        osobną, całkowicie poprawną wymianę DH: z Alice uzgadnia K<sub>MA</sub>, z Bobem
        K<sub>MB</sub>.
      </p>
      <div>
        <p className="formula dh-result-formula">
          K<sub>A</sub> = X<sup>a</sup> = A<sup>x</sup> = K<sub>MA</sub> (mod p)
        </p>
        <p className="formula dh-result-formula">
          K<sub>B</sub> = Y<sup>b</sup> = B<sup>y</sup> = K<sub>MB</sub> (mod p)
        </p>
      </div>
      <p>
        Obliczenia się zgadzają, ale Alice i Bob mają różne sekrety, a Mallory zna oba. Gdyby
        dalej szyfrowali rozmowę tymi kluczami, Mallory mogłaby ją czytać i przekazywać dalej
        niezauważona.
      </p>
      <p>
        Przed tym chroni dopiero uwierzytelnienie wartości publicznych, np. podpis RSA:
        podstawione X i Y nie miałyby ważnego podpisu Boba ani Alice.
      </p>
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

// Porównanie sekretów obu stron. Pokazujemy dopiero, gdy oba węzły zgłosiły K
// w diagnostyce (węzły uruchomione z --allow-diagnostics).
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
      {/* Same K są już w panelach węzłów, tu tylko werdykt i wyjaśnienie. */}
      <h2 id="dh-result-title">
        {match ? 'Sekrety zgodne' : 'Sekrety niezgodne'}
      </h2>
      {session.mode === 'mitm' && <MitmResult session={session} />}
      {match && (
        <>
          <p>
            Obie strony doszły do tej samej liczby, choć żadna nie poznała klucza
            prywatnego drugiej:
          </p>
          <p className="formula dh-result-formula">
            B<sup>a</sup> = (g<sup>b</sup>)<sup>a</sup> = g<sup>ab</sup> = (g<sup>a</sup>)
            <sup>b</sup> = A<sup>b</sup> (mod p)
          </p>
        </>
      )}
      <p className="dh-note">
        K nie jest przesyłane – pokazujemy je tylko na potrzeby demonstracji.
      </p>
    </section>
  )
}

// Wynik ataku: każda ofiara uzgodniła sekret z Mallory, nie z partnerem.
// Pokazujemy, gdy Mallory zgłosiła oba swoje K; porównujemy tylko liczby z diagnostyki.
function MitmResult({ session }: { session: DhSession }) {
  const kA = session.nodes.alice.sharedKey
  const kB = session.nodes.bob.sharedKey
  const kMA = session.mallory?.withAlice
  const kMB = session.mallory?.withBob
  if (kA === undefined || kB === undefined || kMA === undefined || kMB === undefined) {
    return (
      <p className="dh-note">Brak sekretów Mallory w diagnostyce – nie da się ich porównać.</p>
    )
  }
  const sign = (x: number, y: number) => (x === y ? '=' : '≠')
  const success = kA === kMA && kB === kMB && kA !== kB
  return (
    <>
      <p>
        {success
          ? 'Atak się udał: Alice ma sekret wspólny z Mallory, Bob – też z Mallory, a nie ze sobą nawzajem.'
          : 'Wartości nie układają się w udany atak.'}
      </p>
      <p className="formula dh-result-formula">
        K<sub>A</sub> = <output>{kA}</output> {sign(kA, kMA)} <output>{kMA}</output> = K
        <sub>MA</sub>
      </p>
      <p className="formula dh-result-formula">
        K<sub>B</sub> = <output>{kB}</output> {sign(kB, kMB)} <output>{kMB}</output> = K
        <sub>MB</sub>
      </p>
      <p className="formula dh-result-formula">
        K<sub>A</sub> = <output>{kA}</output> {sign(kA, kB)} <output>{kB}</output> = K
        <sub>B</sub>
      </p>
    </>
  )
}

// Wiersze porównania: te same wartości z ostatniej sesji każdego scenariusza.
const COMPARE_ROWS: { label: ReactNode; value: (session: DhSession) => number | undefined }[] = [
  { label: 'A – wysłała Alice', value: (s) => s.nodes.alice.publicValue },
  { label: 'B – wysłał Bob', value: (s) => s.nodes.bob.publicValue },
  { label: 'Alice otrzymała', value: (s) => s.nodes.alice.receivedValue },
  { label: 'Bob otrzymał', value: (s) => s.nodes.bob.receivedValue },
  {
    label: (
      <>
        K<sub>A</sub> – sekret Alice
      </>
    ),
    value: (s) => s.nodes.alice.sharedKey,
  },
  {
    label: (
      <>
        K<sub>B</sub> – sekret Boba
      </>
    ),
    value: (s) => s.nodes.bob.sharedKey,
  },
  {
    label: (
      <>
        K<sub>MA</sub> – Mallory z Alice
      </>
    ),
    value: (s) => s.mallory?.withAlice,
  },
  {
    label: (
      <>
        K<sub>MB</sub> – Mallory z Bobem
      </>
    ),
    value: (s) => s.mallory?.withBob,
  },
]

const COMPARED_MODES = ['normal', 'mitm'] as const

// Werdykt sesji: czy Alice i Bob mają ten sam K (o ile węzły zgłosiły diagnostykę).
function secretsVerdict(session: DhSession): { label: string; tone: Tone } {
  const kA = session.nodes.alice.sharedKey
  const kB = session.nodes.bob.sharedKey
  if (kA === undefined || kB === undefined) return { label: 'brak K w diagnostyce', tone: 'neutral' }
  return kA === kB ? { label: 'zgodne', tone: 'ok' } : { label: 'różne', tone: 'error' }
}

// Porównanie ostatniej zakończonej sesji zwykłej i ataku. Pokazuje tylko to, co przyszło
// z API; wartości różniące się między scenariuszami są wyróżnione.
function ScenarioComparison({ sessions }: { sessions: Partial<Record<DhMode, DhSession>> }) {
  const { normal, mitm } = sessions
  if (!normal && !mitm) return null
  const missing = COMPARED_MODES.filter((mode) => !sessions[mode])

  return (
    <section className="dh-compare" aria-labelledby="dh-compare-title">
      <h2 id="dh-compare-title">Porównanie scenariuszy</h2>
      <p className="dh-note">Ostatnia zakończona sesja każdego scenariusza.</p>
      <div className="dh-log-scroll">
        <table>
          <thead>
            <tr>
              <th scope="col">Wartość</th>
              {COMPARED_MODES.map((mode) => (
                <th scope="col" key={mode}>
                  {MODE_LABEL[mode]}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            <tr>
              <th scope="row">p, g</th>
              {COMPARED_MODES.map((mode) => {
                const s = sessions[mode]
                return (
                  <td className="formula" key={mode}>
                    {s ? `${s.p}, ${s.g}` : '–'}
                  </td>
                )
              })}
            </tr>
            {COMPARE_ROWS.map((row, index) => {
              const values = COMPARED_MODES.map((mode) => {
                const s = sessions[mode]
                return s ? row.value(s) : undefined
              })
              const differs =
                normal !== undefined &&
                mitm !== undefined &&
                values[0] !== undefined &&
                values[1] !== undefined &&
                values[0] !== values[1]
              return (
                <tr key={index}>
                  <th scope="row">{row.label}</th>
                  {values.map((value, column) => (
                    <td
                      className={`formula${differs ? ' dh-compare-diff' : ''}`}
                      key={COMPARED_MODES[column]}
                    >
                      {value ?? '–'}
                    </td>
                  ))}
                </tr>
              )
            })}
            <tr>
              <th scope="row">Sekrety Alice i Boba</th>
              {COMPARED_MODES.map((mode) => {
                const s = sessions[mode]
                if (!s) return <td key={mode}>–</td>
                const verdict = secretsVerdict(s)
                return (
                  <td key={mode}>
                    <Badge tone={verdict.tone}>{verdict.label}</Badge>
                  </td>
                )
              })}
            </tr>
          </tbody>
        </table>
      </div>
      <p className="dh-note">
        {missing.length > 0
          ? `Uruchom też scenariusz „${MODE_LABEL[missing[0]]}”, żeby zobaczyć różnice.`
          : 'Wyróżnione wartości różnią się między scenariuszami.'}
      </p>
    </section>
  )
}

// Uporządkowany dziennik zdarzeń koordynatora.
function EventLog({
  events,
  interceptions,
}: {
  events: DhEvent[]
  interceptions: DhInterception[]
}) {
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
                <EventRow
                  key={event.seq}
                  event={event}
                  interception={interceptions.find((i) => i.messageId === event.messageId)}
                />
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
// Po podmianie (message_forwarded, a potem message_processed) wiadomość naprawdę
// wysyła Mallory, podszywając się pod oryginalnego nadawcę – pokazujemy oba fakty
// i wartość, którą zastąpiła.
function EventRow({ event, interception }: { event: DhEvent; interception?: DhInterception }) {
  const status = MESSAGE_STATUS[event.status]
  const substituted =
    interception !== undefined &&
    (event.type === 'message_forwarded' || event.type === 'message_processed')
  return (
    <tr>
      <td>{event.seq}</td>
      <td>{EVENT_TYPE[event.type]}</td>
      <td>
        {event.from && event.to ? (
          <>
            {substituted ? (
              <>
                <RoleName role="mallory" /> jako <RoleName role={interception.originalSender} />
              </>
            ) : (
              <RoleName role={event.from} />
            )}{' '}
            → <RoleName role={event.to} />
          </>
        ) : (
          '–'
        )}
      </td>
      <td className="formula">
        {event.value ?? '–'}
        {substituted && event.value !== interception.originalValue && (
          <span className="dh-replaced"> zamiast {interception.originalValue}</span>
        )}
      </td>
      <td>{event.from ? <Badge tone={status.tone}>{status.label}</Badge> : '–'}</td>
    </tr>
  )
}

function RoleName({ role }: { role: NodeRole }) {
  return <span className={`dh-role dh-role--${role}`}>{NODE_NAME[role].name}</span>
}

function Badge({ tone, children }: { tone: Tone; children: ReactNode }) {
  return <span className={`dh-badge dh-badge--${tone}`}>{children}</span>
}