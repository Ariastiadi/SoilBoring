import { useEffect, useMemo, useState } from 'react'
import { deleteReport, listReports, updateReport } from '../api'

const PAGE_SIZE_OPTIONS = [5, 10, 15, 25]
const BOREHOLE_COLUMNS = [
  'BoreholeID',
  'ProjectName',
  'SiteName',
  'StartDate',
  'EndDate',
  'DrillingMethod',
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

// Quotes a CSV cell and neutralises spreadsheet formulas (=, +, -, @) so a malicious
// log entry cannot execute when the export is opened in Excel/Sheets.
function csvCell(value: unknown): string {
  let text = value === null || value === undefined ? '' : String(value)
  if (/^[=+\-@\t\r]/.test(text) && !/^-?\d+(\.\d+)?$/.test(text)) {
    text = `'${text}`
  }
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text
}

export default function DailyReportData() {
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

  const loadReports = async () => {
    setLoading(true)
    setError('')
    try {
      const data = await listReports()
      setReports(Array.isArray(data) ? data : [])
      setPage(0)
    } catch (err: any) {
      setError(err.message || 'Failed to load reports')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void loadReports()
  }, [])

  useEffect(() => {
    if (!reports.length) {
      if (page !== 0) setPage(0)
      return
    }
    const lastPage = Math.max(0, Math.ceil(reports.length / pageSize) - 1)
    if (page > lastPage) setPage(lastPage)
  }, [reports, page, pageSize])

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
      const left = a?.[sortKey] ?? ''
      const right = b?.[sortKey] ?? ''
      if (!isNaN(Number(left)) && !isNaN(Number(right))) {
        return Number(left) - Number(right)
      }
      return String(left).localeCompare(String(right))
    })
    return sortDir === 'asc' ? sorted : sorted.reverse()
  }, [filteredReports, sortKey, sortDir])

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

  const nextDisabled = !sortedReports.length || page + 1 >= totalPages
  const prevDisabled = page === 0

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

  const handleDelete = async (boreholeId: string) => {
    if (!boreholeId) return
    if (!window.confirm(`Delete borehole ${boreholeId}?`)) return
    setActionStatus('Deleting...')
    try {
      await deleteReport(boreholeId)
      setActionStatus('Deleted')
      await loadReports()
    } catch (err: any) {
      setActionStatus(`Error: ${err.message}`)
    }
  }

  const startEdit = (row: any) => {
    if (!row?.BoreholeID) return
    setEditTarget(row.BoreholeID)
    const draft: Record<string, string> = {}
    columns.forEach(col => {
      draft[col] = row[col] ?? ''
    })
    setEditDraft(draft)
    window.scrollTo({ top: 0, behavior: 'smooth' })
    setActionStatus(`Editing ${row.BoreholeID}`)
  }

  const saveEdit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!editTarget) return
    setActionStatus('Saving changes...')
    try {
      await updateReport(editTarget, editDraft)
      setActionStatus('Saved')
      setEditTarget(null)
      setEditDraft({})
      await loadReports()
    } catch (err: any) {
      setActionStatus(`Error: ${err.message}`)
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
    link.click()
    URL.revokeObjectURL(url)
  }

  const editableFields: Array<{ key: string; label: string; type?: string }> = [
    { key: 'ProjectName', label: 'Project' },
    { key: 'SiteName', label: 'Site / Zone' },
    { key: 'StartDate', label: 'Start Date', type: 'date' },
    { key: 'EndDate', label: 'End Date', type: 'date' },
    { key: 'DrillingMethod', label: 'Method' },
    { key: 'FinalDepth_m', label: 'Final Depth (m)', type: 'number' },
    { key: 'GroundwaterDepth_m', label: 'Groundwater Depth (m)', type: 'number' },
    { key: 'USCS_Class', label: 'USCS' },
    { key: 'Avg_SPT_N60', label: 'Avg SPT N60', type: 'number' },
    { key: 'Remarks', label: 'Remarks' },
  ]

  return (
    <div>
      <div className="card" style={{ marginBottom: '1rem' }}>
        <h3 style={{ marginTop: 0 }}>Find & Filter</h3>
        <div className="row">
          <div>
            <label>Search</label>
            <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search any field..." />
            <label>Project</label>
            <select value={projectFilter} onChange={e => setProjectFilter(e.target.value)}>
              <option value="">All</option>
              {uniqueValues.projects.map(p => <option key={p} value={p}>{p}</option>)}
            </select>
            <label>Site</label>
            <select value={siteFilter} onChange={e => setSiteFilter(e.target.value)}>
              <option value="">All</option>
              {uniqueValues.sites.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          <div>
            <label>Method</label>
            <select value={methodFilter} onChange={e => setMethodFilter(e.target.value)}>
              <option value="">All</option>
              {uniqueValues.methods.map(m => <option key={m} value={m}>{m}</option>)}
            </select>
            <label>USCS</label>
            <select value={uscsFilter} onChange={e => setUscsFilter(e.target.value)}>
              <option value="">All</option>
              {uniqueValues.uscs.map(u => <option key={u} value={u}>{u}</option>)}
            </select>
            <label>Date range (Start {'->'} End)</label>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '.5rem' }}>
              <input type="date" value={dateFrom} onChange={e => setDateFrom(e.target.value)} />
              <input type="date" value={dateTo} onChange={e => setDateTo(e.target.value)} />
            </div>
          </div>
        </div>
        <div className="actions" style={{ marginTop: '.5rem', flexWrap: 'wrap', gap: '.5rem' }}>
          <button onClick={() => { setSearch(''); setProjectFilter(''); setSiteFilter(''); setMethodFilter(''); setUscsFilter(''); setDateFrom(''); setDateTo(''); }}>Clear Filters</button>
          <button onClick={exportCsv} disabled={!sortedReports.length}>Export CSV</button>
          <span>{actionStatus}</span>
        </div>
      </div>

      {editTarget && (
        <div className="card" style={{ marginBottom: '1rem' }}>
          <h3 style={{ marginTop: 0 }}>Edit Borehole {editTarget}</h3>
          <form onSubmit={saveEdit} className="row">
            {editableFields.map(field => (
              <div key={field.key}>
                <label>{field.label}</label>
                {field.key === 'USCS_Class' ? (
                  <select value={editDraft[field.key] ?? ''} onChange={e => setEditDraft(prev => ({ ...prev, [field.key]: e.target.value }))}>
                    <option value="">Select</option>
                    {['CL','ML','SM','SC','GC','SP','SW'].map(code => (
                      <option key={code} value={code}>{code}</option>
                    ))}
                  </select>
                ) : field.key === 'DrillingMethod' ? (
                  <select value={editDraft[field.key] ?? ''} onChange={e => setEditDraft(prev => ({ ...prev, [field.key]: e.target.value }))}>
                    <option value="">Select</option>
                    {['Wash Boring + SPT','Rotary Wash + SPT','Hollow Stem Auger','Coring + SPT'].map(m => (
                      <option key={m} value={m}>{m}</option>
                    ))}
                  </select>
                ) : field.key === 'Remarks' ? (
                  <textarea value={editDraft[field.key] ?? ''} onChange={e => setEditDraft(prev => ({ ...prev, [field.key]: e.target.value }))} />
                ) : (
                  <input
                    type={field.type || 'text'}
                    value={editDraft[field.key] ?? ''}
                    onChange={e => setEditDraft(prev => ({ ...prev, [field.key]: e.target.value }))}
                  />
                )}
              </div>
            ))}
            <div style={{ gridColumn: '1 / -1', display: 'flex', gap: '.5rem', alignItems: 'center', flexWrap: 'wrap' }}>
              <button type="submit">Save</button>
              <button type="button" onClick={() => { setEditTarget(null); setEditDraft({}); }}>Cancel</button>
            </div>
          </form>
        </div>
      )}

      <div className="actions" style={{ gap: '0.5rem', flexWrap: 'wrap' }}>
        <label style={{ display: 'flex', alignItems: 'center', gap: '.35rem', margin: 0 }}>
          Rows per page
          <select value={pageSize} onChange={e => handlePageSize(Number(e.target.value))}>
            {PAGE_SIZE_OPTIONS.map(opt => (
              <option key={opt} value={opt}>{opt}</option>
            ))}
          </select>
        </label>
        <button onClick={() => setPage(p => Math.max(0, p - 1))} disabled={prevDisabled}>Previous</button>
        <button
          onClick={() => setPage(p => {
            if (!reports.length) return 0
            const lastPage = Math.max(0, Math.ceil(sortedReports.length / pageSize) - 1)
            return Math.min(lastPage, p + 1)
          })}
          disabled={nextDisabled}
        >
          Next
        </button>
        <span>
          {sortedReports.length
            ? `Showing ${startIdx + 1}-${endIdx} of ${sortedReports.length} records`
            : 'No records available'}
        </span>
      </div>

      {loading && <p style={{ marginTop: '1rem' }}>Loading reports...</p>}
      {error && <p style={{ marginTop: '1rem', color: 'var(--danger, #c62828)' }}>{error}</p>}

      {!loading && !error && reports.length === 0 && (
        <div className="card" style={{ marginTop: '1rem' }}>
          <p>No borehole logs have been submitted yet.</p>
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
                    title="Sort"
                  >
                    {col}{sortKey === col ? (sortDir === 'asc' ? ' [asc]' : ' [desc]') : ''}
                  </th>
                ))}
                <th style={{ position: 'sticky', top: 0, background: 'var(--surface, #111827)', padding: '.4rem' }}>Actions</th>
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
                    <button onClick={() => startEdit(row)} style={{ marginRight: '.5rem' }}>Edit</button>
                    <button onClick={() => handleDelete(row.BoreholeID)} style={{ background: 'var(--danger, #c62828)' }}>Delete</button>
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
