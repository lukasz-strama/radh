// Komunikacja z FastAPI. Sesje v2 używają poświadczeń własnej karty.
import {
  currentCredential, forgetCredential, forgetPendingCreation, isSessionId,
  newCreationKey, pendingCreation, saveCredential, savePendingCreation,
} from './dhCredentials'
import type { SessionCredential } from './dhCredentials'

export { currentCredential } from './dhCredentials'

type RequestOptions = {
  signal?: AbortSignal
  headers?: Record<string, string>
  epoch?: string
  onResponse?: (response: Response) => void
}

export type RsaEncryptRequest = {
  message: number
  public_exponent: number
  modulus: number
}

export type RsaEncryptResponse = {
  ciphertext: number
}

// Błąd z czytelnym komunikatem dla użytkownika.
// `code` to stały identyfikator z backendu (np. MESSAGE_OUT_OF_RANGE), jeśli przyszedł.
export class ApiError extends Error {
  readonly code?: string
  readonly status: number
  readonly retryAfter: number

  constructor(message: string, code?: string, status = 0, retryAfter = 0) {
    super(message)
    this.code = code
    this.status = status
    this.retryAfter = retryAfter
  }
}

// Wysyła parametry do backendu i zwraca szyfrogram obliczony przez backend.
export async function encryptRsa(data: RsaEncryptRequest): Promise<RsaEncryptResponse> {
  const body = await requestJson('POST', '/api/v1/rsa/demo/encrypt', data)

  const ciphertext = (body as { ciphertext?: unknown } | null)?.ciphertext
  if (typeof ciphertext !== 'number') throw unexpectedFormat()
  return { ciphertext }
}

// Generowanie edukacyjnej pary kluczy RSA (#56, backend/README.md).
// Wszystkie wartości liczy CryptoCore; frontend tylko je pokazuje.
export type RsaKeygenRequest = {
  p: number
  q: number
  e: number
}

export type RsaKeygenResponse = {
  n: number
  e: number
  d: number
  phi: number
}

export async function generateRsaKeys(data: RsaKeygenRequest): Promise<RsaKeygenResponse> {
  const body = (await requestJson('POST', '/api/v1/rsa/demo/keygen', data)) as Record<
    string,
    unknown
  > | null
  const { n, e, d, phi } = body ?? {}
  if (
    typeof n !== 'number' ||
    typeof e !== 'number' ||
    typeof d !== 'number' ||
    typeof phi !== 'number'
  ) {
    throw unexpectedFormat()
  }
  return { n, e, d, phi }
}

// Sesja DH (#38, #42) z koordynatora (#37, #41: backend/DH_SESSIONS.md, MITM_SESSIONS.md).
// Odpowiedź backendu sprawdzamy i mapujemy na model widoku w toDhSession().

const DH_SESSIONS_URL = '/api/v2/dh/sessions'

// Scenariusz sesji: zwykła wymiana albo atak Man-in-the-Middle (#42).
// Tryb wybiera się przed startem; od niego zależy routing wiadomości w koordynatorze.
export type DhMode = 'normal' | 'mitm'

export type DhSessionParams = {
  prime: number
  generator: number
}

// Ofiary wymiany. Mallory jest osobnym węzłem, ale nie uczestnikiem sesji (#41).
export type Role = 'alice' | 'bob'
export type NodeRole = Role | 'mallory'

// Postęp uczestnika potwierdzony przez koordynatora: waiting → published → received.
// published: koordynator przyjął jego wartość publiczną;
// received: węzeł potwierdził przetworzenie otrzymanej wartości.
export type ParticipantStatus = 'waiting' | 'published' | 'received'

export type SessionStatus = 'created' | 'running' | 'completed' | 'cancelled' | 'expired' | 'failed'

export type EventType =
  | 'session_created'
  | 'session_started'
  | 'public_value'
  | 'message_intercepted'
  | 'message_forwarded'
  | 'message_processed'
  | 'session_completed'
  | 'session_cancelled'
  | 'session_failed'
  | 'session_expired'

