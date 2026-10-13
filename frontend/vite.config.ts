import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // W trybie dev żądania /api/... idą do backendu FastAPI (bez problemów z CORS).
    // Port 8000 to domyślny port FastAPI – do potwierdzenia z backendem.
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
})