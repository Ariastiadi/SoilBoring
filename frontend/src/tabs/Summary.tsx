import { useMemo, useRef, useState } from 'react'
import { getSummary, SummaryResponse } from '../api'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import { LocalNarrative } from '../LocalAI'
import { methodLabel } from '../options'
import { locale, t } from '../i18n'
import { Breakdown, DateInput, PageHead, prettyDates } from '../ui'

function markdownBlock(text: string) {
  const html = DOMPurify.sanitize(marked.parse(text, { breaks: true }) as string)
  return <div className="markdown" dangerouslySetInnerHTML={{ __html: html }} />
}

export default function Summary() {
  const [data, setData] = useState<SummaryResponse | null>(null)
  const [status, setStatus] = useState('')
  const [activePeriod, setActivePeriod] = useState<'weekly' | 'monthly' | null>(null)
  const [mode, setMode] = useState<'weekly' | 'monthly'>('weekly')
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
      await navigator.clipboard.writeText(prettyDates(data.text))
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
    const raw = marked.parse(prettyDates(data.text), { breaks: true }) as string
    return DOMPurify.sanitize(raw)
  }, [data?.text])

  return (
    <div>
      <PageHead title={t('Summaries')} description={t('A written summary of the drilling in one week or one month, with the figures behind it.')} />
      <section className="card" style={{ marginBottom: '1rem' }}>
        <div className="segmented" role="group" aria-label={t('Period')} style={{ marginBottom: '.9rem' }}>
          <button type="button" aria-pressed={mode === 'weekly'} onClick={() => setMode('weekly')}>{t('Weekly (Date Range)')}</button>
          <button type="button" aria-pressed={mode === 'monthly'} onClick={() => setMode('monthly')}>{t('Monthly (Month & Year)')}</button>
        </div>
        <div className="actions" style={{ alignItems: 'flex-end', gap: '.75rem' }}>
          {mode === 'weekly' ? (
            <>
              <div className="field">
                <label htmlFor="summary-from">{t('From')}</label>
                <DateInput id="summary-from" value={weeklyFrom} onChange={setWeeklyFrom} />
              </div>
              <div className="field">
                <label htmlFor="summary-to">{t('To')}</label>
                <DateInput id="summary-to" value={weeklyTo} onChange={setWeeklyTo} />
              </div>
            </>
          ) : (
            <>
              <div className="field">
                <label htmlFor="summary-month">{t('Month')}</label>
                <select id="summary-month" value={monthlyMonth} onChange={e => setMonthlyMonth(e.target.value)}>
                  {Array.from({ length: 12 }, (_, i) => i + 1).map(m => (
                    <option key={m} value={String(m)}>{new Date(0, m - 1).toLocaleString(locale(), { month: 'long' })}</option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label htmlFor="summary-year">{t('Year')}</label>
                <input id="summary-year" type="text" inputMode="numeric" style={{ width: '6rem' }} value={monthlyYear} onChange={e => setMonthlyYear(e.target.value.replace(/\D/g, '').slice(0, 4))} />
              </div>
            </>
          )}
          <button type="button" className="primary" onClick={() => fetchSummary(mode)} disabled={loading}>
            {mode === 'weekly' ? t('Generate Weekly Summary') : t('Generate Monthly Summary')}
          </button>
          {data?.text && <button type="button" onClick={copy}>{t('Copy Detail')}</button>}
          <span className="muted small" role="status">{status}</span>
        </div>
      </section>

      {data && (
        <div style={{ marginTop: '1rem', display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          <div className="card">
            <h2>{t('Executive Summary ({period})', { period: data.period === 'weekly' ? t('weekly') : t('monthly') })}</h2>
            {data.period_label && (
              <p style={{ margin: 0, color: 'var(--muted)', fontSize: '.9rem' }}>
                {t('Period: {label}', { label: prettyDates(data.period_label) })}
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
            <div className="account-grid">
              {methodEntries.length > 0 && <Breakdown title={t('Method Mix')} entries={methodEntries as Array<[string, number]>} label={methodLabel} />}
              {uscsEntries.length > 0 && <Breakdown title={t('USCS Distribution')} entries={uscsEntries as Array<[string, number]>} />}
            </div>
          )}

          {data.highlights && data.highlights.length > 0 && (
            <div className="card">
              <h3>{t('Operational Highlights')}</h3>
              <ul style={{ margin: 0, paddingLeft: '1.25rem' }}>
                {data.highlights.map((line, idx) => (
                  <li key={`${line}-${idx}`} style={{ marginBottom: '.35rem' }}>{prettyDates(line)}</li>
                ))}
              </ul>
            </div>
          )}

          <div className="card">
            <h3>{t('Detailed Breakdown')}</h3>
              {data.period_range && (
                <p style={{ marginTop: 0, color: 'var(--muted)', fontSize: '.85rem' }}>
                  {t('Coverage: {from} -> {to}', { from: prettyDates(data.period_range.from) || '–', to: prettyDates(data.period_range.to) || '–' })}
                </p>
              )}
            {detailHtml ? (
              <div className="markdown" dangerouslySetInnerHTML={{ __html: detailHtml }} />
            ) : (
              <div style={{ whiteSpace: 'pre-wrap', fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace', fontSize: '.95rem' }}>
                {prettyDates(data.text)}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
