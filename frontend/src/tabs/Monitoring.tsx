/**
 * Monitoring instruments (worksheet list 03.11): piezometers, groundwater wells, inclinometers,
 * settlement plates and extensometers with their readings, alarm state and charts. Readings can be
 * pasted from Excel; dates in day/month/year, ISO or Excel serial form are understood.
 */
import { ReactNode, useMemo, useState } from 'react'
import { type Rec } from '../api'
import { t } from '../i18n'
import { useNav, type Intent } from '../nav'
import { RecordsPage, number, optionLabel, useList, useSchemas, type FormLayout } from '../records'
import { formatDate, todayIso } from '../ui'
import { ResultView } from '../worksheets'
import './Monitoring.css'

const TONE: Record<string, string> = { normal: 'ok', alert: 'warn', action: 'bad', no_data: '' }
const STATES: Array<[string, string]> = [['all', 'All'], ['action', 'Action'], ['alert', 'Alert'], ['normal', 'Normal'], ['no_data', 'No readings']]
const STALE_DAYS = 14

const LAYOUT: FormLayout = {
  first: ['code', 'type', 'project_id', 'borehole_id', 'location', 'status'],
  groups: [{ title: 'Installation', fields: ['latitude', 'longitude', 'elevation', 'install_date', 'depth', 'unit', 'reading_is_depth'] }],
  hide: data => data.type === 'inclinometer' ? ['readings', 'reading_is_depth', 'alarm_on'] : ['profile', 'incl_input'],
}

const daysSince = (iso?: string) => {
  if (!iso) return null
  const then = Date.parse(iso.slice(0, 10)), now = Date.parse(todayIso())
  return Number.isFinite(then) && Number.isFinite(now) ? Math.round((now - then) / 86400000) : null
}

// ---------------------------------------------------------------------------
// Paste from Excel
// ---------------------------------------------------------------------------

const MONTHS: Record<string, number> = {
  jan: 1, feb: 2, mar: 3, apr: 4, may: 5, mei: 5, jun: 6, jul: 7, aug: 8, agu: 8, agt: 8, sep: 9, oct: 10, okt: 10, nov: 11, dec: 12, des: 12,
}
const pad = (n: number) => String(n).padStart(2, '0')
const fullYear = (y: number) => (y < 100 ? 2000 + y : y)

/** A date cell from Excel or typed: 2026-10-05, 05/10/2026, 5-10-26, 5 Okt 2026, 5-Oct-26 or an Excel serial number. */
export function parseDateCell(text: string): string | null {
  const s = text.trim()
  let m = /^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})/.exec(s)
  let y: number, mo: number, d: number
  if (m) { y = +m[1]; mo = +m[2]; d = +m[3] }
  else if ((m = /^(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})/.exec(s))) { d = +m[1]; mo = +m[2]; y = fullYear(+m[3]) }
  else if ((m = /^(\d{1,2})[\s-]+([A-Za-z]{3})[A-Za-z]*[\s-]+(\d{2,4})/.exec(s)) && MONTHS[m[2].toLowerCase()]) { d = +m[1]; mo = MONTHS[m[2].toLowerCase()]; y = fullYear(+m[3]) }
  else if (/^\d{5}(\.\d+)?$/.test(s)) {
    // Excel serial date (1900 system): day 25569 is 1970-01-01.
    const ms = (Math.floor(Number(s)) - 25569) * 86400000
    const dt = new Date(ms)
    y = dt.getUTCFullYear(); mo = dt.getUTCMonth() + 1; d = dt.getUTCDate()
  } else return null
  if (mo < 1 || mo > 12 || d < 1 || d > 31 || y < 1900 || y > 2200) return null
  const iso = `${y}-${pad(mo)}-${pad(d)}`
  return new Date(iso + 'T00:00:00Z').getUTCDate() === d ? iso : null
}

const parseNumberCell = (text: string | undefined) => {
  if (text === undefined) return null
  let s = text.trim().replace(/\s/g, '')
  if (!s) return null
  if (/^-?\d{1,3}(\.\d{3})+,\d+$/.test(s)) s = s.replace(/\./g, '').replace(',', '.') // 1.234,5
  else if (/^-?\d+,\d+$/.test(s)) s = s.replace(',', '.')
  else s = s.replace(/,(?=\d{3}\b)/g, '')
  const v = Number(s)
  return Number.isFinite(v) ? v : null
}

type Parsed = { rows: Array<Record<string, any>>, errors: string[] }

