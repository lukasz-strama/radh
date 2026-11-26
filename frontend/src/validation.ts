// Podstawowa walidacja danych wejściowych formularza RSA.
// Zakresy odpowiadają rdzeniowi w C (radh_rsa_encrypt_u32, liczby uint32):
//   modulus:         2 .. 4 294 967 295
//   public_exponent: 1 .. 4 294 967 295
//   message:         0 .. modulus - 1
// Backend i tak sprawdza wszystko sam – tutaj chodzi o szybkie, czytelne komunikaty.

import type { DhSessionParams, RsaEncryptRequest, RsaKeygenRequest } from './api'

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

export type RsaKeyField = keyof RsaKeygenRequest
export type RsaKeyFieldErrors = Partial<Record<RsaKeyField, string>>

export type RsaKeyValidationResult =
  | { ok: true; data: RsaKeygenRequest }
  | { ok: false; errors: RsaKeyFieldErrors }

export function validateRsaKeyParams(raw: Record<RsaKeyField, string>): RsaKeyValidationResult {
  const errors: RsaKeyFieldErrors = {}

  const p = parseUint32(raw.p)
  const q = parseUint32(raw.q)
  const e = parseUint32(raw.e)

  if (typeof p === 'string') errors.p = p
  if (typeof q === 'string') errors.q = q
  if (typeof e === 'string') errors.e = e

  if (typeof p === 'number' && p < 2) errors.p = 'Liczba p musi być co najmniej równa 2.'
  if (typeof q === 'number' && q < 2) errors.q = 'Liczba q musi być co najmniej równa 2.'
  if (typeof p === 'number' && typeof q === 'number' && !errors.p && !errors.q && p === q) {
    errors.q = 'Liczby p i q muszą być różne.'
  }
  if (typeof e === 'number' && e < 2) errors.e = 'Wykładnik e musi być co najmniej równy 2.'

  if (Object.keys(errors).length > 0) return { ok: false, errors }

  return { ok: true, data: { p: p as number, q: q as number, e: e as number } }
}
// Walidacja deszyfrowania i tekstowego cyklu RSA (#100). Zakresy jak w backendzie (#99):
//   ciphertext:       0 .. modulus - 1
//   private_exponent: 1 .. 4 294 967 295
//   tekst:            1 .. 128 bajtów UTF-8; każdy bajt to osobna wiadomość m < n,
//                     więc moduł musi być większy od 255
//   szyfrogramy:      1 .. 128 liczb, każda mniejsza od n
// Pola deszyfrowania mają własne nazwy (`private_*`), bo panel szyfrowania używa już `modulus`.

export const RSA_TEXT_MAX_BYTES = 128
const TEXT_MIN_MODULUS = 256

export type RsaDecryptField = 'ciphertext' | 'private_exponent' | 'private_modulus'
export type RsaTextField = 'text' | 'public_exponent' | 'modulus'
export type RsaTextDecryptField = 'ciphertexts' | 'private_exponent' | 'private_modulus'

type Result<Field extends string, Data> =
  | { ok: true; data: Data }
  | { ok: false; errors: Partial<Record<Field, string>> }

function finish<Field extends string, Data>(
  errors: Partial<Record<Field, string>>,
  data: () => Data,
): Result<Field, Data> {
  return Object.keys(errors).length > 0 ? { ok: false, errors } : { ok: true, data: data() }
}

// Wspólna część dla kluczy: wykładnik ≥ 1, moduł ≥ minimum.
function exponent(raw: string, name: 'e' | 'd'): number | string {
  const value = parseUint32(raw)
  if (typeof value === 'number' && value < 1) return `Wykładnik ${name} musi być co najmniej równy 1.`
  return value
}

function modulus(raw: string, minimum: number, tooSmall: string): number | string {
  const value = parseUint32(raw)
  if (typeof value === 'number' && value < minimum) return tooSmall
  return value
}

const MODULUS_TOO_SMALL = 'Moduł n musi być co najmniej równy 2.'
const TEXT_MODULUS_TOO_SMALL = 'W trybie tekstowym moduł n musi być większy od 255 (każdy bajt to osobne m < n).'

