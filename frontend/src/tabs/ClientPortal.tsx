/**
 * Client portal: what a client account sees. Only its own projects, and of those only the
 * issued (approved and sealed) reports, the authorised laboratory results and the borehole logs.
 * Everything comes from /api/client/...; every other endpoint answers 403 for this role.
 */
import { useEffect, useState } from 'react'
import { apiGet, type Details, type Session } from '../api'
import BoreLog from '../BoreLog'
import ChangePassword from '../ChangePassword'
import { lang, setLang, t } from '../i18n'
import { number } from '../records'
import Security from '../Security'
import { formatSealCode } from '../seal'
import { BrandMark, Icon, PageHead, ScrollTable, formatDate } from '../ui'
import { ReportDocument, type ReportContent, type SealView } from './ClientReports'
import './ClientReports.css'

type PortalReport = { id: string, number: string, version: number, title: string, date: string, current: boolean, code: string }
type PortalProject = {
  id: string, code: string, name: string, location: string, status: string, reports: PortalReport[],
  boreholes: Array<{ id: string, site: string, start: string, final_depth: number | null, gw_depth: number | null }>, lab_results: number
}
type Overview = { clients: Array<{ id: string, name: string }>, projects: PortalProject[] }
type LabRow = {
  id: string, borehole_id: string, sample_ref: string, depth_top: number, depth_base: number | null, test_label: string, standard: string,
  values: Array<{ label: string, value: unknown }>, authorised_at: string, seal_code: string
}

const STATUS: Record<string, string> = { tender: 'Tender', contract: 'Contract', ongoing: 'Ongoing', reporting: 'Reporting', completed: 'Completed', cancelled: 'Cancelled' }
const val = (v: unknown) => (typeof v === 'number' ? number(v) : String(v ?? '–'))

