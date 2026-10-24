import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The on-device AI engine is fetched from jsDelivr at runtime and checked against these
// hashes, so only the exact files of the installed @wllama version can run.
const wllamaVersion = JSON.parse(readFileSync('node_modules/@wllama/wllama/package.json', 'utf-8')).version
const engineFile = (path: string) => readFileSync(`node_modules/${path}`)
const sha256 = (b: Buffer) => createHash('sha256').update(b).digest('hex')
const wasm = engineFile('@wllama/wllama/esm/wasm/wllama.wasm')
const compatWasm = engineFile('@wllama/wllama-compat/wasm/wllama.wasm')
const compatJs = engineFile('@wllama/wllama-compat/wasm/wllama.js')

const host = process.env.VITE_HOST || '0.0.0.0'
const port = Number(process.env.VITE_PORT || 5173)
const backend = process.env.VITE_BACKEND_URL || 'http://localhost:8000'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  define: {
    __WLLAMA_VERSION__: JSON.stringify(wllamaVersion),
    __WLLAMA_WASM_SIZE__: String(wasm.length),
    __WLLAMA_WASM_SHA256__: JSON.stringify(sha256(wasm)),
    __WLLAMA_COMPAT_WASM_SIZE__: String(compatWasm.length),
    __WLLAMA_COMPAT_WASM_SHA256__: JSON.stringify(sha256(compatWasm)),
    __WLLAMA_COMPAT_JS_SIZE__: String(compatJs.length),
    __WLLAMA_COMPAT_JS_SHA256__: JSON.stringify(sha256(compatJs)),
  },
  server: {
    host,
    port,
    // In dev the UI calls same-origin /api/..., Vite forwards it to the backend.
    proxy: {
      '/api': { target: backend, changeOrigin: true },
    },
  },
})
