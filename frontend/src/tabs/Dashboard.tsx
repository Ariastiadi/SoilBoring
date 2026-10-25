import { useEffect, useMemo, useState } from 'react'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import { LocalNarrative } from '../LocalAI'
import { methodLabel } from '../options'
import { t } from '../i18n'
import { Breakdown, PageHead, formatDate, prettyDates } from '../ui'

function markdownBlock(text: string) {
  const html = DOMPurify.sanitize(marked.parse(text, { breaks: true }) as string)
  return <div className="markdown" dangerouslySetInnerHTML={{ __html: html }} />
}
import { DashboardResponse, getDashboard } from '../api'

// "12.5 m", or "-" when the value was not recorded (never "- m").
const metres = (value?: number | null) => (value === null || value === undefined ? '–' : `${value} m`)

export default function Dashboard() {
  const [data, setData] = useState<DashboardResponse | null>(null)
  const [status, setStatus] = useState(() => t('Loading...'))

  useEffect(() => {
    const load = async () => {
      try {
        const payload = await getDashboard()
        setData(payload)
        setStatus('')
      } catch (err: any) {
        setStatus(t('Error: {message}', { message: err.message }))
      }
    }
    load()
  }, [])

  const narrativeHtml = useMemo(() => {
    if (!data?.narrative) return null
    const raw = marked.parse(data.narrative, { breaks: true }) as string
    return DOMPurify.sanitize(raw)
  }, [data?.narrative])

  const methodBreakdown = data?.method_breakdown ? Object.entries(data.method_breakdown) : []
  const uscsBreakdown = data?.uscs_breakdown ? Object.entries(data.uscs_breakdown) : []
  const recent = data?.recent_reports || []
  const periodLabel = data?.period_label || (data?.period_range ? `${data.period_range.from || '-'} -> ${data.period_range.to || '-'}` : null)

  return (
    <div>
      <PageHead title={t('Dashboard')} description={periodLabel ? t('Performance Period: {label}', { label: prettyDates(periodLabel).replace('->', '–') }) : undefined} />
      {status && <p className="muted">{status}</p>}
      {data && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          <div className="kpis">
            <div className="kpi"><h3>{t('Total Boreholes')}</h3><p>{data.total_boreholes}</p></div>
            <div className="kpi"><h3>{t('Total Meterage (m)')}</h3><p>{data.total_meterage_m ?? '-'}</p></div>
            <div className="kpi"><h3>{t('Avg Final Depth (m)')}</h3><p>{data.avg_final_depth_m ?? '-'}</p></div>
            <div className="kpi"><h3>{t('Avg GW Depth (m)')}</h3><p>{data.avg_groundwater_depth_m ?? '-'}</p></div>
            <div className="kpi"><h3>{t('Active Projects')}</h3><p>{data.active_projects ?? '-'}</p></div>
            <div className="kpi"><h3>{t('Top Contractor')}</h3><p style={{ fontSize: '1.15rem' }}>{data.top_contractor ?? '-'}</p></div>
          </div>

          <section className="card">
            <h2>{t('Executive Summary')}</h2>
            {data.project_list && data.project_list.length > 0 && (
              <p className="muted small" style={{ marginTop: 0 }}>{t('Projects in view: {list}', { list: data.project_list.join(', ') })}</p>
            )}
            {narrativeHtml ? (
              <div className="markdown" dangerouslySetInnerHTML={{ __html: narrativeHtml }} />
            ) : data.narrative_prompt ? (
              <LocalNarrative prompt={data.narrative_prompt} render={markdownBlock} />
            ) : (
              <p className="muted" style={{ whiteSpace: 'pre-wrap' }}>
                {data.narrative || t('Narrative unavailable. Try reloading once the AI service is online.')}
              </p>
            )}
          </section>

          {(methodBreakdown.length > 0 || uscsBreakdown.length > 0) && (
            <div className="account-grid">
              {methodBreakdown.length > 0 && <Breakdown title={t('Method Breakdown')} entries={methodBreakdown as Array<[string, number]>} label={methodLabel} />}
              {uscsBreakdown.length > 0 && <Breakdown title={t('USCS Classes')} entries={uscsBreakdown as Array<[string, number]>} />}
            </div>
          )}

          {recent.length > 0 && (
            <section>
              <h3>{t('Most Recent Activities')}</h3>
              <div className="table-wrap">
                <table className="data-table">
                  <thead>
                    <tr><th>{t('Start Date')}</th><th>{t('Borehole')}</th><th>{t('Project')}</th><th className="num">{t('Depth')}</th><th className="num">{t('Groundwater')}</th></tr>
                  </thead>
                  <tbody>
                    {recent.map((item, idx) => (
                      <tr key={`${item?.borehole_id ?? 'row'}-${idx}`}>
                        <td className="nowrap">{formatDate(item?.start_date) || '–'}</td>
                        <td><strong>{item?.borehole_id ?? '–'}</strong></td>
                        <td>{[item?.project, item?.site].filter(Boolean).join(', ')}</td>
                        <td className="num nowrap">{metres(item?.final_depth_m)}</td>
                        <td className="num nowrap">{metres(item?.groundwater_depth_m)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}
        </div>
      )}
    </div>
  )
}