// intercepted: oryginał zatrzymany u Mallory, nigdy nie trafia do kolejki ofiary.
export type MessageStatus = 'intercepted' | 'queued' | 'processed'

// Przechwycenie w MITM: pending (czeka na Mallory) → forwarded (Mallory odesłała
// podmianę) → processed (odbiorca potwierdził jej przetworzenie).
export type InterceptionStatus = 'pending' | 'forwarded' | 'processed'

export type DhInterception = {
  messageId: string
  originalSender: Role
  recipient: Role
  originalValue: number
  // null, dopóki Mallory nie odeśle podmiany.
  deliveredValue: number | null
  status: InterceptionStatus
}

// Stan jednego uczestnika. Brak wartości = jeszcze jej nie ma.
export type DhNode = {
  status: ParticipantStatus
  publicValue?: number
  receivedValue?: number
  // K z diagnostyki węzła (fetchDhDiagnostics); nie jest częścią wiadomości protokołu.
  sharedKey?: number
}

// Mallory w sesji MITM, wyprowadzona z rekordów przechwyceń i jej diagnostyki.
export type DhMallory = {
  fromAlice?: number
  toBob?: number
  fromBob?: number
  toAlice?: number
  // K uzgodnione z każdą ofiarą (fetchDhMalloryDiagnostics).
  withAlice?: number
  withBob?: number
  interceptions: DhInterception[]
}

// Zdarzenie z dziennika koordynatora. Zdarzenia sesji nie mają nadawcy ani wartości.
// W message_forwarded nadawcą jest Mallory; w message_processed – deklarowany nadawca.
export type DhEvent = {
  seq: number
  type: EventType
  from: NodeRole | null
  to: Role | null
  value: number | null
  messageId: string | null
  status: MessageStatus
}

export type DhSession = {
  id: string
  epoch: string
  revision: number
  expiresAt: string
  terminalAt: string | null
  diagnosticsEnabled: boolean
  failureCode: string | null
  mode: DhMode
  p: number
  g: number
  status: SessionStatus
  nodes: Record<Role, DhNode>
  // Tylko w trybie MITM; w zwykłej wymianie null.
  mallory: DhMallory | null
  events: DhEvent[]
}

// Tworzenie ponawiamy wyłącznie po świadomym kliknięciu, z zapisanym kluczem.
export async function startDhSession(
  params: DhSessionParams,
  mode: DhMode,
  diagnosticsEnabled = false,
  signal?: AbortSignal,
): Promise<DhSession> {
  if (currentCredential()) {
    throw new ApiError('Najpierw usuń własną poprzednią sesję przyciskiem Reset.', 'SESSION_ACTIVE')
  }
  const nodes = await fetchDhNodes(signal)
  const body = { ...params, mode, diagnostics_enabled: diagnosticsEnabled }
  let pending = pendingCreation()
  if (pending && (pending.epoch !== nodes.backendEpoch || Date.now() - pending.createdAt >= 60_000 ||
      Date.now() < pending.createdAt || JSON.stringify(pending.params) !== JSON.stringify(body))) {
    throw new ApiError(
      'Poprzednia próba utworzenia wymaga porzucenia. Kliknij Reset, a następnie rozpocznij nową sesję.',
      'CREATE_RETRY_EXPIRED',
    )
  }
  if (!pending) {
    pending = { key: newCreationKey(), epoch: nodes.backendEpoch, createdAt: Date.now(), params: body }
    savePendingCreation(pending)
  }
  const result = await requestJson('POST', DH_SESSIONS_URL, body, {
    signal, epoch: pending.epoch,
    headers: { 'Idempotency-Key': pending.key, 'X-Backend-Epoch': pending.epoch },
  }) as { session?: unknown; session_token?: unknown } | null
  const session = toDhSession({ ...(result?.session as object), events: [] })
  if (typeof result?.session_token !== 'string' || !/^[A-Za-z0-9_-]{43}$/.test(result.session_token) ||
      session.epoch !== pending.epoch) throw unexpectedFormat()
  signal?.throwIfAborted()
  saveCredential({ id: session.id, token: result.session_token, epoch: session.epoch })
  forgetPendingCreation(pending.key)
  // Przy błędzie startu zachowujemy ID/token do wznowienia albo usunięcia.
  return resumeDhSession(session.id, signal)
}

