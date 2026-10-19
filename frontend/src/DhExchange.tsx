// Widok wymiany kluczy Diffiego–Hellmana (PBI-010, #14).
// Frontend niczego nie liczy: wyświetla wartości, które dostaje.

import type { ReactNode } from 'react'

type Party = 'alice' | 'bob'

// Wartości jednej strony wymiany.
export type DhPartyData = {
  privateKey: number
  publicValue: number
  sharedSecret: number
}

export type DhExchangeData = {
  p: number
  g: number
  alice: DhPartyData
  bob: DhPartyData
}

// Nazwa strony i symbole używane we wzorach (Alice: a, A; Bob: b, B).
const PARTIES: Record<Party, { name: string; priv: string; pub: string; other: Party }> = {
  alice: { name: 'Alice', priv: 'a', pub: 'A', other: 'bob' },
  bob: { name: 'Bob', priv: 'b', pub: 'B', other: 'alice' },
}

type DhExchangeProps = {
  data: DhExchangeData
}

export function DhExchange({ data }: DhExchangeProps) {
  return (
    <div className="dh">
      <h1>RADH – wymiana kluczy Diffiego–Hellmana</h1>

      {/* Parametry znane obu stronom (i każdemu, kto podsłuchuje) */}
      <section className="dh-shared" aria-labelledby="dh-shared-title">
        <h2 id="dh-shared-title">Parametry wspólne</h2>
        <p className="formula">
          p = <output>{data.p}</output>
        </p>
        <p className="formula">
          g = <output>{data.g}</output>
        </p>
      </section>

      <div className="dh-parties">
        <PartyPanel party="alice" data={data} />

        {/* Kanał publiczny: tędy później polecą pakiety z A i B */}
        <div className="dh-channel">
          <span className="dh-channel-label">kanał publiczny</span>
        </div>

        <PartyPanel party="bob" data={data} />
      </div>
    </div>
  )
}

type PartyPanelProps = {
  party: Party
  data: DhExchangeData
}

// Panel jednej strony wymiany: klucz prywatny, wartość publiczna, wspólny sekret.
function PartyPanel({ party, data }: PartyPanelProps) {
  const { name, priv, pub, other } = PARTIES[party]
  const own = data[party]
  const received = data[other].publicValue
  const otherPub = PARTIES[other].pub
  const titleId = `dh-${party}-title`

  return (
    <section className={`dh-party dh-party--${party}`} aria-labelledby={titleId}>
      <h2 id={titleId}>{name}</h2>

      <DhValue kind="private" label="Klucz prywatny">
        {priv} = <output>{own.privateKey}</output>
      </DhValue>

      <DhValue kind="public" label="Wartość publiczna">
        {pub} = g<sup>{priv}</sup> mod p = {data.g}
        <sup>{own.privateKey}</sup> mod {data.p} = <output>{own.publicValue}</output>
      </DhValue>

      <DhValue kind="private" label="Wspólny sekret">
        K = {otherPub}
        <sup>{priv}</sup> mod p = {received}
        <sup>{own.privateKey}</sup> mod {data.p} = <output>{own.sharedSecret}</output>
      </DhValue>
    </section>
  )
}

type DhValueProps = {
  kind: 'private' | 'public'
  label: string
  children: ReactNode
}

// Jedna wartość z oznaczeniem, czy jest tajna, czy jawna.
function DhValue({ kind, label, children }: DhValueProps) {
  return (
    <div className={`dh-value dh-value--${kind}`}>
      <div className="dh-value-header">
        <span>{label}</span>
        <span className="dh-value-badge">{kind === 'private' ? 'tajne' : 'jawne'}</span>
      </div>
      <p className="formula">{children}</p>
    </div>
  )
}