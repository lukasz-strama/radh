// Komunikacja z backendem FastAPI (backend/app/api.py).

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

  constructor(message: string, code?: string) {
    super(message)
    this.code = code
  }
}

// Wysyła parametry do backendu i zwraca szyfrogram obliczony przez backend.
export async function encryptRsa(data: RsaEncryptRequest): Promise<RsaEncryptResponse> {
  const body = await requestJson('POST', '/api/v1/rsa/demo/encrypt', data)

  const ciphertext = (body as { ciphertext?: unknown } | null)?.ciphertext
  if (typeof ciphertext !== 'number') throw unexpectedFormat()
  return { ciphertext }
}

// Sesja DH (#38, #42) z koordynatora (#37, #41: backend/DH_SESSIONS.md, MITM_SESSIONS.md).
// Odpowiedź backendu sprawdzamy i mapujemy na model widoku w toDhSession().

const DH_SESSIONS_URL = '/api/v1/dh/sessions'

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

export type SessionStatus = 'created' | 'running' | 'completed' | 'cancelled'

export type EventType =
  | 'session_created'
  | 'session_started'
  | 'public_value'
  | 'message_intercepted'
  | 'message_forwarded'
  | 'message_processed'
  | 'session_completed'
  | 'session_cancelled'

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
  mode: DhMode
  p: number
  g: number
  status: SessionStatus
  nodes: Record<Role, DhNode>
  // Tylko w trybie MITM; w zwykłej wymianie null.
  mallory: DhMallory | null
  events: DhEvent[]
}

// Tworzy sesję i od razu ją uruchamia; zwraca stan po starcie.
// Gdy start się nie uda (np. 409 MALLORY_UNAVAILABLE), anulujemy utworzoną sesję,
// żeby nie blokowała następnej.
export async function startDhSession(
  params: DhSessionParams,
  mode: DhMode,
): Promise<DhSession> {
  const created = toDhSession(await requestJson('POST', DH_SESSIONS_URL, { ...params, mode }))
  try {
    return toDhSession(await requestJson('POST', `${DH_SESSIONS_URL}/${created.id}/start`))
  } catch (error) {
    await cancelDhSession(created.id).catch(() => undefined)
    throw error
  }
}

// Zwraca bieżący stan sesji: postęp uczestników, wiadomości, przechwycenia i dziennik.
export async function fetchDhSession(id: string): Promise<DhSession> {
  return toDhSession(await requestJson('GET', `${DH_SESSIONS_URL}/${id}`))
}

export async function cancelDhSession(id: string): Promise<DhSession> {
  return toDhSession(await requestJson('POST', `${DH_SESSIONS_URL}/${id}/cancel`))
}

// Anuluje bieżącą sesję koordynatora, jeśli jeszcze trwa (np. pozostałą po odświeżeniu
// strony). Koordynator trzyma jedną sesję naraz, więc inaczej nowej nie da się zacząć.
export async function cancelActiveDhSession(): Promise<void> {
  let current: DhSession
  try {
    current = toDhSession(await requestJson('GET', `${DH_SESSIONS_URL}/current`))
  } catch (error) {
    if (error instanceof ApiError && error.code === 'SESSION_NOT_FOUND') return
    throw error
  }
  if (current.status === 'created' || current.status === 'running') {
    await cancelDhSession(current.id)
  }
}

// Dostępność procesu węzła: ostatni heartbeat (co 1 s) nie starszy niż 5 s.
// lastSeen === null: węzeł jeszcze się nie zgłosił. To informacja o ostatnim kontakcie,
// nie gwarancja, że proces za chwilę nie przestanie działać.
export type NodeAvailability = {
  online: boolean
  lastSeen: string | null
}

export type NodesAvailability = Record<Role, NodeAvailability> & {
  // Starszy backend bez MITM nie zgłasza Mallory.
  mallory?: NodeAvailability
}

