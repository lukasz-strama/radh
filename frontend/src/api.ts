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

// TYMCZASOWO, do czasu API sesji (#37): przykładowa sesja dla p = 23, g = 5,
// a = 6, b = 15 (wektor referencyjny z #16).
const SAMPLE_SESSION: DhSession = {
  id: 'przyklad',
  p: 23,
  g: 5,
  status: 'completed',
  nodes: {
    alice: { status: 'complete', publicValue: 8, receivedValue: 19, sharedKey: 2 },
    bob: { status: 'complete', publicValue: 19, receivedValue: 8, sharedKey: 2 },
  },
  events: [
    { seq: 1, from: 'alice', to: 'bob', type: 'PUBLIC_VALUE', value: 8, status: 'accepted' },
    { seq: 2, from: 'bob', to: 'alice', type: 'PUBLIC_VALUE', value: 19, status: 'accepted' },
  ],
}

// Rozpoczyna sesję DH z publicznymi parametrami i zwraca jej stan.
// TYMCZASOWO: zamiast POST do API sesji (#37) zwraca przykładową sesję, z krótkim
// opóźnieniem, żeby było widać stan ładowania. Przykład pasuje tylko do p = 23, g = 5,
// więc dla innych parametrów zwracamy błąd zamiast cudzego wyniku.
export async function startDhSession(params: DhSessionParams): Promise<DhSession> {
  await new Promise((resolve) => setTimeout(resolve, 400))
  if (params.prime !== SAMPLE_SESSION.p || params.generator !== SAMPLE_SESSION.g) {
    throw new ApiError(
      'Do czasu podłączenia API sesji dostępny jest tylko przykład p = 23, g = 5.',
    )
  }
  return SAMPLE_SESSION
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