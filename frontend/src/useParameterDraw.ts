// Losowanie parametrów formularza z API (#97), wspólne dla RSA i DH.
// Pilnuje, żeby nieaktualna odpowiedź nie nadpisała pól: każde nowe losowanie,
// ręczna edycja (cancel) i odmontowanie przerywa poprzednie żądanie.
// Błąd losowania nie zmienia pól – formularz zachowuje dotychczasowe wartości.

import { useEffect, useRef, useState } from 'react'
import { ApiError } from './api'

export type ParameterDraw = {
  // Rozpoczyna losowanie (przerywa poprzednie).
  draw: () => void
  // Przerywa trwające losowanie, np. przy ręcznej edycji pola albo Resecie.
  cancel: () => void
  isDrawing: boolean
  // Po 429/503 z Retry-After losowanie jest zablokowane na podany czas.
  isBlocked: boolean
  error: string | null
}

export function useParameterDraw<T>(
  request: (signal: AbortSignal) => Promise<T>,
  apply: (values: T) => void,
): ParameterDraw {
  const [isDrawing, setIsDrawing] = useState(false)
  const [isBlocked, setIsBlocked] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const current = useRef<AbortController | null>(null)
  const unblockTimer = useRef<number | undefined>(undefined)

  useEffect(
    () => () => {
      current.current?.abort()
      window.clearTimeout(unblockTimer.current)
    },
    [],
  )

  function cancel() {
    if (!current.current) return
    current.current.abort()
    current.current = null
    setIsDrawing(false)
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
      if (current.current === controller) apply(values)
    } catch (caught) {
      if (current.current !== controller) return
      setError(caught instanceof ApiError ? caught.message : 'Nie udało się wylosować parametrów.')
      if (
        caught instanceof ApiError &&
        caught.retryAfter > 0 &&
        (caught.status === 429 || caught.status === 503)
      ) {
        window.clearTimeout(unblockTimer.current)
        setIsBlocked(true)
        unblockTimer.current = window.setTimeout(() => setIsBlocked(false), caught.retryAfter * 1000)
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