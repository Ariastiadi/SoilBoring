/**
 * Work coordination pages: my tasks and the project task board (standard phase tasks per service),
 * the field submission inbox (field → office hand-off with acknowledgement, processing and return),
 * the crew deployment roster with man-days and safety document warnings, and laboratory work orders
 * with turnaround targets, KPIs and the test queue. Live views come from /api/erp/work.
 */
import { ReactNode, useEffect, useMemo, useState } from 'react'
import { apiGet, apiPost, userDirectory, type Rec } from '../api'
import { t, translateServer } from '../i18n'
import { useNav, type Intent, type TabKey } from '../nav'
import { RecordsPage, STATUS_TONE, invalidate, money, number, optionLabel, useList, useSchemas, type FormTools } from '../records'
import { DateInput, Icon, PageHead, ScrollTable, formatDate, todayIso } from '../ui'
import './ErpWork.css'

// Status colours of the work records, added to the shared table where it has no entry yet.
const EXTRA_TONE: Record<string, string> = {
  todo: '', blocked: 'bad', acknowledged: 'active', processing: 'active', in_testing: 'active', awaiting_review: 'warn',
  ready: 'ok', reported: 'ok', finished: '', expiring: 'warn', expired: 'bad', ok: 'ok', on_site: 'active',
}
for (const [k, v] of Object.entries(EXTRA_TONE)) if (!(k in STATUS_TONE)) STATUS_TONE[k] = v

const MANAGERS = ['admin', 'manager']

function useLive<T>(path: string | null, refresh: unknown = 0): { data: T | null, error: string } {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    let live = true
    if (!path) return
    setError('')
    apiGet<T>(path).then(d => { if (live) setData(d) }).catch(e => { if (live) setError(e.message) })
    return () => { live = false }
  }, [path, refresh])
  return { data, error }
}

function Tone({ value, label }: { value: string, label: string }) {
  return <span className={`status ${STATUS_TONE[value] ?? ''}`}>{label}</span>
}

function Kpi({ label, value, sub, tone }: { label: string, value: ReactNode, sub?: ReactNode, tone?: 'bad' | 'warn' }) {
  return <div className={`kpi${tone ? ` wk-kpi-${tone}` : ''}`}><h4>{label}</h4><p>{value}</p>{sub && <span className="muted small">{sub}</span>}</div>
}

function useOption(entity: string, field: string) {
  const schemas = useSchemas()
  return (value: unknown) => {
    const f = schemas?.[entity]?.fields.find(x => x.name === field)
    return f ? optionLabel(f, value) : String(value ?? '')
  }
}

type Warning = { text: string, vars?: Record<string, string | number> }

function warningText(w: Warning) {
  const vars: Record<string, string | number> = {}
  for (const [k, v] of Object.entries(w.vars || {})) {
    vars[k] = typeof v === 'number' ? number(v) : typeof v === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(v) ? formatDate(v) : String(v)
  }
  return t(w.text, vars)
}

function WarningList({ list, title }: { list: Warning[] | undefined, title?: string }) {
  if (!list?.length) return null
  return (
    <div className="notice warn wk-checks" role="status">
      <strong>{title || t('Check before continuing')}</strong>
      <ul>{list.map((w, i) => <li key={i}>{warningText(w)}</li>)}</ul>
    </div>
  )
}

const go2 = (go: (tab: TabKey, intent?: Intent) => void) => (tab: string, intent?: Intent) => go(tab as TabKey, intent)

/** Days left until a date, or how late: "3 days left", "2 days late", "today". */
function DueChip({ due, done, overdue }: { due?: string, done?: boolean, overdue?: boolean }) {
  if (!due) return <span className="muted small">{t('No due date')}</span>
  const days = Math.round((new Date(due + 'T00:00:00').getTime() - new Date(todayIso() + 'T00:00:00').getTime()) / 86400000)
  const late = overdue ?? (!done && days < 0)
  return (
    <span className={`wk-due${late ? ' late' : !done && days <= 2 ? ' soon' : ''}`}>
      {formatDate(due)}
      {!done && <> · {days < 0 ? t('{n} days late', { n: -days }) : days === 0 ? t('today') : t('{n} days left', { n: days })}</>}
    </span>
  )
}

function Bar({ pct, label }: { pct: number | null | undefined, label?: string }) {
  const v = Math.max(0, Math.min(100, Number(pct) || 0))
  return (
    <div className="wk-bar" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={v} aria-label={label || t('Progress')}>
      <span style={{ width: `${v}%` }} />
    </div>
  )
}

