import { FormEvent, Fragment, useEffect, useState } from 'react'
import { type AccountRequest, type Rec, approveAccountRequest, createUser, deleteUser, listAccountRequests, listRecords, listUsers, rejectAccountRequest, resetUserPassword, resetUserTwoFactor, setClientLinks, User } from '../api'
import { t } from '../i18n'
import { Icon, PageHead, ROLE_LABELS, formatDate } from '../ui'

type Props = {
  currentUserEmail: string
  /** Called after a request was approved or rejected (the menu shows how many wait). */
  onRequestsChanged?: () => void
}

const ROLE_CHOICES = ['general', 'lab', 'manager', 'finance', 'admin', 'client']

/** Client records a client account belongs to (it sees only their projects' issued reports and logs). */
function ClientPicker({ clients, value, onChange, id }: { clients: Rec[], value: string[], onChange: (v: string[]) => void, id: string }) {
  if (!clients.length) return <p className="help">{t('Add the client under Clients first.')}</p>
  return (
    <div className="checks" id={id} role="group" aria-label={t('Client')}>
      {clients.map(c => (
        <label key={c.id} className="checkbox">
          <input type="checkbox" checked={value.includes(c.id)} onChange={e => onChange(e.target.checked ? [...value, c.id] : value.filter(x => x !== c.id))} />
          {c.name}
        </label>
      ))}
    </div>
  )
}

const DEPARTMENT_LABELS: Record<string, string> = {
  field: 'Field work (drilling, CPT, survey)', lab: 'Laboratory', engineering: 'Engineering / project leader',
  finance: 'Finance', management: 'Management', other: 'Other',
}

