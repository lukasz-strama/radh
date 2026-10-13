// Komunikacja z backendem FastAPI.

export type RsaEncryptRequest = {
  message: number
  public_exponent: number
  modulus: number
}

// Wysyła parametry do backendu i zwraca surową odpowiedź JSON.
// Kształt odpowiedzi (np. pole `ciphertext`) jest jeszcze do ustalenia z backendem.
export async function encryptRsa(data: RsaEncryptRequest): Promise<unknown> {
  const response = await fetch('/api/v1/rsa/demo/encrypt', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })

  const body: unknown = await response.json().catch(() => null)

  if (!response.ok) {
    throw new Error(`Backend zwrócił błąd ${response.status}`, { cause: body })
  }

  return body
}