/**
 * Operations ERP pages (blueprint A.4 Logistic & General Affair, A.5 Maintenance, procurement card,
 * fixed asset card, work plan & performance card) built on RecordsPage, plus the live views served by
 * /api/erp/ops (equipment status board, maintenance due list, procurement stage, depreciation
 * schedule as of a date, operations overview for the management dashboard).
 */
import { ReactNode, useEffect, useMemo, useState } from 'react'
import { apiGet, listRecords, type CalcResult, type Rec } from '../api'
import { t } from '../i18n'
import { useNav, type Intent, type TabKey } from '../nav'
import {
  RecordFields, RecordForm, RecordsPage, STATUS_TONE, invalidate, money, number, optionLabel, useList, useSchemas,
  type FormLayout, type FormTools,
} from '../records'
import { DateInput, Icon, PageHead, ScrollTable, formatDate, todayIso } from '../ui'
import { ResultView } from '../worksheets'
import './ErpOps.css'

// Status colours of the operations records (only keys the shared table does not define yet).

const go2 = (go: (tab: TabKey, intent?: Intent) => void) => (tab: string, intent?: Intent) => go(tab as TabKey, intent)

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

// Tones of the statuses added by the quality modules (the shared table covers the others).
const TONE: Record<string, string> = {
  ...STATUS_TONE, authorised: 'ok', awaiting: 'warn', conditional: 'warn', blocked: 'bad', not_evaluated: '',
  on_hold: 'warn', in_store: 'active', returned: '', correction: 'warn', corrective_action: 'active', verification: 'warn',
  ok: 'ok', failed: 'bad', not_calibrated: 'bad', not_required: '',
}

function Tone({ value, label }: { value: string, label: string }) {
  return <span className={`status ${TONE[value] ?? ''}`}>{label}</span>
}

/** Records of one kind, read again whenever `round` changes (after an inline save). */
function useRecords(entity: string | null, round = 0) {
  const [rows, setRows] = useState<Rec[] | null>(null)
  useEffect(() => {
    let live = true
    if (!entity) return
    listRecords(entity).then(r => { if (live) setRows(r) }).catch(() => { if (live) setRows([]) })
    return () => { live = false }
  }, [entity, round])
  return rows
}

/** A new record of another kind, filled in without leaving the page. */
function InlineForm({ entityName, title, defaults, layout, onDone }: {
  entityName: string, title: string, defaults: Record<string, any>, layout?: FormLayout, onDone: (saved: Rec | null) => void
}) {
  const schemas = useSchemas()
  const entity = schemas?.[entityName]
  if (!entity) return null
  return (
    <section className="card ops-inline">
      <h3 className="card-title">{title}</h3>
      <RecordForm entity={entity} defaults={defaults} layout={layout} onSaved={r => { invalidate(entityName); onDone(r) }} onCancel={() => onDone(null)} />
    </section>
  )
}

/** Switch between related registers on one page (used until they get their own menu entries). */
export function ViewSwitch({ value, onChange, options, label }: { value: string, onChange: (v: string) => void, options: Array<[string, string]>, label: string }) {
  return (
    <div className="segmented ops-switch" role="group" aria-label={label}>
      {options.map(([k, l]) => <button key={k} type="button" aria-pressed={value === k} onClick={() => onChange(k)}>{t(l)}</button>)}
    </div>
  )
}

const fieldOf = (schemas: ReturnType<typeof useSchemas>, entity: string, field: string) =>
  schemas?.[entity]?.fields.find(f => f.name === field)

function useOption(entity: string, field: string) {
  const schemas = useSchemas()
  return (value: unknown) => {
    const f = fieldOf(schemas, entity, field)
    return f ? optionLabel(f, value) : String(value ?? '')
  }
}

// ---------------------------------------------------------------------------
// Checks stored on a record: [{text, vars, money}] translated with their values
// ---------------------------------------------------------------------------

type Warning = { text: string, vars?: Record<string, string | number>, money?: string[] }

function warningText(w: Warning) {
  const vars: Record<string, string | number> = {}
  for (const [k, v] of Object.entries(w.vars || {})) {
    vars[k] = w.money?.includes(k) ? money(v) : typeof v === 'number' ? number(v)
      : typeof v === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(v) ? formatDate(v) : String(v)
  }
  return t(w.text, vars)
}

export function Checks({ record }: { record: Rec }) {
  const list: Warning[] = Array.isArray(record.warnings) ? record.warnings : []
  if (!list.length) return null
  return (
    <div className="notice warn ops-checks" role="status">
      <strong>{t('Check before continuing')}</strong>
      <ul>{list.map((w, i) => <li key={i}>{warningText(w)}</li>)}</ul>
    </div>
  )
}

function Kpi({ label, value, sub, moneyValue }: { label: string, value: ReactNode, sub?: ReactNode, moneyValue?: boolean }) {
  return <div className="kpi"><h4>{label}</h4><p className={moneyValue ? 'kpi-money' : undefined}>{value}</p>{sub && <span className="muted small">{sub}</span>}</div>
}

// ---------------------------------------------------------------------------
// Equipment register
// ---------------------------------------------------------------------------

export type EquipmentState = {
  id: string, code: string, name: string, category: string, status: string, manual_status: string, note: string,
  location: string, project_id: string, mobilisation: { id: string, number: string } | null, open_work_orders: number,
  last_calibration: string | null, next_calibration_due: string | null, calibration_days_left: number | null, calibration_status: string,
  last_service: string | null, next_service_due: string | null, service_days_left: number | null, next_service_hours: number | null,
  hours_now: number | null, service_status: string,
}

const DUE_LABEL: Record<string, string> = { ok: 'OK', due_soon: 'Due soon', overdue: 'Overdue', missing: 'No record yet' }

function DueCell({ status, date, daysLeft, hours }: { status: string, date: string | null, daysLeft: number | null, hours?: number | null }) {
  if (!status) return <span className="muted">–</span>
  return (
    <>
      <Tone value={status === 'ok' ? 'available' : status} label={t(DUE_LABEL[status] || status)} />
      <div className="bh-sub">
        {date ? formatDate(date) : ''}{daysLeft !== null && daysLeft !== undefined ? ` · ${daysLeft < 0 ? t('{n} days late', { n: -daysLeft }) : t('{n} days left', { n: daysLeft })}` : ''}
        {hours ? ` · ${t('at {h} h', { h: number(hours) })}` : ''}
      </div>
    </>
  )
}

