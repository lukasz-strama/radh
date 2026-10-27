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
  const body = await postJson('/api/v1/rsa/demo/encrypt', data)

  const ciphertext = (body as { ciphertext?: unknown } | null)?.ciphertext
  if (typeof ciphertext !== 'number') throw unexpectedFormat()
  return { ciphertext }
}

// Sesja DH (#38). Kształt danych to propozycja frontendu; po ustaleniu kontraktu
// w #37 odpowiedź backendu mapujemy na te typy w funkcjach poniżej.

export type DhSessionParams = {
  prime: number
  generator: number
}

// Uczestnicy sesji. M3: dojdzie 'mallory'.
export type Role = 'alice' | 'bob'

// Stan węzła. Fazy idle, public_ready, complete pochodzą z węzłów (#36, NodeState.phase);
// offline i error zgłasza koordynator, bo niedziałający węzeł sam o sobie nie powie.
export type NodeStatus = 'offline' | 'idle' | 'public_ready' | 'complete' | 'error'

export type SessionStatus = 'running' | 'completed' | 'failed'

export type EventStatus = 'accepted' | 'rejected'

// Stan jednego węzła. Brak wartości = węzeł jeszcze jej nie zgłosił.
export type DhNode = {
  status: NodeStatus
  publicValue?: number
  receivedValue?: number
  // Diagnostyka węzła, nie wiadomość protokołu.
  sharedKey?: number
}

// Wiadomość protokołu przekazana przez koordynatora.
export type DhEvent = {
  seq: number
  from: Role
  to: Role
  type: string
  value: number
  status: EventStatus
}

export type DhSession = {
  id: string
  p: number
  g: number
  status: SessionStatus
  nodes: Record<Role, DhNode>
  events: DhEvent[]
}

// TYMCZASOWO, do czasu API sesji (#37): przebieg przykładowej sesji dla p = 23, g = 5,
// a = 6, b = 15 (wektor referencyjny z #16), rozpisany w czasie, żeby było co odpytywać.
const SAMPLE_ID = 'przyklad'
const SAMPLE_STEP_MS = 1000
let sampleStartedAt = 0

function sampleSession(elapsedMs: number): DhSession {
  const step = Math.min(2, Math.floor(elapsedMs / SAMPLE_STEP_MS))
  const aliceToBob: DhEvent = {
    seq: 1, from: 'alice', to: 'bob', type: 'PUBLIC_VALUE', value: 8, status: 'accepted',
  }
  const bobToAlice: DhEvent = {
    seq: 2, from: 'bob', to: 'alice', type: 'PUBLIC_VALUE', value: 19, status: 'accepted',
  }
  return {
    id: SAMPLE_ID,
    p: 23,
    g: 5,
    status: step < 2 ? 'running' : 'completed',
    nodes: {
      alice:
        step < 2
          ? { status: 'public_ready', publicValue: 8 }
          : { status: 'complete', publicValue: 8, receivedValue: 19, sharedKey: 2 },
      bob:
        step < 1
          ? { status: 'public_ready', publicValue: 19 }
          : { status: 'complete', publicValue: 19, receivedValue: 8, sharedKey: 2 },
    },
    events: [aliceToBob, bobToAlice].slice(0, step),
  }
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

// Dostępność procesu węzła poza sesją, zgłaszana przez koordynatora.
export type NodeAvailability = 'online' | 'offline'

// Zwraca dostępność węzłów Alice i Boba.
// TYMCZASOWO: zamiast zapytania do koordynatora (#37) oba węzły są dostępne.
export async function fetchDhNodes(): Promise<Record<Role, NodeAvailability>> {
  await delay(200)
  return { alice: 'online', bob: 'online' }
}

// Rozpoczyna sesję DH z publicznymi parametrami i zwraca jej początkowy stan.
// TYMCZASOWO: zamiast POST do API sesji (#37) zaczyna przykładową sesję. Przykład pasuje
// tylko do p = 23, g = 5, więc dla innych parametrów zwracamy błąd zamiast cudzego wyniku.
export async function startDhSession(params: DhSessionParams): Promise<DhSession> {
  await delay(400)
  if (params.prime !== 23 || params.generator !== 5) {
    throw new ApiError(
      'Do czasu podłączenia API sesji dostępny jest tylko przykład p = 23, g = 5.',
    )
  }
  sampleStartedAt = Date.now()
  return sampleSession(0)
}

// Zwraca bieżący stan sesji: fazy węzłów i dziennik zdarzeń.
// TYMCZASOWO: zamiast GET z API sesji (#37) zwraca kolejny etap przykładu.
export async function fetchDhSession(id: string): Promise<DhSession> {
  await delay(150)
  if (id !== SAMPLE_ID) throw new ApiError('Nie znaleziono sesji.')
  return sampleSession(Date.now() - sampleStartedAt)
}

// Wysyła JSON metodą POST i zwraca treść odpowiedzi; błędy zamienia na ApiError.
async function postJson(url: string, data: unknown): Promise<unknown> {
  let response: Response
  try {
    response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
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