function Segments({ value, onChange, options, label }: { value: string, onChange: (v: string) => void, options: Array<[string, string]>, label: string }) {
  return (
    <div className="segmented" role="group" aria-label={label}>
      {options.map(([k, l]) => <button key={k} type="button" aria-pressed={value === k} onClick={() => onChange(k)}>{t(l)}</button>)}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tasks
// ---------------------------------------------------------------------------

type TaskRow = Rec & { overdue?: boolean, days_left?: number | null, project_code?: string, project_name?: string, _can_status?: boolean }

const TASK_STATUSES: Array<[string, string]> = [['todo', 'To do'], ['in_progress', 'In progress'], ['blocked', 'Blocked'], ['done', 'Done']]
const PHASE_LABELS: Record<string, string> = {
  reconnaissance: 'Site reconnaissance', mobilisation: 'Mobilisation', field_data: 'Field data collection',
  processing: 'Data processing and laboratory', analysis: 'Analysis and interpretation', report: 'Report', demobilisation: 'Demobilisation', other: 'Other',
}

/** Standard tasks keep their English title on the server; it is shown in the interface language until someone renames it. */
function useTaskTitle() {
  const service = useOption('tasks', 'service')
  return (task: Rec) => task.template_key && task.generated_title && task.title === task.generated_title
    ? `${t(PHASE_LABELS[task.phase] || task.phase)} – ${service(task.service)}` : String(task.title || '')
}

function StatusPicker({ task, onChanged }: { task: TaskRow, onChanged: (r: Rec) => void }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const change = async (status: string) => {
    if (status === task.status) return
    let note = ''
    if (status === 'blocked') {
      note = window.prompt(t('Why is it blocked?'), task.blocked_reason || '') || ''
      if (!note.trim()) return
    }
    setBusy(true); setError('')
    try {
      onChanged(await apiPost<Rec>(`/api/erp/work/tasks/${task.id}/status`, { status, note }))
      invalidate('tasks')
    } catch (e: any) { setError(e.message) } finally { setBusy(false) }
  }
  return (
    <div className="wk-status-pick">
      <div className="segmented small" role="group" aria-label={t('Status')}>
        {TASK_STATUSES.map(([k, l]) => (
          <button key={k} type="button" disabled={busy} aria-pressed={task.status === k} onClick={e => { e.stopPropagation(); void change(k) }}>{t(l)}</button>
        ))}
      </div>
      {error && <p className="notice error small">{error}</p>}
    </div>
  )
}

function Checklist({ task, onChanged, editable }: { task: TaskRow, onChanged: (r: Rec) => void, editable: boolean }) {
  const rows: Array<{ item: string, done?: boolean }> = Array.isArray(task.checklist) ? task.checklist : []
  const [busy, setBusy] = useState(false)
  if (!rows.length) return null
  const tick = async (i: number, v: boolean) => {
    setBusy(true)
    try {
      onChanged(await apiPost<Rec>(`/api/erp/work/tasks/${task.id}/status`, { status: task.status, checklist: rows.map((r, j) => (j === i ? v : !!r.done)) }))
      invalidate('tasks')
    } catch (e: any) { alert(e.message) } finally { setBusy(false) }
  }
  return (
    <ul className="wk-checklist">
      {rows.map((r, i) => (
        <li key={i}>
          <label className="checkbox">
            <input type="checkbox" checked={!!r.done} disabled={!editable || busy} onChange={e => { void tick(i, e.target.checked) }} />
            {translateServer(r.item)}
          </label>
        </li>
      ))}
    </ul>
  )
}

function TaskCard({ task, onChanged, onOpen, showProject, expand }: {
  task: TaskRow, onChanged: (r: Rec) => void, onOpen: () => void, showProject?: boolean, expand?: boolean
}) {
  const title = useTaskTitle()
  const priority = useOption('tasks', 'priority')
  const [open, setOpen] = useState(!!expand)
  const rows = Array.isArray(task.checklist) ? task.checklist : []
  const canStatus = task._can_status ?? true
  return (
    <article className={`wk-card${task.overdue ? ' overdue' : ''}${task.status === 'done' ? ' done' : ''}`}>
      <div className="wk-card-head">
        <button type="button" className="quiet wk-card-title" onClick={onOpen}>{title(task)}</button>
        {['high', 'urgent'].includes(task.priority) && <span className={`wk-prio ${task.priority}`}>{priority(task.priority)}</span>}
      </div>
      <div className="wk-card-meta">
        {showProject && task.project_code && <span>{task.project_code}</span>}
        {task.phase && task.phase !== 'other' && !(task.template_key && task.title === task.generated_title) && <span>{t(PHASE_LABELS[task.phase] || task.phase)}</span>}
        <span>{task.assignee || t('Not assigned')}</span>
      </div>
      <DueChip due={task.due_date} done={task.status === 'done'} overdue={task.overdue} />
      {task.status === 'blocked' && task.blocked_reason && <p className="wk-blocked">{task.blocked_reason}</p>}
      {rows.length > 0 && (
        <button type="button" className="quiet wk-check-toggle" aria-expanded={open} onClick={() => setOpen(!open)}>
          <Bar pct={task.checklist_pct} label={t('Checklist')} />
          <span className="small">{t('{a} of {b} done', { a: rows.filter((r: Rec) => r.done).length, b: rows.length })}</span>
        </button>
      )}
      {open && <Checklist task={task} onChanged={onChanged} editable={canStatus} />}
      {canStatus && <StatusPicker task={task} onChanged={onChanged} />}
    </article>
  )
}

export function MyTasksPage() {
  const { go } = useNav()
  const [round, setRound] = useState(0)
  const { data, error } = useLive<TaskRow[]>('/api/erp/work/my-tasks', round)
  const [rows, setRows] = useState<TaskRow[] | null>(null)
  useEffect(() => { if (data) setRows(data) }, [data])
  const update = (r: Rec) => setRows(list => (list || []).map(x => (x.id === r.id ? { ...x, ...r, overdue: !!r.due_date && r.status !== 'done' && r.due_date < todayIso() } : x)))
  const open = (rows || []).filter(r => r.status !== 'done')
  return (
    <div className="page">
      <PageHead title={t('My tasks')} description={t('Tasks assigned to you, overdue first. Change the status and tick the checklist as you go.')}
        actions={<button type="button" onClick={() => go('tasks')}><Icon name="list" />{t('Project task board')}</button>} />
      {error && <p className="notice error">{error}</p>}
      {!rows ? <p className="muted">{t('Loading…')}</p> : <>
        <div className="kpis wk-kpis">
          <Kpi label={t('Open')} value={open.length} />
          <Kpi label={t('Overdue')} value={open.filter(r => r.overdue).length} tone={open.some(r => r.overdue) ? 'bad' : undefined} />
          <Kpi label={t('Blocked')} value={open.filter(r => r.status === 'blocked').length} />
          <Kpi label={t('Done in the last 14 days')} value={rows.length - open.length} />
        </div>
        {!rows.length && <div className="card"><p style={{ margin: 0 }}>{t('Nothing is assigned to you.')}</p></div>}
        <div className="wk-cards">
          {rows.map(r => <TaskCard key={r.id} task={r} showProject onChanged={update} onOpen={() => go('tasks', { open: r.id })} />)}
        </div>
        <p className="help"><button type="button" className="quiet small" onClick={() => setRound(n => n + 1)}>{t('Refresh')}</button></p>
      </>}
    </div>
  )
}

function StandardTasksButton({ projectId, onDone }: { projectId: string, onDone: (msg: string) => void }) {
  const { role } = useNav()
  const [preview, setPreview] = useState<Array<{ exists: boolean }> | null>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    let live = true
    setPreview(null)
    if (!projectId || !MANAGERS.includes(role)) return
    apiGet<Array<{ exists: boolean }>>(`/api/erp/work/projects/${projectId}/standard-tasks`).then(p => { if (live) setPreview(p) }).catch(() => {})
    return () => { live = false }
  }, [projectId, role, busy])
  if (!preview) return null
  const missing = preview.filter(p => !p.exists).length
  if (!missing) return null
  const run = async () => {
    setBusy(true)
    try {
      const out = await apiPost<{ created: number, skipped: number }>(`/api/erp/work/projects/${projectId}/standard-tasks`, {})
      invalidate('tasks')
      onDone(t('{n} standard tasks created.', { n: out.created }))
    } catch (e: any) { onDone(e.message) } finally { setBusy(false) }
  }
  return <button type="button" disabled={busy} onClick={() => { void run() }}><Icon name="plus" />{t('Create standard tasks ({n})', { n: missing })}</button>
}

function TaskBoard({ project, mine, onOpen, refresh }: { project: string, mine: boolean, onOpen: (id: string) => void, refresh: number }) {
  const { email } = useNav()
  const { data, error } = useLive<TaskRow[]>(`/api/erp/work/tasks${project ? `?project_id=${project}` : ''}`, refresh)
  const [rows, setRows] = useState<TaskRow[] | null>(null)
  useEffect(() => { if (data) setRows(data) }, [data])
  const update = (r: Rec) => setRows(list => (list || []).map(x => (x.id === r.id ? { ...x, ...r } : x)))
  if (error) return <p className="notice error">{error}</p>
  if (!rows) return <p className="muted">{t('Loading…')}</p>
  const shown = rows.filter(r => !mine || String(r.assignee || '').toLowerCase() === email.toLowerCase())
  if (!shown.length) return <div className="card"><p style={{ margin: 0 }}>{t('No tasks yet.')}</p></div>
  return (
    <div className="wk-board">
      {TASK_STATUSES.map(([key, label]) => {
        const col = shown.filter(r => r.status === key)
        return (
          <section key={key} className={`wk-col wk-col-${key}`} aria-label={t(label)}>
            <h3><Tone value={key} label={t(label)} /> <span className="muted">{col.length}</span></h3>
            {col.map(r => <TaskCard key={r.id} task={r} showProject={!project} onChanged={update} onOpen={() => onOpen(r.id)} />)}
          </section>
        )
      })}
    </div>
  )
}

