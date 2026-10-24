/**
 * Field use without signal: new borehole logs that cannot reach the server are kept in
 * this browser ("outbox") and sent automatically when the connection is back.
 */
import { postReport } from './api'

export type OutboxItem = { id: string, data: Record<string, unknown>, queuedAt: number, error?: string }
const KEY = 'soilboring-outbox'
const listeners = new Set<(items: OutboxItem[]) => void>()

function read(): OutboxItem[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(KEY) || '[]')
    return Array.isArray(parsed) ? parsed.filter(i => i && typeof i.id === 'string' && i.data) : []
  } catch {
    return []
  }
}

function write(items: OutboxItem[]) {
  try {
    if (items.length) localStorage.setItem(KEY, JSON.stringify(items))
    else localStorage.removeItem(KEY)
  } catch {
    // storage full: keep working in memory for this visit
  }
  listeners.forEach(l => l(items))
}

export function outboxItems(): OutboxItem[] {
  return read()
}

export function subscribeOutbox(listener: (items: OutboxItem[]) => void): () => void {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}

/** A failure that means "no connection" (as opposed to the server refusing the log). */
export function isNetworkError(err: unknown): boolean {
  return !navigator.onLine || err instanceof TypeError || /Failed to fetch|NetworkError|Load failed/i.test(String((err as Error)?.message))
}

/** Sends the log now, or keeps it for later when offline. */
export async function submitReport(data: Record<string, unknown>): Promise<'sent' | 'queued'> {
  try {
    await postReport(data)
    return 'sent'
  } catch (err) {
    if (!isNetworkError(err)) throw err
    const items = read()
    items.push({ id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`, data, queuedAt: Date.now() })
    write(items)
    return 'queued'
  }
}

let flushing: Promise<void> | null = null

/** Tries to send every waiting log; stops at the first connection problem. */
export function flushOutbox(): Promise<void> {
  if (!flushing) {
    flushing = (async () => {
      for (const item of read()) {
        if (item.error) continue
        try {
          await postReport(item.data)
          write(read().filter(i => i.id !== item.id))
        } catch (err: any) {
          if (isNetworkError(err) || err?.status === 401) return
          // The server refused it (e.g. the Borehole ID already exists): keep it and show why.
          write(read().map(i => (i.id === item.id ? { ...i, error: String(err?.message || err) } : i)))
        }
      }
    })().finally(() => { flushing = null })
  }
  return flushing
}

export function discardOutboxItem(id: string) {
  write(read().filter(i => i.id !== id))
}

export function retryOutboxItem(id: string) {
  write(read().map(i => (i.id === id ? { ...i, error: undefined } : i)))
  void flushOutbox()
}
