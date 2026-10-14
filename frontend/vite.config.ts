import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // W trybie dev żądania /api/... idą do backendu FastAPI (bez problemów z CORS).
    // Backend uruchomiony przez `uvicorn app.main:app` słucha na 127.0.0.1:8000
    // (patrz backend/README.md).
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
})