export function TasksPage({ intent }: { intent?: Intent }) {
  const { role } = useNav()
  const schemas = useSchemas()
  const projects = useList('projects')
  const [project, setProject] = useState<string>(() => String((intent?.newWith as Rec | undefined)?.project_id || ''))
  const [mine, setMine] = useState(false)
  const [mode, setMode] = useState<'board' | 'records'>(intent?.open || (intent?.newWith && Object.keys(intent.newWith).length > 1) ? 'records' : 'board')
  const [jump, setJump] = useState<{ open?: string, newWith?: Record<string, unknown>, n: number }>({ open: intent?.open, n: 0 })
  const [notice, setNotice] = useState('')
  const [round, setRound] = useState(0)
  const title = useTaskTitle()
  const canCreate = !!schemas?.tasks?.can_create
  const projectPicker = (
    <select value={project} onChange={e => setProject(e.target.value)} aria-label={t('Project')}>
      <option value="">{t('All projects')}</option>
      {(projects || []).map(p => <option key={p.id} value={p.id}>{p.code} {p.name}</option>)}
    </select>
  )
  if (mode === 'records') {
    return (
      <RecordsPage key={jump.n} entityName="tasks" openId={jump.open} startNew={jump.newWith}
        title={t('Project tasks')} description={t('Tasks per project and phase, with who does them and by when.')}
        back={{ label: t('Task board'), onClick: () => { setMode('board'); setRound(n => n + 1) } }}
        filter={project ? (r: Rec) => r.project_id === project : undefined}
        defaults={{ project_id: project || undefined, status: 'todo', priority: 'normal', start_date: todayIso() }}
        columns={['title', 'project_id', 'phase', 'assignee', 'status', 'due_date']}
        toolbar={<div className="toolbar">{projectPicker}</div>}
        formLayout={{
          first: ['title', 'project_id', 'assignee', 'status', 'priority', 'start_date', 'due_date', 'phase', 'description', 'blocked_reason', 'checklist'],
          groups: [{ title: 'Links to a borehole, worksheet or lab test', fields: ['borehole_id', 'field_activity_id', 'lab_test_id', 'service'] }],
          hide: d => d.status === 'blocked' ? [] : ['blocked_reason'],
        }}
        extra={r => <TaskDetail task={r} title={title(r)} />}
        hideInView={['title', 'template_key', 'generated_title', 'sequence', 'checklist_done', 'warning_count', 'checklist']} />
    )
  }
  return (
    <div className="page">
      <PageHead title={t('Project tasks')} description={t('Tasks per project and phase, with who does them and by when.')}
        actions={<>
          {project && MANAGERS.includes(role) && <StandardTasksButton projectId={project} onDone={m => { setNotice(m); setRound(n => n + 1) }} />}
          {canCreate && <button type="button" className="primary" onClick={() => { setJump(j => ({ newWith: { project_id: project || undefined }, n: j.n + 1 })); setMode('records') }}>
            <Icon name="plus" />{t('New task')}</button>}
        </>} />
      {notice && <p className="notice ok" role="status">{notice}</p>}
      <div className="toolbar">
        {projectPicker}
        <Segments value={mine ? 'mine' : 'all'} onChange={v => setMine(v === 'mine')} label={t('Show')} options={[['all', 'Everyone'], ['mine', 'Mine']]} />
        <button type="button" className="quiet" onClick={() => { setJump(j => ({ n: j.n + 1 })); setMode('records') }}><Icon name="list" />{t('Table')}</button>
      </div>
      <TaskBoard project={project} mine={mine} refresh={round} onOpen={id => { setJump(j => ({ open: id, n: j.n + 1 })); setMode('records') }} />
    </div>
  )
}

function TaskDetail({ task, title }: { task: Rec, title: string }) {
  const [current, setCurrent] = useState<TaskRow>(task)
  const { email } = useNav()
  useEffect(() => setCurrent(task), [task])
  const canStatus = !!task._can_edit || String(task.assignee || '').toLowerCase() === email.toLowerCase()
  const history: Array<{ at: string, by: string, from: string, to: string, note?: string }> = Array.isArray(current.history) ? current.history : []
  const status = useOption('tasks', 'status')
  return (
    <section className="card wk-detail">
      <h3 className="card-title">{title}</h3>
      <DueChip due={current.due_date} done={current.status === 'done'} />
      <WarningList list={current.warnings} />
      {canStatus && <StatusPicker task={{ ...current, _can_status: true }} onChanged={r => setCurrent({ ...current, ...r })} />}
      <Checklist task={current} editable={canStatus} onChanged={r => setCurrent({ ...current, ...r })} />
      {history.length > 0 && (
        <details className="wf-history">
          <summary>{t('History')} · {history.length}</summary>
          <ul>{[...history].reverse().map((h, i) => (
            <li key={i}><strong>{status(h.to)}</strong> <span className="muted small">{h.by} · {formatDate(String(h.at).slice(0, 10))}</span>
              {h.note && <div className="wf-note">{h.note}</div>}</li>
          ))}</ul>
        </details>
      )}
    </section>
  )
}

/** On the project page: its tasks at a glance and the standard phase tasks. */
export function ProjectWorkPanel({ project }: { project: Rec }) {
  const { go } = useNav()
  const schemas = useSchemas()
  const [round, setRound] = useState(0)
  const [notice, setNotice] = useState('')
  const { data } = useLive<TaskRow[]>(schemas?.tasks?.can_read ? `/api/erp/work/tasks?project_id=${project.id}` : null, round)
  const title = useTaskTitle()
  if (!schemas?.tasks?.can_read) return null
  const open = (data || []).filter(r => r.status !== 'done')
  const overdue = open.filter(r => r.overdue)
  return (
    <section className="hub-section">
      <div className="hub-head">
        <h3>{t('Project tasks')} <span className="muted">{data ? data.length : ''}</span></h3>
        <div className="actions">
          <StandardTasksButton projectId={project.id} onDone={m => { setNotice(m); setRound(n => n + 1) }} />
          <button type="button" className="small" onClick={() => go('tasks', { newWith: { project_id: project.id } })}>{t('Task board')}</button>
        </div>
      </div>
      {notice && <p className="notice ok" role="status">{notice}</p>}
      {data && data.length > 0 && (
        <div className="kpis wk-kpis">
          <Kpi label={t('Open')} value={open.length} />
          <Kpi label={t('Overdue')} value={overdue.length} tone={overdue.length ? 'bad' : undefined} />
          <Kpi label={t('Blocked')} value={open.filter(r => r.status === 'blocked').length} />
          <Kpi label={t('Done')} value={data.length - open.length} />
        </div>
      )}
      {overdue.length > 0 && (
        <ul className="wk-plain">
          {overdue.slice(0, 5).map(r => (
            <li key={r.id}><button type="button" className="quiet" onClick={() => go('tasks', { open: r.id })}>{title(r)}</button> <DueChip due={r.due_date} overdue /></li>
          ))}
        </ul>
      )}
      {data && !data.length && <p className="muted small">{t('No tasks yet. The standard phase tasks are created when the project moves to contract or ongoing.')}</p>}
    </section>
  )
}

// ---------------------------------------------------------------------------
// Field submissions
// ---------------------------------------------------------------------------

type InboxItem = { id: string, number: string, date: string, state: string, project: string, by: string, samples: boolean, since: string, note: string, items: number }

const SUB_STEPS: Array<[string, string]> = [['draft', 'Field'], ['submitted', 'Sent'], ['acknowledged', 'Acknowledged'], ['processing', 'In processing'], ['done', 'Done']]
const SUB_ACTION_LABEL: Record<string, string> = {
  submit: 'Send to the office', acknowledge: 'Acknowledge receipt', process: 'Start processing', done: 'Mark done',
  return: 'Return for correction', reopen: 'Reopen',
}
const SUB_DONE_LABEL: Record<string, string> = {
  submit: 'Sent', acknowledge: 'Acknowledged', process: 'Processing started', done: 'Done', return: 'Returned', reopen: 'Reopened',
}

