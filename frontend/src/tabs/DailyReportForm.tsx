import { useEffect, useMemo, useState } from 'react'
import { submitReport } from '../outbox'
import { CORE_SIZES, METHOD_OPTIONS as methodOptions, USCS_OPTIONS as uscsOptions, coreSizeLabel, methodLabel } from '../options'
import { t } from '../i18n'
import { DateInput, PageHead } from '../ui'

const DRAFT_KEY = 'borehole-form-draft'

// Typed as text: a number input would silently turn "1,5" into 15.
const decimal = (v: string) => v.replace(/,/g, '.')

type Values = {
  BoreholeID: string; ProjectName: string; SiteName: string; Latitude: string; Longitude: string; GroundElevation_mRL: string
  StartDate: string; EndDate: string; DrillingMethod: string; DrillRig: string; CoreSize: string; BoreholeDiameter_mm: string
  TargetDepth_m: string; FinalDepth_m: string; CasingInstalled_mm: string; GroundwaterDepth_m: string; GroundwaterEncountered: boolean
  SoilDescription: string; USCS_Class: string; Avg_SPT_N60: string; Contractor: string; LoggingGeologist: string; Remarks: string
}

const EMPTY: Values = {
  BoreholeID: '', ProjectName: '', SiteName: '', Latitude: '', Longitude: '', GroundElevation_mRL: '',
  StartDate: '', EndDate: '', DrillingMethod: methodOptions[0], DrillRig: '', CoreSize: '', BoreholeDiameter_mm: '150',
  TargetDepth_m: '', FinalDepth_m: '', CasingInstalled_mm: '100', GroundwaterDepth_m: '', GroundwaterEncountered: true,
  SoilDescription: '', USCS_Class: uscsOptions[0], Avg_SPT_N60: '', Contractor: '', LoggingGeologist: '', Remarks: '',
}

type Key = keyof Values
const REQUIRED: Array<[Key, string]> = [
  ['BoreholeID', 'Borehole ID'],
  ['ProjectName', 'Project'],
  ['SiteName', 'Site / Zone'],
  ['StartDate', 'Start Date'],
  ['EndDate', 'End Date'],
  ['Contractor', 'Contractor'],
  ['FinalDepth_m', 'Final Depth (m)'],
]
const SECTIONS: Array<{ id: string, title: string, keys: Key[] }> = [
  { id: 'sec-id', title: 'Borehole and location', keys: ['BoreholeID', 'ProjectName', 'SiteName', 'Latitude', 'Longitude', 'GroundElevation_mRL'] },
  { id: 'sec-team', title: 'Dates and team', keys: ['StartDate', 'EndDate', 'Contractor', 'LoggingGeologist'] },
  { id: 'sec-drill', title: 'Drilling', keys: ['DrillingMethod', 'DrillRig', 'CoreSize', 'BoreholeDiameter_mm', 'CasingInstalled_mm', 'TargetDepth_m', 'FinalDepth_m', 'Avg_SPT_N60'] },
  { id: 'sec-soil', title: 'Soil and groundwater', keys: ['GroundwaterDepth_m', 'USCS_Class', 'SoilDescription'] },
  { id: 'sec-notes', title: 'Notes', keys: ['Remarks'] },
]

function loadDraft(): Values {
  try {
    const raw = window.localStorage.getItem(DRAFT_KEY)
    return raw ? { ...EMPTY, ...JSON.parse(raw) } : EMPTY
  } catch {
    return EMPTY
  }
}

