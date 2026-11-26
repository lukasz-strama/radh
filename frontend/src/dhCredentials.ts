// Poświadczenia jednej karty. W pamięci trwałej zapisujemy wyłącznie dane do API.
// Każdy scenariusz (zakładka DH i zakładka RSA + DH, #104) ma własne miejsce, więc
// sesje obu zakładek mogą trwać naraz i przełączanie zakładek niczego nie nadpisuje.
export type DhScenario = 'classic' | 'authenticated'
export type SessionCredential = { id: string; token: string; epoch: string }
export type PendingCreation = {
  key: string
  epoch: string
  createdAt: number
  params: {
    prime: number
    generator: number
    mode: 'normal' | 'mitm'
    diagnostics_enabled: boolean
    // Tylko RSA + DH; zwykła wymiana wysyła żądanie jak dotąd, bez tego pola.
    scenario?: 'authenticated'
  }
}

// Klucze zwykłego DH zostają bez zmian – zapisane wcześniej sesje dalej działają.
const KEYS: Record<DhScenario, { session: string; pending: string }> = {
  classic: { session: 'radh.dh.v2.session', pending: 'radh.dh.v2.creation' },
  authenticated: { session: 'radh.dh.v2.authenticated.session', pending: 'radh.dh.v2.authenticated.creation' },
}
const SCENARIOS: readonly DhScenario[] = ['classic', 'authenticated']
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

export function currentCredential(scenario: DhScenario = 'classic'): SessionCredential | null {
  const item = read(KEYS[scenario].session) as Partial<SessionCredential> | null
  if (!item || typeof item.id !== 'string' || !hexId.test(item.id) ||
      typeof item.token !== 'string' || !token.test(item.token) ||
      typeof item.epoch !== 'string' || !hexId.test(item.epoch)) {
    return null
  }
  return item as SessionCredential
}

export function saveCredential(item: SessionCredential, scenario: DhScenario = 'classic') {
  sessionStorage.setItem(KEYS[scenario].session, JSON.stringify(item))
}

// Poświadczenie sesji o danym ID, niezależnie od zakładki, która ją utworzyła.
export function credentialById(id: string): SessionCredential | null {
  for (const scenario of SCENARIOS) {
    const credential = currentCredential(scenario)
    if (credential?.id === id) return credential
  }
  return null
}

export function forgetCredential(expected: SessionCredential) {
  for (const scenario of SCENARIOS) {
    const current = currentCredential(scenario)
    if (current?.id === expected.id && current.token === expected.token && current.epoch === expected.epoch) {
      sessionStorage.removeItem(KEYS[scenario].session)
    }
  }
}

export function pendingCreation(scenario: DhScenario = 'classic'): PendingCreation | null {
  const item = read(KEYS[scenario].pending) as Partial<PendingCreation> | null
  const params = item?.params
  if (!item || typeof item.key !== 'string' || !token.test(item.key) ||
      typeof item.epoch !== 'string' || !hexId.test(item.epoch) ||
      typeof item.createdAt !== 'number' || !Number.isFinite(item.createdAt) ||
      !params || !Number.isInteger(params.prime) || !Number.isInteger(params.generator) ||
      !['normal', 'mitm'].includes(params.mode) || typeof params.diagnostics_enabled !== 'boolean' ||
      (params.scenario !== undefined && params.scenario !== 'authenticated')) {
    return null
  }
  return item as PendingCreation
}

export function savePendingCreation(item: PendingCreation, scenario: DhScenario = 'classic') {
  sessionStorage.setItem(KEYS[scenario].pending, JSON.stringify(item))
}

export function forgetPendingCreation(expected?: string, scenario: DhScenario = 'classic') {
  if (expected === undefined || pendingCreation(scenario)?.key === expected) {
    sessionStorage.removeItem(KEYS[scenario].pending)
  }
}

export function newCreationKey(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(32))
  return btoa(String.fromCharCode(...bytes)).replaceAll('+', '-').replaceAll('/', '_').replace(/=+$/, '')
}

export function isSessionId(value: unknown): value is string {
  return typeof value === 'string' && hexId.test(value)
}