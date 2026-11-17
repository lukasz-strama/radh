import { readFileSync } from 'node:fs'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Wersja z package.json – pokazywana w stopce aplikacji.
const { version } = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf8'))

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  define: {
    __APP_VERSION__: JSON.stringify(version),
  },
  server: {
    // W trybie dev żądania /api/... idą do backendu FastAPI (bez problemów z CORS).
    // Backend uruchomiony przez `uvicorn app.main:app` słucha na 127.0.0.1:8000
    // (patrz backend/README.md).
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
})