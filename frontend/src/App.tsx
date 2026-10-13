import type { FormEvent } from 'react'
import { encryptRsa } from './api'
import './App.css'

function App() {
  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()

    // Zbieramy wartości z pól formularza (po atrybucie `name`).
    const form = new FormData(event.currentTarget)
    const data = {
      message: Number(form.get('message')),
      public_exponent: Number(form.get('public_exponent')),
      modulus: Number(form.get('modulus')),
    }

    try {
      const result = await encryptRsa(data)
      console.log('Odpowiedź backendu:', result)
    } catch (error) {
      console.error('Nie udało się zaszyfrować:', error)
    }
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