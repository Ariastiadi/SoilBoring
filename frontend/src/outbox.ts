/**
 * Field use without signal: new borehole logs that cannot reach the server are kept in
 * this browser ("outbox") and sent automatically when the connection is back.
 * Each log remembers who made it and is only ever sent with that person's sign-in.
 */
import { getReport, postReport } from './api'

export type OutboxItem = { id: string, owner: string, data: Record<string, unknown>, queuedAt: number, error?: string }
const KEY = 'soilboring-outbox'
const listeners = new Set<(items: OutboxItem[]) => void>()
let currentUser = ''

function readAll(): OutboxItem[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(KEY) || '[]')
    return Array.isArray(parsed) ? parsed.filter(i => i && typeof i.id === 'string' && typeof i.owner === 'string' && i.data) : []
  } catch {
    return []
  }
}

const mine = (items: OutboxItem[]) => items.filter(i => currentUser && i.owner === currentUser)

function writeAll(items: OutboxItem[]) {
  try {
    if (items.length) localStorage.setItem(KEY, JSON.stringify(items))
    else localStorage.removeItem(KEY)
  } catch {
    // storage full: keep working in memory for this visit
  }
  const own = mine(items)
  listeners.forEach(l => l(own))
}

/** The signed-in user (lower case), or '' when signed out. */
export function setOutboxUser(email: string) {
  currentUser = (email || '').trim().toLowerCase()
  listeners.forEach(l => l(mine(readAll())))
}

export function outboxItems(): OutboxItem[] {
  return mine(readAll())
}

export function subscribeOutbox(listener: (items: OutboxItem[]) => void): () => void {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}

/** A failure that means "no connection" (as opposed to the server refusing the log). */
export function isNetworkError(err: unknown): boolean {
  const e = err as { name?: string, message?: string, status?: number }
  return !navigator.onLine || err instanceof TypeError || e?.name === 'AbortError' || e?.name === 'TimeoutError'
    || /Failed to fetch|NetworkError|Load failed|timed out/i.test(String(e?.message))
}

/** Server busy or restarting: try again later instead of marking the log as refused. */
function isTemporary(err: unknown): boolean {
  const status = (err as { status?: number })?.status ?? 0
  return isNetworkError(err) || status === 401 || status === 408 || status === 429 || status >= 500
}

/** Sends the log now, or keeps it for later when offline. */
export async function submitReport(data: Record<string, unknown>): Promise<'sent' | 'queued'> {
  try {
    await postReport(data)
    return 'sent'
  } catch (err) {
    if (!isNetworkError(err) || !currentUser) throw err
    const items = readAll()
    items.push({ id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`, owner: currentUser, data, queuedAt: Date.now() })
    writeAll(items)
    return 'queued'
  }
}

/** A 409 may mean the log did arrive earlier but the answer was lost: check before showing an error. */
async function alreadySaved(data: Record<string, unknown>): Promise<boolean> {
  try {
    const row = await getReport(String(data.BoreholeID ?? ''))
    return String(row?.SubmittedBy || '').toLowerCase() === currentUser
  } catch {
    return false
  }
}

let flushing: Promise<void> | null = null

/** Tries to send this user's waiting logs; stops at the first connection problem. */
export function flushOutbox(): Promise<void> {
  if (!flushing) {
    flushing = (async () => {
      for (const item of outboxItems()) {
        if (item.error || item.owner !== currentUser) continue
        try {
          await postReport(item.data)
          writeAll(readAll().filter(i => i.id !== item.id))
        } catch (err: any) {
          if (err?.status === 409 && await alreadySaved(item.data)) {
            writeAll(readAll().filter(i => i.id !== item.id))
            continue
          }
          if (isTemporary(err)) return
          // The server refused it (e.g. the Borehole ID already exists): keep it and show why.
          writeAll(readAll().map(i => (i.id === item.id ? { ...i, error: String(err?.message || err) } : i)))
        }
      }
    })().finally(() => { flushing = null })
  }
  return flushing
}

export function discardOutboxItem(id: string) {
  writeAll(readAll().filter(i => i.id !== id))
}

export function retryOutboxItem(id: string) {
  writeAll(readAll().map(i => (i.id === id ? { ...i, error: undefined } : i)))
  void flushOutbox()
}
