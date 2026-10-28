/** Approvals inbox and the management overview. */
import { useEffect, useState } from 'react'
import { getApprovals, type ApprovalItem } from '../api'
import { t, translateServer } from '../i18n'
import { ENTITY_TAB, useNav, type Intent, type TabKey } from '../nav'
import { CommercialOverviewPanel } from './ErpCommercial'
import { OpsOverviewPanel } from './ErpOps'
import { MonitoringOverview } from './Monitoring'
import { SubmissionsInboxCard, WorkOverviewPanel } from './ErpWork'
import { PageHead, formatDate } from '../ui'

const GROUPS: Array<[string, string, string]> = [
  ['submitted', 'To review', 'Submitted by a drafter; check, correct or return it, then forward it for approval.'],
  ['reviewed', 'To approve', 'Reviewed and waiting for the approver.'],
  ['returned', 'Returned to you', 'Correct and submit again.'],
]

export function ApprovalsPage() {
  const { go } = useNav()
  const [items, setItems] = useState<ApprovalItem[] | null>(null)
  const [error, setError] = useState('')
  useEffect(() => { getApprovals().then(setItems).catch(e => setError(e.message)) }, [])
  return (
    <div className="page">
      <PageHead title={t('Approvals')} description={t('Documents waiting for you in the approval flow: drafter, reviewer, approver.')} />
      {error && <p className="notice error">{error}</p>}
      <SubmissionsInboxCard />
      {items && items.length === 0 && <p className="muted">{t('Nothing is waiting for you.')}</p>}
      {items && GROUPS.map(([state, title, help]) => {
        const list = items.filter(i => i.state === state)
        if (!list.length) return null
        return (
          <section key={state} className="card" style={{ marginBottom: '1rem' }}>
            <h3 className="card-title">{t(title)} <span className="muted small">· {list.length}</span></h3>
            <p className="help" style={{ marginTop: 0 }}>{t(help)}</p>
            <ul className="ws-list">
              {list.map(i => (
                <li key={i.entity + i.id}>
                  <span className="ws-no">{t(i.label_one)}</span>
                  <div className="ws-main">
                    <strong>{i.title}</strong>
                    <span className="ws-std">{i.by} · {formatDate(String(i.since || '').slice(0, 10))}{i.note ? ` · ${translateServer(i.note)}` : ''}</span>
                  </div>
                  <div className="ws-side">
                    <div className="ws-actions">
                      <button type="button" className="small primary" onClick={() => go(ENTITY_TAB[i.entity] || 'projects', { open: i.id })}>{t('Open')}</button>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          </section>
        )
      })}
    </div>
  )
}

/** For the directors and commissioners: commercial position, receivables, projects against budget,
 * equipment and maintenance, purchasing, assets and people, with what waits for approval. */
export function OverviewPage() {
  const { go } = useNav()
  const [items, setItems] = useState<ApprovalItem[] | null>(null)
  useEffect(() => { getApprovals().then(setItems).catch(() => setItems([])) }, [])
  const open = (tab: string, intent?: Intent) => go(tab as TabKey, intent)
  return (
    <div className="page">
      <PageHead title={t('Management overview')} description={t('Commercial position, receivables, projects against budget, equipment, purchasing, assets and people in one place.')} />
      {items && items.length > 0 && (
        <p className="notice warn">
          {t('{n} documents are waiting for you in the approval flow.', { n: items.length })}{' '}
          <button type="button" className="small" onClick={() => go('approvals')}>{t('Open approvals')}</button>
        </p>
      )}
      <CommercialOverviewPanel onOpen={open} />
      <OpsOverviewPanel onOpen={tab => open(tab)} />
      <MonitoringOverview />
      <WorkOverviewPanel onOpen={tab => open(tab)} />
    </div>
  )
}