function LabResults({ project }: { project: PortalProject }) {
  const [rows, setRows] = useState<LabRow[] | null>(null)
  const [error, setError] = useState('')
  useEffect(() => { apiGet<LabRow[]>(`/api/client/projects/${project.id}/lab`).then(setRows).catch(e => setError(e.message)) }, [project.id])
  if (error) return <p className="notice error">{error}</p>
  if (!rows) return <p className="muted">{t('Loading…')}</p>
  if (!rows.length) return <p className="muted small">{t('No authorised laboratory results yet.')}</p>
  return (
    <ScrollTable>
      <table className="data-table portal-lab">
        <thead><tr><th>{t('Borehole')}</th><th>{t('Sample')}</th><th className="num">{t('Depth (m)')}</th><th>{t('Test')}</th><th>{t('Results')}</th><th>{t('Seal')}</th></tr></thead>
        <tbody>
          {rows.map(r => (
            <tr key={r.id}>
              <td data-label={t('Borehole')}>{r.borehole_id}</td>
              <td data-label={t('Sample')}>{r.sample_ref}</td>
              <td data-label={t('Depth (m)')} className="num nowrap">{number(r.depth_top)}{r.depth_base !== null && r.depth_base !== undefined ? `–${number(r.depth_base)}` : ''}</td>
              <td data-label={t('Test')}>{t(r.test_label)}{r.standard && <div className="bh-sub">{r.standard}</div>}</td>
              <td data-label={t('Results')}>{r.values.map(v => `${t(v.label)} ${val(v.value)}`).join('; ')}</td>
              <td data-label={t('Seal')} className="nowrap">{r.seal_code ? <a href={`/verify/${r.seal_code}`} target="_blank" rel="noreferrer">{r.seal_code}</a> : '–'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </ScrollTable>
  )
}

function ProjectCard({ project, onReport, onLog }: { project: PortalProject, onReport: (r: PortalReport) => void, onLog: (id: string) => void }) {
  const [showLab, setShowLab] = useState(false)
  return (
    <section className="card portal-project">
      <div className="portal-project-head">
        <div>
          <h2>{project.name}</h2>
          <p className="muted small" style={{ margin: 0 }}>{[project.code, project.location].filter(Boolean).join(' · ')}</p>
        </div>
        <span className="status active">{t(STATUS[project.status] || project.status)}</span>
      </div>

      <h3>{t('Reports')} <span className="muted">{project.reports.length}</span></h3>
      {project.reports.length ? (
        <ul className="portal-list">
          {project.reports.map(r => (
            <li key={r.id}>
              <div>
                <strong>{r.number} · v{r.version}</strong> {!r.current && <span className="status warn">{t('Superseded by a newer version')}</span>}
                <div>{r.title}</div>
                <div className="muted small">{formatDate(r.date)} · {t('Seal')} {r.code}</div>
              </div>
              <button type="button" className={r.current ? 'primary' : ''} onClick={() => onReport(r)}><Icon name="print" />{t('Open report')}</button>
            </li>
          ))}
        </ul>
      ) : <p className="muted small">{t('No report has been issued for this project yet.')}</p>}

      <h3>{t('Borehole logs')} <span className="muted">{project.boreholes.length}</span></h3>
      {project.boreholes.length ? (
        <ul className="portal-list">
          {project.boreholes.map(b => (
            <li key={b.id}>
              <div>
                <strong>{b.id}</strong>{b.site && <span className="muted"> · {b.site}</span>}
                <div className="muted small">{formatDate(b.start)} · {t('Depth')} {b.final_depth === null ? '–' : `${number(b.final_depth)} m`} · {t('Groundwater')} {b.gw_depth === null ? t('Not encountered') : `${number(b.gw_depth)} m`}</div>
              </div>
              <button type="button" onClick={() => onLog(b.id)}><Icon name="print" />{t('Bore log')}</button>
            </li>
          ))}
        </ul>
      ) : <p className="muted small">{t('No borehole logs yet.')}</p>}

      <h3>{t('Laboratory results')} <span className="muted">{project.lab_results}</span></h3>
      {project.lab_results > 0 && (showLab ? <LabResults project={project} /> :
        <button type="button" onClick={() => setShowLab(true)}>{t('Show authorised results')}</button>)}
      {project.lab_results === 0 && <p className="muted small">{t('No authorised laboratory results yet.')}</p>}
    </section>
  )
}

export default function ClientPortal({ email, orgName, onLogout, onSession }: {
  email: string, orgName: string, onLogout: () => void, onSession: (s: Session) => void
}) {
  const [data, setData] = useState<Overview | null>(null)
  const [error, setError] = useState('')
  const [view, setView] = useState<'projects' | 'account'>('projects')
  const [report, setReport] = useState<{ content: ReportContent, seal: SealView } | null>(null)
  const [log, setLog] = useState<{ report: Record<string, string>, details: Details } | null>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => { apiGet<Overview>('/api/client/overview').then(setData).catch(e => setError(e.message)) }, [])
  const open = async <T,>(path: string, done: (x: T) => void) => {
    setBusy(true); setError('')
    try { done(await apiGet<T>(path)) } catch (e: any) { setError(e.message) } finally { setBusy(false) }
  }
  return (
    <div className="portal">
      <header className="portal-top">
        <div className="brand"><BrandMark /><span className="brand-name">{orgName || 'SoilBoring'}<span className="brand-org">{t('Client portal')}</span></span></div>
        <nav className="actions" aria-label={t('Main menu')}>
          <button type="button" className={view === 'projects' ? 'primary small' : 'small'} onClick={() => setView('projects')}><Icon name="folder" />{t('Projects')}</button>
          <button type="button" className={view === 'account' ? 'primary small' : 'small'} onClick={() => setView('account')}><Icon name="account" />{t('Account & security')}</button>
          <button type="button" className="small" onClick={() => setLang(lang() === 'id' ? 'en' : 'id')}><Icon name="language" />{lang() === 'id' ? 'English' : 'Bahasa Indonesia'}</button>
          <button type="button" className="small" onClick={onLogout}><Icon name="logout" />{t('Sign Out')}</button>
        </nav>
      </header>
      <main className="portal-main">
        {view === 'account' ? (
          <>
            <PageHead title={t('Account & security')} description={t('Signed in as {email}.', { email })} />
            <div className="account-grid"><ChangePassword onChanged={onSession} /><Security /></div>
          </>
        ) : (
          <>
            <PageHead title={data?.clients.length ? data.clients.map(c => c.name).join(', ') : t('Client portal')}
              description={t('Issued reports, authorised laboratory results and borehole logs of your projects. Each issued document carries a seal code you can check at any time.')} />
            {error && <p className="notice error">{error}</p>}
            {busy && <p className="muted" role="status">{t('Loading…')}</p>}
            {!data && !error && <p className="muted">{t('Loading…')}</p>}
            {data && !data.projects.length && <div className="card"><p style={{ margin: 0 }}>{t('No projects are linked to your account yet. Please contact us.')}</p></div>}
            {data?.projects.map(p => (
              <ProjectCard key={p.id} project={p}
                onReport={r => { void open<{ content: ReportContent, seal: SealView }>(`/api/client/reports/${r.id}`, setReport) }}
                onLog={id => { void open<{ report: Record<string, string>, details: Details }>(`/api/client/boreholes/${encodeURIComponent(id)}`, setLog) }} />
            ))}
          </>
        )}
      </main>
      {report && <ReportDocument content={report.content} seal={{ ...report.seal, code: formatSealCode(report.seal.code) }} onClose={() => setReport(null)} />}
      {log && <BoreLog report={log.report} details={log.details} onClose={() => setLog(null)} />}
    </div>
  )
}
