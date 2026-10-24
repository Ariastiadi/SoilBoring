import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const host = process.env.VITE_HOST || '0.0.0.0'
const port = Number(process.env.VITE_PORT || 5173)
const backend = process.env.VITE_BACKEND_URL || 'http://localhost:8000'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    host,
    port,
    // In dev the UI calls same-origin /api/..., Vite forwards it to the backend.
    proxy: {
      '/api': { target: backend, changeOrigin: true },
    },
  },
})