export function validateRsaDecryptInput(
  raw: Record<RsaDecryptField, string>,
): Result<RsaDecryptField, { ciphertext: number; private_exponent: number; modulus: number }> {
  const errors: Partial<Record<RsaDecryptField, string>> = {}
  const ciphertext = parseUint32(raw.ciphertext)
  const privateExponent = exponent(raw.private_exponent, 'd')
  const n = modulus(raw.private_modulus, 2, MODULUS_TOO_SMALL)

  if (typeof ciphertext === 'string') errors.ciphertext = ciphertext
  if (typeof privateExponent === 'string') errors.private_exponent = privateExponent
  if (typeof n === 'string') errors.private_modulus = n
  if (typeof ciphertext === 'number' && typeof n === 'number' && ciphertext >= n) {
    errors.ciphertext = 'Szyfrogram c musi być mniejszy od modułu n.'
  }

  return finish(errors, () => ({
    ciphertext: ciphertext as number,
    private_exponent: privateExponent as number,
    modulus: n as number,
  }))
}

// Pojedynczy surogat (np. ucięta para z wklejenia) nie jest poprawnym tekstem Unicode
// i nie da się go zakodować w UTF-8 bez utraty danych.
const LONE_SURROGATE = /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/

export function utf8Length(text: string): number {
  return new TextEncoder().encode(text).length
}

export function validateRsaTextInput(
  raw: Record<RsaTextField, string>,
): Result<RsaTextField, { text: string; public_exponent: number; modulus: number }> {
  const errors: Partial<Record<RsaTextField, string>> = {}
  const publicExponent = exponent(raw.public_exponent, 'e')
  const n = modulus(raw.modulus, TEXT_MIN_MODULUS, TEXT_MODULUS_TOO_SMALL)

  // Tekst zostaje bez obcinania spacji – szyfrujemy dokładnie to, co wpisano.
  if (raw.text === '') errors.text = 'To pole jest wymagane.'
  else if (LONE_SURROGATE.test(raw.text)) errors.text = 'Tekst zawiera niepoprawny znak Unicode.'
  else if (utf8Length(raw.text) > RSA_TEXT_MAX_BYTES) {
    errors.text = `Tekst może mieć najwyżej ${RSA_TEXT_MAX_BYTES} bajtów UTF-8.`
  }
  if (typeof publicExponent === 'string') errors.public_exponent = publicExponent
  if (typeof n === 'string') errors.modulus = n

  return finish(errors, () => ({
    text: raw.text,
    public_exponent: publicExponent as number,
    modulus: n as number,
  }))
}

export function validateRsaTextDecryptInput(
  raw: Record<RsaTextDecryptField, string>,
): Result<RsaTextDecryptField, { ciphertexts: number[]; private_exponent: number; modulus: number }> {
  const errors: Partial<Record<RsaTextDecryptField, string>> = {}
  const privateExponent = exponent(raw.private_exponent, 'd')
  const n = modulus(raw.private_modulus, TEXT_MIN_MODULUS, TEXT_MODULUS_TOO_SMALL)

  // Liczby rozdzielone przecinkami, średnikami lub białymi znakami.
  const parts = raw.ciphertexts.split(/[\s,;]+/).filter((part) => part !== '')
  const ciphertexts: number[] = []
  if (parts.length === 0) errors.ciphertexts = 'To pole jest wymagane.'
  else if (parts.length > RSA_TEXT_MAX_BYTES) {
    errors.ciphertexts = `Można odszyfrować najwyżej ${RSA_TEXT_MAX_BYTES} szyfrogramów.`
  }
  for (const [index, part] of parts.entries()) {
    if (errors.ciphertexts) break
    const value = parseUint32(part)
    if (typeof value === 'string') errors.ciphertexts = `Szyfrogram nr ${index + 1}: ${value}`
    else if (typeof n === 'number' && value >= n) {
      errors.ciphertexts = `Szyfrogram nr ${index + 1} musi być mniejszy od modułu n.`
    } else ciphertexts.push(value)
  }
  if (typeof privateExponent === 'string') errors.private_exponent = privateExponent
  if (typeof n === 'string') errors.private_modulus = n

  return finish(errors, () => ({
    ciphertexts,
    private_exponent: privateExponent as number,
    modulus: n as number,
  }))
}