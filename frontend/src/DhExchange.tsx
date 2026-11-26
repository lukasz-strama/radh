// Laboratorium DH (#38, #42): sesja niezależnych procesów Alice i Boba, a w scenariuszu
// ataku także Mallory. Frontend niczego nie liczy i nie wymyśla zdarzeń: pokazuje stan
// sesji z API (#37, #41). Sekrety prywatne nigdy nie przechodzą przez przeglądarkę.

import { createContext, useContext, useEffect, useRef, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { Badge, Button, DataBadge, Notice } from './ui'
import { useParameterDraw } from './useParameterDraw'
import type { DataKind, Tone } from './ui'
import {
  ApiError,
  currentCredential,
  drawDhParameters,
  resetOwnDhSession,
  resumeDhSession,
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
  DhScenario,
  DhSession,
  DhSessionParams,
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
  | { status: 'error'; message: string; retryAfter: number }
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

const PARTICIPANT_STATUS: Record<ParticipantStatus, { label: string; tone: Tone }> = {
  waiting: { label: 'oczekuje', tone: 'neutral' },
  published: { label: 'wysłał wartość publiczną', tone: 'neutral' },
  received: { label: 'przetworzył wartość partnera', tone: 'ok' },
  verified: { label: 'zweryfikował podpis partnera', tone: 'ok' },
}

const MODE_LABELS: Record<DhScenario, Record<DhMode, string>> = {
  classic: { normal: 'Zwykła wymiana', mitm: 'Atak MITM' },
  authenticated: { normal: 'Podpisana wymiana', mitm: 'Podpisana wymiana + MITM' },
}

// Ten sam widok obsługuje zakładkę DH i RSA + DH (#104). Scenariusz decyduje o etykietach
// i identyfikatorach elementów: w zwykłej zakładce zostają jak dotąd, w RSA + DH mają
// prefiks, bo obie zakładki są naraz w DOM.
const ScenarioContext = createContext<DhScenario>('classic')

function useScenario() {
  const scenario = useContext(ScenarioContext)
  return {
    scenario,
    authenticated: scenario === 'authenticated',
    modeLabel: MODE_LABELS[scenario],
    id: (name: string) => (scenario === 'classic' ? name : `rsadh-${name}`),
  }
}

// Kod błędu sesji uwierzytelnionej po negatywnej weryfikacji podpisu (AUTHENTICATED_DH.md).
const SIGNATURE_FAILED = 'SIGNATURE_VERIFICATION_FAILED'

function signatureRejected(session: DhSession): boolean {
  return session.status === 'failed' && session.failureCode === SIGNATURE_FAILED
}

const SESSION_STATUS: Record<SessionStatus, { label: string; tone: Tone }> = {
  created: { label: 'utworzona', tone: 'neutral' },
  running: { label: 'w toku', tone: 'neutral' },
  completed: { label: 'zakończona', tone: 'ok' },
  cancelled: { label: 'anulowana', tone: 'error' },
  failed: { label: 'przerwana', tone: 'error' },
  expired: { label: 'wygasła', tone: 'error' },
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
  session_failed: 'przerwanie sesji',
  session_expired: 'wygaśnięcie sesji',
  trusted_key_published: 'klucz publiczny RSA',
  signature_published: 'podpis transkryptu',
  signature_verified: 'weryfikacja podpisu',
  signature_rejected: 'weryfikacja podpisu',
}

const MESSAGE_STATUS: Record<MessageStatus, { label: string; tone: Tone }> = {
  intercepted: { label: 'przechwycona', tone: 'error' },
  queued: { label: 'w kolejce', tone: 'neutral' },
  processed: { label: 'przetworzona', tone: 'ok' },
}

// Co ile odpytujemy stan sesji i dostępność węzłów.
const SESSION_POLL_MS = 2000
const NODES_POLL_MS = 3000
// Ostatni ACK może zakończyć sesję, zanim węzły zgłoszą K, więc diagnostykę
// czytamy jeszcze przez tyle po zakończeniu (albo krócej, gdy przyjdą wszystkie wartości).
const DIAGNOSTICS_GRACE_MS = 30_000
// Zakończoną sesję serwer trzyma jeszcze przez czas retencji, potem ją usuwa (410).
// Sprawdzamy to rzadko, żeby poinformować o wygaśnięciu, zamiast pokazywać nieaktualny stan.
const TERMINAL_POLL_MS = 15_000

// Pyta koordynatora o dostępność węzłów; błąd zamienia na stan do wyświetlenia.
async function checkNodes(signal?: AbortSignal): Promise<NodesState> {
  try {
    return { status: 'ready', nodes: await fetchDhNodes(signal) }
  } catch (error) {
    return {
      status: 'error', message: errorMessage(error, 'nieoczekiwany błąd.'),
      retryAfter: error instanceof ApiError ? error.retryAfter : 0,
    }
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
  return `python -m nodes.multi_session_cli --role ${role}`
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

// Na wąskim ekranie formularz stoi nad sesją, więc po starcie przebieg byłby poza
// ekranem. Przewijamy do niego tylko wtedy, gdy zaczyna się poniżej widocznej części.
function scrollToSceneIfBelow(scene: HTMLElement | null) {
  if (!scene || scene.getBoundingClientRect().top < window.innerHeight * 0.5) return
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
  scene.scrollIntoView({ block: 'start', behavior: reduceMotion ? 'auto' : 'smooth' })
}

// Liczby z backendu w postaci pól formularza (jak przy ręcznym wpisaniu).
function dhFields(values: DhSessionParams): Record<DhField, string> {
  return { prime: String(values.prime), generator: String(values.generator) }
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback
}

// scenario: 'classic' – zakładka DH, 'authenticated' – zakładka RSA + DH (#104).
// Każdy scenariusz ma własne poświadczenie sesji, więc zakładki sobie nie przeszkadzają.
export function DhExchange({ scenario = 'classic' }: { scenario?: DhScenario }) {
  return (
    <ScenarioContext value={scenario}>
      <DhExchangeView scenario={scenario} />
    </ScenarioContext>
  )
}

function DhExchangeView({ scenario }: { scenario: DhScenario }) {
  const { authenticated, modeLabel, id: sid } = useScenario()
  const [fieldErrors, setFieldErrors] = useState<DhFieldErrors>({})
  // Losowanie zmienia tylko formularz: nie dotyka trwającej sesji i niczego nie
  // uruchamia. Pola zostają niesterowane (wartości czyta FormData); losowanie wpisuje
  // nowe wartości, montując pola od nowa (`key`) z nowym defaultValue – tak jak w RSA.
  const [drawn, setDrawn] = useState({ values: DEFAULTS, version: 0 })
  const parameters = useParameterDraw(
    drawDhParameters,
    (values) => validateDhParams(dhFields(values)).ok,
    (values) => {
      setDrawn((previous) => ({ values: dhFields(values), version: previous.version + 1 }))
      setFieldErrors({})
    },
  )
  const [view, setView] = useState<ViewState>(() =>
    currentCredential(scenario) ? { status: 'loading' } : { status: 'empty' },
  )
  const [diagnosticsEnabled, setDiagnosticsEnabled] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  // Błąd ostatniej akcji (start, wznowienie) przy zachowanej sesji – widok sesji zostaje,
  // żeby dalej było widać jej stan, w tym wygaśnięcie.
  const [actionError, setActionError] = useState<string | null>(null)
  // Po 429/503 przy starcie serwer każe odczekać (Retry-After) – do tego czasu
  // przycisk startu jest zablokowany, żeby nie dokładać kolejnych odrzuconych prób.
  const [startBlocked, setStartBlocked] = useState(false)
  const unblockTimer = useRef<number | undefined>(undefined)
  const actionController = useRef<AbortController | null>(null)
  const [mode, setMode] = useState<DhMode>('normal')
  // Ostatnia zakończona sesja każdego scenariusza – do porównania obok siebie.
  // Porównanie obejmuje wyłącznie wyniki sesji utworzonych w tej karcie.
  const [lastByMode, setLastByMode] = useState<Partial<Record<DhMode, DhSession>>>({})
  // Numer bieżącego żądania. Reset albo nowy start go zwiększa, więc spóźniona
  // odpowiedź starego żądania jest ignorowana i nie nadpisze nowszego stanu.
  const requestId = useRef(0)
  // Przebieg sesji – na wąskim ekranie przewijamy do niego po starcie.
  const sceneRef = useRef<HTMLElement>(null)
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

  useEffect(() => {
    const own = currentCredential(scenario)
    if (!own) return
    const controller = new AbortController()
    const id = requestId.current
    void fetchDhSession(own.id, controller.signal).then(
      (session) => {
        if (!controller.signal.aborted && id === requestId.current) {
          setView({ status: 'session', session })
        }
      },
      (error) => {
        if (!controller.signal.aborted && id === requestId.current) {
          setView({ status: 'error', message: errorMessage(error, 'Nie udało się odzyskać własnej sesji.') })
        }
      },
    )
    return () => controller.abort()
  }, [scenario])

  useEffect(
    () => () => {
      actionController.current?.abort()
      window.clearTimeout(unblockTimer.current)
    },
    [],
  )

  // Kontrakt: po wygaśnięciu sesji K znika z widoku – także z porównania scenariuszy.
  function dropComparisonKeys(id: string) {
    setLastByMode((previous) => {
      const next = { ...previous }
      for (const key of ['normal', 'mitm'] as const) {
        const saved = next[key]
        if (saved?.id === id) next[key] = withDiagnostics(saved, NO_DIAGNOSTICS)
      }
      return next
    })
  }

  // Blokuje start na czas z Retry-After, jeśli błąd go podał (429/503).
  function blockStartIfAsked(error: unknown) {
    if (!(error instanceof ApiError) || error.retryAfter <= 0) return
    if (error.status !== 429 && error.status !== 503) return
    window.clearTimeout(unblockTimer.current)
    setStartBlocked(true)
    unblockTimer.current = window.setTimeout(() => setStartBlocked(false), error.retryAfter * 1000)
  }

  // Dostępność węzłów sprawdzamy od razu i potem co NODES_POLL_MS.
  useEffect(() => {
    let active = true
    let timer: number | undefined
    const controller = new AbortController()
    async function tick() {
      const state = await checkNodes(controller.signal)
      if (!active) return
      setNodes(state)
      const delay = state.status === 'error' ? Math.max(NODES_POLL_MS, state.retryAfter * 1000) : NODES_POLL_MS
      timer = window.setTimeout(tick, delay)
    }
    void tick()
    return () => {
      active = false
      controller.abort()
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
    let connectionLostAt: number | null = null
    let firstTick = true
    const controller = new AbortController()

    // Serwer usunął sesję po upływie retencji (410): mówimy o tym zamiast pokazywać
    // nieaktualny stan. Poświadczenie usuwa już klient API.
    function sessionGone() {
      dropComparisonKeys(sessionId as string)
      setView({ status: 'empty' })
      setNotice('Sesja wygasła i została usunięta z serwera. Możesz rozpocząć nową.')
    }

    async function tick() {
      let session: DhSession
      try {
        session = await fetchDhSession(sessionId as string, controller.signal)
      } catch (error) {
        if (!active || id !== requestId.current) return
        if (error instanceof ApiError && error.status === 410) {
          sessionGone()
          return
        }
        if (error instanceof ApiError && (error.status === 429 || error.status === 503 || error.code === 'NETWORK_ERROR' || error.code === 'REQUEST_TIMEOUT')) {
          connectionLostAt ??= Date.now()
          if (Date.now() - connectionLostAt < 30_000) {
            setNotice(error.message)
            timer = window.setTimeout(tick, Math.max(SESSION_POLL_MS, error.retryAfter * 1000))
            return
          }
        }
        setView({
          status: 'error',
          message: `Utracono stan sesji: ${errorMessage(error, 'nieoczekiwany błąd.')}`,
        })
        return
      }
      if (!active || id !== requestId.current) return

      connectionLostAt = null
      setNotice(null)
      let retryDelay = SESSION_POLL_MS
      if (session.status === 'expired' || session.status === 'failed' || session.status === 'cancelled') {
        diagnostics = NO_DIAGNOSTICS
        dropComparisonKeys(session.id)
      }
      // Błąd ostatniej akcji dotyczył sesji „utworzonej”; po zmianie stanu jest nieaktualny.
      if (session.status !== 'created') setActionError(null)
      // Po zakończeniu K czytamy tylko w oknie DIAGNOSTICS_GRACE_MS (albo raz po odświeżeniu
      // strony), a nie przy każdym rzadkim sprawdzeniu wygaśnięcia.
      const inGrace =
        session.terminalAt !== null &&
        Date.now() - Date.parse(session.terminalAt) < DIAGNOSTICS_GRACE_MS
      const wantDiagnostics =
        session.diagnosticsEnabled &&
        (session.status === 'running' ||
          (session.status === 'completed' &&
            !allKeysKnown(session.mode, diagnostics) &&
            (inGrace || firstTick)))
      firstTick = false
      if (wantDiagnostics) {
        try {
          diagnostics = { ...diagnostics, ...(await fetchDhDiagnostics(session.id, controller.signal)) }
        } catch (error) {
          if (error instanceof ApiError) retryDelay = Math.max(retryDelay, error.retryAfter * 1000)
          if (error instanceof ApiError && (error.status === 401 || error.status === 403 ||
              error.status === 404 || error.status === 410 || error.code === 'BACKEND_EPOCH_MISMATCH')) {
            if (active && id === requestId.current) {
              if (error.status === 410) sessionGone()
              else setView({ status: 'error', message: error.message })
            }
            return
          }
        }
        if (session.mode === 'mitm') {
          try {
            diagnostics = { ...diagnostics, ...(await fetchDhMalloryDiagnostics(session.id, controller.signal)) }
          } catch (error) {
            if (error instanceof ApiError) retryDelay = Math.max(retryDelay, error.retryAfter * 1000)
            if (error instanceof ApiError && (error.status === 401 || error.status === 403 ||
                error.status === 404 || error.status === 410 || error.code === 'BACKEND_EPOCH_MISMATCH')) {
              if (active && id === requestId.current) {
                if (error.status === 410) sessionGone()
                else setView({ status: 'error', message: error.message })
              }
              return
            }
          }
        }
        if (!active || id !== requestId.current) return
      }

      const shown = withDiagnostics(session, diagnostics)
      setView({ status: 'session', session: shown })
      // W RSA + DH porównujemy też sesję odrzuconą przez weryfikację podpisu – to jej wynik.
      if (shown.status === 'completed' || signatureRejected(shown)) {
        setLastByMode((previous) => ({ ...previous, [shown.mode]: shown }))
      }

      // Trwająca sesja: co SESSION_POLL_MS. Zakończona: jeszcze w oknie diagnostyki
      // tak samo, potem rzadko, aż serwer ją usunie. Wygasła: koniec (komunikat już jest).
      const waitingForKeys =
        session.status === 'completed' &&
        session.diagnosticsEnabled &&
        !allKeysKnown(session.mode, diagnostics) &&
        inGrace
      if (session.status === 'created' || session.status === 'running' || waitingForKeys) {
        timer = window.setTimeout(tick, retryDelay)
      } else if (session.status !== 'expired') {
        timer = window.setTimeout(tick, Math.max(TERMINAL_POLL_MS, retryDelay))
      }
    }

    timer = window.setTimeout(tick, SESSION_POLL_MS)
    return () => {
      active = false
      controller.abort()
      window.clearTimeout(timer)
    }
  }, [sessionId])

  async function handleStart(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    // Podczas losowania pola mogą się jeszcze zmienić – sesję rozpoczynamy dopiero po nim.
    if (isLoading || nodesOffline || activeId || startBlocked || parameters.isDrawing) return
    const id = ++requestId.current
    actionController.current?.abort()
    const controller = new AbortController()
    actionController.current = controller
    setNotice(null)
    setActionError(null)
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
      const session = await startDhSession(
        validation.data, mode, diagnosticsEnabled, controller.signal, scenario,
      )
      if (id !== requestId.current) return
      setView({ status: 'session', session })
      scrollToSceneIfBelow(sceneRef.current)
    } catch (error) {
      if (id !== requestId.current) return
      blockStartIfAsked(error)
      const message = errorMessage(error, 'Wystąpił nieoczekiwany błąd.')
      const kept = await showKeptSession(id, message, controller.signal)
      // W trakcie odczytu mogła ruszyć nowsza akcja (Reset, nowy start) – wtedy nic nie zmieniamy.
      if (id !== requestId.current) return
      if (!kept) setView({ status: 'error', message })
    }
  }

  // Sesja została utworzona, ale start się nie udał: pokazujemy jej stan (z odpytywaniem,
  // więc widać też wygaśnięcie) i błąd akcji obok. Zwraca false, gdy sesji nie ma.
  async function showKeptSession(id: number, message: string, signal: AbortSignal) {
    const own = currentCredential(scenario)
    if (!own) return false
    try {
      const kept = await fetchDhSession(own.id, signal)
      if (id !== requestId.current) return true
      setView({ status: 'session', session: kept })
      // Przy wygasłej sesji wystarczy jej własny komunikat.
      setActionError(kept.status === 'expired' ? null : message)
      return true
    } catch {
      return false
    }
  }

  async function handleResume() {
    const own = currentCredential(scenario)
    // Po 429/503 czekamy tak samo jak przy nowym starcie.
    if (!own || startBlocked) return
    const id = ++requestId.current
    actionController.current?.abort()
    const controller = new AbortController()
    actionController.current = controller
    setActionError(null)
    setView({ status: 'loading' })
    try {
      const session = await resumeDhSession(own.id, controller.signal)
      if (id === requestId.current) setView({ status: 'session', session })
    } catch (error) {
      if (id !== requestId.current) return
      blockStartIfAsked(error)
      const message = errorMessage(error, 'Nie udało się wznowić sesji.')
      const kept = await showKeptSession(id, message, controller.signal)
      // W trakcie odczytu mogła ruszyć nowsza akcja (Reset, nowy start) – wtedy nic nie zmieniamy.
      if (id !== requestId.current) return
      if (!kept) setView({ status: 'error', message })
    }
  }

  async function handleReset() {
    const id = ++requestId.current
    actionController.current?.abort()
    // Reset unieważnia też trwające losowanie parametrów i czyści jego błąd
    // (blokada Retry-After zostaje). Wartości w polach zostają, jak dotąd.
    parameters.cancel()
    const controller = new AbortController()
    actionController.current = controller
    setFieldErrors({})
    setNotice(null)
    setActionError(null)
    setView({ status: 'loading' })
    try {
      await resetOwnDhSession(controller.signal, scenario)
      if (id === requestId.current) setView({ status: 'empty' })
    } catch (error) {
      if (id !== requestId.current) return
      setView({ status: 'error', message: errorMessage(error, 'Nie udało się usunąć własnej sesji.') })
    }
  }

  const session = view.status === 'session' ? view.session : null
  // W sesji liczy się jej tryb, przed startem – wybrany scenariusz.
  const shownMode = session?.mode ?? mode

  return (
    <div className="dh">
      <h1>{authenticated ? 'Wymiana DH uwierzytelniona podpisami RSA' : 'Wymiana kluczy Diffiego–Hellmana'}</h1>

      <div className="layout">
        <section className="dh-scene" aria-label="Przebieg sesji" ref={sceneRef}>
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
              completed={session?.status === 'completed'}
              rejected={session ? signatureRejected(session) : false}
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

            <NodePanel
              role="bob"
              mode={shownMode}
              node={session?.nodes.bob}
              nodes={nodes}
              completed={session?.status === 'completed'}
              rejected={session ? signatureRejected(session) : false}
            />
          </div>

          {authenticated ? <TrustExplanation /> : shownMode === 'mitm' && <MitmExplanation />}

          {session && <WaitingHint session={session} nodes={nodes} />}
          {authenticated && session && <SignaturesPanel session={session} />}
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
                  {modeLabel[value]}
                </label>
              ))}
            </fieldset>

            {/* Ręczna edycja ma pierwszeństwo: przerywa trwające losowanie, żeby go nie nadpisało. */}
            <Field
              name="prime"
              label="Liczba pierwsza (p)"
              idPrefix={sid('')}
              error={fieldErrors.prime}
              key={`prime-${drawn.version}`}
              defaultValue={drawn.values.prime}
              onChange={parameters.cancel}
            />
            <Field
              name="generator"
              label="Generator (g)"
              idPrefix={sid('')}
              error={fieldErrors.generator}
              key={`generator-${drawn.version}`}
              defaultValue={drawn.values.generator}
              onChange={parameters.cancel}
            />
            {/* Losowanie tylko wypełnia pola – sesję rozpoczyna się przyciskiem niżej. */}
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
            <p className="hint">
              {authenticated
                ? 'Klucze prywatne DH i pary kluczy RSA losują procesy Alice i Boba. Przeglądarka ich nie zna.'
                : <>
                    Klucze prywatne losują procesy{' '}
                    {mode === 'mitm' ? 'Alice, Boba i Mallory' : 'Alice i Boba'}. Przeglądarka ich
                    nie zna.
                  </>}
            </p>

            {/* Świadoma zgoda na diagnostykę: bez niej węzły nie zgłaszają K. */}
            <label className="dh-check">
              <input
                type="checkbox"
                checked={diagnosticsEnabled}
                disabled={isLoading || activeId !== null}
                onChange={(event) => setDiagnosticsEnabled(event.target.checked)}
              />
              Pokaż edukacyjnie wspólne sekrety sesji
            </label>

            <div className="dh-buttons">
              <Button
                type="submit"
                busy={isLoading}
                busyLabel="Uruchamianie…"
                disabled={nodesOffline || activeId !== null || startBlocked || parameters.isDrawing}
                aria-describedby={
                  nodesOffline || nodes.status === 'error' ? sid('dh-nodes-hint') : undefined
                }
              >
                Rozpocznij sesję
              </Button>
              <Button variant="secondary" onClick={handleReset}>
                Reset
              </Button>
            </div>

            {session?.status === 'created' && (
              <Button variant="secondary" onClick={handleResume} disabled={startBlocked}>
                Uruchom własną sesję
              </Button>
            )}
            {view.status === 'error' && currentCredential(scenario) && (
              <Button variant="secondary" onClick={handleResume} disabled={startBlocked}>
                Ponów start własnej sesji
              </Button>
            )}
            <NodesHint nodes={nodes} mode={mode} />
            {notice && <Notice tone="warning">{notice}</Notice>}
            {actionError && session && <Notice tone="error">{actionError}</Notice>}
            {session?.status === 'expired' && (
              <Notice tone="warning">Sesja wygasła. Reset usunie jej historię i pozwoli rozpocząć nową.</Notice>
            )}
            {session && signatureRejected(session) ? (
              <Notice tone="error">
                Podpis odrzucony – wymiana przerwana, wspólny sekret nie został zaakceptowany. Reset
                pozwoli rozpocząć nową sesję.
              </Notice>
            ) : (
              session?.status === 'failed' && (
                <Notice tone="error">Wymiana została przerwana. Usuń sesję przyciskiem Reset i rozpocznij nową.</Notice>
              )
            )}

            {view.status === 'error' && <Notice tone="error">{view.message}</Notice>}
          </form>
        </aside>
      </div>
    </div>
  )
}

// Parametry wspólne i status sesji.
function SessionHeader({ session }: { session: DhSession }) {
  const { modeLabel, id } = useScenario()
  const status = SESSION_STATUS[session.status]
  return (
    <section className="dh-shared" aria-labelledby={id('dh-shared-title')}>
      <div className="dh-shared-header">
        <h2 id={id('dh-shared-title')}>Parametry wspólne</h2>
        <span className="dh-badges">
          <Badge tone={session.mode === 'mitm' ? 'error' : 'neutral'}>
            {modeLabel[session.mode]}
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
    <p className="hint" role="status">
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
  const { id } = useScenario()
  let text: string | null = null
  if (nodes.status === 'error') text = `Nie udało się sprawdzić dostępności węzłów: ${nodes.message}`
  const offline = offlineNodes(nodes, mode)
  if (offline.length > 0) text = `Uruchom proces ${joinNames(offline)}, żeby rozpocząć sesję.`
  if (!text) return null
  return (
    <p className="hint" id={id('dh-nodes-hint')}>
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
  return { label: 'niedostępny', tone: 'error' }
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
  // Sesja zakończona – w RSA + DH dopiero wtedy K jest zaakceptowane.
  completed?: boolean
  // RSA + DH: weryfikacja podpisu się nie powiodła, więc K nie zostało zaakceptowane.
  rejected?: boolean
}

function NodePanel({ role, mode, node, nodes, completed = false, rejected = false }: NodePanelProps) {
  const { id, authenticated } = useScenario()
  const { name, nameOf, priv, pub, fake, other } = ROLES[role]
  const status = nodeBadge(role, node, nodes)
  // W MITM ofiara dostaje wartość Mallory, choć myśli, że to wartość partnera.
  const received = mode === 'mitm' ? fake : ROLES[other].pub
  const titleId = id(`dh-${role}-title`)
  // Wartość dostarczona do węzła, ale jeszcze nieprzyjęta (bez ACK): w RSA + DH węzeł
  // przyjmuje ją dopiero po pozytywnej weryfikacji podpisu partnera.
  const pendingNote =
    node?.deliveredValue !== undefined && node.receivedValue === undefined
      ? rejected
        ? 'dostarczona, nieprzyjęta – podpis partnera się nie zgadza'
        : authenticated
          ? node.status === 'verified'
            ? 'dostarczona, podpis zweryfikowany – czeka na potwierdzenie'
            : 'dostarczona, czeka na weryfikację podpisu partnera'
          : 'dostarczona, czeka na przetworzenie'
      : undefined

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
        value={node?.receivedValue ?? node?.deliveredValue}
        note={pendingNote}
      >
        {received}
      </DhValue>

      {/* Bez diagnostyki K zostaje w procesie: po przetworzeniu wartości partnera
          wiemy tylko, że węzeł je obliczył, więc zamiast „?” mówimy to wprost.
          Gdy diagnostyka przyjdzie (także po zakończeniu sesji), pokazujemy liczbę. */}
      {/* RSA + DH: status verified nie oznacza jeszcze K ani ACK – zaakceptowane K
          pokazujemy dopiero po zakończeniu sesji. */}
      {rejected ? (
        <DhValue kind="private" label="Wspólny sekret" withValue={false}>
          <span className="formula">K</span> – niezaakceptowany: podpis partnera się nie zgadza
        </DhValue>
      ) : authenticated && !completed && node !== undefined ? (
        <DhValue kind="private" label="Wspólny sekret" withValue={false}>
          <span className="formula">K</span> – zostanie zaakceptowany po weryfikacji obu podpisów
          i zakończeniu sesji
        </DhValue>
      ) : authenticated && completed && node?.sharedKey === undefined ? (
        <DhValue kind="private" label="Wspólny sekret" withValue={false}>
          <span className="formula">K</span> – zaakceptowany, zna go tylko proces {nameOf}
        </DhValue>
      ) : !authenticated && node?.status === 'received' && node.sharedKey === undefined ? (
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
  const { id } = useScenario()
  const status = mallory
    ? malloryBadge(mallory)
    : availabilityBadge(nodes.status === 'ready' ? nodes.nodes.mallory : undefined, nodes)
  // Mallory liczy K z ofiarą, gdy obsłuży jej wiadomość (odeśle podmianę).
  const handled = (role: Role) =>
    mallory?.interceptions.some((i) => i.originalSender === role && i.status !== 'pending') ??
    false

  return (
    <section className="dh-party dh-party--mallory" aria-labelledby={id('dh-mallory-title')}>
      <div className="dh-party-header">
        <h2 id={id('dh-mallory-title')}>Mallory</h2>
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

// RSA + DH: krótko, na czym polega ochrona i jakie ma założenia oraz ograniczenia.
function TrustExplanation() {
  const { id } = useScenario()
  return (
    <section className="dh-explain dh-explain--trust" aria-labelledby={id('dh-explain-title')}>
      <h2 id={id('dh-explain-title')}>Jak podpisy chronią wymianę</h2>
      <p>
        Alice i Bob podpisują swoim kluczem prywatnym RSA transkrypt sesji: p, g, obie
        wartości publiczne i oba klucze publiczne RSA. Każde sprawdza podpis partnera jego
        kluczem publicznym. Gdy Mallory podmieni A albo B, transkrypty stron się różnią
        i podpis nie przejdzie weryfikacji.
      </p>
      <p>
        Założenie: klucze publiczne RSA są zaufane – tu przekazuje je koordynator. Ktoś, kto
        mógłby podmienić także klucze, oszukałby obie strony.
      </p>
      <p>
        Ograniczenia: klucze RSA mają 32 bity i nie ma paddingu, więc da się je złamać
        w ułamku sekundy. Podpisywany jest skrót SHA-256 zredukowany modulo n, więc różne
        transkrypty mogą dać tę samą liczbę – dlatego backend dodatkowo porównuje pełne skróty.
      </p>
    </section>
  )
}

const VERIFICATION_BADGE = {
  pending: { label: 'oczekuje', tone: 'neutral' },
  ok: { label: 'podpis poprawny', tone: 'ok' },
  rejected: { label: 'podpis odrzucony', tone: 'error' },
} as const satisfies Record<string, { label: string; tone: Tone }>

// Początek skrótu – wystarczy, żeby zobaczyć, czy dwa skróty się różnią.
function shortHash(hash: string): string {
  return `${hash.slice(0, 12)}…`
}

// RSA + DH: zaufane klucze publiczne, podpisy transkryptu i wyniki weryfikacji obu stron.
// Wszystkie liczby pochodzą z API; klucze prywatne zostają w węzłach.
function SignaturesPanel({ session }: { session: DhSession }) {
  const { id } = useScenario()
  const { keys, signatures, verifications } = session.authentication
  const rejections = (['alice', 'bob'] as const).flatMap((verifier) => {
    const verification = verifications[verifier]
    return verification && !verification.verified ? [{ verifier, verification }] : []
  })
  const bothVerified = verifications.alice?.verified === true && verifications.bob?.verified === true

  return (
    <section className="dh-auth" aria-labelledby={id('dh-auth-title')}>
      <h2 id={id('dh-auth-title')}>Podpisy RSA</h2>
      <div className="dh-auth-parties">
        {(['alice', 'bob'] as const).map((role) => {
          const key = keys[role]
          const signature = signatures[role]
          const verifier = ROLES[role].other
          // Podpis roli sprawdza partner.
          const verification = verifications[verifier]
          const badge = !verification
            ? VERIFICATION_BADGE.pending
            : verification.verified
              ? VERIFICATION_BADGE.ok
              : VERIFICATION_BADGE.rejected
          return (
            <div className="dh-auth-party" key={role}>
              <h3>
                <RoleName role={role} />
              </h3>
              <dl>
                <div>
                  <dt>
                    Zaufany klucz publiczny (n, e) <DataBadge kind="public" />
                  </dt>
                  <dd className="formula">
                    {key ? `(${key.modulus}, ${key.publicExponent})` : '?'}
                  </dd>
                </div>
                <div>
                  <dt>Podpis transkryptu (s)</dt>
                  <dd className="formula">{signature?.signature ?? '?'}</dd>
                </div>
                <div>
                  <dt>Skrót transkryptu (SHA-256)</dt>
                  <dd className="dh-hash">{signature?.transcriptHash ?? '?'}</dd>
                </div>
                <div>
                  <dt>Weryfikacja przez {ROLES[verifier].nameOf}</dt>
                  <dd>
                    <Badge tone={badge.tone}>{badge.label}</Badge>
                  </dd>
                </div>
              </dl>
            </div>
          )
        })}
      </div>

      {bothVerified && (
        <p className="result result--ok">
          Obie strony zweryfikowały podpis partnera: wartości publiczne pochodzą od właścicieli
          zaufanych kluczy.
        </p>
      )}
      {rejections.length > 0 && (
        <div className="result result--error" role="status">
          <h3>Przyczyna odrzucenia</h3>
          {rejections.map(({ verifier, verification }) => (
            <p key={verifier}>
              Weryfikacja {ROLES[verifier].nameOf}: podpis {ROLES[verification.signer].nameOf}{' '}
              odrzucony.{' '}
              {verification.transcriptHash !== verification.publishedTranscriptHash ? (
                <>
                  Skrót transkryptu z widoku {ROLES[verifier].nameOf}{' '}
                  <code>{shortHash(verification.transcriptHash)}</code> różni się od skrótu
                  podpisanego przez {ROLES[verification.signer].nameOf}{' '}
                  <code>{shortHash(verification.publishedTranscriptHash)}</code> – strony widziały
                  inne wartości publiczne, czyli ktoś podmienił wiadomość po drodze.
                </>
              ) : (
                'Skróty są zgodne, ale podpis nie pasuje do zaufanego klucza publicznego.'
              )}
            </p>
          ))}
          <p>Wspólny sekret nie został zaakceptowany i nie jest pokazywany.</p>
        </div>
      )}
    </section>
  )
}

type DhValueProps = {
  kind: DataKind
  label: string
  // undefined: wartości jeszcze nie ma (pokazujemy „?”).
  value?: number
  // false: pole bez wartości liczbowej (klucz prywatny).
  withValue?: boolean
  // Krótki dopisek pod wartością, np. że jest dostarczona, ale nieprzyjęta.
  note?: string
  children: ReactNode
}

// Jedna wartość z oznaczeniem, czy jest tajna, czy jawna.
function DhValue({ kind, label, value, withValue = true, note, children }: DhValueProps) {
  const pending = withValue && value === undefined
  return (
    <div className={`dh-value dh-value--${kind}${pending ? ' dh-value--pending' : ''}`}>
      <div className="dh-value-header">
        <span>{label}</span>
        <DataBadge kind={kind} />
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
      {note && <p className="hint">{note}</p>}
    </div>
  )
}

// Porównanie sekretów obu stron. Pokazujemy dopiero, gdy oba węzły zgłosiły K
// w diagnostyce (węzły uruchomione z --allow-diagnostics).
function SessionResult({ session }: { session: DhSession }) {
  const { id, authenticated } = useScenario()
  // RSA + DH: K jest zaakceptowane dopiero po zakończeniu sesji.
  if (authenticated && session.status !== 'completed') return null
  const kA = session.nodes.alice.sharedKey
  const kB = session.nodes.bob.sharedKey
  if (kA === undefined || kB === undefined) return null

  const match = kA === kB
  return (
    <section
      className={`result dh-result result--${match ? 'ok' : 'error'}`}
      aria-labelledby={id('dh-result-title')}
    >
      {/* Same K są już w panelach węzłów, tu tylko werdykt i wyjaśnienie. */}
      <h2 id={id('dh-result-title')}>
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
      <p className="hint">
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
      <p className="hint">Brak sekretów Mallory w diagnostyce – nie da się ich porównać.</p>
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
// classicOnly: sekrety Mallory – w RSA + DH podmiana jest odrzucana, więc ich nie ma.
const COMPARE_ROWS: {
  label: ReactNode
  value: (session: DhSession) => number | undefined
  classicOnly?: boolean
}[] = [
  { label: 'A – wysłała Alice', value: (s) => s.nodes.alice.publicValue },
  { label: 'B – wysłał Bob', value: (s) => s.nodes.bob.publicValue },
  // Dostarczona wystarczy: w RSA + DH po odrzuceniu podpisu wartość nie zostaje przyjęta.
  { label: 'Alice otrzymała', value: (s) => s.nodes.alice.receivedValue ?? s.nodes.alice.deliveredValue },
  { label: 'Bob otrzymał', value: (s) => s.nodes.bob.receivedValue ?? s.nodes.bob.deliveredValue },
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
    classicOnly: true,
  },
  {
    label: (
      <>
        K<sub>MB</sub> – Mallory z Bobem
      </>
    ),
    value: (s) => s.mallory?.withBob,
    classicOnly: true,
  },
]

const COMPARED_MODES = ['normal', 'mitm'] as const

// Werdykt sesji: czy Alice i Bob mają ten sam K (o ile węzły zgłosiły diagnostykę).
function secretsVerdict(session: DhSession): { label: string; tone: Tone } {
  if (signatureRejected(session)) return { label: 'brak – podpis odrzucony', tone: 'error' }
  const kA = session.nodes.alice.sharedKey
  const kB = session.nodes.bob.sharedKey
  if (kA === undefined || kB === undefined) return { label: 'brak K w diagnostyce', tone: 'neutral' }
  return kA === kB ? { label: 'zgodne', tone: 'ok' } : { label: 'różne', tone: 'error' }
}

// Porównanie ostatniej zakończonej sesji zwykłej i ataku. Pokazuje tylko to, co przyszło
// z API; wartości różniące się między scenariuszami są wyróżnione.
// Domyślnie zwinięte. Po sesji tylko jednego scenariusza nie da się go rozwinąć –
// z jedną sesją nie ma czego porównać, więc podpowiadamy, który scenariusz uruchomić.
// RSA + DH: wynik weryfikacji podpisów w sesji.
function signaturesVerdict(session: DhSession): { label: string; tone: Tone } {
  if (signatureRejected(session)) return { label: 'odrzucone', tone: 'error' }
  return { label: 'zweryfikowane', tone: 'ok' }
}

function ScenarioComparison({ sessions }: { sessions: Partial<Record<DhMode, DhSession>> }) {
  const { authenticated, modeLabel, id } = useScenario()
  const rows = COMPARE_ROWS.filter((row) => !(authenticated && row.classicOnly))
  const { normal, mitm } = sessions
  if (!normal && !mitm) return null
  const missing = COMPARED_MODES.find((mode) => !sessions[mode])

  if (missing) {
    return (
      <section className="dh-compare" aria-labelledby={id('dh-compare-title')}>
        <div className="dh-collapsible-header dh-collapsible-header--disabled">
          <h2 id={id('dh-compare-title')}>Porównanie scenariuszy</h2>
        </div>
        <p className="hint">
          Uruchom scenariusz „{modeLabel[missing]}”, żeby porównać go z ostatnią sesją.
        </p>
      </section>
    )
  }

  return (
    <section className="dh-compare" aria-labelledby={id('dh-compare-title')}>
      <details>
        <summary className="dh-collapsible-header">
          <h2 id={id('dh-compare-title')}>Porównanie scenariuszy</h2>
        </summary>
        <p className="hint">
          {authenticated
            ? 'Ostatnia zakończona albo odrzucona sesja każdego scenariusza.'
            : 'Ostatnia zakończona sesja każdego scenariusza.'}
        </p>
        <div className="dh-log-scroll">
          <table>
            <thead>
              <tr>
                <th scope="col">Wartość</th>
                {COMPARED_MODES.map((mode) => (
                  <th scope="col" key={mode}>
                    {modeLabel[mode]}
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
              {rows.map((row, index) => {
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
              {authenticated && (
                <tr>
                  <th scope="row">Podpisy RSA</th>
                  {COMPARED_MODES.map((mode) => {
                    const s = sessions[mode]
                    if (!s) return <td key={mode}>–</td>
                    const verdict = signaturesVerdict(s)
                    return (
                      <td key={mode}>
                        <Badge tone={verdict.tone}>{verdict.label}</Badge>
                      </td>
                    )
                  })}
                </tr>
              )}
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
        <p className="hint">Wyróżnione wartości różnią się między scenariuszami.</p>
      </details>
    </section>
  )
}

// Uporządkowany dziennik zdarzeń koordynatora. Domyślnie zwinięty; rozwinięty zostaje
// rozwinięty przy kolejnych odczytach sesji.
function EventLog({
  events,
  interceptions,
}: {
  events: DhEvent[]
  interceptions: DhInterception[]
}) {
  const { id } = useScenario()
  return (
    <section className="dh-log" aria-labelledby={id('dh-log-title')}>
      <details>
        <summary className="dh-collapsible-header">
          <h2 id={id('dh-log-title')}>Dziennik zdarzeń</h2>
          <span className="dh-log-count">({events.length})</span>
        </summary>
        {events.length === 0 ? (
          <p className="hint">Brak zdarzeń w tej sesji.</p>
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
      </details>
    </section>
  )
}

// Wiersz dziennika. Zdarzenia sesji (utworzenie, start, koniec) nie mają nadawcy
// ani wartości, więc w tych kolumnach jest kreska.
// Po podmianie (message_forwarded, a potem message_processed) wiadomość naprawdę
// wysyła Mallory, podszywając się pod oryginalnego nadawcę – pokazujemy oba fakty
// i wartość, którą zastąpiła.
// Zdarzenia uwierzytelnienia (RSA + DH) mają tylko autora – przy weryfikacji
// weryfikującego → podpisującego – i zamiast statusu wiadomości wynik weryfikacji.
const AUTH_EVENTS: readonly EventType[] = [
  'trusted_key_published', 'signature_published', 'signature_verified', 'signature_rejected',
]

function EventRow({ event, interception }: { event: DhEvent; interception?: DhInterception }) {
  const status = MESSAGE_STATUS[event.status]
  const auth = AUTH_EVENTS.includes(event.type)
  const substituted =
    interception !== undefined &&
    (event.type === 'message_forwarded' || event.type === 'message_processed')
  if (auth) {
    return (
      <tr>
        <td className="dh-log-seq">{event.seq}</td>
        <td className="dh-log-type">{EVENT_TYPE[event.type]}</td>
        <td className={`dh-log-route${event.from ? '' : ' dh-log-empty'}`}>
          {event.from ? (
            <>
              <RoleName role={event.from} />
              {event.to && (
                <>
                  {' '}
                  → <RoleName role={event.to} />
                </>
              )}
            </>
          ) : (
            '–'
          )}
        </td>
        <td className="formula dh-log-value dh-log-empty" data-label="Wartość">
          –
        </td>
        <td className={`dh-log-status${event.verified === null ? ' dh-log-empty' : ''}`}>
          {event.verified === null ? (
            '–'
          ) : (
            <Badge tone={event.verified ? 'ok' : 'error'}>
              {event.verified ? 'podpis poprawny' : 'podpis odrzucony'}
            </Badge>
          )}
        </td>
      </tr>
    )
  }
  return (
    <tr>
      <td className="dh-log-seq">{event.seq}</td>
      <td className="dh-log-type">{EVENT_TYPE[event.type]}</td>
      <td className={`dh-log-route${event.from && event.to ? '' : ' dh-log-empty'}`}>
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
      <td
        className={`formula dh-log-value${event.value === null ? ' dh-log-empty' : ''}`}
        data-label="Wartość"
      >
        {event.value ?? '–'}
        {substituted && event.value !== interception.originalValue && (
          <span className="dh-replaced"> zamiast {interception.originalValue}</span>
        )}
      </td>
      <td className={`dh-log-status${event.from ? '' : ' dh-log-empty'}`}>
        {event.from ? <Badge tone={status.tone}>{status.label}</Badge> : '–'}
      </td>
    </tr>
  )
}

function RoleName({ role }: { role: NodeRole }) {
  return <span className={`dh-role dh-role--${role}`}>{NODE_NAME[role].name}</span>
}