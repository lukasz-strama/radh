// Podstawowa walidacja danych wejściowych formularza RSA.
// Zakresy odpowiadają rdzeniowi w C (radh_rsa_encrypt_u32, liczby uint32):
//   modulus:         2 .. 4 294 967 295
//   public_exponent: 1 .. 4 294 967 295
//   message:         0 .. modulus - 1
// Backend i tak sprawdza wszystko sam – tutaj chodzi o szybkie, czytelne komunikaty.

import type { DhSessionParams, RsaEncryptRequest } from './api'

const UINT32_MAX = 4_294_967_295

export type RsaField = keyof RsaEncryptRequest
export type FieldErrors = Partial<Record<RsaField, string>>

export type ValidationResult =
  | { ok: true; data: RsaEncryptRequest }
  | { ok: false; errors: FieldErrors }

// Zamienia tekst z pola na liczbę albo zwraca komunikat błędu.
function parseUint32(raw: string): number | string {
  const value = raw.trim()
  if (value === '') return 'To pole jest wymagane.'
  if (!/^[0-9]+$/.test(value)) return 'Podaj nieujemną liczbę całkowitą (same cyfry).'
  const number = Number(value)
  if (number > UINT32_MAX) return `Maksymalna wartość to ${UINT32_MAX}.`
  return number
}

export function validateRsaInput(raw: Record<RsaField, string>): ValidationResult {
  const errors: FieldErrors = {}

  const message = parseUint32(raw.message)
  const publicExponent = parseUint32(raw.public_exponent)
  const modulus = parseUint32(raw.modulus)

  if (typeof message === 'string') errors.message = message
  if (typeof publicExponent === 'string') errors.public_exponent = publicExponent
  if (typeof modulus === 'string') errors.modulus = modulus

  if (typeof modulus === 'number' && modulus < 2) {
    errors.modulus = 'Moduł n musi być co najmniej równy 2.'
  }
  if (typeof publicExponent === 'number' && publicExponent < 1) {
    errors.public_exponent = 'Wykładnik e musi być co najmniej równy 1.'
  }
  if (
    typeof message === 'number' &&
    typeof modulus === 'number' &&
    !errors.modulus &&
    message >= modulus
  ) {
    errors.message = 'Wiadomość m musi być mniejsza od modułu n.'
  }

  if (Object.keys(errors).length > 0) return { ok: false, errors }

  return {
    ok: true,
    data: {
      message: message as number,
      public_exponent: publicExponent as number,
      modulus: modulus as number,
    },
  }
}

// Walidacja publicznych parametrów sesji DH (uint32, jak w backendzie):
//   prime:     liczba pierwsza – pierwszość sprawdza backend
//   generator: 2 .. prime - 1
// Sekrety a i b nie przechodzą przez przeglądarkę: losują je procesy węzłów.

  export type DhField = keyof DhSessionParams
  export type DhFieldErrors = Partial<Record<DhField, string>>

  export type DhValidationResult =
    | { ok: true; data: DhSessionParams }
    | { ok: false; errors: DhFieldErrors }

export function validateDhParams(raw: Record<DhField, string>): DhValidationResult {
  const errors: DhFieldErrors = {}

  const prime = parseUint32(raw.prime)
  const generator = parseUint32(raw.generator)

  if (typeof prime === 'string') errors.prime = prime
  if (typeof generator === 'string') errors.generator = generator

  if (typeof prime === 'number' && prime < 3) {
    errors.prime = 'Liczba pierwsza p musi być co najmniej równa 3.'
  }
  if (typeof generator === 'number' && generator < 2) {
    errors.generator = 'Generator g musi być co najmniej równy 2.'
  } else if (
    typeof generator === 'number' &&
    typeof prime === 'number' &&
    !errors.prime &&
    generator >= prime
  ) {
    errors.generator = 'Generator g musi być mniejszy od p.'
  }

  if (Object.keys(errors).length > 0) return { ok: false, errors }

  return { ok: true, data: { prime: prime as number, generator: generator as number } }
}