function SubmissionFlow({ record, onChanged }: { record: Rec, onChanged: (r: Rec) => void }) {
  const [actions, setActions] = useState<string[]>([])
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const state = String(record.sub_status || 'draft')
  const recipients = useOption('field_submissions', 'recipients')
  const history: Array<{ action: string, by: string, at: string, note: string }> = Array.isArray(record.sub_history) ? record.sub_history : []
  useEffect(() => {
    let live = true
    apiGet<{ actions: string[] }>(`/api/erp/work/submissions/${record.id}/actions`).then(r => { if (live) setActions(r.actions) }).catch(() => { if (live) setActions([]) })
    return () => { live = false }
  }, [record.id, record.sub_status, record.updated_at])
  const run = async (action: string) => {
    if ((action === 'return' || action === 'reopen') && !note.trim()) { setError(t('Write the reason in the note')); return }
    setBusy(true); setError('')
    try {
      const out = await apiPost<Rec & { _actions: string[] }>(`/api/erp/work/submissions/${record.id}/act`, { action, note: note.trim() })
      setNote(''); setActions(out._actions || []); invalidate('field_submissions'); onChanged(out)
    } catch (e: any) { setError(e.message) } finally { setBusy(false) }
  }
  const at = state === 'returned' ? 0 : Math.max(0, SUB_STEPS.findIndex(s => s[0] === state))
  return (
    <section className="card wf-panel" aria-label={t('Hand-off to the office')}>
      <div className="wf-head">
        <h3 className="card-title">{t('Hand-off to the office')}</h3>
        {state === 'returned' && <span className="status bad">{t('Returned for correction')}</span>}
      </div>
      <ol className="wf-steps">
        {SUB_STEPS.map(([key, label], i) => (
          <li key={key} className={i < at || state === 'done' ? 'done' : i === at ? 'now' : ''} aria-current={i === at && state !== 'done' ? 'step' : undefined}>
            <span className="wf-dot">{i < at || state === 'done' ? '✓' : i + 1}</span><span>{t(label)}</span>
          </li>
        ))}
      </ol>
      <p className="help" style={{ marginTop: 0 }}>{t('Sent to')}: {recipients(record.recipients || 'office')}</p>
      {actions.length > 0 && (
        <div className="wf-act">
          <label htmlFor={`sub-note-${record.id}`} className="small">{t('Note (required to return or reopen)')}</label>
          <textarea id={`sub-note-${record.id}`} rows={2} value={note} maxLength={1000} onChange={e => setNote(e.target.value)} />
          <div className="actions">
            {actions.map(a => (
              <button key={a} type="button" disabled={busy} className={a === 'return' ? 'quiet danger-quiet' : a === 'reopen' ? '' : 'primary'}
                onClick={() => { void run(a) }}>{t(SUB_ACTION_LABEL[a] || a)}</button>
            ))}
          </div>
        </div>
      )}
      {actions.length === 0 && state !== 'done' && (
        <p className="help" style={{ margin: '.25rem 0 0' }}>
          {state === 'draft' || state === 'returned' ? t('The field team sends this package when the day is complete.') : t('Waiting for the office.')}
        </p>
      )}
      {error && <p className="notice error" role="alert">{error}</p>}
      {history.length > 0 && (
        <details className="wf-history" open={state === 'returned' || undefined}>
          <summary>{t('History')} · {history.length}</summary>
          <ul>
            {[...history].reverse().map((h, i) => (
              <li key={i}><strong>{t(SUB_DONE_LABEL[h.action] || h.action)}</strong> <span className="muted small">{h.by} · {formatDate(String(h.at).slice(0, 10))} {String(h.at).slice(11, 16)}</span>
                {h.note && <div className="wf-note">{h.note}</div>}</li>
            ))}
          </ul>
        </details>
      )}
    </section>
  )
}

function PackageContents({ record }: { record: Rec }) {
  const nav = useNav()
  const go = go2(nav.go)
  const acts = useList('field_activities')
  const cpts = useList('cpt')
  const name = (id: string) => acts?.find(a => a.id === id)?.code || '…'
  const worksheets: Rec[] = record.worksheets || []
  const holes: Rec[] = record.boreholes || []
  const tests: Rec[] = record.cpt_tests || []
  return (
    <section className="card wk-package">
      <h3 className="card-title">{t('In this package')} <span className="muted small">· {record.item_count ?? 0}</span></h3>
      <ul className="wk-plain">
        {record.daily_report_id && <li><span className="wk-kind">{t('Daily report')}</span> <button type="button" className="quiet" onClick={() => go('fieldwork', { open: record.daily_report_id })}>{name(record.daily_report_id)}</button></li>}
        {worksheets.map((w, i) => <li key={'w' + i}><span className="wk-kind">{t('Worksheet')}</span> <button type="button" className="quiet" onClick={() => go('fieldwork', { open: w.activity_id })}>{name(w.activity_id)}</button>{w.note ? <span className="muted small"> · {w.note}</span> : null}</li>)}
        {tests.map((c, i) => <li key={'c' + i}><span className="wk-kind">CPT</span> <button type="button" className="quiet" onClick={() => go('cpt', { open: c.cpt_id })}>{cpts?.find(x => x.id === c.cpt_id)?.test_id || '…'}</button>{c.note ? <span className="muted small"> · {c.note}</span> : null}</li>)}
        {holes.map((h, i) => <li key={'b' + i}><span className="wk-kind">{t('Borehole log')}</span> <button type="button" className="quiet" onClick={() => go('boreholes', { borehole: h.borehole_id })}>{h.borehole_id}</button>{h.note ? <span className="muted small"> · {h.note}</span> : null}</li>)}
        {record.samples_included && <li><span className="wk-kind">{t('Samples')}</span> {[record.sample_count, record.sample_note].filter(x => x !== null && x !== undefined && x !== '').join(' · ')}</li>}
      </ul>
      <WarningList list={record.warnings} />
    </section>
  )
}

type DayRecords = {
  daily_reports: Array<{ id: string, code: string }>, worksheets: Array<{ id: string, code: string, method: string, summary: string }>,
  cpt: Array<{ id: string, code: string, depth: number | null }>, logs: Array<{ borehole_id: string, site: string, depth: string }>,
}

/** In the package form: pick the day's records of this user and add them. */
const dayPicker: FormTools = (data, setData, place) => place === 'top' ? <DayPicker data={data} setData={setData} /> : null

function DayPicker({ data, setData }: { data: Record<string, any>, setData: (u: (p: Record<string, any>) => Record<string, any>) => void }) {
  const [found, setFound] = useState<DayRecords | null>(null)
  const [error, setError] = useState('')
  const [pick, setPick] = useState<Record<string, boolean>>({})
  const load = async () => {
    setError('')
    if (!data.date) { setError(t('Choose the work date first.')); return }
    try {
      const out = await apiGet<DayRecords>(`/api/erp/work/day-records?date=${data.date}&project_id=${data.project_id || ''}`)
      setFound(out)
      setPick(Object.fromEntries([...out.worksheets.map(w => ['w' + w.id, true]), ...out.cpt.map(c => ['c' + c.id, true]),
        ...out.logs.map(l => ['b' + l.borehole_id, true]), ...out.daily_reports.slice(0, 1).map(d => ['d' + d.id, true])]))
    } catch (e: any) { setError(e.message) }
  }
  const add = () => {
    if (!found) return
    setData(prev => {
      const ws: Array<Record<string, any>> = [...(prev.worksheets || [])]
      for (const w of found.worksheets) if (pick['w' + w.id] && !ws.some(x => x.activity_id === w.id)) ws.push({ activity_id: w.id, note: '' })
      const cs: Array<Record<string, any>> = [...(prev.cpt_tests || [])]
      for (const c of found.cpt) if (pick['c' + c.id] && !cs.some(x => x.cpt_id === c.id)) cs.push({ cpt_id: c.id, note: '' })
      const bs: Array<Record<string, any>> = [...(prev.boreholes || [])]
      for (const l of found.logs) if (pick['b' + l.borehole_id] && !bs.some(x => x.borehole_id === l.borehole_id)) bs.push({ borehole_id: l.borehole_id, note: '' })
      const report = found.daily_reports.find(d => pick['d' + d.id])
      return { ...prev, worksheets: ws, cpt_tests: cs, boreholes: bs, daily_report_id: report ? report.id : prev.daily_report_id }
    })
    setFound(null)
  }
  const total = found ? found.daily_reports.length + found.worksheets.length + found.cpt.length + found.logs.length : 0
  const box = (key: string, label: ReactNode) => (
    <label key={key} className="checkbox"><input type="checkbox" checked={!!pick[key]} onChange={e => setPick({ ...pick, [key]: e.target.checked })} />{label}</label>
  )
  return (
    <div className="wk-daypick">
      <button type="button" onClick={() => { void load() }}><Icon name="calendar" />{t('Fill from my records of this day')}</button>
      {error && <p className="notice error small">{error}</p>}
      {found && (
        <div className="card wk-daypick-box">
          {!total ? <p className="muted" style={{ margin: 0 }}>{t('No records of yours on this day.')}</p> : <>
            <div className="checks">
              {found.daily_reports.map(d => box('d' + d.id, <>{t('Daily report')} {d.code}</>))}
              {found.worksheets.map(w => box('w' + w.id, <>{w.code}{w.summary ? <span className="muted small"> · {translateServer(w.summary)}</span> : null}</>))}
              {found.cpt.map(c => box('c' + c.id, <>CPT {c.code}</>))}
              {found.logs.map(l => box('b' + l.borehole_id, <>{t('Borehole log')} {l.borehole_id}</>))}
            </div>
            <div className="actions"><button type="button" className="primary" onClick={add}>{t('Add to the package')}</button><button type="button" onClick={() => setFound(null)}>{t('Cancel')}</button></div>
          </>}
        </div>
      )}
    </div>
  )
}