export async function fetchDhNodes(): Promise<NodesAvailability> {
  const body = (await requestJson('GET', '/api/v1/dh/nodes')) as Record<string, unknown> | null
  function node(role: NodeRole): NodeAvailability {
    const raw = body?.[role] as Record<string, unknown> | undefined
    if (
      !raw ||
      typeof raw.online !== 'boolean' ||
      (raw.last_seen !== null && typeof raw.last_seen !== 'string')
    ) {
      throw unexpectedFormat()
    }
    return { online: raw.online, lastSeen: raw.last_seen }
  }
  return {
    alice: node('alice'),
    bob: node('bob'),
    ...(body?.mallory === undefined ? {} : { mallory: node('mallory') }),
  }
}

// K zgłoszone przez węzły uruchomione z --allow-diagnostics; null = brak zgłoszenia.
// Przechowywane osobno od wiadomości i zdarzeń protokołu.
export async function fetchDhDiagnostics(id: string): Promise<Record<Role, number | null>> {
  const body = (await requestJson('GET', `${DH_SESSIONS_URL}/${id}/diagnostics`)) as Record<
    string,
    unknown
  > | null
  if (!body) throw unexpectedFormat()
  return { alice: numberOrNull(body.alice), bob: numberOrNull(body.bob) }
}

// Dwa K Mallory: uzgodnione z Alice i z Bobem; null = brak raportu.
export async function fetchDhMalloryDiagnostics(
  id: string,
): Promise<{ withAlice: number | null; withBob: number | null }> {
  const body = (await requestJson(
    'GET',
    `${DH_SESSIONS_URL}/${id}/diagnostics/mallory`,
  )) as Record<string, unknown> | null
  if (!body) throw unexpectedFormat()
  return {
    withAlice: numberOrNull(body.shared_with_alice),
    withBob: numberOrNull(body.shared_with_bob),
  }
}

function numberOrNull(value: unknown): number | null {
  if (value !== null && typeof value !== 'number') throw unexpectedFormat()
  return value
}

const ROLES: readonly Role[] = ['alice', 'bob']
const NODE_ROLES: readonly NodeRole[] = ['alice', 'bob', 'mallory']
const MODES: readonly DhMode[] = ['normal', 'mitm']
const SESSION_STATUSES: readonly SessionStatus[] = ['created', 'running', 'completed', 'cancelled']
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
    typeof raw.session_id !== 'string' ||
    !isOneOf(MODES, raw.mode) ||
    typeof raw.prime !== 'number' ||
    typeof raw.generator !== 'number' ||
    !isOneOf(SESSION_STATUSES, raw.status) ||
    !participants ||
    !ROLES.every((role) => isOneOf(PARTICIPANT_STATUSES, participants[role])) ||
    !Array.isArray(raw.messages) ||
    !Array.isArray(raw.events) ||
    !Array.isArray(rawInterceptions)
  ) {
    throw unexpectedFormat()
  }

  const messages = raw.messages.map((item): RawMessage => {
    const message = item as Record<string, unknown> | null
    if (
      !message ||
      !isOneOf(ROLES, message.sender) ||
      !isOneOf(ROLES, message.recipient) ||
      typeof message.public_value !== 'number' ||
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
      typeof record.original_value !== 'number' ||
      (delivered !== null && typeof delivered !== 'number') ||
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
      typeof event.sequence !== 'number' ||
      !isOneOf(EVENT_TYPES, event.type) ||
      !isOneOfOrNull(NODE_ROLES, event.sender) ||
      !isOneOfOrNull(ROLES, event.recipient) ||
      (value !== null && typeof value !== 'number') ||
      (messageId !== null && messageId !== undefined && typeof messageId !== 'string') ||
      !isOneOf(MESSAGE_STATUSES, event.status)
    ) {
      throw unexpectedFormat()
    }
    return {
      seq: event.sequence,
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
  method: 'GET' | 'POST',
  url: string,
  data?: unknown,
): Promise<unknown> {
  let response: Response
  try {
    response = await fetch(url, {
      method,
      headers: data === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: data === undefined ? undefined : JSON.stringify(data),
    })
  } catch {
    // fetch rzuca wyjątek, gdy w ogóle nie da się wysłać żądania.
    throw new ApiError('Brak połączenia z serwerem. Sprawdź połączenie i spróbuj ponownie.')
  }

  const body: unknown = await response.json().catch(() => null)

  if (!response.ok) {
    throw toApiError(response.status, body)
  }
  return body
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