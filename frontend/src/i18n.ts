/**
 * Interface language: Bahasa Indonesia (default) or English.
 *
 * Texts are written in English in the code and wrapped in t('...'); the Indonesian
 * translation is looked up in ./i18n-id.ts. A missing entry simply shows the English text.
 * Placeholders such as {n} are filled from the second argument.
 */
import { ID } from './i18n-id'

export type Lang = 'id' | 'en'
const KEY = 'soilboring-lang'

function initial(): Lang {
  try {
    const saved = localStorage.getItem(KEY)
    if (saved === 'id' || saved === 'en') return saved
  } catch {
    // storage blocked
  }
  return 'id'
}

let current: Lang = initial()

export function lang(): Lang {
  return current
}

/** Switches the language; the page reloads so every screen picks it up. */
export function setLang(next: Lang) {
  if (next === current) return
  current = next
  try { localStorage.setItem(KEY, next) } catch { /* ignore */ }
  window.location.reload()
}

export function t(text: string, vars?: Record<string, string | number>): string {
  let out = current === 'id' ? (ID[text] ?? text) : text
  if (vars) {
    for (const [k, v] of Object.entries(vars)) out = out.split(`{${k}}`).join(String(v))
  }
  return out
}

/** Locale for numbers and dates. */
export function locale(): string {
  return current === 'id' ? 'id-ID' : 'en-GB'
}

if (typeof document !== 'undefined') document.documentElement.lang = current
