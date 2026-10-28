import { Suspense, lazy, useCallback, useEffect, useMemo, useState } from 'react'
import { deleteReport, downloadAgs, getDepthOverview, listReports, updateReport, type DepthOverview } from '../api'
import { CORE_SIZES, METHOD_OPTIONS, USCS_OPTIONS, coreSizeLabel, methodLabel, withCurrent } from '../options'
import { discardOutboxItem, retryOutboxItem, type OutboxItem } from '../outbox'
import { t } from '../i18n'
import BoreholeDetail from '../BoreholeDetail'
import { StrataStrip } from '../Profile'
import { DateInput, Icon, PageHead, formatDate, todayIso } from '../ui'

// The map library is only downloaded when the map is opened.
const BoreholeMap = lazy(() => import('../BoreholeMap'))
const AgsImport = lazy(() => import('./AgsImport'))

const PAGE_SIZE_OPTIONS = [10, 25, 50, 100]

// Every stored column, in this order, for the CSV export.
const CSV_COLUMNS = [
  'BoreholeID', 'ProjectName', 'SiteName', 'StartDate', 'EndDate', 'DrillingMethod', 'DrillRig', 'CoreSize',
  'BoreholeDiameter_mm', 'TargetDepth_m', 'FinalDepth_m', 'GroundwaterDepth_m', 'GroundwaterEncountered',
  'USCS_Class', 'Avg_SPT_N60', 'Contractor', 'LoggingGeologist', 'Latitude', 'Longitude', 'GroundElevation_mRL',
  'CasingInstalled_mm', 'SoilDescription', 'Remarks', 'SubmittedBy',
]

// Quotes a CSV cell and neutralises spreadsheet formulas (=, +, -, @) so a malicious
// log entry cannot execute when the export is opened in Excel/Sheets.
function csvCell(value: unknown): string {
  let text = value === null || value === undefined ? '' : String(value)
  if (/^[=+\-@\t\r]/.test(text) && !/^-?\d+(\.\d+)?$/.test(text)) {
    text = `'${text}`
  }
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text
}

const EDITABLE_FIELDS: Array<{ key: string; label: string; type?: string }> = [
  { key: 'ProjectName', label: t('Project') },
  { key: 'SiteName', label: t('Site / Zone') },
  { key: 'StartDate', label: t('Start Date'), type: 'date' },
  { key: 'EndDate', label: t('End Date'), type: 'date' },
  { key: 'DrillingMethod', label: t('Method') },
  { key: 'DrillRig', label: t('Drill Rig / Plant') },
  { key: 'CoreSize', label: t('Core Size (wireline)') },
  { key: 'FinalDepth_m', label: t('Final Depth (m)'), type: 'number' },
  { key: 'GroundwaterDepth_m', label: t('Groundwater Depth (m)'), type: 'number' },
  { key: 'USCS_Class', label: 'USCS' },
  { key: 'Avg_SPT_N60', label: t('Avg SPT N60'), type: 'number' },
  { key: 'Remarks', label: t('Remarks') },
]

type Viewer = { email: string, role: string }
type Row = Record<string, any>
export type BoreStatus = 'drilling' | 'complete' | 'partial' | 'none'
type StatusFilter = 'all' | 'drilling' | 'todo' | 'complete'

const num = (v: unknown) => {
  const n = parseFloat(String(v ?? ''))
  return Number.isFinite(n) ? n : null
}

export function statusOf(row: Row, overview: DepthOverview, today = todayIso()): BoreStatus {
  if (row.EndDate && String(row.EndDate) >= today) return 'drilling'
  const o = overview[row.BoreholeID]
  if (!o || (!o.layers.length && !o.spt.length)) return 'none'
  const final = num(row.FinalDepth_m)
  const deepest = Math.max(0, ...o.layers.map(l => l.base))
  if (o.layers.length && o.spt.length && (final === null || deepest >= final - 0.5)) return 'complete'
  return 'partial'
}

