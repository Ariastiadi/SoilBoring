import { FormEvent, useEffect, useState } from 'react'
import { createUser, deleteUser, listUsers, User } from '../api'

type Props = {
  currentUserEmail: string
}

export default function UserAdmin({ currentUserEmail }: Props) {
  const [users, setUsers] = useState<User[]>([])
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [role, setRole] = useState<User['role']>('general')
  const [status, setStatus] = useState('Loading users...')

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
    if (!email.trim() || !password.trim()) {
      setStatus('Email and password are required')
      return
    }
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
    }
  }

  const onDelete = async (targetEmail: string) => {
    if (!window.confirm(`Remove ${targetEmail}? This cannot be undone.`)) return
    setStatus('Removing user...')
    try {
      await deleteUser(targetEmail)
      setStatus('User removed')
      await loadUsers(true)
    } catch (err: any) {
      setStatus(`Error: ${err.message}`)
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
      <div className="card">
        <h3 style={{ marginTop: 0 }}>Add User</h3>
        <form onSubmit={onSubmit} className="row">
          <div>
            <label>Email</label>
            <input type="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="user@example.com" required />
          </div>
          <div>
            <label>Password</label>
            <input type="password" autoComplete="new-password" minLength={8} value={password} onChange={e => setPassword(e.target.value)} placeholder="At least 8 characters" required />
            <label>Role</label>
            <select value={role} onChange={e => setRole(e.target.value as User['role'])}>
              <option value="general">General (no user admin)</option>
              <option value="admin">Admin</option>
            </select>
          </div>
          <div style={{ gridColumn: '1 / -1', display: 'flex', alignItems: 'center', gap: '.75rem', flexWrap: 'wrap' }}>
            <button type="submit">Create</button>
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
              <li key={u.email} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', border: '1px solid var(--border)', borderRadius: '.5rem', padding: '.75rem 1rem' }}>
                <div>
                  <div><strong>{u.email}</strong></div>
                  <div style={{ color: 'var(--muted)', fontSize: '.9rem' }}>Role: {u.role}</div>
                </div>
                <button
                  onClick={() => onDelete(u.email)}
                  disabled={u.email === currentUserEmail}
                  style={{ background: 'var(--danger, #c62828)' }}
                  title={u.email === currentUserEmail ? 'You cannot remove the account currently in use' : 'Delete user'}
                >
                  Remove
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