export function parseReadings(text: string, incline: boolean, surveyDate: string): Parsed {
  const rows: Array<Record<string, any>> = []
  const errors: string[] = []
  const lines = text.split(/\r?\n/).map(l => l.trim()).filter(Boolean)
  lines.forEach((line, i) => {
    const cells = line.split(/\t|;/).map(c => c.trim())
    if (incline) {
      const withDate = !surveyDate
      const date = withDate ? parseDateCell(cells[0] || '') : surveyDate
      const [z, a, b] = (withDate ? cells.slice(1) : cells).map(parseNumberCell)
      if (!date || z === null) {
        if (i === 0) return // header row
        errors.push(t('Row {n}: date or depth not recognised', { n: i + 1 }))
        return
      }
      rows.push({ date, depth: z, a: a ?? '', b: b ?? '' })
    } else {
      const date = parseDateCell(cells[0] || '')
      const v = parseNumberCell(cells[1])
      if (!date || v === null) {
        if (i === 0) return
        errors.push(t('Row {n}: date or reading not recognised', { n: i + 1 }))
        return
      }
      rows.push({ date, value: v, note: (cells[2] || '').slice(0, 120) })
    }
  })
  return { rows, errors }
}

function PasteReadings({ data, setData }: { data: Record<string, any>, setData: (u: (p: Record<string, any>) => Record<string, any>) => void }) {
  const [open, setOpen] = useState(false)
  const [text, setText] = useState('')
  const [surveyDate, setSurveyDate] = useState('')
  const [message, setMessage] = useState<{ ok: boolean, text: string } | null>(null)
  const incline = data.type === 'inclinometer'
  if (!data.type) return null
  const field = incline ? 'profile' : 'readings'
  const apply = (replace: boolean) => {
    const { rows, errors } = parseReadings(text, incline, surveyDate)
    if (!rows.length) { setMessage({ ok: false, text: errors[0] || t('Nothing to add.') }); return }
    setData(prev => ({ ...prev, [field]: [...(replace ? [] : (prev[field] || [])), ...rows] }))
    setMessage({ ok: !errors.length, text: [t('{n} rows added.', { n: rows.length }), ...errors.slice(0, 5)].join(' ') })
    setText('')
  }
  return (
    <div className="ws-head mon-paste">
      <div style={{ flex: 1 }}>
        <strong>{t('Paste readings from Excel')}</strong>
        <p className="help" style={{ margin: '.2rem 0 0' }}>
          {incline ? t('Columns: date, depth (m), A (mm), B (mm). Or enter the survey date and paste depth, A, B.') : t('Columns: date, reading, note. Dates as 05/10/2026, 2026-10-05 or Excel dates; decimal comma or point.')}
        </p>
        {open && (
          <div className="mon-paste-body">
            {incline && (
              <div className="field" style={{ maxWidth: 240 }}>
                <label htmlFor="mon-survey">{t('Survey date')}</label>
                <input id="mon-survey" type="date" value={surveyDate} onChange={e => setSurveyDate(e.target.value)} />
              </div>
            )}
            <label className="sr-only" htmlFor="mon-paste">{t('Paste readings from Excel')}</label>
            <textarea id="mon-paste" rows={6} value={text} onChange={e => setText(e.target.value)}
              placeholder={incline ? '2026-10-05\t0.5\t3.2\t-0.4' : '05/10/2026\t2,45\t'} />
            <div className="actions">
              <button type="button" className="primary" disabled={!text.trim()} onClick={() => apply(false)}>{t('Add these rows')}</button>
              <button type="button" disabled={!text.trim()} onClick={() => apply(true)}>{t('Replace all readings')}</button>
            </div>
          </div>
        )}
        {message && <p className={`notice ${message.ok ? 'ok' : 'warn'}`} role="status">{message.text}</p>}
      </div>
      {!open && <div className="actions"><button type="button" onClick={() => setOpen(true)}>{t('Paste from Excel')}</button></div>}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

function AlarmChip({ value, label }: { value: string, label: string }) {
  return <span className={`status ${TONE[value] ?? ''}`}>{label}</span>
}

function InstrumentHead({ record, stateLabel }: { record: Rec, stateLabel: (v: string) => string }) {
  const age = daysSince(record.latest_date)
  const unit = record.type === 'inclinometer' ? 'mm' : (record.unit || '')
  return (
    <section className="card mon-head">
      <div className="mon-head-row">
        <AlarmChip value={record.alarm_state || 'no_data'} label={stateLabel(record.alarm_state || 'no_data')} />
        {age !== null && <span className={age > STALE_DAYS ? 'mon-stale' : 'muted small'}>
          {t('Last read {date}', { date: formatDate(record.latest_date) })} · {age > STALE_DAYS ? t('{n} days ago, read again', { n: age }) : t('{n} days ago', { n: age })}
        </span>}
        {(record.alert_level !== null && record.alert_level !== undefined) || (record.action_level !== null && record.action_level !== undefined) ? (
          <span className="muted small">{t('Alert level')} {number(record.alert_level)} · {t('Action level')} {number(record.action_level)}{unit ? ` ${unit}` : ''}</span>
        ) : null}
      </div>
      {record.results && Object.keys(record.results).length > 0
        ? <ResultView result={record.results} />
        : <p className="muted" style={{ marginBottom: 0 }}>{t('No readings yet. Edit the instrument to add or paste readings.')}</p>}
    </section>
  )
}

export function MonitoringPage({ intent }: { intent?: Intent }) {
  const schemas = useSchemas()
  const rows = useList('instruments')
  const stateField = schemas?.instruments?.fields.find(f => f.name === 'alarm_state')
  const stateLabel = (v: string) => (stateField ? optionLabel(stateField, v) : v)
  const [state, setState] = useState('all')
  const filter = useMemo(() => (r: Rec) => state === 'all' || (r.alarm_state || 'no_data') === state, [state])
  const counts = useMemo(() => {
    const c: Record<string, number> = { all: 0, action: 0, alert: 0, normal: 0, no_data: 0 }
    for (const r of rows || []) { c.all++; c[r.alarm_state || 'no_data'] = (c[r.alarm_state || 'no_data'] || 0) + 1 }
    return c
  }, [rows])
  const toolbar = (
    <div className="segmented mon-filter" role="group" aria-label={t('Alarm')}>
      {STATES.map(([k, l]) => (
        <button key={k} type="button" aria-pressed={state === k} onClick={() => setState(k)}>
          {k !== 'all' && <span className={`status ${TONE[k]}`} aria-hidden="true" />}{t(l)} <span className="count">{counts[k] ?? 0}</span>
        </button>
      ))}
    </div>
  )
  return (
    <RecordsPage entityName="instruments" openId={intent?.open} startNew={intent?.newWith} filter={filter}
      description={t('Piezometers, groundwater wells, inclinometers, settlement plates and extensometers: readings against time, change since the base reading and alarms.')}
      columns={['code', 'type', 'project_id', 'alarm_state', 'latest_date', 'latest_value']}
      formLayout={LAYOUT} toolbar={rows && rows.length > 0 ? toolbar : null}
      defaults={{ status: 'active', alarm_on: 'change', incl_input: 'cumulative' }}
      hideInView={r => ['results', 'summary', 'readings', 'profile', 'alarm_state', 'latest_date', 'latest_value', 'change', 'rate_per_day', 'max_change', 'reading_count',
        ...(r.type === 'inclinometer' ? ['reading_is_depth', 'alarm_on', 'unit'] : ['incl_input'])]}
      formTools={(data, setData, place) => place === 'top' ? <PasteReadings data={data} setData={setData} /> : null}
      extra={r => <InstrumentHead record={r} stateLabel={stateLabel} />} />
  )
}

// ---------------------------------------------------------------------------
// Management overview: instruments in alarm
// ---------------------------------------------------------------------------

export function MonitoringOverviewPanel({ onOpen }: { onOpen?: (id?: string) => void }) {
  const schemas = useSchemas()
  const readable = !!schemas?.instruments?.can_read
  const rows = useList(readable ? 'instruments' : null)
  const typeField = schemas?.instruments?.fields.find(f => f.name === 'type')
  const stateField = schemas?.instruments?.fields.find(f => f.name === 'alarm_state')
  if (!readable || !rows || !rows.length) return null
  const live = rows.filter(r => r.status !== 'abandoned')
  const action = live.filter(r => r.alarm_state === 'action')
  const alert = live.filter(r => r.alarm_state === 'alert')
  const stale = live.filter(r => (daysSince(r.latest_date) ?? 0) > STALE_DAYS)
  const list = [...action, ...alert]
  const link = (label: ReactNode, id?: string) => onOpen ? <button type="button" className="small quiet" onClick={() => onOpen(id)}>{label}</button> : null
  return (
    <section className="hub-section">
      <div className="hub-head"><h3>{t('Monitoring instruments')}</h3>{link(t('Open monitoring'))}</div>
      <div className="kpis">
        <div className="kpi"><h4>{t('Instruments')}</h4><p>{live.length}</p></div>
        <div className="kpi"><h4>{t('Action level reached')}</h4><p className={action.length ? 'mon-bad' : undefined}>{action.length}</p></div>
        <div className="kpi"><h4>{t('Alert level reached')}</h4><p className={alert.length ? 'mon-warn' : undefined}>{alert.length}</p></div>
        <div className="kpi"><h4>{t('Not read for {n} days', { n: STALE_DAYS })}</h4><p>{stale.length}</p></div>
      </div>
      {list.length > 0 && (
        <ul className="ws-list" style={{ marginTop: '.5rem' }}>
          {list.slice(0, 10).map(r => (
            <li key={r.id}>
              <span className="ws-no"><AlarmChip value={r.alarm_state} label={stateField ? optionLabel(stateField, r.alarm_state) : r.alarm_state} /></span>
              <div className="ws-main">
                <strong>{r.code}</strong>
                <span className="ws-std">{typeField ? optionLabel(typeField, r.type) : r.type} · {formatDate(r.latest_date)} · {number(r.latest_value)} {r.type === 'inclinometer' ? 'mm' : r.unit || ''}</span>
              </div>
              <div className="ws-side"><div className="ws-actions">{link(t('Open'), r.id)}</div></div>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

export function MonitoringOverview() {
  const { go } = useNav()
  return <MonitoringOverviewPanel onOpen={id => go('monitoring', id ? { open: id } : undefined)} />
}
