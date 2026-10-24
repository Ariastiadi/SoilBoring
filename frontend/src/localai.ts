/**
 * On-device AI ("Qwen on this device"): runs a small open model in the browser with
 * llama.cpp compiled to WebAssembly (wllama). No API key, no account, no cost, and the
 * borehole data never leaves the browser. Same approach as the browser engine in
 * talkdude (github.com/Ariastiadi/talkdude).
 *
 * - The model (GGUF from Hugging Face) is downloaded once and kept in the browser's
 *   private storage (OPFS); later visits load it from there.
 * - The engine (wllama.wasm) is fetched from jsDelivr on first use and checked against
 *   the SHA-256 of the exact version this app was built with.
 */
import type { ModelManager, Wllama } from '@wllama/wllama'
import { t } from './i18n'

export type LocalModel = {
  key: string
  name: string
  note: string
  url: string
  /** Download size in bytes. */
  size: number
}

// Ungated GGUF builds on Hugging Face (Qwen 2.5 is Apache-2.0).
export const LOCAL_MODELS: LocalModel[] = [
  {
    key: 'qwen2.5-1.5b',
    name: 'Qwen 2.5 1.5B',
    note: t('Better answers. For laptops/PCs and phones with 6 GB+ RAM.'),
    url: 'https://huggingface.co/bartowski/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/Qwen2.5-1.5B-Instruct-Q4_K_M.gguf',
    size: 986_048_768,
  },
  {
    key: 'qwen2.5-0.5b',
    name: 'Qwen 2.5 0.5B',
    note: t('Smallest and fastest, simpler answers. For older phones.'),
    url: 'https://huggingface.co/bartowski/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/Qwen2.5-0.5B-Instruct-Q4_K_M.gguf',
    size: 397_808_192,
  },
]

export function isMobile(): boolean {
  return /Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent)
}

export function suggestedModel(): string {
  const mem = (navigator as { deviceMemory?: number }).deviceMemory ?? 4
  return isMobile() && mem < 6 ? 'qwen2.5-0.5b' : 'qwen2.5-1.5b'
}

export function modelInfo(key: string): LocalModel | undefined {
  return LOCAL_MODELS.find(m => m.key === key)
}

export function formatSize(bytes: number): string {
  return bytes >= 1e9 ? `${(bytes / 1e9).toFixed(1)} GB` : `${Math.round(bytes / 1e6)} MB`
}

/** Context window used here: phones get less to save memory. */
export function contextTokens(): number {
  return isMobile() ? 2048 : 4096
}

/** Characters of data snapshot that fit next to the question and the answer (≈3.5 chars/token). */
export function promptBudgetChars(maxAnswerTokens: number): number {
  return Math.max(1200, Math.floor((contextTokens() - maxAnswerTokens - 400) * 3.2))
}

export function localSupported(): boolean {
  return typeof WebAssembly === 'object' && !!navigator.storage?.getDirectory
}

// === State shared by every tab (Geo AI, Summaries, Dashboard) ===

export type LocalState = {
  downloaded: string[]
  /** key -> 0..1 while a download runs */
  progress: Record<string, number>
  loading: string | null
  error: string
}

let state: LocalState = { downloaded: [], progress: {}, loading: null, error: '' }
const listeners = new Set<(s: LocalState) => void>()

function setState(patch: Partial<LocalState>) {
  state = { ...state, ...patch }
  listeners.forEach(l => l(state))
}

export function getLocalState(): LocalState {
  return state
}

export function subscribeLocal(listener: (s: LocalState) => void): () => void {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}

// === Engine ===

type EngineFile = { url: string, size: number, sha256: string, type: string }
const CDN = 'https://cdn.jsdelivr.net/npm'
const ENGINE_DEFAULT: EngineFile[] = [
  { url: `${CDN}/@wllama/wllama@${__WLLAMA_VERSION__}/esm/wasm/wllama.wasm`, size: __WLLAMA_WASM_SIZE__, sha256: __WLLAMA_WASM_SHA256__, type: 'application/wasm' },
]
// For browsers without JSPI or Memory64 (Safari, older browsers): slower, but works.
const ENGINE_COMPAT: EngineFile[] = [
  { url: `${CDN}/@wllama/wllama-compat@${__WLLAMA_VERSION__}/wasm/wllama.wasm`, size: __WLLAMA_COMPAT_WASM_SIZE__, sha256: __WLLAMA_COMPAT_WASM_SHA256__, type: 'application/wasm' },
  { url: `${CDN}/@wllama/wllama-compat@${__WLLAMA_VERSION__}/wasm/wllama.js`, size: __WLLAMA_COMPAT_JS_SIZE__, sha256: __WLLAMA_COMPAT_JS_SHA256__, type: 'text/javascript' },
]

