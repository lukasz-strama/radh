import { useRef, useState } from 'react'
import type { KeyboardEvent } from 'react'
import { DhExchange } from './DhExchange'
import { RsaView } from './RsaView'
import './App.css'

type Tab = 'rsa' | 'dh' | 'rsadh'

const TABS: { id: Tab; label: string }[] = [
  { id: 'rsa', label: 'RSA' },
  { id: 'dh', label: 'Diffie–Hellman' },
  // Wymiana DH uwierzytelniona podpisami RSA (#104); własna sesja, niezależna od zakładki DH.
  { id: 'rsadh', label: 'RSA + DH' },
]

const REPOSITORY_URL = 'https://github.com/lukasz-strama/radh'

function App() {
  const [tab, setTab] = useState<Tab>('rsa')
  const tabRefs = useRef<Partial<Record<Tab, HTMLButtonElement | null>>>({})

  // Zakładki jak w ARIA „tabs”: Tab wchodzi tylko na aktywną zakładkę,
  // strzałki, Home i End przełączają między nimi.
  function handleTabKey(event: KeyboardEvent<HTMLButtonElement>) {
    const index = TABS.findIndex(({ id }) => id === tab)
    let next: number | null = null
    if (event.key === 'ArrowRight') next = (index + 1) % TABS.length
    if (event.key === 'ArrowLeft') next = (index - 1 + TABS.length) % TABS.length
    if (event.key === 'Home') next = 0
    if (event.key === 'End') next = TABS.length - 1
    if (next === null) return
    event.preventDefault()
    const id = TABS[next].id
    setTab(id)
    tabRefs.current[id]?.focus()
  }

  return (
    <div className="app">
      <header className="app-header">
        <div className="app-brand">
          <span className="app-name">RADH</span>
          <span className="app-tagline">Demonstrator RSA i wymiany kluczy Diffiego–Hellmana</span>
        </div>

        <div className="tabs" role="tablist" aria-label="Widoki">
          {TABS.map(({ id, label }) => (
            <button
              key={id}
              ref={(element) => {
                tabRefs.current[id] = element
              }}
              type="button"
              role="tab"
              id={`tab-${id}`}
              className="tab"
              aria-selected={tab === id}
              aria-controls={`view-${id}`}
              tabIndex={tab === id ? 0 : -1}
              onClick={() => setTab(id)}
              onKeyDown={handleTabKey}
            >
              {label}
            </button>
          ))}
        </div>
      </header>

      {/* Ukryte zakładki zostają w DOM, żeby nie tracić wpisanych danych i wyników */}
      <main>
        {TABS.map(({ id }) => (
          <div
            key={id}
            role="tabpanel"
            id={`view-${id}`}
            aria-labelledby={`tab-${id}`}
            hidden={tab !== id}
          >
            {id === 'rsa' && <RsaView />}
            {id === 'dh' && <DhExchange />}
            {id === 'rsadh' && <DhExchange scenario="authenticated" />}
          </div>
        ))}
      </main>

      <footer className="app-footer">
        <span>
          RADH v{__APP_VERSION__} · wersja beta · projekt edukacyjny, nie do ochrony prawdziwych
          danych
        </span>
        <a href={REPOSITORY_URL} target="_blank" rel="noreferrer">
          Repozytorium na GitHubie
        </a>
      </footer>
    </div>
  )
}

export default App