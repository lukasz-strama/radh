import type { FormEvent } from 'react'
import './App.css'

function App() {
  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    // Na razie nic nie robimy, tylko blokujemy przeładowanie strony.
    event.preventDefault()
  }

  return (
    <div className="app">
      <h1>RADH – szyfrowanie RSA</h1>

      <div className="layout">
        {/* Ekran: tu później trafi wizualizacja (Alice, Bob, Mallory, pakiety) */}
        <section className="screen" aria-label="Ekran wizualizacji"></section>

        {/* Panel sterowania */}
        <form className="panel" onSubmit={handleSubmit}>
          <label>
            Wiadomość (m)
            <input name="message" type="text" inputMode="numeric" />
          </label>

          <label>
            Wykładnik publiczny (e)
            <input name="public_exponent" type="text" inputMode="numeric" />
          </label>

          <label>
            Moduł (n)
            <input name="modulus" type="text" inputMode="numeric" />
          </label>

          <button type="submit">Szyfruj</button>
        </form>
      </div>
    </div>
  )
}

export default App