function supportsJspi(): boolean {
  return !!(WebAssembly as any).Suspending
}

function supportsMemory64(): boolean {
  try {
    new WebAssembly.Memory({ address: 'i64', initial: 1n } as any)
    return true
  } catch {
    return false
  }
}

function needsCompat(): boolean {
  return !supportsJspi() || !supportsMemory64()
}

function engineFiles(): EngineFile[] {
  return needsCompat() ? ENGINE_COMPAT : ENGINE_DEFAULT
}

export function engineSize(): number {
  return engineFiles().reduce((n, f) => n + f.size, 0)
}

let wllamaMod: typeof import('@wllama/wllama') | null = null
let manager: ModelManager | null = null
let engine: Wllama | null = null
let loadedKey: string | null = null
let loadingPromise: Promise<void> | null = null
let queue: Promise<unknown> = Promise.resolve()
const engineBlobUrls = new Map<string, string>()
const downloadAborts = new Map<string, AbortController>()

const quietLogger = {
  debug: () => {},
  log: () => {},
  warn: (...a: unknown[]) => console.warn('[on-device AI]', ...a),
  error: (...a: unknown[]) => console.error('[on-device AI]', ...a),
}

async function mod() {
  if (!wllamaMod) wllamaMod = await import('@wllama/wllama')
  return wllamaMod
}

async function getManager(): Promise<ModelManager> {
  if (!manager) {
    const m = await mod()
    manager = new m.ModelManager({ logger: quietLogger, allowOffline: true, parallelDownloads: 2 })
  }
  return manager
}

async function sha256Hex(blob: Blob): Promise<string> {
  const buf = await crypto.subtle.digest('SHA-256', await blob.arrayBuffer())
  return [...new Uint8Array(buf)].map(b => b.toString(16).padStart(2, '0')).join('')
}

async function ensureEngine(onProgress?: (loaded: number) => void, signal?: AbortSignal): Promise<Map<string, string>> {
  const cm = (await getManager()).cacheManager
  const out = new Map<string, string>()
  let done = 0
  for (const f of engineFiles()) {
    const known = engineBlobUrls.get(f.url)
    if (known) { out.set(f.url, known); done += f.size; continue }
    let blob = await cm.open(f.url)
    if (!blob || blob.size !== f.size) {
      if (blob) await cm.delete(f.url)
      const base = done
      await cm.download(f.url, { signal, progressCallback: ({ loaded }) => onProgress?.(base + loaded) })
      blob = await cm.open(f.url)
    }
    if (!blob || (await sha256Hex(blob)) !== f.sha256) {
      await cm.delete(f.url).catch(() => {})
      throw new Error(t('The AI engine download was damaged. Please try again.'))
    }
    const url = URL.createObjectURL(new Blob([blob], { type: f.type }))
    engineBlobUrls.set(f.url, url)
    out.set(f.url, url)
    done += f.size
    onProgress?.(done)
  }
  return out
}

// === Models ===

export async function refreshLocal(): Promise<void> {
  if (!localSupported()) return
  try {
    const models = await (await getManager()).getModels()
    const have = LOCAL_MODELS.filter(info => models.some(m => m.url === info.url && m.size === info.size)).map(m => m.key)
    setState({ downloaded: have })
  } catch {
    // storage blocked (private window): nothing downloaded
  }
}

export async function downloadModel(key: string): Promise<void> {
  const info = modelInfo(key)
  if (!info) throw new Error(t('Unknown model'))
  if (state.progress[key] !== undefined) return
  const abort = new AbortController()
  downloadAborts.set(key, abort)
  const total = info.size + engineSize()
  setState({ progress: { ...state.progress, [key]: 0 }, error: '' })
  const report = (loaded: number) => setState({ progress: { ...state.progress, [key]: Math.min(1, loaded / total) } })
  try {
    // Ask the browser not to evict ~1 GB of model when space gets low.
    await navigator.storage?.persist?.().catch(() => false)
    await ensureEngine(report, abort.signal)
    const engineBytes = engineSize()
    const mm = await getManager()
    await mm.downloadModel(info.url, {
      signal: abort.signal,
      progressCallback: ({ loaded }: { loaded: number }) => report(engineBytes + loaded),
    } as any)
    await refreshLocal()
  } catch (e) {
    if (!abort.signal.aborted) {
      const msg = e instanceof Error ? e.message : String(e)
      setState({ error: /quota|space/i.test(msg) ? t('Not enough free storage in this browser for the model.') : t('Download failed: {message}', { message: msg }) })
    }
  } finally {
    downloadAborts.delete(key)
    const { [key]: _done, ...rest } = state.progress
    setState({ progress: rest })
  }
}

export function cancelDownload(key: string) {
  downloadAborts.get(key)?.abort()
}

