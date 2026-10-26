/**
 * Approval flow on a record: Konseptor → Pengulas → Pemutus. Shows where the record is, who did
 * what, and the steps this user may take (with a note; a note is required to return or reopen).
 */
import { useEffect, useState } from 'react'
import { getWorkflowActions, workflowStep, type Rec, type WorkflowStep } from './api'
import { t } from './i18n'
import { formatDate } from './ui'

const STAGES: Array<[string, string]> = [['draft', 'Drafter'], ['submitted', 'Reviewer'], ['reviewed', 'Approver'], ['approved', 'Approved']]

const ACTION_LABEL: Record<string, string> = {
  submit: 'Submit for review', review: 'Reviewed, forward for approval', approve: 'Approve',
  return: 'Return for correction', reopen: 'Reopen',
}

const DONE_LABEL: Record<string, string> = {
  submit: 'Submitted', review: 'Reviewed', approve: 'Approved', return: 'Returned', reopen: 'Reopened',
}

function when(at: string) {
  const d = new Date(at)
  return Number.isNaN(d.getTime()) ? at : `${formatDate(at.slice(0, 10))} ${d.toTimeString().slice(0, 5)}`
}

export function WorkflowPanel({ entity, record, onChanged }: { entity: string, record: Rec, onChanged: (r: Rec) => void }) {
  const [actions, setActions] = useState<string[]>([])
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const state = String(record.wf_status || 'draft')
  const history: WorkflowStep[] = Array.isArray(record.wf_history) ? record.wf_history : []
  useEffect(() => {
    let live = true
    getWorkflowActions(entity, record.id).then(r => { if (live) setActions(r.actions) }).catch(() => { if (live) setActions([]) })
    return () => { live = false }
  }, [entity, record.id, record.wf_status, record.updated_at])
  const run = async (action: string) => {
    if ((action === 'return' || action === 'reopen') && !note.trim()) {
      setError(t('Write the reason in the note'))
      return
    }
    setBusy(true)
    setError('')
    try {
      const out = await workflowStep(entity, record.id, action, note.trim())
      setNote('')
      setActions(out._actions || [])
      onChanged(out)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }
  const at = state === 'returned' ? 0 : Math.max(0, STAGES.findIndex(s => s[0] === state))
  return (
    <section className="card wf-panel" aria-label={t('Approval')}>
      <div className="wf-head">
        <h3 className="card-title">{t('Approval')}</h3>
        {state === 'returned' && <span className="status bad">{t('Returned for correction')}</span>}
      </div>
      <ol className="wf-steps">
        {STAGES.map(([key, label], i) => (
          <li key={key} className={i < at || state === 'approved' ? 'done' : i === at ? 'now' : ''} aria-current={i === at && state !== 'approved' ? 'step' : undefined}>
            <span className="wf-dot">{i < at || state === 'approved' ? '✓' : i + 1}</span>
            <span>{t(label)}</span>
          </li>
        ))}
      </ol>
      {actions.length > 0 && (
        <div className="wf-act">
          <label htmlFor={`wf-note-${record.id}`} className="small">{t('Note (required to return or reopen)')}</label>
          <textarea id={`wf-note-${record.id}`} rows={2} value={note} maxLength={1000} onChange={e => setNote(e.target.value)} />
          <div className="actions">
            {actions.map(a => (
              <button key={a} type="button" disabled={busy} className={a === 'approve' || a === 'review' || a === 'submit' ? 'primary' : a === 'return' ? 'quiet danger-quiet' : ''}
                onClick={() => { void run(a) }}>{t(ACTION_LABEL[a] || a)}</button>
            ))}
          </div>
        </div>
      )}
      {actions.length === 0 && state !== 'approved' && (
        <p className="help" style={{ margin: '.25rem 0 0' }}>
          {state === 'draft' || state === 'returned' ? t('The drafter submits this when it is complete.')
            : state === 'submitted' ? t('Waiting for a reviewer (manager).') : t('Waiting for the approver (director).')}
        </p>
      )}
      {error && <p className="notice error" role="alert">{error}</p>}
      {history.length > 0 && (
        <details className="wf-history" open={state === 'returned' || undefined}>
          <summary>{t('History')} · {history.length}</summary>
          <ul>
            {[...history].reverse().map((h, i) => (
              <li key={i}>
                <strong>{t(DONE_LABEL[h.action] || h.action)}</strong> <span className="muted small">{h.by} · {when(h.at)}</span>
                {h.note && <div className="wf-note">{h.note}</div>}
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  )
}
