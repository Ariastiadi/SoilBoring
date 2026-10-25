import { FormEvent, useState } from 'react'
import { changePassword } from './api'
import { t } from './i18n'

type Session = { token: string; email: string; role: import('./api').Role; expires_in: number }

type Props = {
  onChanged: (session: Session) => void
}

const MIN_LENGTH = 8

export default function ChangePassword({ onChanged }: Props) {
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [repeat, setRepeat] = useState('')
  const [status, setStatus] = useState('')
  const [busy, setBusy] = useState(false)

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault()
    if (busy) return
    if (next.length < MIN_LENGTH) {
      setStatus(t('The new password needs at least {n} characters.', { n: MIN_LENGTH }))
      return
    }
    if (next !== repeat) {
      setStatus(t('The two new passwords do not match.'))
      return
    }
    setBusy(true)
    setStatus(t('Saving...'))
    try {
      const session = await changePassword(current, next)
      setCurrent('')
      setNext('')
      setRepeat('')
      setStatus('')
      onChanged(session)
    } catch (err: any) {
      setStatus(t('Error: {message}', { message: err.message }))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="card">
      <h2>{t('Password')}</h2>
      <p className="muted small" style={{ marginTop: 0 }}>{t('Other devices signed in with this account will be signed out.')}</p>
      <form onSubmit={onSubmit} style={{ display: 'grid', gap: '.75rem', maxWidth: 420 }}>
        <div className="field">
          <label htmlFor="pw-current">{t('Current password')}</label>
          <input id="pw-current" type="password" autoComplete="current-password" value={current} onChange={e => setCurrent(e.target.value)} required />
        </div>
        <div className="field">
          <label htmlFor="pw-new">{t('New password')}</label>
          <input id="pw-new" type="password" autoComplete="new-password" minLength={MIN_LENGTH} value={next} onChange={e => setNext(e.target.value)} required />
          <p className="help">{t('At least {n} characters', { n: MIN_LENGTH })}</p>
        </div>
        <div className="field">
          <label htmlFor="pw-repeat">{t('Repeat new password')}</label>
          <input id="pw-repeat" type="password" autoComplete="new-password" minLength={MIN_LENGTH} value={repeat} onChange={e => setRepeat(e.target.value)} required />
        </div>
        <div className="actions">
          <button type="submit" className="primary" disabled={busy}>{t('Change password')}</button>
          <span role="status">{status}</span>
        </div>
      </form>
    </section>
  )
}
