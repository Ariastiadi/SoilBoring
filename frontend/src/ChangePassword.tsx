import { FormEvent, useState } from 'react'
import { changePassword } from './api'

type Session = { token: string; email: string; role: 'admin' | 'general'; expires_in: number }

type Props = {
  onChanged: (session: Session) => void
  onClose: () => void
}

const MIN_LENGTH = 8

export default function ChangePassword({ onChanged, onClose }: Props) {
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [repeat, setRepeat] = useState('')
  const [status, setStatus] = useState('')
  const [busy, setBusy] = useState(false)

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault()
    if (busy) return
    if (next.length < MIN_LENGTH) {
      setStatus(`The new password needs at least ${MIN_LENGTH} characters.`)
      return
    }
    if (next !== repeat) {
      setStatus('The two new passwords do not match.')
      return
    }
    setBusy(true)
    setStatus('Saving...')
    try {
      const session = await changePassword(current, next)
      onChanged(session)
    } catch (err: any) {
      setStatus(`Error: ${err.message}`)
      setBusy(false)
    }
  }

  return (
    <div className="card" style={{ maxWidth: '480px', margin: '1rem auto' }}>
      <h3 style={{ marginTop: 0 }}>Change Password</h3>
      <p style={{ color: 'var(--muted)', marginTop: 0, fontSize: '.9rem' }}>
        Other devices signed in with this account will be signed out.
      </p>
      <form onSubmit={onSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '.5rem' }}>
        <label htmlFor="pw-current">Current password</label>
        <input id="pw-current" type="password" autoComplete="current-password" value={current} onChange={e => setCurrent(e.target.value)} required />
        <label htmlFor="pw-new">New password</label>
        <input id="pw-new" type="password" autoComplete="new-password" minLength={MIN_LENGTH} value={next} onChange={e => setNext(e.target.value)} required />
        <label htmlFor="pw-repeat">Repeat new password</label>
        <input id="pw-repeat" type="password" autoComplete="new-password" minLength={MIN_LENGTH} value={repeat} onChange={e => setRepeat(e.target.value)} required />
        <div className="actions" style={{ marginTop: '.5rem', alignItems: 'center', flexWrap: 'wrap' }}>
          <button type="submit" disabled={busy}>Save Password</button>
          <button type="button" onClick={onClose} disabled={busy}>Cancel</button>
          <span role="status">{status}</span>
        </div>
      </form>
    </div>
  )
}
