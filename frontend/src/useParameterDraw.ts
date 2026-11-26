// Losowanie parametrów formularza z API (#97), wspólne dla RSA i DH.
// Pilnuje, żeby nieaktualna odpowiedź nie nadpisała pól: każde nowe losowanie,
// ręczna edycja i Reset (cancel) oraz odmontowanie przerywa poprzednie żądanie.
// Błąd losowania i wartości spoza zakresu nie zmieniają pól – formularz
// zachowuje dotychczasowe wartości.

import { useEffect, useRef, useState } from 'react'
import { ApiError } from './api'

const OUT_OF_RANGE = 'Backend zwrócił parametry spoza dozwolonego zakresu.'

export type ParameterDraw = {
  // Rozpoczyna losowanie (przerywa poprzednie).
  draw: () => void
  // Przerywa trwające losowanie i czyści komunikat błędu – przy ręcznej edycji
  // pola i przy Resecie. Blokada Retry-After i jej komunikat zostają do końca blokady.
  cancel: () => void
  // Trwa losowanie – formularz nie powinien wtedy uruchamiać operacji.
  isDrawing: boolean
  // Po 429/503 z Retry-After losowanie jest zablokowane na podany czas.
  isBlocked: boolean
  error: string | null
}

export function useParameterDraw<T>(
  request: (signal: AbortSignal) => Promise<T>,
  // Te same reguły co przy ręcznym wpisaniu – do formularza trafiają tylko
  // wartości, które dają się od razu użyć.
  isValid: (values: T) => boolean,
  apply: (values: T) => void,
): ParameterDraw {
  const [isDrawing, setIsDrawing] = useState(false)
  const [isBlocked, setIsBlocked] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const current = useRef<AbortController | null>(null)
  const unblockTimer = useRef<number | undefined>(undefined)

  useEffect(
    () => () => {
      // Po odmontowaniu żadna odpowiedź nie jest już aktualna.
      current.current?.abort()
      current.current = null
      window.clearTimeout(unblockTimer.current)
    },
    [],
  )

  function cancel() {
    current.current?.abort()
    current.current = null
    setIsDrawing(false)
    // Komunikat blokady wyjaśnia wyłączony przycisk, więc zostaje do jej końca.
    if (!isBlocked) setError(null)
  }

  function block(seconds: number) {
    window.clearTimeout(unblockTimer.current)
    setIsBlocked(true)
    unblockTimer.current = window.setTimeout(() => {
      setIsBlocked(false)
      // Czas z komunikatu („za N s”) już minął.
      setError(null)
    }, seconds * 1000)
  }

  async function draw() {
    if (isBlocked) return
    current.current?.abort()
    const controller = new AbortController()
    current.current = controller
    setIsDrawing(true)
    setError(null)
    try {
      const values = await request(controller.signal)
      // Wynik liczy się tylko, jeśli w międzyczasie nic go nie unieważniło.
      if (current.current !== controller) return
      if (!isValid(values)) {
        setError(OUT_OF_RANGE)
        return
      }
      apply(values)
    } catch (caught) {
      if (current.current !== controller) return
      setError(caught instanceof ApiError ? caught.message : 'Nie udało się wylosować parametrów.')
      if (
        caught instanceof ApiError &&
        caught.retryAfter > 0 &&
        (caught.status === 429 || caught.status === 503)
      ) {
        block(caught.retryAfter)
      }
    } finally {
      if (current.current === controller) {
        current.current = null
        setIsDrawing(false)
      }
    }
  }

  return { draw: () => void draw(), cancel, isDrawing, isBlocked, error }
}