function credentialFor(id: string): SessionCredential {
  const own = currentCredential()
  if (!own || own.id !== id) throw new ApiError('Brak poświadczenia własnej sesji.', 'UNAUTHORIZED', 401)
  return own
}

async function ownRequest(method: 'GET' | 'POST' | 'DELETE', id: string, suffix = '', signal?: AbortSignal) {
  const own = credentialFor(id)
  try {
    return await requestJson(method, DH_SESSIONS_URL + '/' + id + suffix, undefined, {
      signal, epoch: own.epoch, headers: { Authorization: 'Bearer ' + own.token },
    })
  } catch (error) {
    if (error instanceof ApiError &&
        (error.status === 404 || error.status === 410 || error.code === 'BACKEND_EPOCH_MISMATCH')) {
      forgetCredential(own)
    }
    throw error
  }
}

export async function resumeDhSession(id: string, signal?: AbortSignal): Promise<DhSession> {
  const raw = await ownRequest('POST', id, '/start', signal)
  const session = toDhSession({ ...(raw as object), events: [] })
  if (session.id !== id || session.epoch !== credentialFor(id).epoch) throw unexpectedFormat()
  return session
}

export async function fetchDhSession(id: string, signal?: AbortSignal): Promise<DhSession> {
  const raw = await ownRequest('GET', id, '', signal) as Record<string, unknown> | null
  if (!raw) throw unexpectedFormat()
  const history = await ownRequest('GET', id, '/events?after=0&limit=32', signal) as Record<string, unknown>
  if (!history || history.session_id !== id || history.backend_epoch !== raw.backend_epoch) throw unexpectedFormat()
  const session = toDhSession({ ...raw, events: history.events })
  if (session.id !== id || session.epoch !== credentialFor(id).epoch) throw unexpectedFormat()
  return session
}

export async function cancelDhSession(id: string, signal?: AbortSignal): Promise<DhSession> {
  const raw = await ownRequest('POST', id, '/cancel', signal)
  const session = toDhSession({ ...(raw as object), events: [] })
  if (session.id !== id || session.epoch !== credentialFor(id).epoch) throw unexpectedFormat()
  return session
}

export async function deleteDhSession(id: string, signal?: AbortSignal): Promise<void> {
  const own = credentialFor(id)
  await ownRequest('DELETE', id, '', signal)
  forgetCredential(own)
}

// Reset dotyczy wyłącznie sesji i próby tworzenia zapisanych w tej karcie.
export async function resetOwnDhSession(signal?: AbortSignal): Promise<void> {
  const own = currentCredential()
  if (own) {
    try {
      await deleteDhSession(own.id, signal)
    } catch (error) {
      if (!(error instanceof ApiError && (error.status === 404 || error.status === 410))) throw error
    }
  }
  forgetPendingCreation()
}

export type NodeAvailability = { online: boolean }
export type NodesAvailability = Record<NodeRole, NodeAvailability> & { backendEpoch: string }

export async function fetchDhNodes(signal?: AbortSignal): Promise<NodesAvailability> {
  let epoch: string | null = null
  const body = await requestJson('GET', '/api/v2/dh/nodes', undefined, {
    signal, onResponse: (response) => { epoch = response.headers.get('X-Backend-Epoch') },
  }) as Record<string, unknown> | null
  if (!isSessionId(epoch)) throw unexpectedFormat()
  function node(role: NodeRole): NodeAvailability {
    const raw = body?.[role] as Record<string, unknown> | undefined
    if (!raw || typeof raw.online !== 'boolean') throw unexpectedFormat()
    return { online: raw.online }
  }
  return { alice: node('alice'), bob: node('bob'), mallory: node('mallory'), backendEpoch: epoch }
}

