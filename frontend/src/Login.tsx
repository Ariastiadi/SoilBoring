import { useState } from 'react'

type Props = {
  onLogin: (email: string, password: string) => Promise<void>
}

export default function Login({ onLogin }: Props) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [status, setStatus] = useState('')
  const [error, setError] = useState('')

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!email.trim() || !password.trim()) {
      setError('Email and password are required')
      return
    }
    setError('')
    setStatus('Signing in...')
    try {
      await onLogin(email.trim(), password)
      setStatus('Signed in')
    } catch (err: any) {
      setStatus('')
      setError(err?.message || 'Login failed')
    }
  }

  return (
    <div className="card" style={{ maxWidth: '480px', margin: '4rem auto', padding: '2rem' }}>
      <h2 style={{ marginTop: 0 }}>Soil Boring Access</h2>
      <p style={{ color: 'var(--muted)', marginBottom: '1.5rem' }}>
        Sign in with your assigned operator email and password to log boreholes.
      </p>
      <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '.75rem' }}>
        <label style={{ display: 'flex', flexDirection: 'column', gap: '.25rem' }}>
          Email
          <input
            type="email"
            value={email}
            onChange={e => setEmail(e.target.value)}
            placeholder="operator@example.com"
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
            placeholder="Password"
            autoComplete="current-password"
            required
          />
        </label>
        <button type="submit">Sign In</button>
        {status && <span style={{ color: 'var(--muted)' }}>{status}</span>}
        {error && <span style={{ color: 'var(--danger)' }}>{error}</span>}
      </form>
    </div>
  )
}
