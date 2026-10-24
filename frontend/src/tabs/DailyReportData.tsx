import { Suspense, lazy, useEffect, useMemo, useState } from 'react'
import { deleteReport, downloadAgs, listReports, updateReport } from '../api'
import { CORE_SIZES, METHOD_OPTIONS, USCS_OPTIONS, coreSizeLabel, methodLabel, withCurrent } from '../options'
import { t } from '../i18n'
import BoreholeDetail from '../BoreholeDetail'

// The map library is only downloaded when the map is opened.
const BoreholeMap = lazy(() => import('../BoreholeMap'))

const PAGE_SIZE_OPTIONS = [5, 10, 15, 25]
const BOREHOLE_COLUMNS = [
  'BoreholeID',
  'ProjectName',
  'SiteName',
  'StartDate',
  'EndDate',
  'DrillingMethod',
  'DrillRig',
  'CoreSize',
  'BoreholeDiameter_mm',
  'TargetDepth_m',
  'FinalDepth_m',
  'GroundwaterDepth_m',
  'GroundwaterEncountered',
  'USCS_Class',
  'Avg_SPT_N60',
  'Contractor',
  'LoggingGeologist',
  'Latitude',
  'Longitude',
  'GroundElevation_mRL',
  'CasingInstalled_mm',
  'SoilDescription',
  'Remarks',
]

// Readable column headings; the data keys (used for sorting, filtering and the CSV) stay unchanged.
const COLUMN_LABELS: Record<string, string> = {
  BoreholeID: t('Borehole ID'),
  ProjectName: t('Project'),
  SiteName: t('Site / Zone'),
  StartDate: t('Start Date'),
  EndDate: t('End Date'),
  DrillingMethod: t('Drilling Method'),
  DrillRig: t('Drill Rig / Plant'),
  CoreSize: t('Core Size'),
  BoreholeDiameter_mm: t('Borehole Diameter (mm)'),
  TargetDepth_m: t('Target Depth (m)'),
  FinalDepth_m: t('Final Depth (m)'),
  GroundwaterDepth_m: t('Groundwater Depth (m)'),
  GroundwaterEncountered: t('Groundwater Encountered'),
  USCS_Class: t('USCS Class'),
  Avg_SPT_N60: t('Avg SPT N60'),
  Contractor: t('Contractor'),
  LoggingGeologist: t('Logging Geologist'),
  Latitude: t('Latitude'),
  Longitude: t('Longitude'),
  GroundElevation_mRL: t('Ground Elevation (mRL)'),
  CasingInstalled_mm: t('Casing Installed (mm)'),
  SoilDescription: t('Soil Description'),
  Remarks: t('Remarks'),
  SubmittedBy: t('Submitted By'),
}

const columnLabel = (key: string) => COLUMN_LABELS[key] ?? key

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

type Viewer = { email: string, role: 'admin' | 'general' }

