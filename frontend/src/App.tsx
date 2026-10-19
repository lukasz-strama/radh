import { useState } from 'react'
import { DhExchange } from './DhExchange'
import type { DhExchangeData } from './DhExchange'
import { RsaView } from './RsaView'
import './App.css'

type Tab = 'rsa' | 'dh'

// Tymczasowo przykład z kryteriów #14 zamiast odpowiedzi backendu.
const DH_EXAMPLE: DhExchangeData = {
  p: 23,
  g: 5,
  alice: { privateKey: 6, publicValue: 8, sharedSecret: 2 },
  bob: { privateKey: 15, publicValue: 19, sharedSecret: 2 },
}

const TABS: { id: Tab; label: string }[] = [
  { id: 'rsa', label: 'RSA' },
  { id: 'dh', label: 'Diffie–Hellman' },
]

function App() {
  const [tab, setTab] = useState<Tab>('rsa')

  return (
    <div className="app">
      <nav className="tabs" aria-label="Widoki">
        {TABS.map(({ id, label }) => (
          <button
            key={id}
            type="button"
            className="tab"
            aria-current={tab === id ? 'page' : undefined}
            onClick={() => setTab(id)}
          >
            {label}
          </button>
        ))}
      </nav>

      {/* Ukryte zakładki zostają w DOM, żeby nie tracić wpisanych danych i wyników */}
      <div hidden={tab !== 'rsa'}>
        <RsaView />
      </div>
      <div hidden={tab !== 'dh'}>
        <DhExchange state={{ status: 'ready', data: DH_EXAMPLE }} />
      </div>
    </div>
  )
}

export default App