function EquipmentBoard({ board, onOpen }: { board: EquipmentState[], onOpen: (id: string) => void }) {
  const statusLabel = useOption('equipment', 'status')
  const count = (s: string) => board.filter(b => b.status === s).length
  const attention = board.filter(b => b.status !== 'disposed' && (
    ['overdue', 'missing', 'due_soon'].includes(b.calibration_status) || ['overdue', 'missing', 'due_soon'].includes(b.service_status) || b.note))
  const late = board.filter(b => b.status !== 'disposed' && (['overdue', 'missing'].includes(b.calibration_status) || ['overdue', 'missing'].includes(b.service_status))).length
  return (
    <section className="ops-board">
      <div className="kpis">
        <Kpi label={t('Available')} value={count('available')} />
        <Kpi label={t('Mobilised')} value={count('mobilised')} />
        <Kpi label={t('In maintenance')} value={count('maintenance')} />
        <Kpi label={t('Broken')} value={count('broken')} />
        <Kpi label={t('Service or calibration overdue')} value={late} />
      </div>
      {attention.length > 0 && (
        <details className="card ops-attention" open={late > 0 || undefined}>
          <summary>{t('Needs attention')} <span className="muted small">· {attention.length}</span></summary>
          <ScrollTable>
            <table className="data-table">
              <thead><tr><th>{t('Equipment')}</th><th>{t('Status now')}</th><th>{t('Calibration')}</th><th>{t('Servicing')}</th></tr></thead>
              <tbody>
                {attention.map(b => (
                  <tr key={b.id} className="clickable" onClick={() => onOpen(b.id)}>
                    <td><strong>{b.code}</strong><div className="bh-sub">{b.name}</div></td>
                    <td><Tone value={b.status} label={statusLabel(b.status)} />{b.note && <div className="bh-sub">{t(b.note)}</div>}</td>
                    <td><DueCell status={b.calibration_status} date={b.next_calibration_due} daysLeft={b.calibration_days_left} /></td>
                    <td><DueCell status={b.service_status} date={b.next_service_due} daysLeft={b.service_days_left} hours={b.next_service_hours} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </ScrollTable>
        </details>
      )}
    </section>
  )
}

function EquipmentLive({ record, board, metrics }: { record: Rec, board: EquipmentState[] | null, metrics: MaintenanceMetricsResult | null }) {
  const nav = useNav()
  const go = go2(nav.go)
  const schemas = useSchemas()
  const statusLabel = useOption('equipment', 'status')
  const woType = useOption('work_orders', 'type')
  const woStatus = useOption('work_orders', 'status')
  const orders = (useList('work_orders') || []).filter(w => w.equipment_id === record.id)
  const mobs = (useList('mobilisations') || []).filter(m => (m.equipment || []).some((r: Rec) => r.equipment_id === record.id))
  const b = board?.find(x => x.id === record.id)
  const m = metrics?.equipment.find(x => x.id === record.id)
  const canWo = !!schemas?.work_orders?.can_create
  const newWo = (type: string) => go('work_orders', { newWith: { equipment_id: record.id, type, date: todayIso(), status: 'open', hour_meter: b?.hours_now ?? undefined } })
  return (
    <>
      {b && (
        <section className="card ops-live">
          <div className="ops-live-head">
            <div>
              <h3 className="card-title">{t('Status now')}</h3>
              <Tone value={b.status} label={statusLabel(b.status)} />
              {b.status !== b.manual_status && <span className="muted small"> · {t('set by hand: {s}', { s: statusLabel(b.manual_status) })}</span>}
              {b.note && <p className="help">{t(b.note)}</p>}
              <p className="help">{b.location || '–'}{b.mobilisation ? ` · ${b.mobilisation.number}` : ''}</p>
            </div>
            {canWo && (
              <div className="actions">
                <button type="button" className="small" onClick={() => newWo('preventive')}><Icon name="plus" />{t('Servicing')}</button>
                <button type="button" className="small" onClick={() => newWo('corrective')}><Icon name="plus" />{t('Repair')}</button>
                {record.calibration_months ? <button type="button" className="small" onClick={() => newWo('calibration')}><Icon name="plus" />{t('Calibration')}</button> : null}
              </div>
            )}
          </div>
          <dl className="facts-grid compact">
            <div><dt>{t('Calibration')}</dt><dd><DueCell status={b.calibration_status} date={b.next_calibration_due} daysLeft={b.calibration_days_left} /></dd></div>
            <div><dt>{t('Servicing')}</dt><dd><DueCell status={b.service_status} date={b.next_service_due} daysLeft={b.service_days_left} hours={b.next_service_hours} /></dd></div>
            <div><dt>{t('Hour meter (h)')}</dt><dd>{number(b.hours_now)}</dd></div>
            <div><dt>{t('Open work orders')}</dt><dd>{b.open_work_orders}</dd></div>
          </dl>
          {m && (
            <>
              <h4 className="ops-subhead">{t('Maintenance performance, {from} – {to}', { from: formatDate(metrics?.period.from), to: formatDate(metrics?.period.to) })}</h4>
              <dl className="facts-grid compact">
                <div><dt>{t('Availability')}</dt><dd>{pct(m.availability_pct)}</dd></div>
                <div><dt>MTBF</dt><dd>{days(m.mtbf_days)}<div className="bh-sub">{t('{n} failures', { n: m.failures })}</div></dd></div>
                <div><dt>MTTR</dt><dd>{days(m.mttr_days)}</dd></div>
                <div><dt>{t('PM compliance')}</dt><dd>{pct(m.pm_compliance_pct)}</dd></div>
              </dl>
            </>
          )}
        </section>
      )}
      {orders.length > 0 && (
        <section className="hub-section">
          <div className="hub-head"><h3>{t('Maintenance history')} <span className="muted">{orders.length}</span></h3></div>
          <ScrollTable>
            <table className="data-table">
              <thead><tr><th>{t('Number')}</th><th>{t('Type')}</th><th>{t('Status')}</th><th>{t('Reported on')}</th><th className="num">{t('Downtime (days)')}</th><th className="num">{t('Total cost')}</th></tr></thead>
              <tbody>
                {orders.map(w => (
                  <tr key={w.id} className="clickable" onClick={() => go('work_orders', { open: w.id })}>
                    <td>{w.number}</td><td>{woType(w.type)}</td><td><Tone value={w.status} label={woStatus(w.status)} /></td>
                    <td className="nowrap">{formatDate(w.date)}</td><td className="num">{number(w.downtime)}</td><td className="num nowrap">{money(w.total_cost)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </ScrollTable>
        </section>
      )}
      {mobs.length > 0 && (
        <section className="hub-section">
          <div className="hub-head"><h3>{t('Mobilisations')} <span className="muted">{mobs.length}</span></h3></div>
          <ul className="ops-plain">
            {mobs.map(m => (
              <li key={m.id}><button type="button" className="quiet" onClick={() => go('mobilisations', { open: m.id })}>{m.number}</button> {m.to_location} · {formatDate(m.actual_mob_date || m.planned_mob_date)}</li>
            ))}
          </ul>
        </section>
      )}
    </>
  )
}

/** Remount the list to open a record picked from a live board above it. */
function useJump(intent?: Intent) {
  const [jump, setJump] = useState<{ id: string, n: number } | null>(null)
  return {
    key: jump?.n ?? 0,
    openId: jump?.id ?? intent?.open,
    open: (id: string) => setJump(j => ({ id, n: (j?.n ?? 0) + 1 })),
  }
}

const EQUIPMENT_LAYOUT: FormLayout = {
  first: ['code', 'name', 'category', 'status', 'location', 'project_id'],
  groups: [
    { title: 'Make and serial number', fields: ['brand', 'model', 'serial', 'custodian', 'asset_id'] },
    { title: 'Calibration', fields: ['calibration_months', 'last_calibration', 'calibration_cert'] },
    { title: 'Service schedule', fields: ['in_service_date', 'hour_meter', 'hour_meter_date', 'service_days', 'service_hours', 'last_service_date', 'last_service_hours'] },
  ],
}

export function EquipmentPage({ intent }: { intent?: Intent }) {
  const [round, setRound] = useState(0)
  const { data: board } = useLive<EquipmentState[]>('/api/erp/ops/equipment-status', round)
  const { data: metrics } = useLive<MaintenanceMetricsResult>('/api/erp/ops/maintenance-metrics', round)
  const jump = useJump(intent)
  return (
    <RecordsPage key={jump.key} entityName="equipment" openId={jump.openId} startNew={intent?.newWith}
      description={t('Drill rigs, CPT rigs, pumps, instruments and vehicles: where they are, and when service and calibration are due.')}
      defaults={{ status: 'available' }}
      columns={['code', 'name', 'category', 'status', 'location', 'next_calibration_due', 'next_service_due']}
      formLayout={EQUIPMENT_LAYOUT}
      toolbar={board && board.length > 0 ? <EquipmentBoard board={board} onOpen={jump.open} /> : null}
      extra={r => <EquipmentLive record={r} board={board} metrics={metrics} key={r.updated_at} />}
      hideInView={['next_service_hours']}
      formTools={(_d, _s, place) => place === 'bottom' ? <p className="help">{t('The status shown in lists is the one set by hand; the status board above shows mobilised equipment from active mobilisations.')}</p> : null}
      actions={() => <button type="button" className="quiet" onClick={() => setRound(n => n + 1)}>{t('Refresh status')}</button>} />
  )
}

// ---------------------------------------------------------------------------
// Mobilisation & demobilisation
// ---------------------------------------------------------------------------

const MOB_STEPS = ['planned', 'in_transit', 'on_site', 'demobilising', 'returned']

function Steps({ steps, current, label }: { steps: Array<[string, string]>, current: string, label: string }) {
  const index = steps.findIndex(([k]) => k === current)
  return (
    <ol className="stepper" aria-label={label}>
      {steps.map(([k, l], i) => (
        <li key={k} className={i < index ? 'done' : i === index ? 'current' : ''} aria-current={i === index ? 'step' : undefined}>
          <span className="step-no">{i < index ? <Icon name="check" size={13} /> : i + 1}</span>{t(l)}
        </li>
      ))}
    </ol>
  )
}

function MobilisationSummary({ record }: { record: Rec }) {
  const status = useOption('mobilisations', 'status')
  const category = useOption('equipment', 'category')
  const nav = useNav()
  const go = go2(nav.go)
  const management = ['admin', 'manager', 'finance'].includes(nav.role)
  const equipment = useList('equipment')
  const rows: Rec[] = record.equipment || []
  return (
    <>
      {record.status === 'cancelled' ? <p className="notice">{status('cancelled')}</p>
        : <Steps steps={MOB_STEPS.map(s => [s, status(s)])} current={record.status} label={t('Mobilisation stage')} />}
      <Checks record={record} />
      <div className="kpis" style={{ margin: '.75rem 0' }}>
        <Kpi label={t('Equipment items')} value={number(record.equipment_count ?? 0)} />
        <Kpi label={t('Crew')} value={(record.crew || []).length} />
        <Kpi label={t('Days on site')} value={number(record.actual_days)} sub={record.planned_days ? t('planned {n}', { n: number(record.planned_days) }) : undefined} />
        {management && <Kpi label={t('Total cost')} value={money(record.total_cost)} moneyValue />}
      </div>
      {rows.length > 0 && (
        <section className="hub-section">
          <div className="hub-head"><h3>{t('Equipment')} <span className="muted">{rows.length}</span></h3></div>
          <ScrollTable>
            <table className="data-table">
              <thead><tr><th>{t('Equipment code')}</th><th>{t('Name')}</th><th>{t('Category')}</th><th>{t('Note')}</th></tr></thead>
              <tbody>
                {rows.map((r, i) => {
                  const e = equipment?.find(x => x.id === r.equipment_id)
                  return (
                    <tr key={i} className="clickable" onClick={() => go('equipment', { open: r.equipment_id })}>
                      <td><strong>{e?.code ?? '…'}</strong></td><td>{e?.name ?? ''}</td><td>{e ? category(e.category) : ''}</td><td>{r.note || '–'}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </ScrollTable>
        </section>
      )}
    </>
  )
}

export function MobilisationsPage({ intent }: { intent?: Intent }) {
  return (
    <RecordsPage entityName="mobilisations" openId={intent?.open} startNew={intent?.newWith}
      description={t('Moving equipment and crew to a project site and back, with dates and transport costs.')}
      defaults={{ date: todayIso(), status: 'planned' }}
      columns={['number', 'project_id', 'to_location', 'status', 'planned_mob_date', 'warning_count']}
      formLayout={{
        first: ['project_id', 'to_location', 'status', 'date', 'planned_mob_date', 'planned_demob_date', 'equipment', 'crew'],
        groups: [{ title: 'Transport and costs', fields: ['from_location', 'transport_mode', 'vehicle', 'mob_cost', 'demob_cost', 'other_cost'] }],
      }}
      extra={r => <MobilisationSummary record={r} />}
      hideInView={['warning_count', 'equipment', 'total_cost', 'equipment_count', 'planned_days', 'actual_days']} />
  )
}

// ---------------------------------------------------------------------------
// Maintenance work orders and the preventive due list
// ---------------------------------------------------------------------------

type DueItem = { equipment_id: string, code: string, name: string, kind: 'calibration' | 'service', status: string, due: string | null, days_left: number | null, due_hours: number | null, hours_now: number | null }

function DueList({ onCreate }: { onCreate?: (item: DueItem) => void }) {
  const { data, error } = useLive<CalcResult & { items: DueItem[] }>('/api/erp/ops/maintenance-due')
  if (error) return <p className="notice error">{error}</p>
  if (!data) return null
  const items = data.items || []
  const late = items.filter(i => i.status !== 'due_soon').length
  return (
    <details className="card ops-attention" open={late > 0 || undefined}>
      <summary>{t('Service and calibration due')} <span className="muted small">· {t('{a} overdue, {b} due soon', { a: late, b: items.length - late })}</span></summary>
      {items.length === 0 ? <p className="muted">{t('Nothing is due in the coming weeks.')}</p> : (
        <ScrollTable>
          <table className="data-table">
            <thead><tr><th>{t('Equipment')}</th><th>{t('Work')}</th><th>{t('Status')}</th><th>{t('Due date')}</th><th className="num">{t('Hour meter (h)')}</th><th /></tr></thead>
            <tbody>
              {items.map((i, n) => (
                <tr key={n}>
                  <td><strong>{i.code}</strong><div className="bh-sub">{i.name}</div></td>
                  <td>{t(i.kind === 'calibration' ? 'Calibration' : 'Servicing')}</td>
                  <td><Tone value={i.status} label={t(DUE_LABEL[i.status])} /></td>
                  <td className="nowrap">{i.due ? formatDate(i.due) : '–'}{i.days_left !== null && <div className="bh-sub">{i.days_left < 0 ? t('{n} days late', { n: -i.days_left }) : t('{n} days left', { n: i.days_left })}</div>}</td>
                  <td className="num">{i.due_hours ? `${number(i.hours_now)} / ${number(i.due_hours)}` : '–'}</td>
                  <td>{onCreate && <button type="button" className="small" onClick={() => onCreate(i)}>{t('Create work order')}</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </ScrollTable>
      )}
      {data.notes && <ResultView result={{ notes: data.notes }} />}
    </details>
  )
}

type EquipmentMetrics = {
  id: string, code: string, name: string, required_days: number, downtime_days: number, availability_pct: number | null,
  failures: number, mtbf_days: number | null, repairs_completed: number, mttr_days: number | null, preventive_pct: number | null,
  pm_on_time: number, pm_late: number, pm_pending: number, pm_compliance_pct: number | null, scheduled_done: number, corrective_done: number,
}
type FleetMetrics = Omit<EquipmentMetrics, 'id' | 'code' | 'name' | 'pm_pending'> & { equipment: number }
export type MaintenanceMetricsResult = CalcResult & { period: { from: string, to: string }, fleet: FleetMetrics, equipment: EquipmentMetrics[] }

const pct = (v: number | null | undefined) => v === null || v === undefined ? '–' : `${number(v)} %`
const days = (v: number | null | undefined) => v === null || v === undefined ? '–' : t('{n} days', { n: number(v) })

/** Availability, MTBF, MTTR, preventive share and PM compliance over a chosen period. */
function MaintenanceMetrics() {
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const query = [from && `from=${from}`, to && `to=${to}`].filter(Boolean).join('&')
  const { data, error } = useLive<MaintenanceMetricsResult>(`/api/erp/ops/maintenance-metrics${query ? `?${query}` : ''}`)
  const f = data?.fleet
  return (
    <details className="card ops-attention">
      <summary>{t('Maintenance performance')} {f && <span className="muted small">· {t('availability {a}, MTBF {b}, MTTR {c}', { a: pct(f.availability_pct), b: days(f.mtbf_days), c: days(f.mttr_days) })}</span>}</summary>
      <div className="ops-period">
        <div className="field"><label htmlFor="mm-from">{t('Period from')}</label><DateInput id="mm-from" value={from || data?.period.from || ''} onChange={setFrom} /></div>
        <div className="field"><label htmlFor="mm-to">{t('Period to')}</label><DateInput id="mm-to" value={to || data?.period.to || ''} onChange={setTo} /></div>
      </div>
      {error && <p className="notice error">{error}</p>}
      {f && (
        <div className="kpis" style={{ margin: '.5rem 0 1rem' }}>
          <Kpi label={t('Availability')} value={pct(f.availability_pct)} sub={t('{n} days down', { n: number(f.downtime_days) })} />
          <Kpi label="MTBF" value={days(f.mtbf_days)} sub={t('{n} failures', { n: f.failures })} />
          <Kpi label="MTTR" value={days(f.mttr_days)} sub={t('{n} repairs completed', { n: f.repairs_completed })} />
          <Kpi label={t('Preventive share')} value={pct(f.preventive_pct)} sub={t('{a} preventive, {b} corrective', { a: f.scheduled_done, b: f.corrective_done })} />
          <Kpi label={t('PM compliance')} value={pct(f.pm_compliance_pct)} sub={t('{a} on time, {b} late', { a: f.pm_on_time, b: f.pm_late })} />
        </div>
      )}
      {data && <ResultView result={{ tables: data.tables, notes: data.notes, method: data.method }} />}
    </details>
  )
}

function WorkOrderSummary({ record }: { record: Rec }) {
  const open = !['completed', 'cancelled'].includes(record.status) && record.start_date
  const running = open ? Math.max(0, Math.round((Date.parse(todayIso()) - Date.parse(record.start_date)) / 86400000)) : null
  return (
    <>
      <Checks record={record} />
      <div className="kpis" style={{ margin: '.75rem 0' }}>
        <Kpi label={t('Parts cost')} value={money(record.parts_cost)} moneyValue />
        <Kpi label={t('Total cost')} value={money(record.total_cost)} moneyValue />
        <Kpi label={t('Downtime (days)')} value={running !== null ? number(running) : number(record.downtime)} sub={running !== null ? t('so far, since work started') : undefined} />
        {record.next_calibration_due && <Kpi label={t('Next calibration due')} value={formatDate(record.next_calibration_due)} />}
      </div>
    </>
  )
}

const woHide = (d: Record<string, any>) => [
  ...(d.type === 'calibration' ? [] : ['calibration_result', 'certificate_no']),
  ...(d.performed_by === 'vendor' ? [] : ['vendor_id']),
]

export function WorkOrdersPage({ intent }: { intent?: Intent }) {
  const [start, setStart] = useState<{ data: Record<string, unknown>, n: number } | null>(null)
  const schemas = useSchemas()
  const create = (i: DueItem) => setStart(s => ({ n: (s?.n ?? 0) + 1, data: {
    equipment_id: i.equipment_id, type: i.kind === 'calibration' ? 'calibration' : 'preventive', date: todayIso(), status: 'open',
    hour_meter: i.hours_now ?? '', description: t(i.kind === 'calibration' ? 'Scheduled calibration' : 'Scheduled service'),
  } }))
  return (
    <RecordsPage key={start?.n ?? 0} entityName="work_orders" openId={start ? undefined : intent?.open} startNew={start?.data ?? intent?.newWith}
      description={t('Preventive service, repairs, calibration and inspections, with parts, costs and downtime.')}
      defaults={{ date: todayIso(), status: 'open', type: 'corrective', priority: 'normal', performed_by: 'internal' }}
      columns={['number', 'equipment_id', 'type', 'status', 'date', 'total_cost', 'warning_count']}
      toolbar={<><DueList onCreate={schemas?.work_orders?.can_create ? create : undefined} /><MaintenanceMetrics /></>}
      formLayout={{
        first: ['equipment_id', 'type', 'priority', 'status', 'date', 'description'],
        groups: [{ title: 'Calibration certificate', fields: ['calibration_result', 'certificate_no'] }],
        hide: woHide,
      }}
      extra={r => <WorkOrderSummary record={r} />}
      hideInView={['warning_count', 'parts_cost', 'total_cost', 'downtime', 'next_calibration_due']} />
  )
}

// ---------------------------------------------------------------------------
// Vendors
// ---------------------------------------------------------------------------

function VendorHistory({ record }: { record: Rec }) {
  const nav = useNav()
  const go = go2(nav.go)
  const schemas = useSchemas()
  const pos = useList(schemas?.purchase_orders?.can_read ? 'purchase_orders' : null)
  const progress = useOption('purchase_orders', 'progress')
  const mine = (pos || []).filter(p => p.vendor_id === record.id && p.status !== 'cancelled')
  if (!mine.length) return null
  const total = mine.filter(p => p.status !== 'draft').reduce((s, p) => s + (p.total || 0), 0)
  return (
    <section className="hub-section">
      <div className="hub-head"><h3>{t('Purchase orders')} <span className="muted">{mine.length} · {money(total)}</span></h3></div>
      <ScrollTable>
        <table className="data-table">
          <thead><tr><th>{t('PO number')}</th><th>{t('PO date')}</th><th>{t('Progress')}</th><th className="num">{t('Total')}</th></tr></thead>
          <tbody>
            {mine.map(p => (
              <tr key={p.id} className="clickable" onClick={() => go('purchase_orders', { open: p.id })}>
                <td>{p.number}</td><td className="nowrap">{formatDate(p.date)}</td><td><Tone value={p.progress} label={progress(p.progress)} /></td><td className="num nowrap">{money(p.total)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </ScrollTable>
    </section>
  )
}

export type VendorStanding = {
  id: string, name: string, category: string, active: boolean, status: string, score: number | null, date: string | null,
  next_due: string | null, reevaluation_overdue: boolean, evaluation_id: string | null,
}

const VENDOR_STATUS: Record<string, string> = { approved: 'Approved', conditional: 'Conditional', blocked: 'Blocked', not_evaluated: 'Not evaluated yet' }

function VendorBoard({ board, onOpen }: { board: VendorStanding[], onOpen: (id: string) => void }) {
  const active = board.filter(v => v.active)
  const count = (s: string) => active.filter(v => v.status === s).length
  const attention = active.filter(v => ['blocked', 'conditional'].includes(v.status) || v.reevaluation_overdue)
  return (
    <section className="ops-board">
      <div className="kpis">
        <Kpi label={t('Approved')} value={count('approved')} />
        <Kpi label={t('Conditional')} value={count('conditional')} />
        <Kpi label={t('Blocked')} value={count('blocked')} />
        <Kpi label={t('Not evaluated yet')} value={count('not_evaluated')} />
        <Kpi label={t('Re-evaluation overdue')} value={active.filter(v => v.reevaluation_overdue).length} />
      </div>
      {attention.length > 0 && (
        <details className="card ops-attention">
          <summary>{t('Needs attention')} <span className="muted small">· {attention.length}</span></summary>
          <ScrollTable>
            <table className="data-table">
              <thead><tr><th>{t('Vendor')}</th><th>{t('Evaluation')}</th><th className="num">{t('Score (%)')}</th><th>{t('Next evaluation due')}</th></tr></thead>
              <tbody>
                {attention.map(v => (
                  <tr key={v.id} className="clickable" onClick={() => onOpen(v.id)}>
                    <td><strong>{v.name}</strong></td>
                    <td><Tone value={v.status} label={t(VENDOR_STATUS[v.status] || v.status)} /></td>
                    <td className="num">{number(v.score)}</td>
                    <td className="nowrap">{v.next_due ? formatDate(v.next_due) : '–'}{v.reevaluation_overdue && <div className="bh-sub">{t('Overdue')}</div>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </ScrollTable>
        </details>
      )}
    </section>
  )
}

const EVALUATION_LAYOUT: FormLayout = {
  first: ['vendor_id', 'date', 'evaluator', 'score_quality', 'score_delivery', 'score_price', 'score_hse', 'score_responsiveness', 'actions'],
  groups: [
    { title: 'Period and basis', fields: ['period_from', 'period_to', 'basis'] },
    { title: 'Serious breach', fields: ['critical_issue', 'critical_note'] },
  ],
}

function VendorEvaluations({ record, standing, onChanged }: { record: Rec, standing: VendorStanding | undefined, onChanged: () => void }) {
  const { email } = useNav()
  const schemas = useSchemas()
  const [round, setRound] = useState(0)
  const [adding, setAdding] = useState(false)
  const outcome = useOption('vendor_evaluations', 'outcome')
  const rows = (useRecords('vendor_evaluations', round) || []).filter(e => e.vendor_id === record.id)
    .sort((a, b) => String(b.date).localeCompare(String(a.date)))
  const canAdd = !!schemas?.vendor_evaluations?.can_create
  return (
    <section className="card ops-live">
      <div className="ops-live-head">
        <div>
          <h3 className="card-title">{t('Vendor evaluation')}</h3>
          {standing && <Tone value={standing.status} label={t(VENDOR_STATUS[standing.status] || standing.status)} />}
          {standing?.score !== null && standing?.score !== undefined && <span className="muted small"> · {number(standing.score)} %</span>}
          {standing?.next_due && <p className="help">{t('Next evaluation due {d}', { d: formatDate(standing.next_due) })}{standing.reevaluation_overdue ? ` · ${t('Overdue')}` : ''}</p>}
        </div>
        {canAdd && !adding && <button type="button" className="small" onClick={() => setAdding(true)}><Icon name="plus" />{t('New evaluation')}</button>}
      </div>
      {adding && (
        <InlineForm entityName="vendor_evaluations" title={t('New evaluation')} layout={EVALUATION_LAYOUT}
          defaults={{ vendor_id: record.id, date: todayIso(), evaluator: email }}
          onDone={saved => { setAdding(false); if (saved) { setRound(n => n + 1); onChanged() } }} />
      )}
      {rows.length > 0 ? (
        <ScrollTable>
          <table className="data-table">
            <thead><tr><th>{t('Evaluated on')}</th><th className="num">{t('Score (%)')}</th><th>{t('Outcome')}</th><th>{t('Improvement actions agreed')}</th></tr></thead>
            <tbody>
              {rows.map(e => (
                <tr key={e.id}>
                  <td className="nowrap">{formatDate(e.date)}</td><td className="num">{number(e.score_pct)}</td>
                  <td>{e.outcome ? <Tone value={e.outcome} label={outcome(e.outcome)} /> : '–'}</td><td>{e.actions || '–'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </ScrollTable>
      ) : <p className="muted">{t('No evaluation yet. ISO 9001 asks for criteria to evaluate, select, monitor and re-evaluate suppliers.')}</p>}
    </section>
  )
}

export function VendorEvaluationsPage({ intent, switcher }: { intent?: Intent, switcher?: ReactNode }) {
  const { email } = useNav()
  return (
    <RecordsPage entityName="vendor_evaluations" openId={intent?.open} startNew={intent?.newWith}
      description={t('Periodic scoring of vendors on quality, delivery, price, HSE and compliance, and responsiveness; the outcome approves, conditions or blocks the vendor.')}
      defaults={{ date: todayIso(), evaluator: email }}
      columns={['vendor_id', 'date', 'score_pct', 'outcome', 'warning_count']}
      toolbar={switcher}
      formLayout={EVALUATION_LAYOUT}
      extra={r => <Checks record={r} />}
      hideInView={['warning_count']} />
  )
}

export function VendorsPage({ intent }: { intent?: Intent }) {
  const [view, setView] = useState('vendors')
  const [round, setRound] = useState(0)
  const { data: board } = useLive<VendorStanding[]>('/api/erp/ops/vendor-standing', round)
  const jump = useJump(intent)
  const switcher = <ViewSwitch value={view} onChange={setView} label={t('Show')} options={[['vendors', 'Vendors'], ['evaluations', 'Vendor evaluations']]} />
  if (view === 'evaluations') return <VendorEvaluationsPage switcher={switcher} />
  return (
    <RecordsPage key={jump.key} entityName="vendors" openId={jump.openId} startNew={intent?.newWith}
      description={t('Suppliers, workshops, calibration laboratories and transporters, with their evaluation: approved, conditional or blocked.')}
      defaults={{ active: true }}
      toolbar={<>{switcher}{board && board.length > 0 ? <VendorBoard board={board} onOpen={jump.open} /> : null}</>}
      formLayout={{ groups: [{ title: 'Tax and bank details', fields: ['npwp', 'bank_name', 'bank_account', 'bank_holder'] }] }}
      extra={r => <><VendorEvaluations record={r} standing={board?.find(b => b.id === r.id)} onChanged={() => setRound(n => n + 1)} /><VendorHistory record={r} /></>} />
  )
}

// ---------------------------------------------------------------------------
// Procurement card
// ---------------------------------------------------------------------------

export type ProcurementState = {
  id: string, number: string, title: string, stage: string, wf_status: string, approved_amount: number,
  ordered: number | null, invoiced: number | null, paid: number | null, warning_count: number,
  orders: Array<{ id: string, number: string, progress: string, total: number | null }>,
}

const STAGES: Array<[string, string]> = [
  ['request', 'Request'], ['approval', 'Approval'], ['approved', 'Approved'], ['ordered', 'Ordered'],
  ['received', 'Received'], ['invoiced', 'Invoiced'], ['paid', 'Paid'],
]
const STAGE_LABEL: Record<string, string> = { ...Object.fromEntries(STAGES), partly_received: 'Partly received', cancelled: 'Cancelled' }

function StagePipeline({ states }: { states: ProcurementState[] }) {
  const counts = (k: string) => states.filter(s => s.stage === k || (k === 'received' && s.stage === 'partly_received')).length
  return (
    <ol className="ops-pipeline" aria-label={t('Procurement in progress')}>
      {STAGES.map(([k, l]) => <li key={k}><span className="ops-pipeline-n">{counts(k)}</span>{t(l)}</li>)}
    </ol>
  )
}

function QuotationTable({ record }: { record: Rec }) {
  const vendors = useList('vendors')
  const rows: Rec[] = (record.quotations || []).filter((q: Rec) => q.amount !== null && q.amount !== undefined && q.amount !== '')
  if (!rows.length) return null
  const lowest = Math.min(...rows.map(q => Number(q.amount)))
  const name = (q: Rec) => vendors?.find(v => v.id === q.vendor_id)?.name || q.vendor_name || '–'
  return (
    <section className="hub-section">
      <div className="hub-head"><h3>{t('Quotation comparison')} <span className="muted">{rows.length}/{number(record.required_quotes)}</span></h3></div>
      <ScrollTable>
        <table className="data-table">
          <thead><tr><th>{t('Vendor')}</th><th className="num">{t('Total incl. VAT (IDR)')}</th><th className="num">{t('Above lowest')}</th><th className="num">{t('Delivery (days)')}</th><th>{t('Payment terms / warranty')}</th><th>{t('Chosen')}</th></tr></thead>
          <tbody>
            {[...rows].sort((a, b) => Number(a.amount) - Number(b.amount)).map((q, i) => (
              <tr key={i} className={q.chosen ? 'ops-chosen' : undefined}>
                <td>{name(q)}{q.quote_ref && <div className="bh-sub">{q.quote_ref}{q.quote_date ? ` · ${formatDate(q.quote_date)}` : ''}</div>}</td>
                <td className="num nowrap">{money(q.amount)}</td>
                <td className="num">{lowest > 0 && Number(q.amount) > lowest ? `+${number(Math.round((Number(q.amount) / lowest - 1) * 1000) / 10)} %` : t('Lowest')}</td>
                <td className="num">{number(q.delivery_days)}</td>
                <td>{q.terms || '–'}</td>
                <td>{q.chosen ? <Icon name="check" /> : ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </ScrollTable>
    </section>
  )
}

function ProcurementCard({ record, states }: { record: Rec, states: ProcurementState[] | null }) {
  const nav = useNav()
  const go = go2(nav.go)
  const schemas = useSchemas()
  const progress = useOption('purchase_orders', 'progress')
  const st = states?.find(s => s.id === record.id)
  const stage = st?.stage || (record.cancelled ? 'cancelled' : record.wf_status === 'approved' ? 'approved' : ['submitted', 'reviewed'].includes(record.wf_status) ? 'approval' : 'request')
  const current = stage === 'partly_received' ? 'received' : stage
  const canPo = !!schemas?.purchase_orders?.can_create && record.wf_status === 'approved' && !record.cancelled
  const newPo = () => go('purchase_orders', { newWith: {
    procurement_id: record.id, vendor_id: record.chosen_vendor_id || '', date: todayIso(), status: 'draft', tax_pct: 11,
    items: (record.items || []).map((i: Rec) => ({ description: i.description + (i.spec ? ` – ${i.spec}` : ''), unit: i.unit, qty: i.qty, unit_price: i.est_price })),
  } })
  return (
    <>
      {stage === 'cancelled' ? <p className="notice">{t('Cancelled')}</p> : <Steps steps={STAGES} current={current} label={t('Procurement stage')} />}
      {stage === 'partly_received' && <p className="help">{t('Partly received')}</p>}
      <Checks record={record} />
      <div className="kpis" style={{ margin: '.75rem 0' }}>
        <Kpi label={t('Estimated total')} value={money(record.est_total)} moneyValue />
        <Kpi label={t('Amount to approve')} value={money(record.approved_amount)} moneyValue
          sub={record.chosen_vendor ? <>{record.chosen_vendor}{record.chosen_vendor_status && <> · <Tone value={record.chosen_vendor_status} label={t(VENDOR_STATUS[record.chosen_vendor_status] || record.chosen_vendor_status)} /></>}</> : undefined} />
        <Kpi label={t('Quotations')} value={`${number(record.quote_count ?? 0)} / ${number(record.required_quotes ?? 1)}`} sub={t('received / required')} />
        {st && st.ordered !== null && st.orders.length > 0 && <Kpi label={t('Ordered')} value={money(st.ordered)} moneyValue sub={st.paid ? t('paid {amount}', { amount: money(st.paid) }) : undefined} />}
      </div>
      <QuotationTable record={record} />
      {(st?.orders.length || canPo) ? (
        <section className="hub-section">
          <div className="hub-head">
            <h3>{t('Purchase orders')} <span className="muted">{st?.orders.length ?? 0}</span></h3>
            {canPo && <button type="button" className="small" onClick={newPo}><Icon name="plus" />{t('Create purchase order')}</button>}
          </div>
          {st && st.orders.length > 0 && (
            <ul className="ops-plain">
              {st.orders.map(o => (
                <li key={o.id}>
                  {schemas?.purchase_orders?.can_read ? <button type="button" className="quiet" onClick={() => go('purchase_orders', { open: o.id })}>{o.number}</button> : o.number}
                  {' '}<Tone value={o.progress} label={progress(o.progress)} />{o.total !== null && <span className="muted"> · {money(o.total)}</span>}
                </li>
              ))}
            </ul>
          )}
        </section>
      ) : null}
    </>
  )
}

const procurementTools = (settings: Rec | undefined): FormTools => (data, _set, place) => {
  if (place !== 'bottom') return null
  const est = (data.items || []).reduce((s: number, i: Rec) => s + (Number(i.qty) || 0) * (Number(i.est_price) || 0), 0)
  const chosen = (data.quotations || []).find((q: Rec) => q.chosen)
  const value = Math.max(est, Number(chosen?.amount) || 0)
  const two = Number(settings?.two_quotes_from ?? 10_000_000), three = Number(settings?.three_quotes_from ?? 50_000_000)
  const needed = value >= three ? 3 : value >= two ? 2 : 1
  const got = (data.quotations || []).filter((q: Rec) => q.amount !== '' && q.amount !== null && q.amount !== undefined).length
  return (
    <p className={`notice ${got < needed ? 'warn' : ''}`}>
      {t('Estimated total {amount}; {n} quotations needed, {got} entered.', { amount: money(est), n: needed, got })}
    </p>
  )
}

export function ProcurementPage({ intent }: { intent?: Intent }) {
  const { email } = useNav()
  const { data: states } = useLive<ProcurementState[]>('/api/erp/ops/procurement-status')
  const settings = useList('ops_settings')
  const tools = useMemo(() => procurementTools(settings?.[0]), [settings])
  const active = (states || []).filter(s => !['paid', 'cancelled'].includes(s.stage))
  return (
    <RecordsPage entityName="procurements" openId={intent?.open} startNew={intent?.newWith}
      description={t('Purchase request, quotation comparison and approval, then purchase orders, goods receipt and the vendor invoice.')}
      defaults={{ date: todayIso(), requester: email, cost_centre: 'project', coi_by: email, coi_date: todayIso() }}
      columns={['number', 'title', 'date', 'requester', 'approved_amount', 'wf_status', 'warning_count']}
      toolbar={active.length > 0 ? <StagePipeline states={active} /> : null}
      formLayout={{
        first: ['title', 'date', 'requester', 'cost_centre', 'project_id', 'needed_by', 'items', 'budget', 'quotations', 'selection_reason', 'coi_status'],
        groups: [
          { title: 'Fewer quotations than required', fields: ['exception_reason'] },
          { title: 'Conflict of interest', fields: ['coi_details', 'coi_mitigation', 'coi_by', 'coi_date'] },
        ],
        hide: d => d.coi_status === 'declared' ? [] : ['coi_details', 'coi_mitigation'],
      }}
      formTools={tools}
      extra={r => <ProcurementCard record={r} states={states} />}
      hideInView={r => ['warning_count', 'est_total', 'quote_count', 'required_quotes', 'lowest_amount', 'chosen_vendor_id', 'chosen_vendor', 'approved_amount', 'chosen_vendor_status',
        ...(r.quotations || []).some((q: Rec) => q.amount !== null && q.amount !== undefined && q.amount !== '') ? ['quotations'] : [], ...(r.cancelled ? [] : ['cancelled'])]} />
  )
}

// ---------------------------------------------------------------------------
// Purchase orders: goods receipt and vendor invoice
// ---------------------------------------------------------------------------

function ReceiptProgress({ record }: { record: Rec }) {
  const items: Rec[] = record.items || []
  const got = (n: number) => (record.receipts || []).filter((r: Rec) => Number(r.line) === n && r.condition !== 'damaged').reduce((s: number, r: Rec) => s + (Number(r.qty) || 0), 0)
  return (
    <>
      <Checks record={record} />
      <div className="kpis" style={{ margin: '.75rem 0' }}>
        <Kpi label={t('Total')} value={money(record.total)} moneyValue />
        <Kpi label={t('Received (%)')} value={`${number(record.received_pct ?? 0)} %`} />
        <Kpi label={t('Vendor invoice')} value={record.invoice_amount ? money(record.invoice_amount) : '–'} moneyValue sub={record.paid_date ? t('paid on {d}', { d: formatDate(record.paid_date) }) : record.invoice_due ? t('due {d}', { d: formatDate(record.invoice_due) }) : undefined} />
      </div>
      {items.length > 0 && (
        <section className="hub-section">
          <div className="hub-head"><h3>{t('Goods receipt per item')}</h3></div>
          <ScrollTable>
            <table className="data-table">
              <thead><tr><th>{t('PO item no.')}</th><th>{t('Item')}</th><th className="num">{t('Ordered')}</th><th className="num">{t('Received')}</th><th className="num">{t('Not yet received')}</th></tr></thead>
              <tbody>
                {items.map((i, n) => {
                  const r = got(n + 1)
                  const left = Math.max(0, (Number(i.qty) || 0) - r)
                  return <tr key={n}><td>{n + 1}</td><td>{i.description}</td><td className="num">{number(i.qty)} {i.unit}</td><td className="num">{number(r)}</td><td className="num">{left > 0 ? <span className="status warn">{number(left)}</span> : <Icon name="check" />}</td></tr>
                })}
              </tbody>
            </table>
          </ScrollTable>
          <p className="help">{t('Each goods receipt row names the PO item number it delivers; damaged or rejected goods do not count.')}</p>
        </section>
      )}
    </>
  )
}

export function PurchaseOrdersPage({ intent }: { intent?: Intent }) {
  return (
    <RecordsPage entityName="purchase_orders" openId={intent?.open} startNew={intent?.newWith}
      description={t('Orders to vendors from approved procurement cards, with goods received and the vendor invoice (three-way match).')}
      defaults={{ date: todayIso(), status: 'draft', tax_pct: 11 }}
      columns={['number', 'procurement_id', 'vendor_id', 'date', 'total', 'progress', 'warning_count']}
      formLayout={{
        first: ['procurement_id', 'vendor_id', 'date', 'status', 'items', 'tax_pct', 'delivery_date', 'delivery_to', 'terms', 'receipts'],
        groups: [{ title: 'Vendor invoice', fields: ['invoice_no', 'invoice_date', 'invoice_amount', 'invoice_due', 'paid_date'] }],
      }}
      extra={r => <ReceiptProgress record={r} />}
      hideInView={['warning_count', 'subtotal', 'tax', 'total', 'received_pct']} />
  )
}

// ---------------------------------------------------------------------------
// Fixed asset card
// ---------------------------------------------------------------------------

type AssetGroups = { groups: Record<string, { life_years: number, straight_line_pct: number, declining_pct: number | null }>, suggested: Record<string, string> }

function AssetSchedule({ record }: { record: Rec }) {
  const [asOf, setAsOf] = useState(todayIso())
  const path = asOf ? `/api/erp/ops/assets/${encodeURIComponent(record.id)}/schedule?as_of=${asOf}` : null
  const { data, error } = useLive<CalcResult>(path, record.updated_at)
  const equipment = (useList('equipment') || []).filter(e => e.asset_id === record.id)
  const status = useOption('fixed_assets', 'asset_status')
  return (
    <section className="card ops-live">
      <div className="ops-live-head">
        <div>
          <h3 className="card-title">{t('Depreciation')}</h3>
          <Tone value={record.asset_status} label={status(record.asset_status)} />
          {equipment.length > 0 && <p className="help">{t('Equipment')}: {equipment.map(e => `${e.code} ${e.name}`).join(', ')}</p>}
        </div>
        <div className="field ops-asof">
          <label htmlFor="ops-asof">{t('Values as of')}</label>
          <DateInput id="ops-asof" value={asOf} onChange={setAsOf} />
        </div>
      </div>
      {error && <p className="notice error">{error}</p>}
      <ResultView result={data} />
    </section>
  )
}

const assetTools = (groups: AssetGroups | null): FormTools => (data, setData, place) => {
  if (place !== 'top' || !groups || !data.category) return null
  const key = groups.suggested[data.category]
  const g = key ? groups.groups[key] : null
  if (!key || !g) return null
  const text = key === 'none' ? t('Suggested tax group for this category: not depreciated (land).')
    : g.declining_pct ? t('Suggested tax group for this category: {g}; straight line {sl}% or declining balance {db}% a year.', {
      g: t(TAX_GROUP_LABEL[key] || key), sl: number(g.straight_line_pct), db: number(g.declining_pct) })
      : t('Suggested tax group for this category: {g}; straight line {sl}% a year.', { g: t(TAX_GROUP_LABEL[key] || key), sl: number(g.straight_line_pct) })
  return (
    <div className="notice ops-suggest">
      <span>{text} {t('Confirm the group with the tax adviser.')}</span>
      {data.tax_group !== key && <button type="button" className="small" onClick={() => setData(prev => ({ ...prev, tax_group: key, ...(key.startsWith('building') ? { tax_method: 'straight_line' } : {}) }))}>{t('Use this group')}</button>}
    </div>
  )
}

const TAX_GROUP_LABEL: Record<string, string> = {
  g1: 'Non-building group 1 (4 years)', g2: 'Non-building group 2 (8 years)', g3: 'Non-building group 3 (16 years)', g4: 'Non-building group 4 (20 years)',
  building_permanent: 'Permanent building (20 years)', building_nonpermanent: 'Non-permanent building (10 years)', none: 'Not depreciated (land)',
}

export function FixedAssetsPage({ intent }: { intent?: Intent }) {
  const { data: groups } = useLive<AssetGroups>('/api/erp/ops/asset-groups')
  const rows = useList('fixed_assets')
  const tools = useMemo(() => assetTools(groups), [groups])
  const held = (rows || []).filter(a => a.asset_status !== 'disposed')
  const sum = (k: string) => held.reduce((s, a) => s + (Number(a[k]) || 0), 0)
  return (
    <RecordsPage entityName="fixed_assets" openId={intent?.open} startNew={intent?.newWith}
      description={t('Fixed asset cards with tax depreciation (PMK 72/2023) and book depreciation (PSAK 216), impairment review (PSAK 236), book value and disposals.')}
      defaults={{ tax_method: 'straight_line', book_method: 'same_as_tax' }}
      toolbar={!intent?.open && held.length > 0 ? (
        <div className="kpis" style={{ marginBottom: '1rem' }}>
          <Kpi label={t('Assets held')} value={held.length} />
          <Kpi label={t('Acquisition cost')} value={money(sum('cost'))} moneyValue />
          <Kpi label={t('Accumulated depreciation (books)')} value={money(sum('accumulated_book'))} moneyValue />
          <Kpi label={t('Book value')} value={money(sum('book_value'))} moneyValue sub={t('as last saved')} />
        </div>
      ) : null}
      formLayout={{
        first: ['code', 'name', 'category', 'acquisition_date', 'cost', 'tax_group', 'tax_method', 'book_method', 'book_life_years', 'residual_value'],
        groups: [
          { title: 'Location and purchase', fields: ['location', 'custodian', 'vendor_id', 'procurement_id', 'invoice_ref'] },
          { title: 'Disposal', fields: ['disposal_date', 'disposal_type', 'disposal_proceeds'] },
          { title: 'Impairment (PSAK 236)', fields: ['impairment_review_date', 'impairment_indicators', 'recoverable_amount', 'impairment_note'] },
        ],
        hide: d => [...(d.book_method === 'same_as_tax' || d.book_method === 'none' ? ['book_life_years', 'residual_value'] : [])],
      }}
      formTools={tools}
      extra={r => <AssetSchedule record={r} />}
      hideInView={['tax_life_years', 'tax_rate_pct', 'book_life', 'dep_year_book', 'accumulated_book', 'book_value', 'dep_year_tax', 'accumulated_tax',
        'tax_value', 'gain_loss_book', 'gain_loss_tax', 'asset_status', 'as_of']} />
  )
}

// ---------------------------------------------------------------------------
// Work plan & performance card
// ---------------------------------------------------------------------------

const performanceTools: FormTools = (data, _set, place) => {
  if (place !== 'bottom') return null
  const total = (rows: Rec[] | undefined) => (rows || []).reduce((s, r) => s + (Number(r.weight) || 0), 0)
  const kw = total(data.kpis), cw = total(data.competencies)
  const off = (n: number, rows: Rec[] | undefined) => (rows || []).length > 0 && Math.abs(n - 100) > 0.01
  return (
    <p className={`notice ${off(kw, data.kpis) || off(cw, data.competencies) ? 'warn' : 'ok'}`}>
      {t('KPI weights total {k}%; competency weights total {c}%. Each must be 100%.', { k: number(kw), c: number(cw) })}
    </p>
  )
}

function Scorecard({ record }: { record: Rec }) {
  const rating = useOption('performance_cards', 'rating')
  return (
    <section className="card ops-live">
      <div className="ops-live-head">
        <h3 className="card-title">{t('Scorecard')}</h3>
        {record.rating ? <Tone value={record.rating} label={rating(record.rating)} /> : <span className="muted small">{t('Final score once every KPI has an actual and every competency a score.')}</span>}
      </div>
      <ResultView result={record.scorecard} />
    </section>
  )
}

export function PerformancePage({ intent }: { intent?: Intent }) {
  const { email } = useNav()
  const year = todayIso().slice(0, 4)
  return (
    <RecordsPage entityName="performance_cards" openId={intent?.open} startNew={intent?.newWith}
      description={t('Individual work plan with KPI targets and weights, results, behaviour scores and the final rating; reviewed by the superior and approved.')}
      defaults={{ employee: email, period_type: 'annual', period_start: `${year}-01-01`, period_end: `${year}-12-31`, kpi_share_pct: 70, cap_pct: 120 }}
      columns={['title', 'position', 'period_start', 'final_score', 'rating', 'wf_status']}
      formLayout={{
        first: ['employee', 'employee_name', 'position', 'unit', 'superior', 'period_type', 'period_start', 'period_end', 'kpis', 'competencies'],
        groups: [{ title: 'Score settings', fields: ['kpi_share_pct', 'cap_pct'] }],
      }}
      formTools={performanceTools}
      extra={r => <Scorecard record={r} />}
      hideInView={['kpi_weight_total', 'competency_weight_total', 'kpi_score', 'competency_score', 'final_score', 'rating', 'title']} />
  )
}

// ---------------------------------------------------------------------------
// Laboratory quality (ISO/IEC 17025): sample receipts, nonconformities, checks on a lab test
// ---------------------------------------------------------------------------

type CalibrationCheck = { equipment_id: string, code: string, name: string, status: string, last: string | null, due: string | null }

const CAL_STATUS: Record<string, string> = {
  ok: 'In calibration', overdue: 'Calibration overdue', failed: 'Failed calibration', not_calibrated: 'No calibration on record', not_required: 'No calibration needed',
}

/** Fields of a lab test added for ISO/IEC 17025 (for the form layout of the laboratory page). */
export const LAB_QUALITY_FIELDS = ['receipt_id', 'equipment_used', 'uncertainty', 'authorised']
/** Fields shown by LabQualityPanel instead of the plain record view. */
export const LAB_QUALITY_HIDDEN = ['warning_count', 'report_disclaimer', 'result_status', 'authorised', 'authorised_by', 'authorised_at', 'results_entered_by']

const NC_LAYOUT: FormLayout = {
  first: ['date', 'source', 'description', 'risk', 'lab_test_id', 'equipment_id', 'project_id', 'detected_by'],
  groups: [
    { title: 'Control and correction', fields: ['correction', 'work_halted', 'impact', 'decision', 'customer_action', 'resumption_authorised_by', 'resumed_on'] },
    { title: 'Corrective action', fields: ['corrective_action_needed', 'root_cause', 'corrective_action', 'action_owner', 'action_due', 'action_done_on',
      'effectiveness_on', 'effective', 'effectiveness_note', 'risks_updated', 'system_change'] },
    { title: 'Closure', fields: ['closed_on'] },
  ],
  hide: d => [
    ...(d.work_halted ? [] : ['resumption_authorised_by', 'resumed_on']),
    ...(d.corrective_action_needed === 'yes' ? [] : ['root_cause', 'corrective_action', 'action_owner', 'action_due', 'action_done_on',
      'effectiveness_on', 'effective', 'effectiveness_note', 'risks_updated', 'system_change']),
  ],
}

/** Release status, report disclaimer, calibration of the equipment used and nonconformities of one lab test. */
export function LabQualityPanel({ record }: { record: Rec }) {
  const { email } = useNav()
  const schemas = useSchemas()
  const release = useOption('lab_tests', 'result_status')
  const stage = useOption('nonconformities', 'stage')
  const deviation = useOption('sample_receipts', 'deviations')
  const [round, setRound] = useState(0)
  const [raising, setRaising] = useState(false)
  const ncs = (useRecords(schemas?.nonconformities?.can_read ? 'nonconformities' : null, round) || []).filter(n => n.lab_test_id === record.id)
  const receipts = useList(schemas?.sample_receipts?.can_read ? 'sample_receipts' : null)
  const receipt = receipts?.find(r => r.id === record.receipt_id)
  const checks: CalibrationCheck[] = Array.isArray(record.calibration_check) ? record.calibration_check : []
  const canRaise = !!schemas?.nonconformities?.can_create
  return (
    <section className="card ops-live">
      <div className="ops-live-head">
        <div>
          <h3 className="card-title">{t('Quality checks')}</h3>
          {record.result_status && <Tone value={record.result_status} label={release(record.result_status)} />}
          {record.authorised_by && <p className="help">{t('Authorised by {who} on {d}', { who: record.authorised_by, d: formatDate(record.authorised_at) })}</p>}
          {record.results_entered_by && <p className="help">{t('Results entered by {who}', { who: record.results_entered_by })}</p>}
          {receipt && <p className="help">{t('Sample receipt {n}, received {d}', { n: receipt.number, d: formatDate(receipt.received_on) })}</p>}
        </div>
        {canRaise && !raising && <button type="button" className="small" onClick={() => setRaising(true)}><Icon name="plus" />{t('Raise nonconformity')}</button>}
      </div>
      <Checks record={record} />
      {record.report_disclaimer && <p className="notice warn"><strong>{t('Disclaimer for the report')}:</strong> {receipt
        ? t('Sample received with deviations from the specified conditions ({detail}); the customer asked for testing. Results may be affected.', {
          detail: [...(receipt.deviations || []).map((d: string) => deviation(d)), receipt.condition_note].filter(Boolean).join('; ') })
        : record.report_disclaimer}</p>}
      {checks.length > 0 && (
        <ScrollTable>
          <table className="data-table">
            <thead><tr><th>{t('Equipment used')}</th><th>{t('Calibration on the test date')}</th><th>{t('Last calibration')}</th><th>{t('Due')}</th></tr></thead>
            <tbody>
              {checks.map(c => (
                <tr key={c.equipment_id}>
                  <td><strong>{c.code}</strong><div className="bh-sub">{c.name}</div></td>
                  <td><Tone value={c.status} label={t(CAL_STATUS[c.status] || c.status)} /></td>
                  <td className="nowrap">{c.last ? formatDate(c.last) : '–'}</td><td className="nowrap">{c.due ? formatDate(c.due) : '–'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </ScrollTable>
      )}
      {raising && (
        <InlineForm entityName="nonconformities" title={t('Raise nonconformity')} layout={NC_LAYOUT}
          defaults={{ date: todayIso(), source: checks.some(c => c.status !== 'ok' && c.status !== 'not_required') ? 'equipment' : 'testing',
            risk: 'medium', lab_test_id: record.id, project_id: record.project_id || '', detected_by: email }}
          onDone={saved => { setRaising(false); if (saved) setRound(n => n + 1) }} />
      )}
      {ncs.length > 0 && (
        <>
          <h4 className="ops-subhead">{t('Nonconformities')}</h4>
          <ul className="ops-plain">
            {ncs.map(n => <li key={n.id}><strong>{n.number}</strong> {n.description} · <Tone value={n.stage} label={stage(n.stage)} /></li>)}
          </ul>
        </>
      )}
    </section>
  )
}

const NC_STEPS: Array<[string, string]> = [['open', 'Open'], ['correction', 'Correction'], ['corrective_action', 'Corrective action'], ['verification', 'Effectiveness check'], ['closed', 'Closed']]

export function NonconformitiesPage({ intent, switcher }: { intent?: Intent, switcher?: ReactNode }) {
  const { email } = useNav()
  return (
    <RecordsPage entityName="nonconformities" openId={intent?.open} startNew={intent?.newWith}
      description={t('Work or results that do not conform: immediate correction, impact on earlier results, decision, customer notice, and corrective action checked for effectiveness (ISO/IEC 17025 7.10 and 8.7).')}
      defaults={{ date: todayIso(), risk: 'medium', detected_by: email }}
      columns={['number', 'date', 'source', 'risk', 'stage', 'closed_on', 'warning_count']}
      toolbar={switcher}
      formLayout={NC_LAYOUT}
      extra={r => <><Steps steps={NC_STEPS} current={r.stage} label={t('Stage')} /><Checks record={r} /></>}
      hideInView={['warning_count', 'stage']} />
  )
}

const RECEIPT_LAYOUT: FormLayout = {
  first: ['received_on', 'borehole_id', 'sample_ref', 'depth_top', 'depth_base', 'sample_type', 'condition', 'deviations', 'condition_note', 'storage_location'],
  groups: [
    { title: 'Deviation', fields: ['customer_consulted_on', 'customer_instruction', 'decision'] },
    { title: 'Receipt details', fields: ['time', 'received_by', 'delivered_by', 'project_id', 'storage_condition'] },
    { title: 'Chain of custody', fields: ['custody'] },
    { title: 'Retention and disposal', fields: ['retain_until', 'disposed_on', 'disposal_method', 'disposal_by'] },
  ],
  hide: d => d.condition === 'deviation' ? [] : ['deviations', 'customer_consulted_on', 'customer_instruction', 'decision'],
}

function ReceiptSummary({ record }: { record: Rec }) {
  const tests = (useList('lab_tests') || []).filter(x => x.receipt_id === record.id)
  const testType = useOption('lab_tests', 'test_type')
  const status = useOption('lab_tests', 'status')
  return (
    <>
      <Checks record={record} />
      <div className="kpis" style={{ margin: '.75rem 0' }}>
        <Kpi label={t('Now held by')} value={record.current_holder || '–'} sub={record.current_location || undefined} />
        <Kpi label={t('Days in store')} value={number(record.days_in_store)} sub={record.retain_until ? t('keep until {d}', { d: formatDate(record.retain_until) }) : undefined} />
        <Kpi label={t('Laboratory tests')} value={tests.length} />
      </div>
      {tests.length > 0 && (
        <ul className="ops-plain">
          {tests.map(x => <li key={x.id}>{testType(x.test_type)} · <Tone value={x.status} label={status(x.status)} /></li>)}
        </ul>
      )}
    </>
  )
}

export function SampleReceiptsPage({ intent, switcher }: { intent?: Intent, switcher?: ReactNode }) {
  const { email } = useNav()
  return (
    <RecordsPage entityName="sample_receipts" openId={intent?.open} startNew={intent?.newWith}
      description={t('Samples arriving at the laboratory: condition on arrival, deviations and the customer’s decision, storage, chain of custody, retention and disposal (ISO/IEC 17025 7.4).')}
      defaults={{ received_on: todayIso(), condition: 'as_specified', received_by: email }}
      columns={['number', 'received_on', 'borehole_id', 'sample_ref', 'condition', 'receipt_status', 'warning_count']}
      toolbar={switcher}
      formLayout={RECEIPT_LAYOUT}
      extra={r => <ReceiptSummary record={r} />}
      hideInView={['warning_count', 'custody']} />
  )
}

/** Receipt of one sample from the sample register, filled in without leaving the register. */
export function SampleReceiptForm({ sample, project, onDone }: {
  sample: { borehole_id: string, ref: string, top: number | null, base: number | null, type: string }, project?: string, onDone: (saved: Rec | null) => void
}) {
  const { email } = useNav()
  return (
    <InlineForm entityName="sample_receipts" title={t('Sample receipt: {s}', { s: `${sample.borehole_id} ${sample.ref}` })} layout={RECEIPT_LAYOUT}
      defaults={{ received_on: todayIso(), condition: 'as_specified', received_by: email, borehole_id: sample.borehole_id,
        sample_ref: sample.ref || `${sample.type}-${sample.top}`, depth_top: sample.top ?? '', depth_base: sample.base ?? '', project_id: project || '' }}
      onDone={onDone} />
  )
}

// ---------------------------------------------------------------------------
// Operations settings
// ---------------------------------------------------------------------------

export function OpsSettingsPage() {
  const schemas = useSchemas()
  const rows = useList('ops_settings')
  const [saved, setSaved] = useState(false)
  const entity = schemas?.ops_settings
  if (!entity || !rows) return <p className="muted">{t('Loading…')}</p>
  return (
    <div style={{ maxWidth: 820 }}>
      <PageHead title={t('Operations settings')} description={t('Limits for quotations and work orders, when due service and calibration are flagged, vendor evaluation weights and limits, and the rule for unauthorised laboratory results.')} />
      {saved && <p className="notice ok" role="status">{t('Saved.')}</p>}
      {entity.can_create ? (
        <RecordForm entity={entity} record={rows[0] || null} hide={['name']} onSaved={() => { invalidate('ops_settings'); setSaved(true) }} />
      ) : rows[0] ? <section className="card"><RecordFields entity={entity} record={rows[0]} hide={['name']} /></section> : <p className="muted">{t('Default limits are used.')}</p>}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Operations overview for the management dashboard (GET /api/erp/ops/overview)
// ---------------------------------------------------------------------------

export type OpsOverview = {
  as_of: string
  equipment: { total: number, by_status: Record<string, number>, utilisation_pct: number | null } | null
  maintenance: {
    calibration_overdue: number, calibration_due_soon: number, service_overdue: number, service_due_soon: number,
    open_work_orders: number, open_by_type: Record<string, number>, urgent_open: number, downtime_days_year: number, cost_year: number,
    last_12_months?: { availability_pct: number | null, mtbf_days: number | null, mttr_days: number | null, failures: number,
      preventive_pct: number | null, pm_compliance_pct: number | null, pm_late: number },
  } | null
  procurement: {
    by_stage: Record<string, number>, in_progress: number, waiting_approval: number, approval_value: number,
    spend_year: number | null, unpaid_invoices: number | null,
    vendors?: { active: number, approved: number, conditional: number, blocked: number, not_evaluated: number, reevaluation_due: number },
  } | null
  assets: {
    count: number, cost: number, accumulated_book: number, book_value: number, tax_value: number, depreciation_year_book: number,
    fully_depreciated: number, impairment_indicated?: number, by_category: Record<string, { count: number, cost: number, book_value: number }>,
  } | null
  performance: { cards: number, by_state: Record<string, number>, by_rating: Record<string, number>, average_score: number | null, average_score_approved: number | null } | null
  laboratory?: {
    tests_open: number, awaiting_authorisation: number, authorised: number, calibration_issues: number, nonconformities_open: number,
    corrective_actions_overdue: number, samples_on_hold: number, samples_past_retention: number,
  } | null
}

/** The operations part of the management dashboard; `onOpen` goes to a page by its suggested tab key. */
export function OpsOverviewPanel({ onOpen }: { onOpen?: (tab: string) => void }) {
  const { data, error } = useLive<OpsOverview>('/api/erp/ops/overview')
  const statusLabel = useOption('equipment', 'status')
  if (error) return <p className="notice error">{error}</p>
  if (!data) return <p className="muted">{t('Loading…')}</p>
  const link = (tab: string, label: string) => onOpen ? <button type="button" className="small quiet" onClick={() => onOpen(tab)}>{label}</button> : null
  return (
    <div className="ops-overview">
      {data.equipment && data.maintenance && (
        <section className="hub-section">
          <div className="hub-head"><h3>{t('Equipment & maintenance')}</h3>{link('equipment', t('Equipment register'))}</div>
          <div className="kpis">
            <Kpi label={t('Equipment')} value={data.equipment.total} sub={Object.entries(data.equipment.by_status).map(([k, n]) => `${statusLabel(k)} ${n}`).join(' · ')} />
            <Kpi label={t('Utilisation')} value={data.equipment.utilisation_pct === null ? '–' : `${number(data.equipment.utilisation_pct)} %`} sub={t('share mobilised')} />
            <Kpi label={t('Calibration overdue')} value={data.maintenance.calibration_overdue} sub={t('{n} due soon', { n: data.maintenance.calibration_due_soon })} />
            <Kpi label={t('Service overdue')} value={data.maintenance.service_overdue} sub={t('{n} due soon', { n: data.maintenance.service_due_soon })} />
            <Kpi label={t('Open work orders')} value={data.maintenance.open_work_orders} sub={data.maintenance.urgent_open ? t('{n} urgent', { n: data.maintenance.urgent_open }) : undefined} />
            <Kpi label={t('Downtime this year (days)')} value={number(data.maintenance.downtime_days_year)} sub={t('maintenance cost {amount}', { amount: money(data.maintenance.cost_year) })} />
          </div>
          {data.maintenance.last_12_months && (
            <div className="kpis" style={{ marginTop: '.5rem' }}>
              <Kpi label={t('Availability')} value={pct(data.maintenance.last_12_months.availability_pct)} sub={t('last 12 months')} />
              <Kpi label="MTBF" value={days(data.maintenance.last_12_months.mtbf_days)} sub={t('{n} failures', { n: data.maintenance.last_12_months.failures })} />
              <Kpi label="MTTR" value={days(data.maintenance.last_12_months.mttr_days)} />
              <Kpi label={t('Preventive share')} value={pct(data.maintenance.last_12_months.preventive_pct)} />
              <Kpi label={t('PM compliance')} value={pct(data.maintenance.last_12_months.pm_compliance_pct)} sub={data.maintenance.last_12_months.pm_late ? t('{n} late', { n: data.maintenance.last_12_months.pm_late }) : undefined} />
            </div>
          )}
        </section>
      )}
      {data.procurement && (
        <section className="hub-section">
          <div className="hub-head"><h3>{t('Procurement')}</h3>{link('procurements', t('Procurement cards'))}</div>
          <div className="kpis">
            <Kpi label={t('Procurement in progress')} value={data.procurement.in_progress} />
            <Kpi label={t('Waiting for approval')} value={data.procurement.waiting_approval} sub={money(data.procurement.approval_value)} />
            {data.procurement.spend_year !== null && <Kpi label={t('Ordered this year')} value={money(data.procurement.spend_year)} moneyValue />}
            {data.procurement.unpaid_invoices !== null && <Kpi label={t('Vendor invoices unpaid')} value={money(data.procurement.unpaid_invoices)} moneyValue />}
            {data.procurement.vendors && <Kpi label={t('Vendors blocked')} value={data.procurement.vendors.blocked}
              sub={t('{a} conditional, {b} re-evaluation due', { a: data.procurement.vendors.conditional, b: data.procurement.vendors.reevaluation_due })} />}
          </div>
        </section>
      )}
      {data.assets && (
        <section className="hub-section">
          <div className="hub-head"><h3>{t('Fixed assets')}</h3>{link('fixed_assets', t('Fixed assets'))}</div>
          <div className="kpis">
            <Kpi label={t('Assets held')} value={data.assets.count} sub={data.assets.fully_depreciated ? t('{n} fully depreciated', { n: data.assets.fully_depreciated }) : undefined} />
            <Kpi label={t('Acquisition cost')} value={money(data.assets.cost)} moneyValue />
            <Kpi label={t('Accumulated depreciation (books)')} value={money(data.assets.accumulated_book)} moneyValue />
            <Kpi label={t('Book value')} value={money(data.assets.book_value)} moneyValue sub={t('tax book value {amount}', { amount: money(data.assets.tax_value) })} />
            <Kpi label={t('Depreciation this year (books)')} value={money(data.assets.depreciation_year_book)} moneyValue
              sub={data.assets.impairment_indicated ? t('{n} with signs of impairment', { n: data.assets.impairment_indicated }) : undefined} />
          </div>
        </section>
      )}
      {data.laboratory && (
        <section className="hub-section">
          <div className="hub-head"><h3>{t('Laboratory quality')}</h3>{link('lab', t('Laboratory tests'))}</div>
          <div className="kpis">
            <Kpi label={t('Awaiting authorisation')} value={data.laboratory.awaiting_authorisation} sub={t('{n} tests in progress', { n: data.laboratory.tests_open })} />
            <Kpi label={t('Tests with calibration issues')} value={data.laboratory.calibration_issues} />
            <Kpi label={t('Open nonconformities')} value={data.laboratory.nonconformities_open}
              sub={data.laboratory.corrective_actions_overdue ? t('{n} corrective actions overdue', { n: data.laboratory.corrective_actions_overdue }) : undefined} />
            <Kpi label={t('Samples on hold')} value={data.laboratory.samples_on_hold}
              sub={data.laboratory.samples_past_retention ? t('{n} past retention', { n: data.laboratory.samples_past_retention }) : undefined} />
          </div>
        </section>
      )}
      {data.performance && data.performance.cards > 0 && (
        <section className="hub-section">
          <div className="hub-head"><h3>{t('Performance cards')}</h3>{link('performance', t('Work plan & performance cards'))}</div>
          <div className="kpis">
            <Kpi label={t('Cards')} value={data.performance.cards} sub={t('{n} approved', { n: data.performance.by_state.approved || 0 })} />
            <Kpi label={t('Average final score')} value={data.performance.average_score === null ? '–' : `${number(data.performance.average_score)} %`} />
            <Kpi label={t('Waiting for review or approval')} value={(data.performance.by_state.submitted || 0) + (data.performance.by_state.reviewed || 0)} />
          </div>
        </section>
      )}
    </div>
  )
}