export async function fetchDhDiagnostics(id: string, signal?: AbortSignal): Promise<Record<Role, number | null>> {
  const body = await ownRequest('GET', id, '/diagnostics', signal) as Record<string, unknown> | null
  if (!body) throw unexpectedFormat()
  return { alice: numberOrNull(body.alice), bob: numberOrNull(body.bob) }
}

export async function fetchDhMalloryDiagnostics(id: string, signal?: AbortSignal):
Promise<{ withAlice: number | null; withBob: number | null }> {
  const body = await ownRequest('GET', id, '/diagnostics/mallory', signal) as Record<string, unknown> | null
  if (!body) throw unexpectedFormat()
  return { withAlice: numberOrNull(body.shared_with_alice), withBob: numberOrNull(body.shared_with_bob) }
}

function uint32(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0 && value <= 4294967295
}

function numberOrNull(value: unknown): number | null {
  if (value !== null && !uint32(value)) throw unexpectedFormat()
  return value
}

const ROLES: readonly Role[] = ['alice', 'bob']
const NODE_ROLES: readonly NodeRole[] = ['alice', 'bob', 'mallory']
const MODES: readonly DhMode[] = ['normal', 'mitm']
const SESSION_STATUSES: readonly SessionStatus[] = ['created', 'running', 'completed', 'cancelled', 'expired', 'failed']
const PARTICIPANT_STATUSES: readonly ParticipantStatus[] = ['waiting', 'published', 'received']
const MESSAGE_STATUSES: readonly MessageStatus[] = ['intercepted', 'queued', 'processed']
const INTERCEPTION_STATUSES: readonly InterceptionStatus[] = ['pending', 'forwarded', 'processed']
const EVENT_TYPES: readonly EventType[] = [
  'session_created',
  'session_started',
  'public_value',
  'message_intercepted',
  'message_forwarded',
  'message_processed',
  'session_completed',
  'session_cancelled',
  'session_failed',
  'session_expired',
]

type RawMessage = {
  sender: Role
  recipient: Role
  public_value: number
  status: MessageStatus
}

function isOneOf<T extends string>(values: readonly T[], value: unknown): value is T {
  return typeof value === 'string' && (values as readonly string[]).includes(value)
}

function isOneOfOrNull<T extends string>(values: readonly T[], value: unknown): value is T | null {
  return value === null || isOneOf(values, value)
}