function InboxList({ items, onOpen }: { items: InboxItem[], onOpen: (id: string) => void }) {
  const states = useOption('field_submissions', 'sub_status')
  return (
    <ul className="ws-list">
      {items.map(i => (
        <li key={i.id}>
          <span className="ws-no">{i.number}</span>
          <div className="ws-main">
            <strong>{i.project || '–'} · {formatDate(i.date)}</strong>
            <span className="ws-std"><Tone value={i.state} label={states(i.state)} /> · {i.by} · {t('{n} items', { n: i.items })}{i.samples ? ` · ${t('with samples')}` : ''}{i.note ? ` · ${i.note}` : ''}</span>
          </div>
          <div className="ws-side"><div className="ws-actions"><button type="button" className="small primary" onClick={() => onOpen(i.id)}>{t('Open')}</button></div></div>
        </li>
      ))}
    </ul>
  )
}

/** Packages waiting for this user, for the approvals page. */
export function SubmissionsInboxCard() {
  const { go } = useNav()
  const { data } = useLive<InboxItem[]>('/api/erp/work/submissions/inbox')
  if (!data?.length) return null
  return (
    <section className="card" style={{ marginBottom: '1rem' }}>
      <h3 className="card-title">{t('Field submissions')} <span className="muted small">· {data.length}</span></h3>
      <p className="help" style={{ marginTop: 0 }}>{t('Day packages from the field to acknowledge, process or correct.')}</p>
      <InboxList items={data} onOpen={id => go('submissions' as TabKey, { open: id })} />
    </section>
  )
}

export function SubmissionsPage({ intent }: { intent?: Intent }) {
  const [view, setView] = useState('all')
  const [jump, setJump] = useState<{ id?: string, n: number }>({ id: intent?.open, n: 0 })
  const { data: inbox } = useLive<InboxItem[]>('/api/erp/work/submissions/inbox', jump.n)
  const filter = useMemo(() => (r: Rec) => view === 'all' || (view === 'open' ? !['done'].includes(r.sub_status) : r.sub_status === view), [view])
  return (
    <RecordsPage key={jump.n} entityName="field_submissions" openId={jump.id} startNew={intent?.newWith} filter={filter}
      description={t('The field team sends each day\'s daily report, worksheets, logs and attachments to the office; the office acknowledges, processes or returns them.')}
      defaults={{ date: todayIso() }}
      columns={['number', 'date', 'project_id', 'sub_status', 'item_count', 'warning_count']}
      toolbar={<>
        {inbox && inbox.length > 0 && (
          <section className="card wk-inbox">
            <h3 className="card-title">{t('Waiting for you')} <span className="muted small">· {inbox.length}</span></h3>
            <InboxList items={inbox} onOpen={id => setJump(j => ({ id, n: j.n + 1 }))} />
          </section>
        )}
        <Segments value={view} onChange={setView} label={t('Show')} options={[['all', 'All'], ['open', 'Not done'], ['returned', 'Returned'], ['done', 'Done']]} />
      </>}
      formTools={dayPicker}
      formLayout={{
        first: ['date', 'project_id', 'daily_report_id', 'worksheets', 'cpt_tests', 'boreholes', 'samples_included', 'sample_count', 'sample_note', 'note', 'files'],
        hide: d => d.samples_included ? [] : ['sample_count', 'sample_note'],
      }}
      extra={(r, reload) => <><SubmissionFlow record={r} onChanged={() => reload()} /><PackageContents record={r} /></>}
      hideInView={['sub_history', 'warning_count', 'submitted_at', 'done_at', 'resubmissions', 'item_count', 'recipients', 'sub_status', 'worksheets', 'cpt_tests', 'boreholes', 'daily_report_id', 'samples_included', 'sample_count', 'sample_note']} />
  )
}

// ---------------------------------------------------------------------------
// Crew roster
// ---------------------------------------------------------------------------

type RosterRow = Rec & { deployment_status: string, man_days: number, planned_man_days: number | null, cost_to_date?: number | null,
  compliance: string, medical_state: string, induction_state: string, warnings: Warning[] }
type RosterProject = { project_id: string, code: string, name: string, people: number, on_site: number, planned: number, man_days: number,
  planned_man_days: number, warnings: number, cost_to_date?: number }
type Roster = { as_of: string, rows: RosterRow[], projects: RosterProject[], totals: { people: number, on_site: number, man_days: number, with_warnings: number, expired: number } }

