import { useMemo, useRef, useState } from 'react'
import { getSummary, SummaryResponse } from '../api'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import { LocalNarrative } from '../LocalAI'
import { methodLabel } from '../options'
import { locale, t } from '../i18n'

function markdownBlock(text: string) {
  const html = DOMPurify.sanitize(marked.parse(text, { breaks: true }) as string)
  return <div className="markdown" dangerouslySetInnerHTML={{ __html: html }} />
}

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
        setStatus(t('Select both start and end dates for the weekly summary.'))
        return
      }
      if (weeklyFrom > weeklyTo) {
        setStatus(t('The start date must not be after the end date.'))
        return
      }
      filters.start_date = weeklyFrom
      filters.end_date = weeklyTo
    } else {
      const year = Number(monthlyYear)
      if (!monthlyMonth || !Number.isInteger(year) || year < 2000 || year > 2100) {
        setStatus(t('Select a month and a year between 2000 and 2100.'))
        return
      }
      filters.month = monthlyMonth
      filters.year = monthlyYear
    }
    const id = ++requestId.current
    setStatus(t('Loading...'))
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
      setStatus(t('Error: {message}', { message: err.message }))
    } finally {
      if (id === requestId.current) setLoading(false)
    }
  }

  const copy = async () => {
    if (!data?.text) return
    try {
      await navigator.clipboard.writeText(data.text)
      setStatus(t('Copied to clipboard'))
    } catch {
      setStatus(t('Copy failed'))
    }
  }

  const stats = data?.stats
  const methodEntries = Object.entries(stats?.method_breakdown || {})
  const uscsEntries = Object.entries(stats?.uscs_breakdown || {})
  const statTiles = stats
    ? [
        { label: t('Boreholes'), value: stats.boreholes ?? '-' },
        { label: t('Projects'), value: stats.projects?.length ?? 0 },
        { label: t('Sites'), value: stats.sites?.length ?? 0 },
        { label: t('Total Meterage (m)'), value: stats.total_meterage_m ?? '-' },
        { label: t('Avg Final Depth (m)'), value: stats.avg_final_depth_m ?? '-' },
        { label: t('Avg GW Depth (m)'), value: stats.avg_groundwater_depth_m ?? '-' },
        { label: t('Avg SPT N60'), value: stats.avg_spt_n60 ?? '-' },
        { label: t('Top Contractor'), value: stats.top_contractor ?? '-' },
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
        <h3 style={{ marginTop: 0 }}>{t('Summary Parameters')}</h3>
        <div className="row">
          <div>
            <h4>{t('Weekly (Date Range)')}</h4>
            <label htmlFor="summary-from">{t('From')}</label>
            <input id="summary-from" type="date" value={weeklyFrom} onChange={e => setWeeklyFrom(e.target.value)} />
            <label htmlFor="summary-to">{t('To')}</label>
            <input id="summary-to" type="date" value={weeklyTo} onChange={e => setWeeklyTo(e.target.value)} />
            <button style={{ marginTop: '.5rem' }} onClick={() => fetchSummary('weekly')} disabled={loading} className={activePeriod === 'weekly' ? 'active' : ''}>{t('Generate Weekly Summary')}</button>
          </div>
          <div>
            <h4>{t('Monthly (Month & Year)')}</h4>
            <label htmlFor="summary-month">{t('Month')}</label>
            <select id="summary-month" value={monthlyMonth} onChange={e => setMonthlyMonth(e.target.value)}>
              {Array.from({ length: 12 }, (_, i) => i + 1).map(m => (
                <option key={m} value={String(m)}>
                  {new Date(0, m - 1).toLocaleString(locale(), { month: 'long' })}
                </option>
              ))}
            </select>
            <label htmlFor="summary-year">{t('Year')}</label>
            <input id="summary-year" type="number" value={monthlyYear} onChange={e => setMonthlyYear(e.target.value)} min={2000} max={2100} />
            <button style={{ marginTop: '.5rem' }} onClick={() => fetchSummary('monthly')} disabled={loading} className={activePeriod === 'monthly' ? 'active' : ''}>{t('Generate Monthly Summary')}</button>
          </div>
        </div>
        <div className="actions" style={{ marginTop: '.5rem', gap: '.5rem', flexWrap: 'wrap' }}>
          <button onClick={copy} disabled={!data?.text}>{t('Copy Detail')}</button>
          <span>{status}</span>
        </div>
      </div>

      {data && (
        <div style={{ marginTop: '1rem', display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          <div className="card">
            <h3 style={{ marginTop: 0 }}>{t('Executive Summary ({period})', { period: data.period === 'weekly' ? t('weekly') : t('monthly') })}</h3>
            {data.period_label && (
              <p style={{ margin: 0, color: 'var(--muted)', fontSize: '.9rem' }}>
                {t('Period: {label}', { label: data.period_label })}
              </p>
            )}
            {stats?.projects && stats.projects.length > 0 && (
              <p style={{ margin: 0, color: 'var(--muted)', fontSize: '.85rem' }}>
                {t('Projects: {list}', { list: stats.projects.join(', ') })}
              </p>
            )}
            {narrativeHtml ? (
              <div className="markdown" dangerouslySetInnerHTML={{ __html: narrativeHtml }} />
            ) : data.narrative_prompt ? (
              <LocalNarrative prompt={data.narrative_prompt} render={markdownBlock} />
            ) : (
              <p style={{ whiteSpace: 'pre-wrap', color: 'var(--muted)' }}>
                {data.narrative || t('Narrative unavailable. Run the summary again once the AI service is reachable.')}
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
                  <h4 style={{ marginTop: 0 }}>{t('Method Mix')}</h4>
                  <ul style={{ margin: 0, paddingLeft: '1.25rem' }}>
                    {methodEntries.map(([method, count]) => (
                      <li key={method}>{methodLabel(method)}: {count}</li>
                    ))}
                  </ul>
                </div>
              )}
              {uscsEntries.length > 0 && (
                <div className="card" style={{ flex: 1 }}>
                  <h4 style={{ marginTop: 0 }}>{t('USCS Distribution')}</h4>
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
              <h4 style={{ marginTop: 0 }}>{t('Operational Highlights')}</h4>
              <ul style={{ margin: 0, paddingLeft: '1.25rem' }}>
                {data.highlights.map((line, idx) => (
                  <li key={`${line}-${idx}`} style={{ marginBottom: '.35rem' }}>{line}</li>
                ))}
              </ul>
            </div>
          )}

          <div className="card">
            <h4 style={{ marginTop: 0 }}>{t('Detailed Breakdown')}</h4>
              {data.period_range && (
                <p style={{ marginTop: 0, color: 'var(--muted)', fontSize: '.85rem' }}>
                  {t('Coverage: {from} -> {to}', { from: data.period_range.from || '-', to: data.period_range.to || '-' })}
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