// Sprawdza odpowiedź sesji i zamienia ją na model widoku. Niepełna albo
// niezgodna odpowiedź to błąd: nie pokazujemy częściowo poprawnych danych.
function toDhSession(body: unknown): DhSession {
  const raw = body as Record<string, unknown> | null
  const participants = raw?.participants as Record<string, unknown> | undefined
  // Starszy backend (#37 bez #41) nie zwraca interceptions – wtedy brak przechwyceń.
  const rawInterceptions = raw?.interceptions ?? []
  if (
    !raw ||
    !isSessionId(raw.session_id) ||
    !isSessionId(raw.backend_epoch) ||
    !Number.isInteger(raw.revision) || (raw.revision as number) < 0 ||
    typeof raw.expires_at !== 'string' || !Number.isFinite(Date.parse(raw.expires_at)) ||
    (raw.terminal_at !== null && (typeof raw.terminal_at !== 'string' || !Number.isFinite(Date.parse(raw.terminal_at)))) ||
    typeof raw.diagnostics_enabled !== 'boolean' ||
    (raw.failure_code !== null && typeof raw.failure_code !== 'string') ||
    !isOneOf(MODES, raw.mode) ||
    !uint32(raw.prime) ||
    !uint32(raw.generator) ||
    !isOneOf(SESSION_STATUSES, raw.status) ||
    !participants ||
    !ROLES.every((role) => isOneOf(PARTICIPANT_STATUSES, participants[role])) ||
    !Array.isArray(raw.messages) || raw.messages.length > 2 ||
    !Array.isArray(raw.events) || raw.events.length > 32 ||
    !Array.isArray(rawInterceptions) || rawInterceptions.length > 2
  ) {
    throw unexpectedFormat()
  }

  const messages = raw.messages.map((item): RawMessage => {
    const message = item as Record<string, unknown> | null
    if (
      !message ||
      !isOneOf(ROLES, message.sender) ||
      !isOneOf(ROLES, message.recipient) ||
      !uint32(message.public_value) ||
      !isOneOf(MESSAGE_STATUSES, message.status)
    ) {
      throw unexpectedFormat()
    }
    return {
      sender: message.sender,
      recipient: message.recipient,
      public_value: message.public_value,
      status: message.status,
    }
  })

  const interceptions = rawInterceptions.map((item): DhInterception => {
    const record = item as Record<string, unknown> | null
    const delivered = record?.delivered_value
    if (
      !record ||
      typeof record.message_id !== 'string' ||
      !isOneOf(ROLES, record.original_sender) ||
      !isOneOf(ROLES, record.recipient) ||
      !uint32(record.original_value) ||
      (delivered !== null && !uint32(delivered)) ||
      !isOneOf(INTERCEPTION_STATUSES, record.status)
    ) {
      throw unexpectedFormat()
    }
    return {
      messageId: record.message_id,
      originalSender: record.original_sender,
      recipient: record.recipient,
      originalValue: record.original_value,
      deliveredValue: delivered as number | null,
      status: record.status,
    }
  })

  const events = raw.events.map((item): DhEvent => {
    const event = item as Record<string, unknown> | null
    const value = event?.public_value
    const messageId = event?.message_id
    if (
      !event ||
      !Number.isInteger(event.sequence) || (event.sequence as number) < 1 ||
      !isOneOf(EVENT_TYPES, event.type) ||
      !isOneOfOrNull(NODE_ROLES, event.sender) ||
      !isOneOfOrNull(ROLES, event.recipient) ||
      (value !== null && !uint32(value)) ||
      (messageId !== null && messageId !== undefined && typeof messageId !== 'string') ||
      !isOneOf(MESSAGE_STATUSES, event.status)
    ) {
      throw unexpectedFormat()
    }
    return {
      seq: event.sequence as number,
      type: event.type,
      from: event.sender,
      to: event.recipient,
      value: value as number | null,
      messageId: (messageId as string | null | undefined) ?? null,
      status: event.status,
    }
  })

  const mitm = raw.mode === 'mitm'

  // Zwykła wymiana: wartość własna to wiadomość od uczestnika, otrzymana – wiadomość
  // do niego, której przetworzenie potwierdził.
  // MITM: messages[].public_value po podmianie zawiera już zamiennik, a sender to
  // deklarowana (podszyta) tożsamość. Dlatego wartość własną bierzemy z oryginału
  // przechwycenia, a otrzymaną z wartości doręczonej po jej przetworzeniu (#41).
  function node(role: Role): DhNode {
    const status = participants![role] as ParticipantStatus
    if (mitm) {
      const own = interceptions.find((i) => i.originalSender === role)
      const received = interceptions.find((i) => i.recipient === role && i.status === 'processed')
      return {
        status,
        publicValue: own?.originalValue,
        receivedValue: received?.deliveredValue ?? undefined,
      }
    }
    return {
      status,
      publicValue: messages.find((m) => m.sender === role)?.public_value,
      receivedValue: messages.find((m) => m.recipient === role && m.status === 'processed')
        ?.public_value,
    }
  }

  // Mallory: oryginał od Alice zastępuje wartością dla Boba (Y) i odwrotnie (X).
  function mallory(): DhMallory {
    const fromAlice = interceptions.find((i) => i.originalSender === 'alice')
    const fromBob = interceptions.find((i) => i.originalSender === 'bob')
    return {
      fromAlice: fromAlice?.originalValue,
      toBob: fromAlice?.deliveredValue ?? undefined,
      fromBob: fromBob?.originalValue,
      toAlice: fromBob?.deliveredValue ?? undefined,
      interceptions,
    }
  }

  return {
    id: raw.session_id,
    epoch: raw.backend_epoch,
    revision: raw.revision as number,
    expiresAt: raw.expires_at,
    terminalAt: raw.terminal_at as string | null,
    diagnosticsEnabled: raw.diagnostics_enabled,
    failureCode: raw.failure_code as string | null,
    mode: raw.mode,
    p: raw.prime,
    g: raw.generator,
    status: raw.status,
    nodes: { alice: node('alice'), bob: node('bob') },
    mallory: mitm ? mallory() : null,
    events: [...events].sort((x, y) => x.seq - y.seq),
  }
}

