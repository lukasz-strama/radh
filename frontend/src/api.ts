// Komunikacja z backendem FastAPI.

export type RsaEncryptRequest = {
  message: number
  public_exponent: number
  modulus: number
}

// Błąd z czytelnym komunikatem dla użytkownika.
export class ApiError extends Error {}

// Wysyła parametry do backendu i zwraca surową odpowiedź JSON.
// Kształt odpowiedzi (np. pole `ciphertext`) i format błędów są jeszcze
// do ustalenia z backendem.
export async function encryptRsa(data: RsaEncryptRequest): Promise<unknown> {
  let response: Response
  try {
    response = await fetch('/api/v1/rsa/demo/encrypt', {
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
    throw new ApiError(describeHttpError(response.status, body))
  }

  return body
}

function describeHttpError(status: number, body: unknown): string {
  // 502/503/504: proxy Vite nie może się połączyć z backendem (np. nie jest uruchomiony).
  if (status === 502 || status === 503 || status === 504) {
    return 'Nie można połączyć się z backendem. Upewnij się, że serwer FastAPI działa.'
  }

  // Jeśli backend zwrócił tekstowe `detail` (konwencja FastAPI), pokazujemy je.
  const detail = (body as { detail?: unknown } | null)?.detail
  if (typeof detail === 'string' && detail !== '') {
    return detail
  }

  if (status >= 400 && status < 500) {
    return `Serwer odrzucił dane (błąd ${status}). Sprawdź wprowadzone wartości.`
  }
  return `Wystąpił błąd serwera (błąd ${status}). Spróbuj ponownie później.`
}