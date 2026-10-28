/**
 * Data checks (administrators and managers): duplicate borehole IDs, strata that overlap or
 * leave gaps, depth data deeper than the hole, SPT outliers, missing coordinates, samples and
 * lab tests without a borehole, results waiting for authorisation, CPT without readings.
 * Each finding links to the record. Nothing is changed here.
 */
import { useEffect, useState } from 'react'
import { apiGet } from '../api'
import { t } from '../i18n'
import { useNav } from '../nav'
import { PageHead } from '../ui'
import './ClientReports.css'

type Item = { target: { kind: string, id: string, label: string }, text: string, vars: Record<string, string | number> }
type Check = { key: string, title: string, severity: 'error' | 'warn', count: number, items: Item[] }
type Result = { checks: Check[], days: number, boreholes: number, total: number }

const HELP: Record<string, string> = {
  duplicate_ids: 'IDs used twice, or written differently for what may be the same borehole (BH-01, BH 1).',
  strata: 'Strata should run without overlaps or gaps from the ground surface to the final depth (ASTM D5434).',
  too_deep: 'Strata, SPT, samples and core runs cannot be deeper than the final depth of the hole.',
  spt: 'ASTM D1586 / SNI 4153: the test stops at 50 blows per 150 mm or 100 blows in total (refusal). Large jumps within one stratum are listed for checking.',
  location: 'Coordinates and ground elevation are needed for the location plan and the AGS4 export.',
  orphans: 'Laboratory tests and sample receipts whose borehole or sample is not in the logs.',
  unauthorised: 'Finished tests whose results have not been reviewed and authorised (ISO/IEC 17025 7.8.1.1).',
  cpt_readings: 'A CPT needs at least two readings to be interpreted.',
}

const translateVars = (vars: Record<string, string | number>) =>
  Object.fromEntries(Object.entries(vars).map(([k, v]) => [k, typeof v === 'string' && /^[A-Z][a-z]/.test(v) ? t(v) : v]))

export default function DataChecks() {
  const { go } = useNav()
  const [days, setDays] = useState(7)
  const [data, setData] = useState<Result | null>(null)
  const [error, setError] = useState('')
  const [open, setOpen] = useState<Record<string, boolean>>({})
  useEffect(() => {
    let live = true
    setError('')
    apiGet<Result>(`/api/data-checks?days=${days}`).then(r => { if (live) setData(r) }).catch(e => { if (live) setError(e.message) })
    return () => { live = false }
  }, [days])
  const openTarget = (target: Item['target']) => {
    if (target.kind === 'borehole') go('boreholes', { borehole: target.id })
    else if (target.kind === 'lab_test') go('lab', { open: target.id })
    else if (target.kind === 'cpt') go('cpt', { open: target.id })
    else if (target.kind === 'sample_receipt') go('sample_receipts', { open: target.id })
  }
  return (
    <div>
      <PageHead title={t('Data checks')} description={t('Records that look wrong or incomplete, each with a link to fix it. Nothing is changed here.')} />
      <div className="toolbar dc-toolbar">
        <label htmlFor="dc-days">{t('Lab results waiting for authorisation longer than (days)')}</label>
        <input id="dc-days" type="number" inputMode="numeric" min={0} max={365} value={days} onChange={e => setDays(Math.max(0, Math.min(365, Number(e.target.value) || 0)))} />
      </div>
      {error && <p className="notice error">{error}</p>}
      {!data && !error && <p className="muted">{t('Loading…')}</p>}
      {data && (
        <>
          <p className={`notice ${data.total ? 'warn' : 'ok'}`} role="status">
            {data.total ? t('{n} findings in {b} borehole logs and the related records.', { n: data.total, b: data.boreholes }) : t('No findings. The data passed every check.')}
          </p>
          <div className="dc-grid">
            {data.checks.map(c => (
              <section key={c.key} className={`card dc-check${c.count ? ' has' : ''}`}>
                <div className="dc-head">
                  <h3>{t(c.title)}</h3>
                  <span className={`status ${c.count ? (c.severity === 'error' ? 'bad' : 'warn') : 'ok'}`}>{c.count ? c.count : t('OK')}</span>
                </div>
                <p className="help">{t(HELP[c.key] || '')}</p>
                {c.count > 0 && (
                  <>
                    <ul className="dc-items">
                      {(open[c.key] ? c.items : c.items.slice(0, 6)).map((it, i) => (
                        <li key={i}>
                          <span>{t(it.text, translateVars(it.vars))}</span>
                          <button type="button" className="quiet small" onClick={() => openTarget(it.target)}>{t('Open')}</button>
                        </li>
                      ))}
                    </ul>
                    {c.items.length > 6 && (
                      <button type="button" className="quiet small" onClick={() => setOpen(o => ({ ...o, [c.key]: !o[c.key] }))}>
                        {open[c.key] ? t('Show fewer') : t('Show all {n}', { n: c.items.length })}
                      </button>
                    )}
                  </>
                )}
              </section>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
