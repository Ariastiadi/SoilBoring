/** Unsaved edits on screen (depth data): asked about before leaving that screen. */
import { t } from './i18n'

let dirty = false

export function setUnsaved(value: boolean) {
  dirty = value
}

/** True when it is fine to leave (nothing unsaved, or the user agreed to drop it). */
export function confirmLeave(): boolean {
  if (!dirty) return true
  const ok = window.confirm(t('You have unsaved changes. Close anyway?'))
  if (ok) dirty = false
  return ok
}

window.addEventListener('beforeunload', event => {
  if (dirty) {
    event.preventDefault()
    event.returnValue = ''
  }
})
