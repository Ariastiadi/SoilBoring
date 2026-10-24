import { useEffect, useMemo, useState } from 'react'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import { LocalNarrative } from '../LocalAI'
import { methodLabel } from '../options'
import { t } from '../i18n'

function markdownBlock(text: string) {
  const html = DOMPurify.sanitize(marked.parse(text, { breaks: true }) as string)
  return <div className="markdown" dangerouslySetInnerHTML={{ __html: html }} />
}
import { DashboardResponse, getDashboard } from '../api'

// "12.5 m", or "-" when the value was not recorded (never "- m").
const metres = (value?: number | null) => (value === null || value === undefined ? '-' : `${value} m`)

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
      {status && <p>{status}</p>}
      {data && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          <div className="card">
            <h3 style={{ marginTop: 0 }}>{t('Executive Summary')}</h3>
            {periodLabel && (
              <p style={{ marginTop: 0, color: 'var(--muted)', fontSize: '.9rem' }}>
                {t('Performance Period: {label}', { label: periodLabel })}
              </p>
            )}
            {data.project_list && data.project_list.length > 0 && (
              <p style={{ marginTop: 0, color: 'var(--muted)', fontSize: '.85rem' }}>
                {t('Projects in view: {list}', { list: data.project_list.join(', ') })}
              </p>
            )}
            {narrativeHtml ? (
              <div className="markdown" dangerouslySetInnerHTML={{ __html: narrativeHtml }} />
            ) : data.narrative_prompt ? (
              <LocalNarrative prompt={data.narrative_prompt} render={markdownBlock} />
            ) : (
              <p style={{ color: 'var(--muted)', whiteSpace: 'pre-wrap' }}>
                {data.narrative || t('Narrative unavailable. Try reloading once the AI service is online.')}
              </p>
            )}
          </div>

          <div className="kpis">
            <div className="kpi">
              <h3>{t('Total Boreholes')}</h3>
              <p>{data.total_boreholes}</p>
            </div>
            <div className="kpi">
              <h3>{t('Total Meterage (m)')}</h3>
              <p>{data.total_meterage_m ?? '-'}</p>
            </div>
            <div className="kpi">
              <h3>{t('Avg Final Depth (m)')}</h3>
              <p>{data.avg_final_depth_m ?? '-'}</p>
            </div>
            <div className="kpi">
              <h3>{t('Avg GW Depth (m)')}</h3>
              <p>{data.avg_groundwater_depth_m ?? '-'}</p>
            </div>
            <div className="kpi">
              <h3>{t('Active Projects')}</h3>
              <p>{data.active_projects ?? '-'}</p>
            </div>
            <div className="kpi">
              <h3>{t('Top Contractor')}</h3>
              <p>{data.top_contractor ?? '-'}</p>
            </div>
          </div>

          {(methodBreakdown.length > 0 || uscsBreakdown.length > 0) && (
            <div className="row">
              {methodBreakdown.length > 0 && (
                <div className="card" style={{ flex: 1 }}>
                  <h4 style={{ marginTop: 0 }}>{t('Method Breakdown')}</h4>
                  <ul style={{ margin: 0, paddingLeft: '1.25rem' }}>
                    {methodBreakdown.map(([method, count]) => (
                      <li key={method}>{methodLabel(method)}: {count}</li>
                    ))}
                  </ul>
                </div>
              )}
              {uscsBreakdown.length > 0 && (
                <div className="card" style={{ flex: 1 }}>
                  <h4 style={{ marginTop: 0 }}>{t('USCS Classes')}</h4>
                  <ul style={{ margin: 0, paddingLeft: '1.25rem' }}>
                    {uscsBreakdown.map(([cls, count]) => (
                      <li key={cls}>{cls}: {count}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}

          {recent.length > 0 && (
            <div className="card">
              <h4 style={{ marginTop: 0 }}>{t('Most Recent Activities')}</h4>
              <ul style={{ margin: 0, paddingLeft: '1.25rem' }}>
                {recent.map((item, idx) => (
                  <li key={`${item?.borehole_id ?? 'row'}-${idx}`} style={{ marginBottom: '.35rem' }}>
                    <strong>{item?.start_date ?? '-'}</strong> - {item?.borehole_id ?? 'BH ?'} {item?.project ? `@ ${item?.project}` : ''} ({item?.site ?? t('Site ?')}) | {t('Depth {depth}, GW {gw}', { depth: metres(item?.final_depth_m), gw: metres(item?.groundwater_depth_m) })}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
