import { FormEvent, useEffect, useState } from 'react'
import { createUser, deleteUser, listUsers, resetUserPassword, resetUserTwoFactor, User } from '../api'

type Props = {
  currentUserEmail: string
}

export default function UserAdmin({ currentUserEmail }: Props) {
  const [users, setUsers] = useState<User[]>([])
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [role, setRole] = useState<User['role']>('general')
  const [status, setStatus] = useState('Loading users...')
  const [busy, setBusy] = useState(false)
  const [resetTarget, setResetTarget] = useState<string | null>(null)
  const [resetPassword, setResetPassword] = useState('')

  const loadUsers = async (silent = false) => {
    if (!silent) {
      setStatus('Loading users...')
    }
    try {
      const res = await listUsers()
      setUsers(res)
      if (!silent) {
        setStatus('')
      }
    } catch (err: any) {
      setStatus(`Error: ${err.message}`)
    }
  }

  useEffect(() => {
    void loadUsers()
  }, [])

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault()
    if (busy) return
    if (!email.trim() || !password.trim()) {
      setStatus('Email and password are required')
      return
    }
    setBusy(true)
    setStatus('Creating user...')
    try {
      await createUser({ email: email.trim(), password, role })
      setEmail('')
      setPassword('')
      setRole('general')
      setStatus('User created')
      await loadUsers(true)
    } catch (err: any) {
      setStatus(`Error: ${err.message}`)
    } finally {
      setBusy(false)
    }
  }

  const onDelete = async (targetEmail: string) => {
    if (busy) return
    if (!window.confirm(`Remove ${targetEmail}? This cannot be undone.`)) return
    setBusy(true)
    setStatus('Removing user...')
    try {
      await deleteUser(targetEmail)
      setStatus('User removed')
      await loadUsers(true)
    } catch (err: any) {
      setStatus(`Error: ${err.message}`)
    } finally {
      setBusy(false)
    }
  }

  const onReset = async (e: FormEvent) => {
    e.preventDefault()
    if (!resetTarget || busy) return
    if (resetPassword.length < 8) {
      setStatus('The new password needs at least 8 characters.')
      return
    }
    setBusy(true)
    setStatus(`Resetting the password of ${resetTarget}...`)
    try {
      await resetUserPassword(resetTarget, resetPassword)
      setStatus(`Password of ${resetTarget} reset. Their other sessions were signed out.`)
      setResetTarget(null)
      setResetPassword('')
    } catch (err: any) {
      setStatus(`Error: ${err.message}`)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
      <div className="card">
        <h3 style={{ marginTop: 0 }}>Add User</h3>
        <form onSubmit={onSubmit} className="row">
          <div>
            <label htmlFor="new-user-email">Email</label>
            <input id="new-user-email" type="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="user@example.com" required />
          </div>
          <div>
            <label htmlFor="new-user-password">Password</label>
            <input id="new-user-password" type="password" autoComplete="new-password" minLength={8} value={password} onChange={e => setPassword(e.target.value)} placeholder="At least 8 characters" required />
            <label htmlFor="new-user-role">Role</label>
            <select id="new-user-role" value={role} onChange={e => setRole(e.target.value as User['role'])}>
              <option value="general">General (no user admin)</option>
              <option value="admin">Admin</option>
            </select>
          </div>
          <div style={{ gridColumn: '1 / -1', display: 'flex', alignItems: 'center', gap: '.75rem', flexWrap: 'wrap' }}>
            <button type="submit" disabled={busy}>Create</button>
            <span>{status}</span>
          </div>
        </form>
      </div>

      <div className="card">
        <h3 style={{ marginTop: 0 }}>Existing Users</h3>
        {users.length === 0 ? (
          <p style={{ color: 'var(--muted)' }}>No users found.</p>
        ) : (
          <ul style={{ listStyle: 'none', padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: '.5rem' }}>
            {users.map(u => (
              <li key={u.email} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '.5rem', border: '1px solid var(--border)', borderRadius: '.5rem', padding: '.75rem 1rem' }}>
                <div>
                  <div><strong>{u.email}</strong></div>
                  <div style={{ color: 'var(--muted)', fontSize: '.9rem' }}>Role: {u.role} · {u.totp_enabled ? 'Two-step verification: on' : 'Two-step verification: off'}</div>
                </div>
                <div style={{ display: 'flex', gap: '.5rem', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
                {u.email.toLowerCase() !== currentUserEmail.toLowerCase() && (
                  <button onClick={() => { setResetTarget(u.email); setResetPassword('') }} disabled={busy}>
                    Reset Password
                  </button>
                )}
                {u.totp_enabled && (
                  <button
                    onClick={async () => {
                      if (!window.confirm(`Turn off two-step verification for ${u.email}? Use this when they lost their phone and their recovery codes.`)) return
                      try {
                        await resetUserTwoFactor(u.email)
                        setStatus('Two-step verification turned off')
                        await loadUsers(true)
                      } catch (err: any) {
                        setStatus(`Error: ${err.message}`)
                      }
                    }}
                    disabled={busy}
                  >
                    Turn off 2FA
                  </button>
                )}
                <button
                  onClick={() => onDelete(u.email)}
                  disabled={busy || u.email.toLowerCase() === currentUserEmail.toLowerCase()}
                  style={{ background: 'var(--danger)' }}
                  title={u.email.toLowerCase() === currentUserEmail.toLowerCase() ? 'You cannot remove the account currently in use' : 'Delete user'}
                >
                  Remove
                </button>
                </div>
                {resetTarget === u.email && (
                  <form onSubmit={onReset} style={{ display: 'flex', gap: '.5rem', alignItems: 'center', flexWrap: 'wrap', width: '100%' }}>
                    <label htmlFor="reset-password" style={{ margin: 0 }}>New password for {u.email}</label>
                    <input id="reset-password" type="password" autoComplete="new-password" minLength={8} value={resetPassword} onChange={e => setResetPassword(e.target.value)} required />
                    <button type="submit" disabled={busy}>Save</button>
                    <button type="button" onClick={() => setResetTarget(null)}>Cancel</button>
                  </form>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
