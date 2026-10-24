import { useEffect, useMemo, useState } from 'react'
import { getActivity, type AuditEvent } from '../api'
import { describeEvent, formatTime } from '../BoreholeDetail'
import { t } from '../i18n'

const ACCOUNT_LABELS: Record<string, string> = {
  'account.first_admin': 'First admin created',
  'account.password_changed': 'Password changed',
  'account.2fa_enabled': 'Two-step verification turned on',
  'account.2fa_disabled': 'Two-step verification turned off',
  'account.recovery_codes_created': 'Recovery codes created',
  'account.password_reset_with_code': 'Password reset with a recovery code',
  'account.reset_email_sent': 'Password reset email sent',
  'account.reset_email_failed': 'Password reset email failed',
  'account.password_reset_by_email': 'Password reset from email link',
  'user.created': 'User created',
  'user.deleted': 'User removed',
  'user.password_reset': 'Password reset by admin',
  'user.2fa_reset': 'Two-step verification turned off by admin',
}

function describe(e: AuditEvent): string {
  return ACCOUNT_LABELS[e.action] ? t(ACCOUNT_LABELS[e.action]) : describeEvent(e)
}

/** Admin view of every change: logs, depth data, photos and accounts. */
export default function Activity() {
  const [events, setEvents] = useState<AuditEvent[] | null>(null)
  const [error, setError] = useState('')
  const [filter, setFilter] = useState('')

  const load = () => {
    setError('')
    getActivity(undefined, 1000).then(setEvents).catch(e => setError(e.message))
  }
  useEffect(load, [])

  const shown = useMemo(() => {
    const q = filter.trim().toLowerCase()
    if (!events) return []
    return q ? events.filter(e => [e.user, e.target, e.action, describe(e)].join(' ').toLowerCase().includes(q)) : events
  }, [events, filter])

  return (
    <div className="card">
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: '.5rem', flexWrap: 'wrap', alignItems: 'center' }}>
        <h3 style={{ margin: 0 }}>{t('Activity log')}</h3>
        <div className="actions">
          <input value={filter} onChange={e => setFilter(e.target.value)} placeholder={t('Filter by user, borehole or action')} />
          <button type="button" onClick={load}>{t('Refresh')}</button>
        </div>
      </div>
      <p style={{ color: 'var(--muted)', fontSize: '.85rem' }}>{t('Who changed what, and when. The newest 5000 changes are kept.')}</p>
      {error && <p className="notice error">{error}</p>}
      {!events ? <p>{t('Loading…')}</p> : (
        <div className="table-scroll">
          <table className="grid-table">
            <thead><tr><th>{t('Time')}</th><th>{t('User')}</th><th>{t('Borehole / account')}</th><th>{t('Change')}</th></tr></thead>
            <tbody>
              {shown.map((e, i) => (
                <tr key={i}>
                  <td style={{ whiteSpace: 'nowrap' }}>{formatTime(e.at)}</td>
                  <td>{e.user}</td>
                  <td>{e.target}</td>
                  <td>{describe(e)}</td>
                </tr>
              ))}
              {!shown.length && <tr><td colSpan={4} style={{ color: 'var(--muted)' }}>{t('Nothing found.')}</td></tr>}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
