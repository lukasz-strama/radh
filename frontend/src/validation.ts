// Podstawowa walidacja danych wejściowych formularza RSA.
// Zakresy odpowiadają rdzeniowi w C (radh_rsa_encrypt_u32, liczby uint32):
//   modulus:         2 .. 4 294 967 295
//   public_exponent: 1 .. 4 294 967 295
//   message:         0 .. modulus - 1
// Backend i tak sprawdza wszystko sam – tutaj chodzi o szybkie, czytelne komunikaty.

import type { RsaEncryptRequest } from './api'

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