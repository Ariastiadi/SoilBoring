import { useEffect, useState } from 'react'
import { getSetupStatus } from './api'

type Props = {
  onLogin: (email: string, password: string) => Promise<void>
  onSetup: (email: string, password: string) => Promise<void>
  title: string
}

const MIN_PASSWORD_LENGTH = 8

export default function Login({ onLogin, onSetup, title }: Props) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [status, setStatus] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  // A fresh deployment has no accounts yet: offer to create the first admin instead of signing in.
  const [setupMode, setSetupMode] = useState(false)

  useEffect(() => {
    let active = true
    getSetupStatus().then(needed => {
      if (active) setSetupMode(needed)
    })
    return () => { active = false }
  }, [])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (busy) return
    if (!email.trim() || !password.trim()) {
      setError('Email and password are required')
      return
    }
    if (setupMode) {
      if (password.length < MIN_PASSWORD_LENGTH) {
        setError(`Password must be at least ${MIN_PASSWORD_LENGTH} characters`)
        return
      }
      if (password !== confirm) {
        setError('The two passwords do not match')
        return
      }
    }
    setError('')
    setBusy(true)
    setStatus(setupMode ? 'Creating admin account...' : 'Signing in...')
    try {
      if (setupMode) {
        await onSetup(email.trim(), password)
      } else {
        await onLogin(email.trim(), password)
      }
      setStatus('Signed in')
    } catch (err: any) {
      setStatus('')
      // Someone finished setup in the meantime: fall back to the normal sign-in form.
      if (setupMode && err?.status === 409) setSetupMode(false)
      setError(err?.message || (setupMode ? 'Setup failed' : 'Login failed'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card" style={{ maxWidth: '480px', margin: '4rem auto', padding: '2rem' }}>
      <h2 style={{ marginTop: 0 }}>{title}</h2>
      <p style={{ color: 'var(--muted)', marginBottom: '1.5rem' }}>
        {setupMode
          ? 'Welcome! No accounts exist yet. Create the first administrator account; you can add operators afterwards under Users.'
          : 'Sign in with your assigned operator email and password to log boreholes.'}
      </p>
      <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '.75rem' }}>
        <label style={{ display: 'flex', flexDirection: 'column', gap: '.25rem' }}>
          Email
          <input
            type="email"
            value={email}
            onChange={e => setEmail(e.target.value)}
            placeholder={setupMode ? 'admin@example.com' : 'operator@example.com'}
            autoComplete="username"
            required
          />
        </label>
        <label style={{ display: 'flex', flexDirection: 'column', gap: '.25rem' }}>
          Password
          <input
            type="password"
            value={password}
            onChange={e => setPassword(e.target.value)}
            placeholder={setupMode ? `At least ${MIN_PASSWORD_LENGTH} characters` : 'Password'}
            autoComplete={setupMode ? 'new-password' : 'current-password'}
            minLength={setupMode ? MIN_PASSWORD_LENGTH : undefined}
            required
          />
        </label>
        {setupMode && (
          <label style={{ display: 'flex', flexDirection: 'column', gap: '.25rem' }}>
            Repeat password
            <input
              type="password"
              value={confirm}
              onChange={e => setConfirm(e.target.value)}
              autoComplete="new-password"
              required
            />
          </label>
        )}
        <button type="submit" disabled={busy}>{setupMode ? 'Create admin account' : 'Sign In'}</button>
        {status && <span style={{ color: 'var(--muted)' }}>{status}</span>}
        {error && <span style={{ color: 'var(--danger)' }}>{error}</span>}
      </form>
    </div>
  )
}