export default function DailyReportData({ user }: { user: Viewer }) {
  const [reports, setReports] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [pageSize, setPageSize] = useState(PAGE_SIZE_OPTIONS[0])
  const [page, setPage] = useState(0)
  const [search, setSearch] = useState('')
  const [projectFilter, setProjectFilter] = useState('')
  const [siteFilter, setSiteFilter] = useState('')
  const [methodFilter, setMethodFilter] = useState('')
  const [uscsFilter, setUscsFilter] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [sortKey, setSortKey] = useState<string | null>('StartDate')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')
  const [actionStatus, setActionStatus] = useState('')
  const [editTarget, setEditTarget] = useState<string | null>(null)
  const [editDraft, setEditDraft] = useState<Record<string, string>>({})
  const [editOriginal, setEditOriginal] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [openId, setOpenId] = useState<string | null>(null)
  const [showMap, setShowMap] = useState(false)

  // Keeps the current page after an edit or delete; only the first load starts at page 1.
  const loadReports = async () => {
    setLoading(true)
    setError('')
    try {
      const data = await listReports()
      setReports(Array.isArray(data) ? data : [])
    } catch (err: any) {
      setError(err.message || t('Failed to load reports'))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadReports()
  }, [])


  const columns = useMemo(() => {
    if (!reports.length) return []
    const keySet = new Set<string>()
    reports.forEach(r => Object.keys(r || {}).forEach(k => keySet.add(k)))
    const pickOrder = (order: string[]) => order.filter(k => keySet.has(k))
    const borehole = pickOrder(BOREHOLE_COLUMNS)
    const extra = pickOrder(['SubmittedBy'])
    if (borehole.length) return [...borehole, ...extra]
    return Array.from(keySet)
  }, [reports])

  const filteredReports = useMemo(() => {
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
      const joined = Object.values(r)
        .map(v => (v ?? '').toString().toLowerCase())
        .join(' ')
      return joined.includes(term)
    })
  }, [reports, search, projectFilter, siteFilter, methodFilter, uscsFilter, dateFrom, dateTo])

  const sortedReports = useMemo(() => {
    if (!sortKey) return filteredReports
    const sorted = [...filteredReports].sort((a: any, b: any) => {
      const left = String(a?.[sortKey] ?? '').trim()
      const right = String(b?.[sortKey] ?? '').trim()
      // Empty cells always go last; Number('') would otherwise count them as 0.
      if (!left || !right) return left === right ? 0 : left ? -1 : 1
      const ln = Number(left)
      const rn = Number(right)
      if (Number.isFinite(ln) && Number.isFinite(rn)) return ln - rn
      return left.localeCompare(right, undefined, { numeric: true, sensitivity: 'base' })
    })
    if (sortDir === 'asc') return sorted
    // Reverse only the filled cells so empty ones stay at the bottom in both directions.
    const filled = sorted.filter((r: any) => String(r?.[sortKey] ?? '').trim() !== '')
    const empty = sorted.filter((r: any) => String(r?.[sortKey] ?? '').trim() === '')
    return [...filled.reverse(), ...empty]
  }, [filteredReports, sortKey, sortDir])

  // A new search, filter or sort order starts again at the first page.
  useEffect(() => {
    setPage(0)
  }, [search, projectFilter, siteFilter, methodFilter, uscsFilter, dateFrom, dateTo, sortKey, sortDir])

  const totalPages = sortedReports.length ? Math.ceil(sortedReports.length / pageSize) : 0
  const safePage = totalPages ? Math.min(page, totalPages - 1) : 0
  const startIdx = sortedReports.length ? safePage * pageSize : 0
  const endIdx = sortedReports.length ? Math.min(sortedReports.length, startIdx + pageSize) : 0

  const pageRows = useMemo(() => {
    if (!sortedReports.length) return []
    return sortedReports.slice(startIdx, endIdx)
  }, [sortedReports, startIdx, endIdx])

  const handlePageSize = (value: number) => {
    setPageSize(value)
    setPage(0)
  }

  // Keep the stored page inside the (filtered) result, e.g. after deleting the last row of a page.
  useEffect(() => {
    if (page !== safePage) setPage(safePage)
  }, [page, safePage])

  const nextDisabled = !sortedReports.length || safePage + 1 >= totalPages
  const prevDisabled = safePage === 0

  const uniqueValues = useMemo(() => {
    const getUnique = (key: string) => Array.from(new Set(reports.map(r => r?.[key]).filter(Boolean))).sort()
    return {
      projects: getUnique('ProjectName'),
      sites: getUnique('SiteName'),
      methods: getUnique('DrillingMethod'),
      uscs: getUnique('USCS_Class'),
    }
  }, [reports])

  const toggleSort = (col: string) => {
    if (sortKey === col) {
      setSortDir(sortDir === 'asc' ? 'desc' : 'asc')
    } else {
      setSortKey(col)
      setSortDir('asc')
    }
  }

  const closeEdit = () => {
    setEditTarget(null)
    setEditDraft({})
    setEditOriginal({})
  }

  const handleDelete = async (boreholeId: string) => {
    if (!boreholeId || busy) return
    if (!window.confirm(t('Delete borehole {id}?', { id: boreholeId }))) return
    setBusy(true)
    setActionStatus(t('Deleting...'))
    try {
      await deleteReport(boreholeId)
      if (editTarget === boreholeId) closeEdit()
      setActionStatus(t('Deleted'))
      await loadReports()
    } catch (err: any) {
      setActionStatus(t('Error: {message}', { message: err.message }))
    } finally {
      setBusy(false)
    }
  }

  const startEdit = (row: any) => {
    if (!row?.BoreholeID) return
    setEditTarget(row.BoreholeID)
    const draft: Record<string, string> = {}
    EDITABLE_FIELDS.forEach(({ key }) => {
      draft[key] = row[key] === null || row[key] === undefined ? '' : String(row[key])
    })
    setEditDraft(draft)
    setEditOriginal(draft)
    window.scrollTo({ top: 0, behavior: 'smooth' })
    setActionStatus(t('Editing {id}', { id: row.BoreholeID }))
  }

  const saveEdit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!editTarget || busy) return
    // Send only what was changed, so untouched (possibly legacy-formatted) values are never rewritten.
    const changes: Record<string, string> = {}
    Object.entries(editDraft).forEach(([key, value]) => {
      if (value !== editOriginal[key]) changes[key] = value
    })
    if (!Object.keys(changes).length) {
      setActionStatus(t('No changes to save'))
      closeEdit()
      return
    }
    setBusy(true)
    setActionStatus(t('Saving changes...'))
    try {
      await updateReport(editTarget, changes)
      setActionStatus(t('Saved'))
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
    if (!columns.length || !sortedReports.length) return
    const header = columns.map(csvCell).join(',')
    const rows = sortedReports.map(row => columns.map(col => csvCell(row?.[col])).join(','))
    // BOM so Excel opens UTF-8 text (e.g. Indonesian place names) correctly.
    const content = '\uFEFF' + [header, ...rows].join('\r\n')
    const blob = new Blob([content], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = 'borehole-logs.csv'
    document.body.appendChild(link)
    link.click()
    link.remove()
    // Revoking immediately can cancel the download in some browsers.
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }


  const canEdit = (row: any) =>
    user.role === 'admin' || String(row?.SubmittedBy || '').toLowerCase() === user.email.toLowerCase()
  const opened = openId ? reports.find(r => r.BoreholeID === openId) : null
  if (opened) {
    return <BoreholeDetail report={opened} canEdit={canEdit(opened)} onClose={() => setOpenId(null)} />
  }

  return (
    <div>
      <div className="card" style={{ marginBottom: '1rem' }}>
        <h3 style={{ marginTop: 0 }}>{t('Find & Filter')}</h3>
        <div className="row">
          <div>
            <label htmlFor="filter-search">{t('Search')}</label>
            <input id="filter-search" value={search} onChange={e => setSearch(e.target.value)} placeholder={t('Search any field...')} />
            <label htmlFor="filter-project">{t('Project')}</label>
            <select id="filter-project" value={projectFilter} onChange={e => setProjectFilter(e.target.value)}>
              <option value="">{t('All')}</option>
              {uniqueValues.projects.map(p => <option key={p} value={p}>{p}</option>)}
            </select>
            <label htmlFor="filter-site">{t('Site')}</label>
            <select id="filter-site" value={siteFilter} onChange={e => setSiteFilter(e.target.value)}>
              <option value="">{t('All')}</option>
              {uniqueValues.sites.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          <div>
            <label htmlFor="filter-method">{t('Method')}</label>
            <select id="filter-method" value={methodFilter} onChange={e => setMethodFilter(e.target.value)}>
              <option value="">{t('All')}</option>
              {uniqueValues.methods.map(m => <option key={m} value={m}>{methodLabel(m)}</option>)}
            </select>
            <label htmlFor="filter-uscs">USCS</label>
            <select id="filter-uscs" value={uscsFilter} onChange={e => setUscsFilter(e.target.value)}>
              <option value="">{t('All')}</option>
              {uniqueValues.uscs.map(u => <option key={u} value={u}>{u}</option>)}
            </select>
            <label>{t('Date range (Start -> End)')}</label>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '.5rem' }}>
              <input type="date" aria-label={t('Start date from')} value={dateFrom} onChange={e => setDateFrom(e.target.value)} />
              <input type="date" aria-label={t('End date to')} value={dateTo} onChange={e => setDateTo(e.target.value)} />
            </div>
          </div>
        </div>
        <div className="actions" style={{ marginTop: '.5rem', flexWrap: 'wrap', gap: '.5rem' }}>
          <button onClick={() => { setSearch(''); setProjectFilter(''); setSiteFilter(''); setMethodFilter(''); setUscsFilter(''); setDateFrom(''); setDateTo(''); }}>{t('Clear Filters')}</button>
          <button onClick={exportCsv} disabled={!sortedReports.length}>{t('Export CSV')}</button>
          <button
            onClick={exportAgs}
            disabled={!projectFilter || busy}
            title={projectFilter ? t('AGS4 file with every log of {project}', { project: projectFilter }) : t('Choose a project in the Project filter first')}
          >
            {t('Export AGS4')}
          </button>
          <button onClick={() => setShowMap(v => !v)}>{showMap ? t('Hide Map') : t('Show Map')}</button>
          <span>{actionStatus}</span>
        </div>
      </div>

      {showMap && (
        <div className="card" style={{ marginBottom: '1rem' }}>
          <Suspense fallback={<p>{t('Loading map…')}</p>}>
            <BoreholeMap reports={sortedReports} onOpen={setOpenId} />
          </Suspense>
        </div>
      )}

      {editTarget && (
        <div className="card" style={{ marginBottom: '1rem' }}>
          <h3 style={{ marginTop: 0 }}>{t('Edit Borehole {id}', { id: editTarget })}</h3>
          <form onSubmit={saveEdit} className="row">
            {EDITABLE_FIELDS.map(field => (
              <div key={field.key}>
                <label htmlFor={`edit-${field.key}`}>{field.label}</label>
                {field.key === 'USCS_Class' ? (
                  <select id={`edit-${field.key}`} value={editDraft[field.key] ?? ''} onChange={e => setEditDraft(prev => ({ ...prev, [field.key]: e.target.value }))}>
                    <option value="">{t('Select')}</option>
                    {withCurrent(USCS_OPTIONS, editOriginal[field.key]).map(code => (
                      <option key={code} value={code}>{code}</option>
                    ))}
                  </select>
                ) : field.key === 'DrillingMethod' ? (
                  <select id={`edit-${field.key}`} value={editDraft[field.key] ?? ''} onChange={e => setEditDraft(prev => ({ ...prev, [field.key]: e.target.value }))}>
                    <option value="">{t('Select')}</option>
                    {withCurrent(METHOD_OPTIONS, editOriginal[field.key]).map(m => (
                      <option key={m} value={m}>{methodLabel(m)}</option>
                    ))}
                  </select>
                ) : field.key === 'CoreSize' ? (
                  <select id={`edit-${field.key}`} value={editDraft[field.key] ?? ''} onChange={e => setEditDraft(prev => ({ ...prev, [field.key]: e.target.value }))}>
                    <option value="">{t('Not cored')}</option>
                    {CORE_SIZES.map(s => <option key={s.code} value={s.code}>{coreSizeLabel(s.code)}</option>)}
                  </select>
                ) : field.key === 'Remarks' ? (
                  <textarea id={`edit-${field.key}`} value={editDraft[field.key] ?? ''} onChange={e => setEditDraft(prev => ({ ...prev, [field.key]: e.target.value }))} />
                ) : (
                  <input
                    id={`edit-${field.key}`}
                    type={field.type || 'text'}
                    step={field.type === 'number' ? 'any' : undefined}
                    value={editDraft[field.key] ?? ''}
                    onChange={e => setEditDraft(prev => ({ ...prev, [field.key]: e.target.value }))}
                  />
                )}
              </div>
            ))}
            <div style={{ gridColumn: '1 / -1', display: 'flex', gap: '.5rem', alignItems: 'center', flexWrap: 'wrap' }}>
              <button type="submit" disabled={busy}>{t('Save')}</button>
              <button type="button" onClick={closeEdit}>{t('Cancel')}</button>
            </div>
          </form>
        </div>
      )}

      <div className="actions" style={{ gap: '0.5rem', flexWrap: 'wrap' }}>
        <label style={{ display: 'flex', alignItems: 'center', gap: '.35rem', margin: 0 }}>
          {t('Rows per page')}
          <select value={pageSize} onChange={e => handlePageSize(Number(e.target.value))}>
            {PAGE_SIZE_OPTIONS.map(opt => (
              <option key={opt} value={opt}>{opt}</option>
            ))}
          </select>
        </label>
        <button onClick={() => setPage(Math.max(0, safePage - 1))} disabled={prevDisabled}>{t('Previous')}</button>
        <button
          onClick={() => setPage(Math.min(Math.max(0, totalPages - 1), safePage + 1))}
          disabled={nextDisabled}
        >
          {t('Next')}
        </button>
        <span>
          {sortedReports.length
            ? t('Showing {from}-{to} of {total} records', { from: startIdx + 1, to: endIdx, total: sortedReports.length })
            : t('No records available')}
        </span>
      </div>

      {loading && <p style={{ marginTop: '1rem' }}>{t('Loading reports...')}</p>}
      {error && <p style={{ marginTop: '1rem', color: 'var(--danger)' }}>{error}</p>}

      {!loading && !error && reports.length === 0 && (
        <div className="card" style={{ marginTop: '1rem' }}>
          <p>{t('No borehole logs have been submitted yet.')}</p>
        </div>
      )}

      {!loading && !error && reports.length > 0 && (
        <div style={{ overflowX: 'auto', overflowY: 'auto', marginTop: '1rem', maxHeight: '70vh' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: '800px' }}>
            <thead>
              <tr>
                {columns.map(col => (
                  <th
                    key={col}
                    style={{
                      textAlign: 'left',
                      borderBottom: '1px solid #24304a',
                      padding: '.4rem',
                      whiteSpace: 'nowrap',
                      position: 'sticky',
                      top: 0,
                      background: 'var(--surface, #111827)',
                      zIndex: 1,
                      cursor: 'pointer',
                    }}
                    onClick={() => toggleSort(col)}
                    title={t('Sort by {column}', { column: columnLabel(col) })}
                  >
                    {columnLabel(col)}{sortKey === col ? (sortDir === 'asc' ? ` [${t('asc')}]` : ` [${t('desc')}]`) : ''}
                  </th>
                ))}
                <th style={{ position: 'sticky', top: 0, background: 'var(--surface, #111827)', padding: '.4rem' }}>{t('Actions')}</th>
              </tr>
            </thead>
            <tbody>
              {pageRows.map((row, idx) => (
                <tr key={`${row.BoreholeID || idx}-${idx}`}>
                  {columns.map(col => {
                    const value = row?.[col]
                    let display: string
                    if (value === null || value === undefined || value === '') {
                      display = ''
                    } else if (typeof value === 'object') {
                      display = JSON.stringify(value)
                    } else if (col === 'DrillingMethod') {
                      display = methodLabel(String(value))
                    } else if (col === 'GroundwaterEncountered' && /^(true|false)$/i.test(String(value))) {
                      display = String(value).toLowerCase() === 'true' ? t('Yes') : t('No')
                    } else {
                      display = String(value)
                    }
                    return (
                      <td key={col} style={{ padding: '.35rem', borderBottom: '1px dashed #1b263f', fontSize: '.9rem' }}>
                        {display}
                      </td>
                    )
                  })}
                  <td style={{ padding: '.35rem', borderBottom: '1px dashed #1b263f', whiteSpace: 'nowrap' }}>
                    <button onClick={() => setOpenId(row.BoreholeID)} style={{ marginRight: '.5rem' }}>{t('Open')}</button>
                    <button onClick={() => startEdit(row)} style={{ marginRight: '.5rem' }}>{t('Edit')}</button>
                    <button onClick={() => handleDelete(row.BoreholeID)} disabled={busy} style={{ background: 'var(--danger)' }}>{t('Delete')}</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
