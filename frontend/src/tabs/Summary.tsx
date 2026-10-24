import { useMemo, useRef, useState } from 'react'
import { getSummary, SummaryResponse } from '../api'
import { marked } from 'marked'
import DOMPurify from 'dompurify'

export default function Summary() {
  const [data, setData] = useState<SummaryResponse | null>(null)
  const [status, setStatus] = useState('')
  const [activePeriod, setActivePeriod] = useState<'weekly' | 'monthly' | null>(null)
  const [weeklyFrom, setWeeklyFrom] = useState('')
  const [weeklyTo, setWeeklyTo] = useState('')
  const [monthlyMonth, setMonthlyMonth] = useState(() => (new Date().getMonth() + 1).toString())
  const [monthlyYear, setMonthlyYear] = useState(() => new Date().getFullYear().toString())
  const [loading, setLoading] = useState(false)
  // Only the newest request may update the screen (a slow weekly answer must not
  // replace a monthly one requested later).
  const requestId = useRef(0)

  const fetchSummary = async (period: 'weekly' | 'monthly') => {
    const filters: Record<string, string> = {}
    if (period === 'weekly') {
      if (!weeklyFrom || !weeklyTo) {
        setStatus('Select both start and end dates for the weekly summary.')
        return
      }
      if (weeklyFrom > weeklyTo) {
        setStatus('The start date must not be after the end date.')
        return
      }
      filters.start_date = weeklyFrom
      filters.end_date = weeklyTo
    } else {
      const year = Number(monthlyYear)
      if (!monthlyMonth || !Number.isInteger(year) || year < 2000 || year > 2100) {
        setStatus('Select a month and a year between 2000 and 2100.')
        return
      }
      filters.month = monthlyMonth
      filters.year = monthlyYear
    }
    const id = ++requestId.current
    setStatus('Loading...')
    setLoading(true)
    setActivePeriod(period)
    try {
      const payload = await getSummary(period, filters)
      if (id !== requestId.current) return
      setData(payload)
      setStatus('')
    } catch (err: any) {
      if (id !== requestId.current) return
      setData(null)
      setStatus(`Error: ${err.message}`)
    } finally {
      if (id === requestId.current) setLoading(false)
    }
  }

  const copy = async () => {
    if (!data?.text) return
    try {
      await navigator.clipboard.writeText(data.text)
      setStatus('Copied to clipboard')
    } catch {
      setStatus('Copy failed')
    }
  }

  const stats = data?.stats
  const methodEntries = Object.entries(stats?.method_breakdown || {})
  const uscsEntries = Object.entries(stats?.uscs_breakdown || {})
  const statTiles = stats
    ? [
        { label: 'Boreholes', value: stats.boreholes ?? '-' },
        { label: 'Projects', value: stats.projects?.length ?? 0 },
        { label: 'Sites', value: stats.sites?.length ?? 0 },
        { label: 'Total Meterage (m)', value: stats.total_meterage_m ?? '-' },
        { label: 'Avg Final Depth (m)', value: stats.avg_final_depth_m ?? '-' },
        { label: 'Avg GW Depth (m)', value: stats.avg_groundwater_depth_m ?? '-' },
        { label: 'Avg SPT N60', value: stats.avg_spt_n60 ?? '-' },
        { label: 'Top Contractor', value: stats.top_contractor ?? '-' },
      ]
    : []

  const narrativeHtml = useMemo(() => {
    if (!data?.narrative) return null
    const raw = marked.parse(data.narrative, { breaks: true }) as string
    return DOMPurify.sanitize(raw)
  }, [data?.narrative])

  const detailHtml = useMemo(() => {
    if (!data?.text) return null
    const raw = marked.parse(data.text, { breaks: true }) as string
    return DOMPurify.sanitize(raw)
  }, [data?.text])

  return (
    <div>
      <div className="card" style={{ marginBottom: '1rem' }}>
        <h3 style={{ marginTop: 0 }}>Summary Parameters</h3>
        <div className="row">
          <div>
            <h4>Weekly (Date Range)</h4>
            <label htmlFor="summary-from">From</label>
            <input id="summary-from" type="date" value={weeklyFrom} onChange={e => setWeeklyFrom(e.target.value)} />
            <label htmlFor="summary-to">To</label>
            <input id="summary-to" type="date" value={weeklyTo} onChange={e => setWeeklyTo(e.target.value)} />
            <button style={{ marginTop: '.5rem' }} onClick={() => fetchSummary('weekly')} disabled={loading} className={activePeriod === 'weekly' ? 'active' : ''}>Generate Weekly Summary</button>
          </div>
          <div>
            <h4>Monthly (Month & Year)</h4>
            <label htmlFor="summary-month">Month</label>
            <select id="summary-month" value={monthlyMonth} onChange={e => setMonthlyMonth(e.target.value)}>
              {Array.from({ length: 12 }, (_, i) => i + 1).map(m => (
                <option key={m} value={String(m)}>
                  {new Date(0, m - 1).toLocaleString('en-US', { month: 'long' })}
                </option>
              ))}
            </select>
            <label htmlFor="summary-year">Year</label>
            <input id="summary-year" type="number" value={monthlyYear} onChange={e => setMonthlyYear(e.target.value)} min={2000} max={2100} />
            <button style={{ marginTop: '.5rem' }} onClick={() => fetchSummary('monthly')} disabled={loading} className={activePeriod === 'monthly' ? 'active' : ''}>Generate Monthly Summary</button>
          </div>
        </div>
        <div className="actions" style={{ marginTop: '.5rem', gap: '.5rem', flexWrap: 'wrap' }}>
          <button onClick={copy} disabled={!data?.text}>Copy Detail</button>
          <span>{status}</span>
        </div>
      </div>

      {data && (
        <div style={{ marginTop: '1rem', display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          <div className="card">
            <h3 style={{ marginTop: 0 }}>Executive Summary ({data.period})</h3>
            {data.period_label && (
              <p style={{ margin: 0, color: 'var(--muted)', fontSize: '.9rem' }}>
                Period: {data.period_label}
              </p>
            )}
            {stats?.projects && stats.projects.length > 0 && (
              <p style={{ margin: 0, color: 'var(--muted)', fontSize: '.85rem' }}>
                Projects: {stats.projects.join(', ')}
              </p>
            )}
            {narrativeHtml ? (
              <div className="markdown" dangerouslySetInnerHTML={{ __html: narrativeHtml }} />
            ) : (
              <p style={{ whiteSpace: 'pre-wrap', color: 'var(--muted)' }}>
                {data.narrative || 'Narrative unavailable. Run the summary again once the AI service is reachable.'}
              </p>
            )}
          </div>

          {statTiles.length > 0 && (
            <div className="kpis">
              {statTiles.map(tile => (
                <div key={tile.label} className="kpi">
                  <h4>{tile.label}</h4>
                  <p>{tile.value ?? '-'}</p>
                </div>
              ))}
            </div>
          )}

          {(methodEntries.length > 0 || uscsEntries.length > 0) && (
            <div className="row">
              {methodEntries.length > 0 && (
                <div className="card" style={{ flex: 1 }}>
                  <h4 style={{ marginTop: 0 }}>Method Mix</h4>
                  <ul style={{ margin: 0, paddingLeft: '1.25rem' }}>
                    {methodEntries.map(([method, count]) => (
                      <li key={method}>{method}: {count}</li>
                    ))}
                  </ul>
                </div>
              )}
              {uscsEntries.length > 0 && (
                <div className="card" style={{ flex: 1 }}>
                  <h4 style={{ marginTop: 0 }}>USCS Distribution</h4>
                  <ul style={{ margin: 0, paddingLeft: '1.25rem' }}>
                    {uscsEntries.map(([uscs, count]) => (
                      <li key={uscs}>{uscs}: {count}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}

          {data.highlights && data.highlights.length > 0 && (
            <div className="card">
              <h4 style={{ marginTop: 0 }}>Operational Highlights</h4>
              <ul style={{ margin: 0, paddingLeft: '1.25rem' }}>
                {data.highlights.map((line, idx) => (
                  <li key={`${line}-${idx}`} style={{ marginBottom: '.35rem' }}>{line}</li>
                ))}
              </ul>
            </div>
          )}

          <div className="card">
            <h4 style={{ marginTop: 0 }}>Detailed Breakdown</h4>
              {data.period_range && (
                <p style={{ marginTop: 0, color: 'var(--muted)', fontSize: '.85rem' }}>
                  Coverage: {data.period_range.from || '-'} {'->'} {data.period_range.to || '-'}
                </p>
              )}
            {detailHtml ? (
              <div className="markdown" dangerouslySetInnerHTML={{ __html: detailHtml }} />
            ) : (
              <div style={{ whiteSpace: 'pre-wrap', fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace', fontSize: '.95rem' }}>
                {data.text}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