function RosterSummary({ data, project, onOpen }: { data: Roster, project: string, onOpen: (id: string) => void }) {
  const { role } = useNav()
  const position = useOption('crew_deployments', 'position')
  const money_ = ['admin', 'manager', 'finance'].includes(role)
  const rows = data.rows.filter(r => !project || r.project_id === project)
  const attention = rows.filter(r => r.deployment_status !== 'finished' && r.warnings.length)
  const projects = data.projects.filter(p => !project || p.project_id === project)
  return (
    <>
      <div className="kpis wk-kpis">
        <Kpi label={t('On site now')} value={rows.filter(r => r.deployment_status === 'on_site').length} sub={t('{n} planned', { n: rows.filter(r => r.deployment_status === 'planned').length })} />
        <Kpi label={t('Man-days to date')} value={number(rows.reduce((s, r) => s + r.man_days, 0))} />
        <Kpi label={t('Safety documents expired or missing')} value={rows.filter(r => r.deployment_status !== 'finished' && ['expired', 'missing'].includes(r.compliance)).length}
          tone={rows.some(r => r.deployment_status !== 'finished' && r.compliance === 'expired') ? 'bad' : undefined}
          sub={t('{n} expiring soon', { n: rows.filter(r => r.deployment_status !== 'finished' && r.compliance === 'expiring').length })} />
        {money_ && <Kpi label={t('Crew cost to date')} value={money(projects.reduce((s, p) => s + (p.cost_to_date || 0), 0))} />}
      </div>
      {attention.length > 0 && (
        <details className="card wk-attention" open>
          <summary>{t('Needs attention')} <span className="muted small">· {attention.length}</span></summary>
          <ul className="wk-plain">
            {attention.map(r => (
              <li key={r.id}>
                <button type="button" className="quiet" onClick={() => onOpen(r.id)}>{r.person_name}</button>
                <span className="muted small"> · {position(r.position)}</span>
                <ul className="wk-sub">{r.warnings.map((w, i) => <li key={i}>{warningText(w)}</li>)}</ul>
              </li>
            ))}
          </ul>
        </details>
      )}
      {projects.length > 0 && (
        <section className="hub-section">
          <h3>{t('Man-days per project')}</h3>
          <ScrollTable>
            <table className="data-table">
              <thead><tr><th>{t('Project')}</th><th className="num">{t('People')}</th><th className="num">{t('On site now')}</th>
                <th className="num">{t('Man-days to date')}</th><th className="num">{t('Planned man-days')}</th>
                {money_ && <th className="num">{t('Cost to date')}</th>}<th className="num">{t('With warnings')}</th></tr></thead>
              <tbody>
                {projects.map(p => (
                  <tr key={p.project_id}>
                    <td><strong>{p.code}</strong><div className="bh-sub">{p.name}</div></td>
                    <td className="num">{p.people}</td><td className="num">{p.on_site}</td><td className="num">{number(p.man_days)}</td>
                    <td className="num">{p.planned_man_days ? number(p.planned_man_days) : '–'}</td>
                    {money_ && <td className="num nowrap">{money(p.cost_to_date)}</td>}<td className="num">{p.warnings}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </ScrollTable>
        </section>
      )}
    </>
  )
}

function DeploymentLive({ record, live }: { record: Rec, live: RosterRow | undefined }) {
  const { role } = useNav()
  const compliance = useOption('crew_deployments', 'compliance')
  const status = useOption('crew_deployments', 'deployment_status')
  if (!live) return null
  return (
    <section className="card wk-detail">
      <dl className="facts-grid compact">
        <div><dt>{t('On site')}</dt><dd><Tone value={live.deployment_status} label={status(live.deployment_status)} /></dd></div>
        <div><dt>{t('Man-days to date')}</dt><dd>{number(live.man_days)}{live.planned_man_days ? <span className="muted small"> / {number(live.planned_man_days)}</span> : null}</dd></div>
        <div><dt>{t('Medical clearance')}</dt><dd><Tone value={live.medical_state} label={compliance(live.medical_state)} /><div className="bh-sub">{formatDate(record.medical_expiry)}</div></dd></div>
        <div><dt>{t('Safety induction')}</dt><dd><Tone value={live.induction_state} label={compliance(live.induction_state)} /><div className="bh-sub">{formatDate(live.induction_valid_until as string)}</div></dd></div>
        {['admin', 'manager', 'finance'].includes(role) && <div><dt>{t('Cost to date')}</dt><dd>{money(live.cost_to_date)}</dd></div>}
      </dl>
      <WarningList list={live.warnings} />
    </section>
  )
}

export function RosterPage({ intent }: { intent?: Intent }) {
  const projects = useList('projects')
  const [project, setProject] = useState('')
  const [status, setStatus] = useState('current')
  const [warnOnly, setWarnOnly] = useState(false)
  const [jump, setJump] = useState<{ id?: string, n: number }>({ id: intent?.open, n: 0 })
  const { data, error } = useLive<Roster>('/api/erp/work/roster', jump.n)
  const live = useMemo(() => new Map((data?.rows || []).map(r => [r.id, r])), [data])
  const filter = useMemo(() => (r: Rec) => {
    const l = live.get(r.id)
    const st = l?.deployment_status || r.deployment_status
    if (project && r.project_id !== project) return false
    if (status === 'current' && st === 'finished') return false
    if (['on_site', 'planned', 'finished'].includes(status) && st !== status) return false
    return !warnOnly || !!(l?.warnings.length)
  }, [live, project, status, warnOnly])
  return (
    <RecordsPage key={jump.n} entityName="crew_deployments" openId={jump.id} startNew={intent?.newWith} filter={filter}
      description={t('Who is deployed on each project, from when to when, with safety documents and man-days.')}
      defaults={{ project_id: project || undefined, deploy_start: todayIso(), employer_type: 'permanent' }}
      columns={['person_name', 'position', 'project_id', 'deployment_status', 'deploy_start', 'deploy_end', 'compliance']}
      toolbar={<>
        {error && <p className="notice error">{error}</p>}
        <div className="toolbar">
          <select value={project} onChange={e => setProject(e.target.value)} aria-label={t('Project')}>
            <option value="">{t('All projects')}</option>
            {(projects || []).map(p => <option key={p.id} value={p.id}>{p.code} {p.name}</option>)}
          </select>
          <Segments value={status} onChange={setStatus} label={t('Show')} options={[['current', 'Current and planned'], ['on_site', 'On site'], ['finished', 'Finished'], ['all', 'All']]} />
          <label className="checkbox"><input type="checkbox" checked={warnOnly} onChange={e => setWarnOnly(e.target.checked)} />{t('Only with warnings')}</label>
        </div>
        {data && <RosterSummary data={data} project={project} onOpen={id => setJump(j => ({ id, n: j.n + 1 }))} />}
      </>}
      formLayout={{
        first: ['project_id', 'person_name', 'position', 'employer_type', 'deploy_start', 'deploy_end', 'location', 'accommodation', 'medical_expiry', 'induction_date', 'phone', 'emergency_name', 'emergency_phone'],
        groups: [{ title: 'Employer, mobilisation and pay', fields: ['employer', 'mobilisation_id', 'daily_rate'] }],
      }}
      extra={r => <DeploymentLive record={r} live={live.get(r.id)} />}
      hideInView={['deployment_status', 'compliance', 'warning_count', 'man_days', 'planned_man_days', 'cost_to_date', 'induction_valid_until']} />
  )
}

// ---------------------------------------------------------------------------
// Laboratory work orders
// ---------------------------------------------------------------------------

type OrderState = {
  id: string, number: string, project_id: string, priority: string, technician: string, received: string, reported_on: string,
  status: string, sla_days: number | null, due_date: string, progress_pct: number, test_count: number, tests_done: number, tests_authorised: number,
  turnaround_days: number | null, on_time: string, overdue: boolean, days_late: number, days_left: number | null, basis: string,
}
type QueueItem = { id: string, borehole_id: string, sample_ref: string, test_type: string, status: string, authorised: boolean, stage: string,
  order: { id: string, number: string, due_date: string, priority: string } | null, due_date: string, overdue: boolean, technician: string }
type LabBoard = {
  as_of: string, orders: OrderState[], basis: string, sla: Record<string, number>,
  kpis: { reported: number, average_turnaround_days: number | null, on_time_pct: number | null, open: number, overdue: number, awaiting_review: number, in_testing: number, ready: number, period_months: number },
  queue: Array<{ category: string, label: string, items: QueueItem[] }>,
  unassigned: Array<{ id: string, project_id: string, borehole_id: string, sample_ref: string, depth_top: number, test_type: string, status: string, category: string }>,
}

const STAGE_LABEL: Record<string, string> = { requested: 'Requested', received: 'Received', testing: 'Testing', review: 'Awaiting review' }

export function LabKpis({ kpis, basis }: { kpis: LabBoard['kpis'], basis: string }) {
  const unit = basis === 'calendar' ? t('calendar days') : t('working days')
  return (
    <div className="kpis wk-kpis">
      <Kpi label={t('Average turnaround')} value={kpis.average_turnaround_days === null ? '–' : `${number(kpis.average_turnaround_days)}`}
        sub={`${unit} · ${t('{n} reported, last {m} months', { n: kpis.reported, m: kpis.period_months })}`} />
      <Kpi label={t('On time')} value={kpis.on_time_pct === null ? '–' : `${number(kpis.on_time_pct)} %`} />
      <Kpi label={t('Open work orders')} value={kpis.open} sub={t('{n} in testing', { n: kpis.in_testing })} />
      <Kpi label={t('Overdue')} value={kpis.overdue} tone={kpis.overdue ? 'bad' : undefined} />
      <Kpi label={t('Awaiting review')} value={kpis.awaiting_review} tone={kpis.awaiting_review ? 'warn' : undefined} sub={t('{n} ready to report', { n: kpis.ready })} />
    </div>
  )
}

function TestQueue({ board }: { board: LabBoard }) {
  const nav = useNav()
  const go = go2(nav.go)
  const testLabel = useOption('lab_tests', 'test_type')
  if (!board.queue.length) return <div className="card"><p style={{ margin: 0 }}>{t('No tests waiting.')}</p></div>
  return (
    <div className="wk-board wk-queue">
      {board.queue.map(q => (
        <section key={q.category} className="wk-col" aria-label={t(q.label)}>
          <h3>{t(q.label)} <span className="muted">{q.items.length}</span></h3>
          <p className="help" style={{ margin: '0 0 .4rem' }}>{t('Target {n} days', { n: board.sla[q.category] })}</p>
          {q.items.map(i => (
            <article key={i.id} className={`wk-card${i.overdue ? ' overdue' : ''}`}>
              <div className="wk-card-head">
                <button type="button" className="quiet wk-card-title" onClick={() => go('lab', { open: i.id })}>{i.borehole_id} {i.sample_ref}</button>
                <Tone value={i.stage === 'review' ? 'awaiting_review' : i.status} label={t(STAGE_LABEL[i.stage] || i.stage)} />
              </div>
              <div className="wk-card-meta"><span>{testLabel(i.test_type)}</span>{i.order ? <span>{i.order.number}</span> : <span className="wk-warn-text">{t('No work order')}</span>}</div>
              {i.order && <DueChip due={i.due_date} overdue={i.overdue} />}
            </article>
          ))}
        </section>
      ))}
    </div>
  )
}

function Unassigned({ board, onCreated }: { board: LabBoard, onCreated: (id: string) => void }) {
  const projects = useList('projects')
  const testLabel = useOption('lab_tests', 'test_type')
  const [pick, setPick] = useState<Record<string, boolean>>({})
  const [priority, setPriority] = useState('normal')
  const [tech, setTech] = useState('')
  const [due, setDue] = useState('')
  const [users, setUsers] = useState<Array<{ email: string, role: string }>>([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => { userDirectory().then(u => setUsers(u.filter(x => ['lab', 'manager', 'admin'].includes(x.role)))).catch(() => {}) }, [])
  const groups = useMemo(() => {
    const m = new Map<string, LabBoard['unassigned']>()
    for (const u of board.unassigned) m.set(u.project_id, [...(m.get(u.project_id) || []), u])
    return [...m.entries()]
  }, [board])
  const chosen = board.unassigned.filter(u => pick[u.id])
  if (!board.unassigned.length) return <div className="card"><p style={{ margin: 0 }}>{t('Every requested test is on a work order.')}</p></div>
  const create = async () => {
    setBusy(true); setError('')
    try {
      const out = await apiPost<Rec>('/api/erp/work/lab/orders/from-tests', { test_ids: chosen.map(c => c.id), priority, technician: tech, agreed_due: due })
      invalidate('lab_work_orders'); setPick({}); onCreated(out.id)
    } catch (e: any) { setError(e.message) } finally { setBusy(false) }
  }
  const pname = (id: string) => { const p = projects?.find(x => x.id === id); return p ? `${p.code} ${p.name}` : t('No project') }
  return (
    <section className="card">
      <h3 className="card-title">{t('Tests without a work order')} <span className="muted small">· {board.unassigned.length}</span></h3>
      <p className="help" style={{ marginTop: 0 }}>{t('Tests requested through the laboratory instruction (sample register). Tick the tests of one project and make a work order; its due date follows the turnaround targets.')}</p>
      {groups.map(([pid, items]) => (
        <div key={pid} className="wk-group">
          <label className="checkbox wk-group-head"><input type="checkbox" checked={items.every(i => pick[i.id])}
            onChange={e => setPick({ ...pick, ...Object.fromEntries(items.map(i => [i.id, e.target.checked])) })} /><strong>{pname(pid)}</strong> <span className="muted small">· {items.length}</span></label>
          <div className="checks wk-tests">
            {items.map(i => (
              <label key={i.id} className="checkbox"><input type="checkbox" checked={!!pick[i.id]} onChange={e => setPick({ ...pick, [i.id]: e.target.checked })} />
                {i.borehole_id} {i.sample_ref} · {testLabel(i.test_type)}</label>
            ))}
          </div>
        </div>
      ))}
      {chosen.length > 0 && (
        <div className="fields wk-make">
          <div className="field"><label htmlFor="lwo-prio">{t('Priority')}</label>
            <select id="lwo-prio" value={priority} onChange={e => setPriority(e.target.value)}>
              <option value="normal">{t('Normal')}</option><option value="high">{t('High')}</option><option value="urgent">{t('Urgent')}</option>
            </select></div>
          <div className="field"><label htmlFor="lwo-tech">{t('Technician')}</label>
            <select id="lwo-tech" value={tech} onChange={e => setTech(e.target.value)}>
              <option value="">{t('Select')}</option>{users.map(u => <option key={u.email} value={u.email}>{u.email}</option>)}
            </select></div>
          <div className="field"><label htmlFor="lwo-due">{t('Due date agreed')}</label>
            <DateInput id="lwo-due" value={due} onChange={setDue} /><p className="help">{t('Empty: from the turnaround targets.')}</p></div>
        </div>
      )}
      {error && <p className="notice error">{error}</p>}
      <div className="actions"><button type="button" className="primary" disabled={!chosen.length || busy} onClick={() => { void create() }}>
        {t('Make a work order for {n} tests', { n: chosen.length })}</button></div>
    </section>
  )
}

/** In the work order form: the laboratory tests of the project, ticked to include them. */
const testPicker: FormTools = (data, setData, place) => place === 'bottom' ? <TestPicker data={data} setData={setData} /> : null

function TestPicker({ data, setData }: { data: Record<string, any>, setData: (u: (p: Record<string, any>) => Record<string, any>) => void }) {
  const tests = useList('lab_tests')
  const orders = useList('lab_work_orders')
  const testLabel = useOption('lab_tests', 'test_type')
  const rows: Array<Record<string, any>> = Array.isArray(data.tests) ? data.tests : []
  const chosen = new Set(rows.map(r => r.lab_test_id))
  const elsewhere = new Set((orders || []).filter(o => !o.cancelled && o.number !== data.number).flatMap(o => (o.tests || []).map((r: Rec) => r.lab_test_id)))
  const shown = (tests || []).filter(x => chosen.has(x.id) || ((!data.project_id || x.project_id === data.project_id) && !elsewhere.has(x.id) && !(x.status === 'done' && x.authorised)))
  const toggle = (id: string, on: boolean) => setData(prev => {
    const list: Array<Record<string, any>> = Array.isArray(prev.tests) ? prev.tests : []
    return { ...prev, tests: on ? [...list, { lab_test_id: id, note: '' }] : list.filter(r => r.lab_test_id !== id) }
  })
  return (
    <section className="field wide wk-testpick">
      <label>{t('Samples and tests')} <span className="muted small">· {t('{n} chosen', { n: chosen.size })}</span></label>
      {!tests ? <p className="muted">{t('Loading…')}</p> : !shown.length ? <p className="muted small">{t('No laboratory tests of this project without a work order.')}</p> : (
        <div className="checks wk-tests">
          {shown.map(x => (
            <label key={x.id} className="checkbox"><input type="checkbox" checked={chosen.has(x.id)} onChange={e => toggle(x.id, e.target.checked)} />
              {x.borehole_id} {x.sample_ref} ({number(x.depth_top)} m) · {testLabel(x.test_type)}</label>
          ))}
        </div>
      )}
      <p className="help">{t('Laboratory tests of the samples; the work order follows their status and authorisation.')}</p>
    </section>
  )
}

function OrderDetail({ record, state }: { record: Rec, state: OrderState | undefined }) {
  const nav = useNav()
  const go = go2(nav.go)
  const tests = useList('lab_tests')
  const testLabel = useOption('lab_tests', 'test_type')
  const statusLabel = useOption('lab_work_orders', 'status')
  const testStatus = useOption('lab_tests', 'status')
  const s = state
  const linked: Rec[] = (record.tests || []).map((r: Rec) => tests?.find(x => x.id === r.lab_test_id)).filter(Boolean)
  return (
    <section className="card wk-detail">
      <div className="wk-order-head">
        <Tone value={s?.status || record.status} label={statusLabel(s?.status || record.status)} />
        {s && <DueChip due={s.due_date} done={['reported', 'cancelled'].includes(s.status)} overdue={s.overdue} />}
      </div>
      <Bar pct={s?.progress_pct ?? record.progress_pct} />
      <dl className="facts-grid compact">
        <div><dt>{t('Progress (%)')}</dt><dd>{number(s?.progress_pct ?? record.progress_pct)}</dd></div>
        <div><dt>{t('Tests done')}</dt><dd>{number(s?.tests_done ?? record.tests_done)} / {number(s?.test_count ?? record.test_count)}</dd></div>
        <div><dt>{t('Tests authorised')}</dt><dd>{number(s?.tests_authorised ?? record.tests_authorised)}</dd></div>
        <div><dt>{t('Turnaround target (days)')}</dt><dd>{number(s?.sla_days ?? record.sla_days)}<div className="bh-sub">{(s?.basis || 'working') === 'calendar' ? t('calendar days') : t('working days')}</div></dd></div>
        {(s?.turnaround_days ?? record.turnaround_days) !== null && (s?.turnaround_days ?? record.turnaround_days) !== undefined &&
          <div><dt>{t('Turnaround (days)')}</dt><dd>{number(s?.turnaround_days ?? record.turnaround_days)}{record.on_time ? <div className="bh-sub">{record.on_time === 'yes' ? t('On time') : t('Late')}</div> : null}</dd></div>}
      </dl>
      <WarningList list={record.warnings} />
      {linked.length > 0 && (
        <ScrollTable>
          <table className="data-table">
            <thead><tr><th>{t('Sample')}</th><th>{t('Test')}</th><th>{t('Status')}</th><th>{t('Authorised')}</th></tr></thead>
            <tbody>
              {linked.map(x => (
                <tr key={x.id} className="clickable" onClick={() => go('lab', { open: x.id })}>
                  <td><strong>{x.borehole_id}</strong> {x.sample_ref}<div className="bh-sub">{number(x.depth_top)} m</div></td>
                  <td>{testLabel(x.test_type)}</td>
                  <td><Tone value={x.status} label={testStatus(x.status)} /></td>
                  <td>{x.status === 'done' ? (x.authorised ? t('Yes') : t('No')) : '–'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </ScrollTable>
      )}
    </section>
  )
}

export function LabOrdersPage({ intent }: { intent?: Intent }) {
  const [view, setView] = useState('orders')
  const [jump, setJump] = useState<{ id?: string, n: number }>({ id: intent?.open, n: 0 })
  const [status, setStatus] = useState('open')
  const { data: board, error } = useLive<LabBoard>('/api/erp/work/lab/board', jump.n)
  const states = useMemo(() => new Map((board?.orders || []).map(o => [o.id, o])), [board])
  const filter = useMemo(() => (r: Rec) => {
    const st = states.get(r.id)?.status || r.status
    return status === 'all' || (status === 'open' ? !['reported', 'cancelled'].includes(st) : status === 'overdue' ? !!states.get(r.id)?.overdue : st === status)
  }, [states, status])
  const switcher = (
    <Segments value={view} onChange={setView} label={t('Show')}
      options={[['orders', 'Work orders'], ['queue', 'Test queue'], ['unassigned', board ? t('Without work order ({n})', { n: board.unassigned.length }) : 'Without work order']]} />
  )
  const head = <>
    {error && <p className="notice error">{error}</p>}
    {board && <LabKpis kpis={board.kpis} basis={board.basis} />}
    <div className="toolbar">{switcher}</div>
  </>
  if (view !== 'orders') {
    return (
      <div className="page">
        <PageHead title={t('Laboratory work orders')} description={t('Samples and tests per customer request, due dates from the turnaround targets, and the test queue by category.')} />
        {head}
        {!board ? <p className="muted">{t('Loading…')}</p> : view === 'queue' ? <TestQueue board={board} />
          : <Unassigned board={board} onCreated={id => { setView('orders'); setJump(j => ({ id, n: j.n + 1 })) }} />}
      </div>
    )
  }
  return (
    <RecordsPage key={jump.n} entityName="lab_work_orders" openId={jump.id} startNew={intent?.newWith} filter={filter}
      description={t('Samples and tests per customer request, due dates from the turnaround targets, and the test queue by category.')}
      defaults={{ received: todayIso(), priority: 'normal' }}
      columns={['number', 'project_id', 'received', 'priority', 'due_date', 'status', 'progress_pct']}
      toolbar={<>{head}<Segments value={status} onChange={setStatus} label={t('Status')}
        options={[['open', 'Open'], ['overdue', 'Overdue'], ['awaiting_review', 'Awaiting review'], ['reported', 'Reported'], ['all', 'All']]} /></>}
      formTools={testPicker}
      hideInForm={['tests']}
      formLayout={{
        first: ['project_id', 'client_id', 'received', 'priority', 'technician', 'agreed_due', 'instructions'],
        groups: [{ title: 'Report and cancellation', fields: ['reported_on', 'report_ref', 'cancelled'] }],
      }}
      extra={r => <OrderDetail record={r} state={states.get(r.id)} />}
      hideInView={['status', 'progress_pct', 'test_count', 'tests_done', 'tests_authorised', 'sla_days', 'turnaround_days', 'on_time', 'by_category', 'warning_count', 'tests']} />
  )
}

// ---------------------------------------------------------------------------
// Management overview
// ---------------------------------------------------------------------------

type WorkOverview = {
  tasks: { open: number, overdue: number, blocked: number, done: number, projects: Array<{ project_id: string, code: string, name: string, open: number, overdue: number }> } | null
  submissions: { by_state: Record<string, number>, waiting: number, this_month: number } | null
  crew: { people: number, on_site: number, man_days: number, with_warnings: number, expired: number } | null
  lab: LabBoard['kpis'] | null
  lab_basis?: string
}

export function WorkOverviewPanel({ onOpen }: { onOpen?: (tab: string) => void }) {
  const { data, error } = useLive<WorkOverview>('/api/erp/work/overview')
  if (error) return <p className="notice error">{error}</p>
  if (!data) return null
  const link = (tab: string, label: string) => onOpen ? <button type="button" className="small quiet" onClick={() => onOpen(tab)}>{label}</button> : null
  return (
    <div className="ops-overview">
      {data.tasks && (data.tasks.open + data.tasks.done > 0) && (
        <section className="hub-section">
          <div className="hub-head"><h3>{t('Project tasks')}</h3>{link('tasks', t('Task board'))}</div>
          <div className="kpis">
            <Kpi label={t('Open tasks')} value={data.tasks.open} sub={t('{n} blocked', { n: data.tasks.blocked })} />
            <Kpi label={t('Overdue')} value={data.tasks.overdue} tone={data.tasks.overdue ? 'bad' : undefined} />
            {data.tasks.projects.filter(p => p.overdue).slice(0, 3).map(p => <Kpi key={p.project_id} label={p.code || t('Project')} value={p.overdue} sub={t('overdue of {n} open', { n: p.open })} />)}
          </div>
        </section>
      )}
      {data.lab && (
        <section className="hub-section">
          <div className="hub-head"><h3>{t('Laboratory turnaround')}</h3>{link('lab_orders', t('Laboratory work orders'))}</div>
          <LabKpis kpis={data.lab} basis={data.lab_basis || 'working'} />
        </section>
      )}
      {(data.submissions || data.crew) && (
        <section className="hub-section">
          <div className="hub-head"><h3>{t('Field hand-off and crew')}</h3>{link('roster', t('Crew roster'))}</div>
          <div className="kpis">
            {data.submissions && <Kpi label={t('Field submissions waiting')} value={data.submissions.waiting} sub={t('{n} sent this month', { n: data.submissions.this_month })} />}
            {data.submissions && <Kpi label={t('Returned to the field')} value={data.submissions.by_state.returned || 0} />}
            {data.crew && <Kpi label={t('Crew on site now')} value={data.crew.on_site} sub={t('{n} man-days recorded', { n: number(data.crew.man_days) })} />}
            {data.crew && <Kpi label={t('Safety documents expired')} value={data.crew.expired} tone={data.crew.expired ? 'bad' : undefined} sub={t('{n} with warnings', { n: data.crew.with_warnings })} />}
          </div>
        </section>
      )}
    </div>
  )
}