// Wysyła żądanie (z JSON-em, jeśli jest treść) i zwraca treść odpowiedzi;
// błędy zamienia na ApiError.
async function requestJson(
  method: 'GET' | 'POST' | 'DELETE',
  url: string,
  data?: unknown,
  options: RequestOptions = {},
): Promise<unknown> {
  const controller = new AbortController()
  const abort = () => controller.abort(options.signal?.reason)
  options.signal?.addEventListener('abort', abort, { once: true })
  if (options.signal?.aborted) abort()
  const timeout = window.setTimeout(() => controller.abort(), 5000)
  try {
    const response = await fetch(url, {
      method, signal: controller.signal, cache: 'no-store',
      headers: { ...(data === undefined ? {} : { 'Content-Type': 'application/json' }), ...options.headers },
      body: data === undefined ? undefined : JSON.stringify(data),
    })
    if (options.epoch && response.headers.get('X-Backend-Epoch') !== options.epoch) {
      throw new ApiError('Serwer uruchomił się ponownie. Rozpocznij nową sesję.', 'BACKEND_EPOCH_MISMATCH')
    }
    options.onResponse?.(response)
    const body: unknown = response.status === 204 ? null : await response.json().catch(() => null)
    options.signal?.throwIfAborted()
    controller.signal.throwIfAborted()
    if (!response.ok) {
      const retry = response.headers.get('Retry-After')
      const seconds = retry && /^\d+$/.test(retry) ? Math.min(Number(retry), 30) : 0
      const error = toApiError(response.status, body)
      throw new ApiError(error.message, error.code, response.status, seconds)
    }
    return body
  } catch (error) {
    options.signal?.throwIfAborted()
    if (error instanceof ApiError) throw error
    throw new ApiError(
      controller.signal.aborted ? 'Serwer nie odpowiedział w wymaganym czasie.' :
        'Brak połączenia z serwerem. Spróbuj ponownie.',
      controller.signal.aborted ? 'REQUEST_TIMEOUT' : 'NETWORK_ERROR',
    )
  } finally {
    window.clearTimeout(timeout)
    options.signal?.removeEventListener('abort', abort)
  }
}

function unexpectedFormat(): ApiError {
  return new ApiError('Backend zwrócił odpowiedź w nieoczekiwanym formacie.')
}

// Backend zwraca błędy w formacie: { "error": { "code": "...", "message": "..." } }.
function toApiError(status: number, body: unknown): ApiError {
  const error = (body as { error?: { code?: unknown; message?: unknown } } | null)?.error
  if (error && typeof error.message === 'string' && error.message !== '') {
    const code = typeof error.code === 'string' ? error.code : undefined
    return new ApiError(error.message, code)
  }

  // Fallback: domyślny format błędów FastAPI ({ "detail": "..." }).
  const detail = (body as { detail?: unknown } | null)?.detail
  if (typeof detail === 'string' && detail !== '') {
    return new ApiError(detail)
  }

  // Brak odpowiedzi JSON z backendu – najczęściej proxy Vite nie może się z nim
  // połączyć (backend nie jest uruchomiony) i samo zwraca 502/503/504.
  if (status === 502 || status === 503 || status === 504) {
    return new ApiError(
      'Nie można połączyć się z backendem. Upewnij się, że serwer FastAPI działa.',
    )
  }
  if (status >= 400 && status < 500) {
    return new ApiError(`Serwer odrzucił dane (błąd ${status}). Sprawdź wprowadzone wartości.`)
  }
  return new ApiError(`Wystąpił błąd serwera (błąd ${status}). Spróbuj ponownie później.`)
}