export default function UserAdmin({ currentUserEmail, onRequestsChanged }: Props) {
  const [users, setUsers] = useState<User[]>([])
  const [requests, setRequests] = useState<AccountRequest[]>([])
  const [requestRoles, setRequestRoles] = useState<Record<string, User['role']>>({})
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [role, setRole] = useState<User['role']>('general')
  const [status, setStatus] = useState(() => t('Loading users...'))
  const [busy, setBusy] = useState(false)
  const [resetTarget, setResetTarget] = useState<string | null>(null)
  const [resetPassword, setResetPassword] = useState('')
  const [clients, setClients] = useState<Rec[]>([])
  const [newClients, setNewClients] = useState<string[]>([])
  const [requestClients, setRequestClients] = useState<Record<string, string[]>>({})
  const [linkTarget, setLinkTarget] = useState<string | null>(null)
  const [links, setLinks] = useState<string[]>([])
  useEffect(() => { listRecords('clients').then(setClients).catch(() => setClients([])) }, [])
  const clientNames = (ids?: string[]) => (ids || []).map(id => clients.find(c => c.id === id)?.name || id).join(', ')

  const loadUsers = async (silent = false) => {
    if (!silent) {
      setStatus(t('Loading users...'))
    }
    try {
      const [res, open] = await Promise.all([listUsers(), listAccountRequests()])
      setUsers(res)
      setRequests(open)
      if (!silent) {
        setStatus('')
      }
    } catch (err: any) {
      setStatus(t('Error: {message}', { message: err.message }))
    }
  }

  useEffect(() => {
    void loadUsers()
  }, [])

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault()
    if (busy) return
    if (!email.trim() || !password.trim()) {
      setStatus(t('Email and password are required'))
      return
    }
    setBusy(true)
    setStatus(t('Creating user...'))
    try {
      await createUser({ email: email.trim(), password, role, client_ids: role === 'client' ? newClients : [] })
      setNewClients([])
      setEmail('')
      setPassword('')
      setRole('general')
      setStatus(t('User created'))
      await loadUsers(true)
    } catch (err: any) {
      setStatus(t('Error: {message}', { message: err.message }))
    } finally {
      setBusy(false)
    }
  }

  const onDelete = async (targetEmail: string) => {
    if (busy) return
    if (!window.confirm(t('Remove {email}? This cannot be undone.', { email: targetEmail }))) return
    setBusy(true)
    setStatus(t('Removing user...'))
    try {
      await deleteUser(targetEmail)
      setStatus(t('User removed'))
      await loadUsers(true)
    } catch (err: any) {
      setStatus(t('Error: {message}', { message: err.message }))
    } finally {
      setBusy(false)
    }
  }

  const onReset = async (e: FormEvent) => {
    e.preventDefault()
    if (!resetTarget || busy) return
    if (resetPassword.length < 8) {
      setStatus(t('The new password needs at least {n} characters.', { n: 8 }))
      return
    }
    setBusy(true)
    setStatus(t('Resetting the password of {email}...', { email: resetTarget }))
    try {
      await resetUserPassword(resetTarget, resetPassword)
      setStatus(t('Password of {email} reset. Their other sessions were signed out.', { email: resetTarget }))
      setResetTarget(null)
      setResetPassword('')
    } catch (err: any) {
      setStatus(t('Error: {message}', { message: err.message }))
    } finally {
      setBusy(false)
    }
  }

  const decide = async (req: AccountRequest, approve: boolean) => {
    if (busy) return
    const role = requestRoles[req.email] || req.suggested_role
    if (approve && role === 'admin' && !window.confirm(t('Give {email} full administrator access?', { email: req.email }))) return
    if (!approve && !window.confirm(t('Reject the account request of {email}?', { email: req.email }))) return
    setBusy(true)
    try {
      if (approve) {
        await approveAccountRequest(req.email, role, role === 'client' ? (requestClients[req.email] || []) : [])
        setStatus(t('{email} can now sign in as {role}.', { email: req.email, role: t(ROLE_LABELS[role] || role) }))
      } else {
        await rejectAccountRequest(req.email)
        setStatus(t('Request of {email} rejected.', { email: req.email }))
      }
      await loadUsers(true)
      onRequestsChanged?.()
    } catch (err: any) {
      setStatus(t('Error: {message}', { message: err.message }))
    } finally {
      setBusy(false)
    }
  }

  const me = currentUserEmail.toLowerCase()
  return (
    <div>
      <PageHead title={t('Users')} description={t('Who can sign in. Field users add logs and change their own; the laboratory records test results; project leaders run projects, quotations, contracts and reports; finance handles invoices; administrators can do everything and manage users; client accounts only see the issued reports of their own projects.')} />
      {requests.length > 0 && (
        <section className="card" style={{ marginBottom: '1rem' }}>
          <h2 style={{ display: 'flex', alignItems: 'center', gap: '.5rem' }}>{t('Account requests')} <span className="count">{requests.length}</span></h2>
          <p className="help">{t('People who asked for an account on the sign-in page. Check that you know them, choose their role, then approve. They sign in with the password they chose.')}</p>
          <ul className="request-list">
            {requests.map(req => (
              <li key={req.email} className="request-item">
                <div className="request-who">
                  <strong>{req.name}</strong>
                  <span className="bh-sub" style={{ overflowWrap: 'anywhere' }}>{req.email}</span>
                  <span className="help" style={{ margin: 0 }}>
                    {t(DEPARTMENT_LABELS[req.department] || 'Other')} · {t('Requested')} {formatDate(req.requested_at.slice(0, 10))}
                  </span>
                  {req.note && <span className="request-note">{req.note}</span>}
                </div>
                <div className="request-decide">
                  <label className="sr-only" htmlFor={`req-role-${req.email}`}>{t('Role for {email}', { email: req.email })}</label>
                  <select id={`req-role-${req.email}`} value={requestRoles[req.email] || req.suggested_role}
                    onChange={e => setRequestRoles(r => ({ ...r, [req.email]: e.target.value as User['role'] }))}>
                    {ROLE_CHOICES.map(r => <option key={r} value={r}>{t(ROLE_LABELS[r])}</option>)}
                  </select>
                  {(requestRoles[req.email] || req.suggested_role) === 'client' && (
                    <ClientPicker id={`req-clients-${req.email}`} clients={clients} value={requestClients[req.email] || []}
                      onChange={v => setRequestClients(r => ({ ...r, [req.email]: v }))} />
                  )}
                  <button type="button" className="primary" disabled={busy} onClick={() => void decide(req, true)}>{t('Approve')}</button>
                  <button type="button" className="danger-quiet" disabled={busy} onClick={() => void decide(req, false)}>{t('Reject')}</button>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}
      <div className="users-layout">
        <section>
          <div className="table-wrap">
            <table className="data-table">
              <thead><tr><th>{t('Email')}</th><th>{t('Role')}</th><th>{t('Two-step verification')}</th><th><span className="sr-only">{t('Actions')}</span></th></tr></thead>
              <tbody>
                {users.length === 0 && <tr><td colSpan={4} className="muted">{t('No users found.')}</td></tr>}
                {users.map(u => (
                  <Fragment key={u.email}>
                    <tr>
                      <td><strong style={{ overflowWrap: 'anywhere' }}>{u.email}</strong>{u.name && <div className="bh-sub">{u.name}</div>}{u.email.toLowerCase() === me && <div className="bh-sub">{t('You')}</div>}</td>
                      <td>{t(ROLE_LABELS[u.role] || u.role)}{u.role === 'client' && <div className="bh-sub">{clientNames(u.client_ids) || t('Not linked to a client yet')}</div>}</td>
                      <td><span className={`status${u.totp_enabled ? ' ok' : ''}`}>{u.totp_enabled ? t('On') : t('Off')}</span></td>
                      <td className="nowrap" style={{ textAlign: 'right' }}>
                        <details className="menu" style={{ display: 'inline-block' }}>
                          <summary className="button-like" style={{ minHeight: '2rem', padding: '.1rem .55rem' }} aria-label={t('More actions for {id}', { id: u.email })}><Icon name="more" /></summary>
                          <div className="menu-pop">
                            {u.email.toLowerCase() !== me && (
                              <button type="button" onClick={e => { (e.currentTarget.closest('details') as HTMLDetailsElement).open = false; setResetTarget(u.email); setResetPassword('') }} disabled={busy}>{t('Reset Password')}</button>
                            )}
                            {u.role === 'client' && (
                              <button type="button" disabled={busy} onClick={e => { (e.currentTarget.closest('details') as HTMLDetailsElement).open = false; setLinkTarget(u.email); setLinks(u.client_ids || []) }}>{t('Choose clients')}</button>
                            )}
                            {u.totp_enabled && (
                              <button type="button" disabled={busy} onClick={async e => {
                                (e.currentTarget.closest('details') as HTMLDetailsElement).open = false
                                if (!window.confirm(t('Turn off two-step verification for {email}? Use this when they lost their phone and their recovery codes.', { email: u.email }))) return
                                try {
                                  await resetUserTwoFactor(u.email)
                                  setStatus(t('Two-step verification turned off'))
                                  await loadUsers(true)
                                } catch (err: any) {
                                  setStatus(t('Error: {message}', { message: err.message }))
                                }
                              }}>{t('Turn off 2FA')}</button>
                            )}
                            <button type="button" className="danger-quiet" onClick={e => { (e.currentTarget.closest('details') as HTMLDetailsElement).open = false; void onDelete(u.email) }}
                              disabled={busy || u.email.toLowerCase() === me}
                              title={u.email.toLowerCase() === me ? t('You cannot remove the account currently in use') : t('Delete user')}>{t('Remove')}</button>
                          </div>
                        </details>
                      </td>
                    </tr>
                    {linkTarget === u.email && (
                      <tr>
                        <td colSpan={4}>
                          <div className="field" style={{ margin: 0 }}>
                            <label htmlFor="link-clients">{t('Clients of {email}', { email: u.email })}</label>
                            <ClientPicker id="link-clients" clients={clients} value={links} onChange={setLinks} />
                            <div className="actions">
                              <button type="button" className="primary" disabled={busy} onClick={async () => {
                                try {
                                  await setClientLinks(u.email, links)
                                  setStatus(t('Saved.'))
                                  setLinkTarget(null)
                                  await loadUsers(true)
                                } catch (err: any) {
                                  setStatus(t('Error: {message}', { message: err.message }))
                                }
                              }}>{t('Save')}</button>
                              <button type="button" onClick={() => setLinkTarget(null)}>{t('Cancel')}</button>
                            </div>
                          </div>
                        </td>
                      </tr>
                    )}
                    {resetTarget === u.email && (
                      <tr key={`${u.email}-reset`}>
                        <td colSpan={4}>
                          <form onSubmit={onReset} className="actions">
                            <label htmlFor="reset-password" style={{ margin: 0 }}>{t('New password for {email}', { email: u.email })}</label>
                            <input id="reset-password" type="password" autoComplete="new-password" minLength={8} value={resetPassword} onChange={e => setResetPassword(e.target.value)} required />
                            <button type="submit" className="primary" disabled={busy}>{t('Save')}</button>
                            <button type="button" onClick={() => setResetTarget(null)}>{t('Cancel')}</button>
                          </form>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>
          {status && <p role="status" className="muted small">{status}</p>}
        </section>
        <section className="card">
          <h2>{t('Add User')}</h2>
          <form onSubmit={onSubmit} style={{ display: 'grid', gap: '.75rem' }}>
            <div className="field">
              <label htmlFor="new-user-email">{t('Email')}</label>
              <input id="new-user-email" type="email" value={email} onChange={e => setEmail(e.target.value)} required />
            </div>
            <div className="field">
              <label htmlFor="new-user-password">{t('Password')}</label>
              <input id="new-user-password" type="password" autoComplete="new-password" minLength={8} value={password} onChange={e => setPassword(e.target.value)} required />
              <p className="help">{t('At least {n} characters', { n: 8 })}</p>
            </div>
            <div className="field">
              <label htmlFor="new-user-role">{t('Role')}</label>
              <select id="new-user-role" value={role} onChange={e => setRole(e.target.value as User['role'])}>
                {ROLE_CHOICES.map(r => <option key={r} value={r}>{t(ROLE_LABELS[r])}</option>)}
              </select>
              {role === 'client' && <p className="help">{t('A client account only sees the approved reports, authorised lab results and borehole logs of its own projects.')}</p>}
            </div>
            {role === 'client' && (
              <div className="field">
                <label htmlFor="new-user-clients">{t('Client')}</label>
                <ClientPicker id="new-user-clients" clients={clients} value={newClients} onChange={setNewClients} />
              </div>
            )}
            <div className="actions"><button type="submit" className="primary" disabled={busy}>{t('Add user')}</button></div>
          </form>
        </section>
      </div>
    </div>
  )
}
