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

// Sesja DH (#38) z koordynatora (#37, backend/DH_SESSIONS.md).
// Odpowiedź backendu sprawdzamy i mapujemy na model widoku w toDhSession().

const DH_SESSIONS_URL = '/api/v1/dh/sessions'

export type DhSessionParams = {
  prime: number
  generator: number
}

// Uczestnicy sesji. M3: dojdzie 'mallory'.
export type Role = 'alice' | 'bob'

// Postęp uczestnika potwierdzony przez koordynatora: waiting → published → received.
// published: koordynator przyjął jego wartość publiczną;
// received: węzeł potwierdził przetworzenie wartości partnera.
export type ParticipantStatus = 'waiting' | 'published' | 'received'

export type SessionStatus = 'created' | 'running' | 'completed' | 'cancelled'

export type EventType =
  | 'session_created'
  | 'session_started'
  | 'public_value'
  | 'message_processed'
  | 'session_completed'
  | 'session_cancelled'

export type MessageStatus = 'queued' | 'processed'

// Stan jednego uczestnika. Brak wartości = jeszcze jej nie ma.
export type DhNode = {
  status: ParticipantStatus
  publicValue?: number
  receivedValue?: number
  // K z diagnostyki węzła. API #37 go nie udostępnia, więc na razie zawsze undefined.
  sharedKey?: number
}

// Zdarzenie z dziennika koordynatora. Zdarzenia sesji nie mają nadawcy ani wartości.
export type DhEvent = {
  seq: number
  type: EventType
  from: Role | null
  to: Role | null
  value: number | null
  status: MessageStatus
}

export type DhSession = {
  id: string
  p: number
  g: number
  status: SessionStatus
  nodes: Record<Role, DhNode>
  events: DhEvent[]
}

// Tworzy sesję i od razu ją uruchamia; zwraca stan po starcie.
// Gdy start się nie uda, anulujemy utworzoną sesję, żeby nie blokowała następnej.
export async function startDhSession(params: DhSessionParams): Promise<DhSession> {
  const created = toDhSession(
    await requestJson('POST', DH_SESSIONS_URL, { ...params, mode: 'normal' }),
  )
  try {
    return toDhSession(await requestJson('POST', `${DH_SESSIONS_URL}/${created.id}/start`))
  } catch (error) {
    await cancelDhSession(created.id).catch(() => undefined)
    throw error
  }
}

// Zwraca bieżący stan sesji: postęp uczestników, wiadomości i dziennik zdarzeń.
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

const ROLES: readonly Role[] = ['alice', 'bob']
const SESSION_STATUSES: readonly SessionStatus[] = ['created', 'running', 'completed', 'cancelled']
const PARTICIPANT_STATUSES: readonly ParticipantStatus[] = ['waiting', 'published', 'received']
const MESSAGE_STATUSES: readonly MessageStatus[] = ['queued', 'processed']
const EVENT_TYPES: readonly EventType[] = [
  'session_created',
  'session_started',
  'public_value',
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

function isRoleOrNull(value: unknown): value is Role | null {
  return value === null || isOneOf(ROLES, value)
}

// Sprawdza odpowiedź sesji i zamienia ją na model widoku. Niepełna albo
// niezgodna odpowiedź to błąd: nie pokazujemy częściowo poprawnych danych.
function toDhSession(body: unknown): DhSession {
  const raw = body as Record<string, unknown> | null
  const participants = raw?.participants as Record<string, unknown> | undefined
  if (
    !raw ||
    typeof raw.session_id !== 'string' ||
    typeof raw.prime !== 'number' ||
    typeof raw.generator !== 'number' ||
    !isOneOf(SESSION_STATUSES, raw.status) ||
    !participants ||
    !ROLES.every((role) => isOneOf(PARTICIPANT_STATUSES, participants[role])) ||
    !Array.isArray(raw.messages) ||
    !Array.isArray(raw.events)
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

  const events = raw.events.map((item): DhEvent => {
    const event = item as Record<string, unknown> | null
    const value = event?.public_value
    if (
      !event ||
      typeof event.sequence !== 'number' ||
      !isOneOf(EVENT_TYPES, event.type) ||
      !isRoleOrNull(event.sender) ||
      !isRoleOrNull(event.recipient) ||
      (value !== null && typeof value !== 'number') ||
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
      status: event.status,
    }
  })

  // Wartość publiczna uczestnika: jego wiadomość przyjęta przez koordynatora.
  // Otrzymana: wiadomość do niego, której przetworzenie potwierdził.
  function node(role: Role): DhNode {
    return {
      status: participants![role] as ParticipantStatus,
      publicValue: messages.find((m) => m.sender === role)?.public_value,
      receivedValue: messages.find((m) => m.recipient === role && m.status === 'processed')
        ?.public_value,
    }
  }

  return {
    id: raw.session_id,
    p: raw.prime,
    g: raw.generator,
    status: raw.status,
    nodes: { alice: node('alice'), bob: node('bob') },
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