const STATUS_LABEL: Record<BoreStatus, string> = {
  drilling: 'Drilling in progress',
  complete: 'Depth data complete',
  partial: 'Depth data incomplete',
  none: 'No depth data yet',
}
const STATUS_CLASS: Record<BoreStatus, string> = { drilling: 'active', complete: 'ok', partial: 'warn', none: '' }
const STATUS_COLOR: Record<BoreStatus, string> = { drilling: '#1f5f8b', complete: '#2e7d4f', partial: '#d08a12', none: '#9aa0a5' }

type SortKey = 'BoreholeID' | 'StartDate' | 'FinalDepth_m' | 'Avg_SPT_N60'

export default function Boreholes({ user, outbox = [], onNew, openBorehole }: { user: Viewer, outbox?: OutboxItem[], onNew?: () => void, openBorehole?: string }) {
  const [reports, setReports] = useState<Row[]>([])
  const [overview, setOverview] = useState<DepthOverview>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [pageSize, setPageSize] = useState(25)
  const [page, setPage] = useState(0)
  const [search, setSearch] = useState('')
  const [projectFilter, setProjectFilter] = useState('')
  const [siteFilter, setSiteFilter] = useState('')
  const [methodFilter, setMethodFilter] = useState('')
  const [uscsFilter, setUscsFilter] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')
  const [moreFilters, setMoreFilters] = useState(false)
  const [sortKey, setSortKey] = useState<SortKey>('StartDate')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')
  const [actionStatus, setActionStatus] = useState('')
  const [editTarget, setEditTarget] = useState<string | null>(null)
  const [editDraft, setEditDraft] = useState<Record<string, string>>({})
  const [editOriginal, setEditOriginal] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [openId, setOpenId] = useState<string | null>(openBorehole || null)
  const [showImport, setShowImport] = useState(false)
  const canImport = ['admin', 'manager', 'general'].includes(user.role)
  const [showMap, setShowMap] = useState(() => {
    try { return localStorage.getItem('soilboring-show-map') === '1' } catch { return false }
  })

  const loadReports = async () => {
    setError('')
    try {
      const [data, ov] = await Promise.all([listReports(), getDepthOverview().catch(() => ({}))])
      setReports(Array.isArray(data) ? data : [])
      setOverview(ov)
    } catch (err: any) {
      setError(err.message || t('Failed to load reports'))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void loadReports() }, [])
  // A log sent from the outbox appears in the list without a manual refresh.
  useEffect(() => { if (!loading) void loadReports() }, [outbox.length]) // eslint-disable-line react-hooks/exhaustive-deps

  const toggleMap = () => {
    setShowMap(v => {
      try { localStorage.setItem('soilboring-show-map', v ? '0' : '1') } catch { /* ignore */ }
      return !v
    })
  }

  const today = todayIso()
  const statuses = useMemo(() => {
    const out: Record<string, BoreStatus> = {}
    reports.forEach(r => { out[r.BoreholeID] = statusOf(r, overview, today) })
    return out
  }, [reports, overview, today])

  const baseFiltered = useMemo(() => {
    const term = search.trim().toLowerCase()
    return reports.filter(r => {
      if (!r) return false
      if (projectFilter && r.ProjectName !== projectFilter) return false
      if (siteFilter && r.SiteName !== siteFilter) return false
      if (methodFilter && r.DrillingMethod !== methodFilter) return false
      if (uscsFilter && r.USCS_Class !== uscsFilter) return false
      if (dateFrom && r.StartDate && r.StartDate < dateFrom) return false
      if (dateTo && r.EndDate && r.EndDate > dateTo) return false
      if (!term) return true
      return Object.values(r).map(v => (v ?? '').toString().toLowerCase()).join(' ').includes(term)
    })
  }, [reports, search, projectFilter, siteFilter, methodFilter, uscsFilter, dateFrom, dateTo])

  const counts = useMemo(() => {
    const c = { all: baseFiltered.length, drilling: 0, todo: 0, complete: 0 }
    baseFiltered.forEach(r => {
      const s = statuses[r.BoreholeID]
      if (s === 'drilling') c.drilling++
      else if (s === 'complete') c.complete++
      else c.todo++
    })
    return c
  }, [baseFiltered, statuses])

  const filtered = useMemo(() => baseFiltered.filter(r => {
    const s = statuses[r.BoreholeID]
    if (statusFilter === 'drilling') return s === 'drilling'
    if (statusFilter === 'complete') return s === 'complete'
    if (statusFilter === 'todo') return s === 'partial' || s === 'none'
    return true
  }), [baseFiltered, statuses, statusFilter])

  const sorted = useMemo(() => {
    const value = (r: Row) => String(r?.[sortKey] ?? '').trim()
    const list = [...filtered].sort((a, b) => {
      const left = value(a), right = value(b)
      if (!left || !right) return left === right ? 0 : left ? -1 : 1
      const ln = Number(left), rn = Number(right)
      if (Number.isFinite(ln) && Number.isFinite(rn)) return ln - rn
      return left.localeCompare(right, undefined, { numeric: true, sensitivity: 'base' })
    })
    if (sortDir === 'asc') return list
    // Reverse only the filled cells so empty ones stay at the bottom in both directions.
    return [...list.filter(r => value(r)).reverse(), ...list.filter(r => !value(r))]
  }, [filtered, sortKey, sortDir])

  useEffect(() => { setPage(0) }, [search, projectFilter, siteFilter, methodFilter, uscsFilter, dateFrom, dateTo, sortKey, sortDir, statusFilter])

  const totalPages = Math.max(1, Math.ceil(sorted.length / pageSize))
  const safePage = Math.min(page, totalPages - 1)
  const pageRows = sorted.slice(safePage * pageSize, safePage * pageSize + pageSize)

  const unique = useMemo(() => {
    const get = (key: string) => Array.from(new Set(reports.map(r => r?.[key]).filter(Boolean))).sort() as string[]
    return { projects: get('ProjectName'), sites: get('SiteName'), methods: get('DrillingMethod'), uscs: get('USCS_Class') }
  }, [reports])

  const extraFilters = [siteFilter, methodFilter, uscsFilter, dateFrom, dateTo].filter(Boolean).length
  const anyFilter = Boolean(search || projectFilter || extraFilters || statusFilter !== 'all')
  const clearFilters = () => {
    setSearch(''); setProjectFilter(''); setSiteFilter(''); setMethodFilter(''); setUscsFilter('')
    setDateFrom(''); setDateTo(''); setStatusFilter('all')
  }

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) setSortDir(sortDir === 'asc' ? 'desc' : 'asc')
    else { setSortKey(key); setSortDir(key === 'BoreholeID' ? 'asc' : 'desc') }
  }
  const sortMark = (key: SortKey) => (sortKey === key ? (sortDir === 'asc' ? '▲' : '▼') : '')
  const ariaSort = (key: SortKey) => (sortKey === key ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none')

  const closeEdit = () => { setEditTarget(null); setEditDraft({}); setEditOriginal({}) }

  const handleDelete = async (boreholeId: string) => {
    if (!boreholeId || busy) return
    if (!window.confirm(t('Delete borehole {id}?', { id: boreholeId }))) return
    setBusy(true)
    setActionStatus(t('Deleting...'))
    try {
      await deleteReport(boreholeId)
      if (editTarget === boreholeId) closeEdit()
      setActionStatus(t('Borehole {id} deleted.', { id: boreholeId }))
      await loadReports()
    } catch (err: any) {
      setActionStatus(t('Error: {message}', { message: err.message }))
    } finally {
      setBusy(false)
    }
  }

  const startEdit = (row: Row) => {
    if (!row?.BoreholeID) return
    setEditTarget(row.BoreholeID)
    const draft: Record<string, string> = {}
    EDITABLE_FIELDS.forEach(({ key }) => { draft[key] = row[key] === null || row[key] === undefined ? '' : String(row[key]) })
    setEditDraft(draft)
    setEditOriginal(draft)
    window.scrollTo({ top: 0, behavior: 'smooth' })
    setActionStatus('')
  }

  const saveEdit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!editTarget || busy) return
    // Send only what was changed, so untouched (possibly legacy-formatted) values are never rewritten.
    const changes: Record<string, string> = {}
    Object.entries(editDraft).forEach(([key, value]) => { if (value !== editOriginal[key]) changes[key] = value })
    if (!Object.keys(changes).length) { closeEdit(); return }
    setBusy(true)
    setActionStatus(t('Saving changes...'))
    try {
      await updateReport(editTarget, changes)
      setActionStatus(t('Borehole {id} saved.', { id: editTarget }))
      closeEdit()
      await loadReports()
    } catch (err: any) {
      setActionStatus(t('Error: {message}', { message: err.message }))
    } finally {
      setBusy(false)
    }
  }

  // AGS4 (ground investigation data exchange format) holds one project per file.
  const exportAgs = async () => {
    if (!projectFilter || busy) return
    setBusy(true)
    setActionStatus(t('Preparing AGS4 file...'))
    try {
      const filename = await downloadAgs(projectFilter)
      setActionStatus(t('Downloaded {file}', { file: filename }))
    } catch (err: any) {
      setActionStatus(t('Error: {message}', { message: err.message }))
    } finally {
      setBusy(false)
    }
  }

  const exportCsv = () => {
    if (!sorted.length) return
    const header = CSV_COLUMNS.map(csvCell).join(',')
    const rows = sorted.map(row => CSV_COLUMNS.map(col => csvCell(row?.[col])).join(','))
    // BOM so Excel opens UTF-8 text (e.g. Indonesian place names) correctly.
    const content = '﻿' + [header, ...rows].join('\r\n')
    const url = URL.createObjectURL(new Blob([content], { type: 'text/csv;charset=utf-8;' }))
    const link = document.createElement('a')
    link.href = url
    link.download = 'borehole-logs.csv'
    document.body.appendChild(link)
    link.click()
    link.remove()
    // Revoking immediately can cancel the download in some browsers.
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }

  const colorFor = useCallback((r: Row) => STATUS_COLOR[statuses[r.BoreholeID] || 'none'], [statuses])

  const canEdit = (row: Row) =>
    user.role === 'admin' || user.role === 'manager' || String(row?.SubmittedBy || '').toLowerCase() === user.email.toLowerCase()
  const opened = openId ? reports.find(r => r.BoreholeID === openId) : null
  if (opened) {
    return <BoreholeDetail report={opened} canEdit={canEdit(opened)} onClose={() => { setOpenId(null); void loadReports() }} />
  }

  const projects = new Set(reports.map(r => r.ProjectName).filter(Boolean)).size
  const metres = reports.reduce((sum, r) => sum + (num(r.FinalDepth_m) || 0), 0)
  const todo = Object.values(statuses).filter(s => s === 'partial' || s === 'none').length

  const summary = reports.length ? (
    <>
      {t('{boreholes} in {projects}, {m} m drilled in total.', {
        boreholes: reports.length === 1 ? t('1 borehole') : t('{n} boreholes', { n: reports.length }),
        projects: projects === 1 ? t('1 project') : t('{n} projects', { n: projects }),
        m: Number(metres.toFixed(1)),
      })}{' '}
      {todo > 0 ? (todo === 1 ? t('1 still needs depth data.') : t('{n} still need depth data.', { n: todo })) : t('All have depth data.')}
    </>
  ) : t('No borehole logs have been submitted yet.')

  const exportMenu = (
    <details className="menu">
      <summary className="button-like"><Icon name="download" />{canImport ? t('Import / export') : t('Export')}</summary>
      <div className="menu-pop">
        <button type="button" onClick={exportCsv} disabled={!sorted.length}>{t('CSV (rows shown)')}</button>
        <button type="button" onClick={exportAgs} disabled={!projectFilter || busy}>{t('AGS4 for the chosen project')}</button>
        {!projectFilter && <p className="hint">{t('Choose a project in the Project filter first')}</p>}
        {canImport && <button type="button" onClick={e => { const menu = e.currentTarget.closest('details'); if (menu) menu.open = false; setShowImport(true) }}>{t('Import AGS4 file…')}</button>}
      </div>
    </details>
  )

  const queued = outbox.map(item => {
    const d = item.data as Row
    return (
      <tr key={`q-${item.id}`} className="queued-row" style={{ cursor: 'default' }}>
        <td className="c-strip"><StrataStrip layers={[]} depth={num(d.FinalDepth_m)} title={t('Not sent yet')} /></td>
        <td className="c-id"><div className="bh-id">{String(d.BoreholeID || '')}</div><div className="bh-sub">{[d.ProjectName, d.SiteName].filter(Boolean).join(', ')}</div></td>
        <td className="c-dates nowrap">{formatDate(String(d.StartDate || ''))}</td>
        <td className="c-depth num">{d.FinalDepth_m ? `${d.FinalDepth_m} m` : '–'}</td>
        <td className="c-n num">{String(d.Avg_SPT_N60 || '–')}</td>
        <td className="c-uscs">{String(d.USCS_Class || '')}</td>
        <td className="c-status">
          {item.error
            ? <span className="status" style={{ color: 'var(--danger)', whiteSpace: 'normal' }}>{t('Refused: {why}', { why: item.error })}</span>
            : <span className="status queued">{t('Waiting to be sent')}</span>}
        </td>
        <td className="c-act nowrap">
          {item.error && (
            <>
              <button type="button" className="small" onClick={() => retryOutboxItem(item.id)}>{t('Retry')}</button>{' '}
              <button type="button" className="small danger-quiet" onClick={() => { if (window.confirm(t('Discard this unsent log?'))) discardOutboxItem(item.id) }}>{t('Discard')}</button>
            </>
          )}
        </td>
      </tr>
    )
  })

  return (
    <div>
      <PageHead
        title={t('Boreholes')}
        description={summary}
        actions={<>
          <button type="button" onClick={toggleMap} aria-pressed={showMap}><Icon name={showMap ? 'list' : 'map'} />{showMap ? t('Hide map') : t('Show map')}</button>
          {exportMenu}
          {onNew && <button type="button" className="primary" onClick={onNew}><Icon name="plus" />{t('New log')}</button>}
        </>}
      />

      {showImport && (
        <Suspense fallback={<p className="muted">{t('Loading…')}</p>}>
          <AgsImport onClose={() => setShowImport(false)} onImported={() => { void loadReports() }} />
        </Suspense>
      )}

      {editTarget && (
        <section className="card" style={{ marginBottom: '1rem' }} aria-label={t('Edit Borehole {id}', { id: editTarget })}>
          <h2>{t('Edit Borehole {id}', { id: editTarget })}</h2>
          <form onSubmit={saveEdit}>
            <div className="fields">
              {EDITABLE_FIELDS.map(field => {
                const id = `edit-${field.key}`
                const set = (v: string) => setEditDraft(prev => ({ ...prev, [field.key]: v }))
                const value = editDraft[field.key] ?? ''
                return (
                  <div key={field.key} className={`field${field.key === 'Remarks' ? ' wide' : ''}`}>
                    <label htmlFor={id}>{field.label}</label>
                    {field.key === 'USCS_Class' ? (
                      <select id={id} value={value} onChange={e => set(e.target.value)}>
                        <option value="">{t('Select')}</option>
                        {withCurrent(USCS_OPTIONS, editOriginal[field.key]).map(code => <option key={code} value={code}>{code}</option>)}
                      </select>
                    ) : field.key === 'DrillingMethod' ? (
                      <select id={id} value={value} onChange={e => set(e.target.value)}>
                        <option value="">{t('Select')}</option>
                        {withCurrent(METHOD_OPTIONS, editOriginal[field.key]).map(m => <option key={m} value={m}>{methodLabel(m)}</option>)}
                      </select>
                    ) : field.key === 'CoreSize' ? (
                      <select id={id} value={value} onChange={e => set(e.target.value)}>
                        <option value="">{t('Not cored')}</option>
                        {CORE_SIZES.map(s => <option key={s.code} value={s.code}>{coreSizeLabel(s.code)}</option>)}
                      </select>
                    ) : field.key === 'Remarks' ? (
                      <textarea id={id} value={value} onChange={e => set(e.target.value)} />
                    ) : field.type === 'date' ? (
                      <DateInput id={id} value={value} onChange={set} />
                    ) : (
                      <input id={id} type="text" inputMode={field.type === 'number' ? 'decimal' : undefined} value={value}
                        onChange={e => set(field.type === 'number' ? e.target.value.replace(/,/g, '.') : e.target.value)} />
                    )}
                  </div>
                )
              })}
            </div>
            <div className="actions" style={{ marginTop: '1rem' }}>
              <button type="submit" className="primary" disabled={busy}>{t('Save changes')}</button>
              <button type="button" onClick={closeEdit}>{t('Cancel')}</button>
            </div>
          </form>
        </section>
      )}

      <div className="segmented" role="group" aria-label={t('Show boreholes')}>
        {([
          ['all', t('All'), counts.all],
          ['drilling', t('Drilling now'), counts.drilling],
          ['todo', t('Needs depth data'), counts.todo],
          ['complete', t('Complete'), counts.complete],
        ] as Array<[StatusFilter, string, number]>).map(([key, label, n]) => (
          <button key={key} type="button" aria-pressed={statusFilter === key} onClick={() => setStatusFilter(key)}>
            {label} <span className="count">{n}</span>
          </button>
        ))}
      </div>

      <div className="toolbar">
        <input type="search" value={search} onChange={e => setSearch(e.target.value)} placeholder={t('Search borehole, project, contractor…')} aria-label={t('Search')} />
        <select value={projectFilter} onChange={e => setProjectFilter(e.target.value)} aria-label={t('Project')}>
          <option value="">{t('All projects')}</option>
          {unique.projects.map(p => <option key={p} value={p}>{p}</option>)}
        </select>
        <button type="button" onClick={() => setMoreFilters(v => !v)} aria-expanded={moreFilters}>
          <Icon name="filter" />{extraFilters ? t('Filters ({n})', { n: extraFilters }) : t('More filters')}
        </button>
        {anyFilter && <button type="button" className="quiet" onClick={clearFilters}>{t('Clear filters')}</button>}
        {actionStatus && <span role="status" className="muted small">{actionStatus}</span>}
      </div>

      {moreFilters && (
        <div className="more-filters">
          <div className="field">
            <label htmlFor="filter-site">{t('Site')}</label>
            <select id="filter-site" value={siteFilter} onChange={e => setSiteFilter(e.target.value)}>
              <option value="">{t('All')}</option>
              {unique.sites.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          <div className="field">
            <label htmlFor="filter-method">{t('Method')}</label>
            <select id="filter-method" value={methodFilter} onChange={e => setMethodFilter(e.target.value)}>
              <option value="">{t('All')}</option>
              {unique.methods.map(m => <option key={m} value={m}>{methodLabel(m)}</option>)}
            </select>
          </div>
          <div className="field">
            <label htmlFor="filter-uscs">USCS</label>
            <select id="filter-uscs" value={uscsFilter} onChange={e => setUscsFilter(e.target.value)}>
              <option value="">{t('All')}</option>
              {unique.uscs.map(u => <option key={u} value={u}>{u}</option>)}
            </select>
          </div>
          <div className="field">
            <label htmlFor="filter-from">{t('Started from')}</label>
            <DateInput id="filter-from" value={dateFrom} onChange={setDateFrom} />
          </div>
          <div className="field">
            <label htmlFor="filter-to">{t('Finished by')}</label>
            <DateInput id="filter-to" value={dateTo} onChange={setDateTo} />
          </div>
        </div>
      )}

      {error && <p className="notice error">{error}</p>}

      <div className={`split${showMap ? '' : ' no-map'}`}>
        <div style={{ minWidth: 0 }}>
          {loading ? <p className="muted">{t('Loading reports...')}</p> : (sorted.length === 0 && outbox.length === 0) ? (
            <div className="card">
              {reports.length === 0 ? (
                <>
                  <h2>{t('No boreholes yet')}</h2>
                  <p className="muted">{t('Start with the first borehole log. Depth data, photos and the bore log sheet are added afterwards.')}</p>
                  {onNew && <button type="button" className="primary" onClick={onNew}>{t('New log')}</button>}
                </>
              ) : (
                <>
                  <p style={{ marginTop: 0 }}>{t('No borehole matches these filters.')}</p>
                  <button type="button" onClick={clearFilters}>{t('Clear filters')}</button>
                </>
              )}
            </div>
          ) : (
            <>
              <div className="table-wrap">
                <table className={`bh-table${showMap ? ' compact' : ''}`}>
                  <thead>
                    <tr>
                      <th style={{ width: 52 }}><span className="sr-only">{t('Soil column')}</span></th>
                      <th aria-sort={ariaSort('BoreholeID')}><button type="button" onClick={() => toggleSort('BoreholeID')}>{t('Borehole')} {sortMark('BoreholeID')}</button></th>
                      <th aria-sort={ariaSort('StartDate')}><button type="button" onClick={() => toggleSort('StartDate')}>{t('Dates')} {sortMark('StartDate')}</button></th>
                      <th className="num" aria-sort={ariaSort('FinalDepth_m')}><button type="button" onClick={() => toggleSort('FinalDepth_m')}>{t('Depth')} {sortMark('FinalDepth_m')}</button></th>
                      <th className="num" aria-sort={ariaSort('Avg_SPT_N60')}><button type="button" onClick={() => toggleSort('Avg_SPT_N60')}>{t('Avg N')} {sortMark('Avg_SPT_N60')}</button></th>
                      <th>USCS</th>
                      <th>{t('Status')}</th>
                      <th><span className="sr-only">{t('Actions')}</span></th>
                    </tr>
                  </thead>
                  <tbody>
                    {safePage === 0 && queued}
                    {pageRows.map(row => {
                      const id = String(row.BoreholeID)
                      const st = statuses[id] || 'none'
                      const ov = overview[id]
                      const final = num(row.FinalDepth_m)
                      const target = num(row.TargetDepth_m)
                      const open = () => setOpenId(id)
                      return (
                        <tr key={id} onClick={open}>
                          <td className="c-strip"><StrataStrip layers={ov?.layers || []} depth={final} title={t(STATUS_LABEL[st])} /></td>
                          <td className="c-id">
                            <button type="button" className="quiet" style={{ padding: 0, minHeight: 0, color: 'inherit' }} onClick={e => { e.stopPropagation(); open() }}>
                              <span className="bh-id">{id}</span>
                            </button>
                            <div className="bh-sub">{[row.ProjectName, row.SiteName].filter(Boolean).join(', ')}</div>
                          </td>
                          <td className="c-dates nowrap">
                            {formatDate(row.StartDate)}
                            {row.EndDate && row.EndDate !== row.StartDate && <div className="bh-sub">{t('to {date}', { date: formatDate(row.EndDate) })}</div>}
                          </td>
                          <td className="c-depth num nowrap">
                            {final !== null ? `${final} m` : '–'}
                            {target !== null && <div className="bh-sub">{t('target {d} m', { d: target })}</div>}
                          </td>
                          <td className="c-n num">{row.Avg_SPT_N60 || '–'}</td>
                          <td className="c-uscs">{row.USCS_Class || '–'}</td>
                          <td className="c-status">
                            <span className={`status ${STATUS_CLASS[st]}`}>{t(STATUS_LABEL[st])}</span>
                            {ov && (ov.photos > 0 || ov.samples > 0) && (
                              <div className="bh-sub">{[
                                ov.samples ? (ov.samples === 1 ? t('1 sample') : t('{n} samples', { n: ov.samples })) : '',
                                ov.photos ? (ov.photos === 1 ? t('1 photo') : t('{n} photos', { n: ov.photos })) : '',
                              ].filter(Boolean).join(', ')}</div>
                            )}
                          </td>
                          <td className="c-act" onClick={e => e.stopPropagation()}>
                            {canEdit(row) && (
                              <details className="menu">
                                <summary className="button-like" style={{ minHeight: '2rem', padding: '.1rem .55rem' }} aria-label={t('More actions for {id}', { id })}>
                                  <Icon name="more" />
                                </summary>
                                <div className="menu-pop">
                                  <button type="button" onClick={e => { (e.currentTarget.closest('details') as HTMLDetailsElement).open = false; open() }}>{t('Open')}</button>
                                  <button type="button" onClick={e => { (e.currentTarget.closest('details') as HTMLDetailsElement).open = false; startEdit(row) }}>{t('Edit log details')}</button>
                                  <button type="button" className="danger-quiet" disabled={busy} onClick={e => { (e.currentTarget.closest('details') as HTMLDetailsElement).open = false; void handleDelete(id) }}>{t('Delete')}</button>
                                </div>
                              </details>
                            )}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
              <div className="pager">
                <span>
                  {sorted.length
                    ? t('Showing {from}-{to} of {total} records', { from: safePage * pageSize + 1, to: Math.min(sorted.length, (safePage + 1) * pageSize), total: sorted.length })
                    : ''}
                </span>
                <div className="actions">
                  <label className="nowrap" style={{ display: 'flex', alignItems: 'center', gap: '.4rem' }}>
                    {t('Rows per page')}
                    <select value={pageSize} onChange={e => { setPageSize(Number(e.target.value)); setPage(0) }}>
                      {PAGE_SIZE_OPTIONS.map(opt => <option key={opt} value={opt}>{opt}</option>)}
                    </select>
                  </label>
                  <button type="button" className="small" onClick={() => setPage(Math.max(0, safePage - 1))} disabled={safePage === 0}>{t('Previous')}</button>
                  <button type="button" className="small" onClick={() => setPage(Math.min(totalPages - 1, safePage + 1))} disabled={safePage + 1 >= totalPages}>{t('Next')}</button>
                </div>
              </div>
            </>
          )}
        </div>
        {showMap && (
          <div className="map-col">
            <Suspense fallback={<div className="map-box" />}>
              <BoreholeMap reports={sorted} onOpen={setOpenId} colorFor={colorFor} caption={false} />
            </Suspense>
            <div className="map-legend">
              {(['drilling', 'partial', 'none', 'complete'] as BoreStatus[]).map(s => (
                <span key={s} className="small" style={{ display: 'inline-flex', alignItems: 'center', gap: '.35rem' }}>
                  <svg width="10" height="10" aria-hidden="true"><circle cx="5" cy="5" r="4" fill={STATUS_COLOR[s]} stroke="#23282d" /></svg>{t(STATUS_LABEL[s])}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
