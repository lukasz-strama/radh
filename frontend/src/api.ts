// Komunikacja z backendem FastAPI (backend/app/api.py).

export type RsaEncryptRequest = {
  message: number
  public_exponent: number
  modulus: number
}

export type RsaEncryptResponse = {
  ciphertext: number
}

export type DhExchangeRequest = {
  prime: number
  generator: number
  alice_secret: number
  bob_secret: number
}

export type DhExchangeResponse = {
  alice_public: number
  bob_public: number
  alice_shared_key: number
  bob_shared_key: number
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

const DH_RESPONSE_FIELDS = [
  'alice_public',
  'bob_public',
  'alice_shared_key',
  'bob_shared_key',
] as const

// Wysyła parametry wymiany DH i zwraca wartości obliczone przez backend.
export async function exchangeDh(data: DhExchangeRequest): Promise<DhExchangeResponse> {
  const body = (await postJson('/api/v1/dh/demo/exchange', data)) as Record<
    string,
    unknown
  > | null

  // Niepełna odpowiedź to błąd: nie pokazujemy częściowych wyników.
  if (!body || DH_RESPONSE_FIELDS.some((field) => typeof body[field] !== 'number')) {
    throw unexpectedFormat()
  }
  const response = body as DhExchangeResponse
  return {
    alice_public: response.alice_public,
    bob_public: response.bob_public,
    alice_shared_key: response.alice_shared_key,
    bob_shared_key: response.bob_shared_key,
  }
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