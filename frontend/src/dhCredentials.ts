// Poświadczenia jednej karty. W pamięci trwałej zapisujemy wyłącznie dane do API.
export type SessionCredential = { id: string; token: string; epoch: string }
export type PendingCreation = {
  key: string
  epoch: string
  createdAt: number
  params: { prime: number; generator: number; mode: 'normal' | 'mitm'; diagnostics_enabled: boolean }
}

const SESSION_KEY = 'radh.dh.v2.session'
const PENDING_KEY = 'radh.dh.v2.creation'
const hexId = /^[0-9a-f]{32}$/
const token = /^[A-Za-z0-9_-]{43}$/

function read(key: string): unknown {
  try {
    const raw = sessionStorage.getItem(key)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

export function currentCredential(): SessionCredential | null {
  const item = read(SESSION_KEY) as Partial<SessionCredential> | null
  if (!item || typeof item.id !== 'string' || !hexId.test(item.id) ||
      typeof item.token !== 'string' || !token.test(item.token) ||
      typeof item.epoch !== 'string' || !hexId.test(item.epoch)) {
    return null
  }
  return item as SessionCredential
}

export function saveCredential(item: SessionCredential) {
  sessionStorage.setItem(SESSION_KEY, JSON.stringify(item))
}

export function forgetCredential(expected: SessionCredential) {
  const current = currentCredential()
  if (current?.id === expected.id && current.token === expected.token && current.epoch === expected.epoch) {
    sessionStorage.removeItem(SESSION_KEY)
  }
}

export function pendingCreation(): PendingCreation | null {
  const item = read(PENDING_KEY) as Partial<PendingCreation> | null
  const params = item?.params
  if (!item || typeof item.key !== 'string' || !token.test(item.key) ||
      typeof item.epoch !== 'string' || !hexId.test(item.epoch) ||
      typeof item.createdAt !== 'number' || !Number.isFinite(item.createdAt) ||
      !params || !Number.isInteger(params.prime) || !Number.isInteger(params.generator) ||
      !['normal', 'mitm'].includes(params.mode) || typeof params.diagnostics_enabled !== 'boolean') {
    return null
  }
  return item as PendingCreation
}

export function savePendingCreation(item: PendingCreation) {
  sessionStorage.setItem(PENDING_KEY, JSON.stringify(item))
}

export function forgetPendingCreation(expected?: string) {
  if (expected === undefined || pendingCreation()?.key === expected) sessionStorage.removeItem(PENDING_KEY)
}

export function newCreationKey(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(32))
  return btoa(String.fromCharCode(...bytes)).replaceAll('+', '-').replaceAll('/', '_').replace(/=+$/, '')
}

export function isSessionId(value: unknown): value is string {
  return typeof value === 'string' && hexId.test(value)
}