export async function removeModel(key: string): Promise<void> {
  const info = modelInfo(key)
  if (!info) return
  if (loadedKey === key && engine) {
    await engine.exit().catch(() => {})
    engine = null
    loadedKey = null
  }
  const mm = await getManager()
  for (const m of await mm.getModels({ includeInvalid: true })) if (m.url === info.url) await m.remove()
  await refreshLocal()
}

async function ensureLoaded(key: string): Promise<Wllama> {
  if (engine && loadedKey === key) return engine
  if (loadingPromise) await loadingPromise.catch(() => {})
  if (engine && loadedKey === key) return engine
  const info = modelInfo(key)
  if (!info) throw new Error(t('Unknown model'))
  setState({ loading: key })
  loadingPromise = (async () => {
    if (engine) {
      await engine.exit().catch(() => {})
      engine = null
      loadedKey = null
    }
    const m = await mod()
    const mm = await getManager()
    const model = (await mm.getModels()).find(x => x.url === info.url)
    if (!model) throw new Error(t('{model} is not downloaded yet.', { model: info.name }))
    const urls = await ensureEngine()
    const compat = needsCompat()
    let compatWorker = ''
    if (compat) {
      const js = await mm.cacheManager.open(ENGINE_COMPAT[1].url)
      compatWorker = js ? await js.text() : ''
    }
    const make = () => {
      const w = new m.Wllama(
        { default: urls.get((compat ? ENGINE_COMPAT : ENGINE_DEFAULT)[0].url)! },
        { logger: quietLogger, allowOffline: true, modelManager: mm },
      )
      w.setCompat(compat ? { worker: { code: compatWorker }, wasm: urls.get(ENGINE_COMPAT[0].url)! } : null)
      return w
    }
    const threads = Math.max(1, Math.min(4, (navigator.hardwareConcurrency || 2) - 1))
    const params = isMobile()
      ? { n_ctx: contextTokens(), n_batch: 256, n_ubatch: 256, n_threads: threads }
      : { n_ctx: contextTokens(), n_threads: threads }
    let w = make()
    // WebGPU on phones is still unreliable, so phones always use the CPU.
    const tryGpu = !isMobile() && !compat && w.isSupportWebGPU()
    try {
      await w.loadModel(model, { ...params, n_gpu_layers: tryGpu ? 999 : 0 } as any)
    } catch (e) {
      await w.exit().catch(() => {})
      if (!tryGpu) throw e
      w = make()
      await w.loadModel(model, { ...params, n_gpu_layers: 0 } as any)
    }
    engine = w
    loadedKey = key
  })()
  try {
    await loadingPromise
  } finally {
    loadingPromise = null
    setState({ loading: null })
  }
  return engine!
}

export type ChatMessage = { role: 'system' | 'user' | 'assistant', content: string }

/**
 * Runs one chat completion on this device and streams the text through onText.
 * Only one generation runs at a time (the engine has a single context).
 */
export async function chatLocal(
  key: string,
  messages: ChatMessage[],
  onText: (full: string) => void,
  opts: { maxTokens?: number, signal?: AbortSignal } = {},
): Promise<string> {
  const run = async () => {
    let out = ''
    try {
      const w = await ensureLoaded(key)
      if (opts.signal?.aborted) return out
      const stream = await w.createChatCompletion({
        messages,
        max_tokens: opts.maxTokens ?? 512,
        temperature: 0.3,
        top_p: 0.9,
        stream: true,
        abortSignal: opts.signal,
      } as any)
      for await (const chunk of stream as unknown as AsyncIterable<any>) {
        if (opts.signal?.aborted) break
        const piece = chunk?.choices?.[0]?.delta?.content
        if (typeof piece === 'string' && piece) {
          out += piece
          onText(out)
        }
      }
      return out.trim()
    } catch (e) {
      if (opts.signal?.aborted || (e as any)?.name === 'AbortError') return out.trim()
      const msg = e instanceof Error ? e.message : String(e)
      // A crashed engine can't be reused; the next question starts a fresh one.
      if (/ABORT|crash|RuntimeError|unreachable/i.test(msg) && engine) {
        const dead = engine
        engine = null
        loadedKey = null
        void dead.exit().catch(() => {})
      }
      throw new Error(/memory|OOM|allocate/i.test(msg)
        ? t('Not enough memory to run this model. Close other tabs or choose Qwen 2.5 0.5B.')
        : t('The on-device AI stopped ({message}). Try again.', { message: msg.trim() || t('unknown error') }))
    }
  }
  const p = queue.then(run, run)
  queue = p.catch(() => {})
  return p
}

/** Picks the model to use: the chosen one if downloaded, else any downloaded one. */
export function readyModel(preferred: string): string | null {
  if (state.downloaded.includes(preferred)) return preferred
  return state.downloaded[0] ?? null
}