export default function DailyReportForm({ onDone, defaults }: { onDone?: () => void, defaults?: Record<string, string> }) {
  const [v, setV] = useState<Values>(() => ({ ...loadDraft(), ...(defaults || {}) }))
  const [errors, setErrors] = useState<string[]>([])
  const [status, setStatus] = useState('')
  const [saved, setSaved] = useState<{ id: string, queued: boolean } | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [locating, setLocating] = useState(false)

  const set = <K extends Key>(key: K, value: Values[K]) => setV(prev => ({ ...prev, [key]: value }))
  const text = (key: Key) => ({ value: String(v[key] ?? ''), onChange: (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => set(key, e.target.value as never) })
  const number = (key: Key) => ({
    type: 'text', inputMode: 'decimal' as const, value: String(v[key] ?? ''),
    onChange: (e: React.ChangeEvent<HTMLInputElement>) => set(key, decimal(e.target.value) as never),
  })

  // The draft stays on this device until the log is sent, so field work is never lost.
  useEffect(() => {
    try { window.localStorage.setItem(DRAFT_KEY, JSON.stringify(v)) } catch { /* storage full */ }
  }, [v])

  const missing = REQUIRED.filter(([key]) => String(v[key] ?? '').trim() === '')
  const filledIn = (keys: Key[]) => keys.filter(k => {
    const val = v[k]
    return typeof val === 'boolean' ? false : String(val ?? '').trim() !== '' && val !== EMPTY[k]
  }).length

  const resetForm = () => {
    setV(EMPTY)
    setErrors([])
    setStatus('')
    try { window.localStorage.removeItem(DRAFT_KEY) } catch { /* ignore */ }
  }

  const validate = () => {
    const out: string[] = []
    const toNumber = (val: string) => {
      if (val === '') return null
      const n = Number(val)
      return Number.isFinite(n) ? n : NaN
    }
    missing.forEach(([, label]) => out.push(t('{label} is required.', { label: t(label) })))
    if (/[/\\?#%\u0000-\u001f]/.test(v.BoreholeID) || ['.', '..'].includes(v.BoreholeID.trim())) {
      out.push(t('Borehole ID cannot contain / \\ ? # % characters or be "." / "..".'))
    }
    const lat = toNumber(v.Latitude)
    if (lat !== null && (Number.isNaN(lat) || lat < -90 || lat > 90)) out.push(t('Latitude must be between -90 and 90.'))
    const lon = toNumber(v.Longitude)
    if (lon !== null && (Number.isNaN(lon) || lon < -180 || lon > 180)) out.push(t('Longitude must be between -180 and 180.'))
    const diameter = toNumber(v.BoreholeDiameter_mm)
    if (Number.isNaN(diameter) || (diameter !== null && diameter <= 0)) out.push(t('Borehole diameter must be a positive number.'))
    const finalDepth = toNumber(v.FinalDepth_m)
    if (v.FinalDepth_m !== '' && (Number.isNaN(finalDepth) || (finalDepth !== null && finalDepth < 0))) {
      out.push(t('Final depth is required and must be a number of 0 or more.'))
    }
    for (const [label, value] of [[t('Casing'), v.CasingInstalled_mm], [t('Target depth'), v.TargetDepth_m], [t('Groundwater depth'), v.GroundwaterDepth_m], [t('Average SPT N60'), v.Avg_SPT_N60]] as const) {
      const n = toNumber(value)
      if (Number.isNaN(n) || (n !== null && n < 0)) out.push(t('{label} cannot be negative.', { label }))
    }
    if (v.StartDate && v.EndDate && v.StartDate > v.EndDate) out.push(t('Start date must be earlier than end date.'))
    return out
  }

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    const found = validate()
    setErrors(found)
    if (found.length) return
    // Drilling past the target (e.g. to reach bearing strata) is normal, so this only asks.
    const target = Number(v.TargetDepth_m)
    const final = Number(v.FinalDepth_m)
    if (v.TargetDepth_m !== '' && target > 0 && final > target * 1.5 &&
        !window.confirm(t('Final depth {final} m is more than 1.5x the target depth {target} m. Save anyway?', { final, target }))) {
      setStatus(t('Not saved. Check the final and target depths.'))
      return
    }
    setStatus(t('Submitting...'))
    setIsSubmitting(true)
    try {
      const result = await submitReport({ ...v })
      setSaved({ id: v.BoreholeID, queued: result !== 'sent' })
      setStatus('')
      resetForm()
      window.scrollTo({ top: 0, behavior: 'smooth' })
    } catch (err: any) {
      setStatus(t('Error: {message}', { message: err.message }))
    } finally {
      setIsSubmitting(false)
    }
  }

  const useMyLocation = () => {
    if (!navigator.geolocation) { setStatus(t('This device cannot share its location.')); return }
    setLocating(true)
    navigator.geolocation.getCurrentPosition(pos => {
      set('Latitude', pos.coords.latitude.toFixed(6))
      set('Longitude', pos.coords.longitude.toFixed(6))
      setLocating(false)
    }, err => {
      setStatus(t('Location not available: {why}', { why: err.message }))
      setLocating(false)
    }, { enableHighAccuracy: true, timeout: 15000 })
  }

  const coreChange = (next: string) => {
    const size = CORE_SIZES.find(s => s.code === next)
    // Fill the hole diameter only while it still holds the default or a previous core size.
    const auto = v.BoreholeDiameter_mm === '' || v.BoreholeDiameter_mm === '150' || CORE_SIZES.some(s => String(s.hole) === v.BoreholeDiameter_mm)
    setV(prev => ({ ...prev, CoreSize: next, ...(size && auto ? { BoreholeDiameter_mm: String(size.hole) } : {}) }))
  }

  const sectionCounts = useMemo(() => SECTIONS.map(s => [filledIn(s.keys), s.keys.length]), [v]) // eslint-disable-line react-hooks/exhaustive-deps
  const req = (label: string) => <>{t(label)}<span className="tag-req">{t('required')}</span></>

  return (
    <div>
      <PageHead title={t('New borehole log')} description={t('One log per borehole. Depth data (strata, SPT, samples, core) and photos are added afterwards from the borehole list.')} />

      {saved && (
        <div className={`notice ${saved.queued ? 'warn' : 'ok'}`} role="status" style={{ display: 'flex', gap: '.75rem', alignItems: 'center', flexWrap: 'wrap' }}>
          <span style={{ flex: 1 }}>
            {saved.queued
              ? t('No connection: {id} is kept on this device and will be sent automatically when you are back online.', { id: saved.id })
              : t('{id} saved. Add its depth data and photos from the borehole list.', { id: saved.id })}
          </span>
          {onDone && <button type="button" onClick={onDone}>{t('Go to boreholes')}</button>}
          <button type="button" className="quiet" onClick={() => setSaved(null)}>{t('Close')}</button>
        </div>
      )}

      <form onSubmit={onSubmit} noValidate className="form-layout">
        <div className="card">
          <section className="section" id="sec-id" aria-labelledby="sec-id-h">
            <h2 id="sec-id-h">{t('Borehole and location')}</h2>
            <p className="muted">{t('Which hole this is and where it was drilled.')}</p>
            <div className="fields">
              <div className="field">
                <label htmlFor="f-id">{req('Borehole ID')}</label>
                <input id="f-id" {...text('BoreholeID')} maxLength={64} autoComplete="off" aria-describedby="f-id-help" />
                <p className="help" id="f-id-help">{t('The code from the drilling programme. Must be unique.')}</p>
              </div>
              <div className="field">
                <label htmlFor="f-project">{req('Project')}</label>
                <input id="f-project" {...text('ProjectName')} />
              </div>
              <div className="field">
                <label htmlFor="f-site">{req('Site / Zone')}</label>
                <input id="f-site" {...text('SiteName')} />
              </div>
              <div className="field">
                <label htmlFor="f-elev">{t('Ground Elevation (mRL)')}</label>
                <input id="f-elev" {...number('GroundElevation_mRL')} inputMode="text" />
                <p className="help">{t('Relative to mRL or the local datum.')}</p>
              </div>
              <div className="field">
                <label htmlFor="f-lat">{t('Latitude')}</label>
                <input id="f-lat" {...number('Latitude')} inputMode="text" />
              </div>
              <div className="field">
                <label htmlFor="f-lon">{t('Longitude')}</label>
                <input id="f-lon" {...number('Longitude')} inputMode="text" />
              </div>
              <div className="wide actions" style={{ marginTop: '-.4rem' }}>
                <p className="help" style={{ margin: 0, flex: 1, fontSize: '.82rem', color: 'var(--ink-2)' }}>{t('Decimal degrees. South latitudes are negative (Jakarta is about -6.2).')}</p>
                <button type="button" className="small" onClick={useMyLocation} disabled={locating}>{locating ? t('Finding location…') : t('Use my location')}</button>
              </div>
            </div>
          </section>

          <section className="section" id="sec-team" aria-labelledby="sec-team-h">
            <h2 id="sec-team-h">{t('Dates and team')}</h2>
            <div className="fields">
              <div className="field">
                <label htmlFor="f-start">{req('Start Date')}</label>
                <DateInput id="f-start" value={v.StartDate} onChange={d => set('StartDate', d)} required />
              </div>
              <div className="field">
                <label htmlFor="f-end">{req('End Date')}</label>
                <DateInput id="f-end" value={v.EndDate} onChange={d => set('EndDate', d)} required />
                <p className="help">{t('Still drilling? Enter the planned end date; the borehole shows as in progress until then.')}</p>
              </div>
              <div className="field">
                <label htmlFor="f-contractor">{req('Contractor')}</label>
                <input id="f-contractor" {...text('Contractor')} />
              </div>
              <div className="field">
                <label htmlFor="f-geo">{t('Logging Geologist')}</label>
                <input id="f-geo" {...text('LoggingGeologist')} />
              </div>
            </div>
          </section>

          <section className="section" id="sec-drill" aria-labelledby="sec-drill-h">
            <h2 id="sec-drill-h">{t('Drilling')}</h2>
            <div className="fields">
              <div className="field">
                <label htmlFor="f-method">{t('Drilling Method')}</label>
                <select id="f-method" value={v.DrillingMethod} onChange={e => set('DrillingMethod', e.target.value)}>
                  {methodOptions.map(m => <option key={m} value={m}>{methodLabel(m)}</option>)}
                </select>
              </div>
              <div className="field">
                <label htmlFor="f-rig">{t('Drill Rig / Plant')}</label>
                <input id="f-rig" {...text('DrillRig')} maxLength={100} />
              </div>
              <div className="field">
                <label htmlFor="f-core">{t('Core Size (wireline)')}</label>
                <select id="f-core" value={v.CoreSize} onChange={e => coreChange(e.target.value)}>
                  <option value="">{t('Not cored')}</option>
                  {CORE_SIZES.map(s => <option key={s.code} value={s.code}>{coreSizeLabel(s.code)}</option>)}
                </select>
              </div>
              <div className="field">
                <label htmlFor="f-diam">{t('Borehole Diameter (mm)')}</label>
                <input id="f-diam" {...number('BoreholeDiameter_mm')} />
              </div>
              <div className="field">
                <label htmlFor="f-target">{t('Target Depth (m)')}</label>
                <input id="f-target" {...number('TargetDepth_m')} />
              </div>
              <div className="field">
                <label htmlFor="f-final">{req('Final Depth (m)')}</label>
                <input id="f-final" {...number('FinalDepth_m')} />
              </div>
              <div className="field">
                <label htmlFor="f-casing">{t('Casing Installed (mm)')}</label>
                <input id="f-casing" {...number('CasingInstalled_mm')} />
              </div>
              <div className="field">
                <label htmlFor="f-spt">{t('Average SPT N60')}</label>
                <input id="f-spt" {...number('Avg_SPT_N60')} />
                <p className="help">{t('Each SPT can be entered later under depth data.')}</p>
              </div>
            </div>
          </section>

          <section className="section" id="sec-soil" aria-labelledby="sec-soil-h">
            <h2 id="sec-soil-h">{t('Soil and groundwater')}</h2>
            <div className="fields">
              <label className="checkbox wide">
                <input type="checkbox" checked={v.GroundwaterEncountered} onChange={e => set('GroundwaterEncountered', e.target.checked)} />
                {t('Groundwater encountered')}
              </label>
              <div className="field">
                <label htmlFor="f-gw">{t('Groundwater Depth (m)')}</label>
                <input id="f-gw" {...number('GroundwaterDepth_m')} disabled={!v.GroundwaterEncountered} />
              </div>
              <div className="field">
                <label htmlFor="f-uscs">{t('Main soil type (USCS)')}</label>
                <select id="f-uscs" value={v.USCS_Class} onChange={e => set('USCS_Class', e.target.value)}>
                  {uscsOptions.map(code => <option key={code} value={code}>{code}</option>)}
                </select>
              </div>
              <div className="field wide">
                <label htmlFor="f-soil">{t('Soil Description')}</label>
                <textarea id="f-soil" {...text('SoilDescription')} rows={3} />
                <p className="help">{t('The dominant soil. Layer-by-layer descriptions go in the depth data.')}</p>
              </div>
            </div>
          </section>

          <section className="section" id="sec-notes" aria-labelledby="sec-notes-h">
            <h2 id="sec-notes-h">{t('Notes')}</h2>
            <div className="field">
              <label htmlFor="f-remarks">{t('Remarks')}</label>
              <textarea id="f-remarks" {...text('Remarks')} rows={3} />
              <p className="help">{t('Access, utilities, safety, anything the next shift should know.')}</p>
            </div>
          </section>
        </div>

        <aside className="form-side">
          <div className="card section-links-card">
            <h3>{t('Sections')}</h3>
            <nav className="section-links">
              {SECTIONS.map((s, i) => (
                <a key={s.id} href={`#${s.id}`}>{t(s.title)}<span>{sectionCounts[i][0]}/{sectionCounts[i][1]}</span></a>
              ))}
            </nav>
          </div>
          <div className="card">
            <h3>{missing.length ? t('Still needed') : t('Ready to submit')}</h3>
            <ul className="checklist">
              {REQUIRED.map(([key, label]) => (
                <li key={key} className={String(v[key] ?? '').trim() ? 'done' : ''}>{t(label)}</li>
              ))}
            </ul>
            {errors.length > 0 && (
              <div className="notice error" role="alert">
                <ul style={{ margin: 0, paddingLeft: '1.1rem' }}>{errors.map((m, i) => <li key={i}>{m}</li>)}</ul>
              </div>
            )}
            <div className="actions" style={{ marginTop: '.9rem' }}>
              <button type="submit" className="primary" disabled={isSubmitting} style={{ flex: 1 }}>
                {isSubmitting ? t('Submitting...') : t('Submit Borehole Log')}
              </button>
            </div>
            <div className="actions" style={{ marginTop: '.5rem', justifyContent: 'space-between' }}>
              <span className="muted small">{t('Saved on this device as you type.')}</span>
              <button type="button" className="quiet small" onClick={() => { if (window.confirm(t('Clear every field of this form?'))) resetForm() }} disabled={isSubmitting}>{t('Clear form')}</button>
            </div>
            {status && <p role="status" className="small">{status}</p>}
          </div>
        </aside>
      </form>
    </div>
  )
}
