// Widok wymiany kluczy Diffiego–Hellmana (PBI-010, #14).
// Na razie szkielet: wspólne parametry i panele Alice oraz Boba.

type Party = 'alice' | 'bob'

const PARTY_NAMES: Record<Party, string> = {
  alice: 'Alice',
  bob: 'Bob',
}

type DhExchangeProps = {
  p: number
  g: number
}

export function DhExchange({ p, g }: DhExchangeProps) {
  return (
    <div className="dh">
      <h1>RADH – wymiana kluczy Diffiego–Hellmana</h1>

      {/* Parametry znane obu stronom (i każdemu, kto podsłuchuje) */}
      <section className="dh-shared" aria-labelledby="dh-shared-title">
        <h2 id="dh-shared-title">Parametry wspólne</h2>
        <p className="formula">
          p = <output>{p}</output>
        </p>
        <p className="formula">
          g = <output>{g}</output>
        </p>
      </section>

      <div className="dh-parties">
        <PartyPanel party="alice" />

        {/* Kanał publiczny: tędy później polecą pakiety z A i B */}
        <div className="dh-channel">
          <span className="dh-channel-label">kanał publiczny</span>
        </div>

        <PartyPanel party="bob" />
      </div>
    </div>
  )
}

type PartyPanelProps = {
  party: Party
}

// Panel jednej strony wymiany.
function PartyPanel({ party }: PartyPanelProps) {
  const titleId = `dh-${party}-title`
  return (
    <section className={`dh-party dh-party--${party}`} aria-labelledby={titleId}>
      <h2 id={titleId}>{PARTY_NAMES[party]}</h2>
      {/* Tu trafią: klucz prywatny, wartość publiczna i wspólny sekret */}
    </section>
  )
}