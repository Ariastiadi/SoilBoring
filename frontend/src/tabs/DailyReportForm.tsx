import { useEffect, useMemo, useState } from 'react'
import { submitReport } from '../outbox'
import { CORE_SIZES, METHOD_OPTIONS as methodOptions, USCS_OPTIONS as uscsOptions, coreSizeLabel, methodLabel } from '../options'
import { t } from '../i18n'

const DRAFT_KEY = 'borehole-form-draft'

// Typed as text: a number input would silently turn "1,5" into 15.
const decimal = (v: string) => v.replace(/,/g, '.')

export default function DailyReportForm() {
  const draft = useMemo(() => {
    if (typeof window === 'undefined') return null
    const raw = window.localStorage.getItem(DRAFT_KEY)
    if (!raw) return null
    try {
      return JSON.parse(raw)
    } catch {
      return null
    }
  }, [])

  const [BoreholeID, setBoreholeID] = useState(draft?.BoreholeID ?? '')
  const [ProjectName, setProjectName] = useState(draft?.ProjectName ?? '')
  const [SiteName, setSiteName] = useState(draft?.SiteName ?? '')
  const [Latitude, setLatitude] = useState(draft?.Latitude ?? '')
  const [Longitude, setLongitude] = useState(draft?.Longitude ?? '')
  const [GroundElevation_mRL, setGroundElevation] = useState(draft?.GroundElevation_mRL ?? '')
  const [StartDate, setStartDate] = useState(draft?.StartDate ?? '')
  const [EndDate, setEndDate] = useState(draft?.EndDate ?? '')
  const [DrillingMethod, setDrillingMethod] = useState(draft?.DrillingMethod ?? methodOptions[0])
  const [DrillRig, setDrillRig] = useState(draft?.DrillRig ?? '')
  const [CoreSize, setCoreSize] = useState(draft?.CoreSize ?? '')
  const [BoreholeDiameter_mm, setBoreholeDiameter] = useState(draft?.BoreholeDiameter_mm ?? '150')
  const [TargetDepth_m, setTargetDepth] = useState(draft?.TargetDepth_m ?? '')
  const [FinalDepth_m, setFinalDepth] = useState(draft?.FinalDepth_m ?? '')
  const [CasingInstalled_mm, setCasingInstalled] = useState(draft?.CasingInstalled_mm ?? '100')
  const [GroundwaterDepth_m, setGroundwaterDepth] = useState(draft?.GroundwaterDepth_m ?? '')
  const [GroundwaterEncountered, setGroundwaterEncountered] = useState(draft?.GroundwaterEncountered ?? true)
  const [SoilDescription, setSoilDescription] = useState(draft?.SoilDescription ?? '')
  const [USCS_Class, setUSCS] = useState(draft?.USCS_Class ?? uscsOptions[0])
  const [Avg_SPT_N60, setAvgSpt] = useState(draft?.Avg_SPT_N60 ?? '')
  const [Contractor, setContractor] = useState(draft?.Contractor ?? '')
  const [LoggingGeologist, setLoggingGeologist] = useState(draft?.LoggingGeologist ?? '')
  const [Remarks, setRemarks] = useState(draft?.Remarks ?? '')
  const [status, setStatus] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)

  const tooltips = {
    BoreholeID: t('Unique borehole code from the drilling program. Example: BH-2024-012.'),
    ProjectName: t('Project or corridor for this soil boring work.'),
    SiteName: t('Specific site/zone in the field, e.g., Zone B-2.'),
    Latitude: t('Latitude in decimal degrees.'),
    Longitude: t('Longitude in decimal degrees.'),
    GroundElevation_mRL: t('Ground elevation relative to mRL or local datum.'),
    StartDate: t('Drilling start date (YYYY-MM-DD).'),
    EndDate: t('Drilling end date (YYYY-MM-DD).'),
    DrillingMethod: t('Drilling method used, e.g., Wash Boring + SPT.'),
    DrillRig: t('Drill rig / plant used, e.g. the rig model or fleet number.'),
    CoreSize: t('Wireline core barrel size for cored holes; fills in the nominal hole diameter.'),
    BoreholeDiameter_mm: t('Diameter of the drilled hole (mm).'),
    TargetDepth_m: t('Programmed target depth (m).'),
    FinalDepth_m: t('Actual final depth achieved (m).'),
    CasingInstalled_mm: t('Casing size installed (mm), if any.'),
    GroundwaterDepth_m: t('Groundwater depth from surface (m).'),
    GroundwaterEncountered: t('Check if groundwater was observed during drilling.'),
    SoilDescription: t('Dominant soil description for the latest interval.'),
    USCS_Class: t('USCS soil classification.'),
    Avg_SPT_N60: t('Average SPT N60 value recorded for this hole.'),
    Contractor: t('Drilling contractor.'),
    LoggingGeologist: t('Field logger/geologist name.'),
    Remarks: t('Additional notes, risks, or recommendations.'),
  }

  const persistDraft = () => {
    if (typeof window === 'undefined') return
    const payload = {
      BoreholeID,
      ProjectName,
      SiteName,
      Latitude,
      Longitude,
      GroundElevation_mRL,
      StartDate,
      EndDate,
      DrillingMethod,
      DrillRig,
      CoreSize,
      BoreholeDiameter_mm,
      TargetDepth_m,
      FinalDepth_m,
      CasingInstalled_mm,
      GroundwaterDepth_m,
      GroundwaterEncountered,
      SoilDescription,
      USCS_Class,
      Avg_SPT_N60,
      Contractor,
      LoggingGeologist,
      Remarks,
    }
    window.localStorage.setItem(DRAFT_KEY, JSON.stringify(payload))
  }

  useEffect(() => {
    persistDraft()
  }, [
    BoreholeID,
    ProjectName,
    SiteName,
    Latitude,
    Longitude,
    GroundElevation_mRL,
    StartDate,
    EndDate,
    DrillingMethod,
    DrillRig,
    CoreSize,
    BoreholeDiameter_mm,
    TargetDepth_m,
    FinalDepth_m,
    CasingInstalled_mm,
    GroundwaterDepth_m,
    GroundwaterEncountered,
    SoilDescription,
    USCS_Class,
    Avg_SPT_N60,
    Contractor,
    LoggingGeologist,
    Remarks,
  ])

  const resetForm = () => {
    setBoreholeID('')
    setProjectName('')
    setSiteName('')
    setLatitude('')
    setLongitude('')
    setGroundElevation('')
    setStartDate('')
    setEndDate('')
    setDrillingMethod(methodOptions[0])
    setDrillRig('')
    setCoreSize('')
    setBoreholeDiameter('150')
    setTargetDepth('')
    setFinalDepth('')
    setCasingInstalled('100')
    setGroundwaterDepth('')
    setGroundwaterEncountered(true)
    setSoilDescription('')
    setUSCS(uscsOptions[0])
    setAvgSpt('')
    setContractor('')
    setLoggingGeologist('')
    setRemarks('')
    if (typeof window !== 'undefined') {
      window.localStorage.removeItem(DRAFT_KEY)
    }
  }

  const validate = () => {
    const errors: string[] = []
    const toNumber = (val: string) => {
      if (val === '') return null
      const n = Number(val)
      return Number.isFinite(n) ? n : NaN
    }
    if (/[\/\\?#%\u0000-\u001f]/.test(BoreholeID) || ['.', '..'].includes(BoreholeID.trim())) {
      errors.push(t('Borehole ID cannot contain / \\ ? # % characters or be "." / "..".'))
    }
    const latNum = toNumber(Latitude)
    if (latNum !== null && (Number.isNaN(latNum) || latNum < -90 || latNum > 90)) {
      errors.push(t('Latitude must be between -90 and 90.'))
    }
    const lonNum = toNumber(Longitude)
    if (lonNum !== null && (Number.isNaN(lonNum) || lonNum < -180 || lonNum > 180)) {
      errors.push(t('Longitude must be between -180 and 180.'))
    }
    const diameter = toNumber(BoreholeDiameter_mm)
    if (Number.isNaN(diameter) || (diameter !== null && diameter <= 0)) {
      errors.push(t('Borehole diameter must be a positive number.'))
    }
    const finalDepth = toNumber(FinalDepth_m)
    if (Number.isNaN(finalDepth) || finalDepth === null || finalDepth < 0) {
      errors.push(t('Final depth is required and must be a number of 0 or more.'))
    }
    for (const [label, value] of [[t('Casing'), CasingInstalled_mm], [t('Target depth'), TargetDepth_m], [t('Groundwater depth'), GroundwaterDepth_m], [t('Average SPT N60'), Avg_SPT_N60]] as const) {
      const n = toNumber(value)
      if (Number.isNaN(n) || (n !== null && n < 0)) errors.push(t('{label} cannot be negative.', { label }))
    }
    const start = StartDate ? new Date(StartDate) : null
    const end = EndDate ? new Date(EndDate) : null
    if (start && end && start > end) {
      errors.push(t('Start date must be earlier than end date.'))
    }
    return errors
  }

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!StartDate || !EndDate) {
      setStatus(t('Start and end dates are required.'))
      return
    }
    const validationErrors = validate()
    if (validationErrors.length) {
      setStatus(validationErrors.join(' '))
      return
    }
    // Drilling past the target (e.g. to reach bearing strata) is normal, so this only asks.
    const target = Number(TargetDepth_m)
    const final = Number(FinalDepth_m)
    if (TargetDepth_m !== '' && target > 0 && final > target * 1.5 &&
        !window.confirm(t('Final depth {final} m is more than 1.5x the target depth {target} m. Save anyway?', { final, target }))) {
      setStatus(t('Not saved. Check the final and target depths.'))
      return
    }
    persistDraft()
    setStatus(t('Submitting...'))
    setIsSubmitting(true)
    try {
      const payload = {
        BoreholeID,
        ProjectName,
        SiteName,
        Latitude,
        Longitude,
        GroundElevation_mRL,
        StartDate,
        EndDate,
        DrillingMethod,
        DrillRig,
        CoreSize,
        BoreholeDiameter_mm,
        TargetDepth_m,
        FinalDepth_m,
        CasingInstalled_mm,
        GroundwaterDepth_m,
        GroundwaterEncountered,
        SoilDescription,
        USCS_Class,
        Avg_SPT_N60,
        Contractor,
        LoggingGeologist,
        Remarks,
      }
      const result = await submitReport(payload)
      setStatus(result === 'sent'
        ? t('Saved! Draft cleared.')
        : t('No connection: the log is kept on this device and will be sent automatically when you are back online.'))
      resetForm()
    } catch (err: any) {
      setStatus(t('Error: {message}', { message: err.message }))
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <form onSubmit={onSubmit}>
      <div className="row">
        <div>
          <h3>{t('Project & Borehole Info')}</h3>
          <label title={tooltips.BoreholeID}>{t('Borehole ID')}</label>
          <input value={BoreholeID} onChange={e => setBoreholeID(e.target.value)} required title={tooltips.BoreholeID} placeholder="BH-2024-001" />
          <label title={tooltips.ProjectName}>{t('Project')}</label>
          <input value={ProjectName} onChange={e => setProjectName(e.target.value)} required title={tooltips.ProjectName} placeholder={t('North Ring Toll')} />
          <label title={tooltips.SiteName}>{t('Site / Zone')}</label>
          <input value={SiteName} onChange={e => setSiteName(e.target.value)} required title={tooltips.SiteName} placeholder={t('Zone B-2')} />
          <label title={tooltips.Latitude}>{t('Latitude')}</label>
          <input type="text" pattern="-?[0-9]*[.]?[0-9]*" value={Latitude} onChange={e => setLatitude(decimal(e.target.value))} title={tooltips.Latitude} placeholder="-6.17510" />
          <label title={tooltips.Longitude}>{t('Longitude')}</label>
          <input type="text" pattern="-?[0-9]*[.]?[0-9]*" value={Longitude} onChange={e => setLongitude(decimal(e.target.value))} title={tooltips.Longitude} placeholder="106.86520" />
          <label title={tooltips.GroundElevation_mRL}>{t('Ground Elevation (mRL)')}</label>
          <input type="text" pattern="-?[0-9]*[.]?[0-9]*" value={GroundElevation_mRL} onChange={e => setGroundElevation(decimal(e.target.value))} title={tooltips.GroundElevation_mRL} placeholder="8.5" />
        </div>
        <div>
          <h3>{t('Schedule & Team')}</h3>
          <label title={tooltips.StartDate}>{t('Start Date')}</label>
          <input type="date" value={StartDate} onChange={e => setStartDate(e.target.value)} required title={tooltips.StartDate} />
          <label title={tooltips.EndDate}>{t('End Date')}</label>
          <input type="date" value={EndDate} onChange={e => setEndDate(e.target.value)} required title={tooltips.EndDate} />
          <label title={tooltips.Contractor}>{t('Contractor')}</label>
          <input value={Contractor} onChange={e => setContractor(e.target.value)} required title={tooltips.Contractor} placeholder="GeoBore Ltd." />
          <label title={tooltips.LoggingGeologist}>{t('Logging Geologist')}</label>
          <input value={LoggingGeologist} onChange={e => setLoggingGeologist(e.target.value)} title={tooltips.LoggingGeologist} placeholder="A. Carter" />
          <label title={tooltips.Remarks}>{t('Remarks')}</label>
          <textarea value={Remarks} onChange={e => setRemarks(e.target.value)} title={tooltips.Remarks} placeholder={t('Access, utilities, safety notes, etc.')} />
        </div>
      </div>

      <div style={{ marginTop: '1rem' }}>
        <h3>{t('Drilling Parameters')}</h3>
        <div className="row">
          <div>
            <label title={tooltips.DrillingMethod}>{t('Drilling Method')}</label>
            <select value={DrillingMethod} onChange={e => setDrillingMethod(e.target.value)} title={tooltips.DrillingMethod}>
              {methodOptions.map(method => (
                <option key={method} value={method}>{methodLabel(method)}</option>
              ))}
            </select>
            <label title={tooltips.DrillRig}>{t('Drill Rig / Plant')}</label>
            <input value={DrillRig} maxLength={100} onChange={e => setDrillRig(e.target.value)} title={tooltips.DrillRig} placeholder={t('Rig model or fleet no.')} />
            <label title={tooltips.CoreSize}>{t('Core Size (wireline)')}</label>
            <select
              value={CoreSize}
              title={tooltips.CoreSize}
              onChange={e => {
                const next = e.target.value
                const size = CORE_SIZES.find(s => s.code === next)
                // Fill the hole diameter only while it still holds the default or a previous core size.
                const auto = BoreholeDiameter_mm === '' || BoreholeDiameter_mm === '150' ||
                  CORE_SIZES.some(s => String(s.hole) === BoreholeDiameter_mm)
                if (size && auto) setBoreholeDiameter(String(size.hole))
                setCoreSize(next)
              }}
            >
              <option value="">{t('Not cored')}</option>
              {CORE_SIZES.map(s => <option key={s.code} value={s.code}>{coreSizeLabel(s.code)}</option>)}
            </select>
            <label title={tooltips.BoreholeDiameter_mm}>{t('Borehole Diameter (mm)')}</label>
            <input type="text" inputMode="decimal" pattern="[0-9]*[.]?[0-9]*" value={BoreholeDiameter_mm} onChange={e => setBoreholeDiameter(decimal(e.target.value))} title={tooltips.BoreholeDiameter_mm} />
            <label title={tooltips.CasingInstalled_mm}>{t('Casing Installed (mm)')}</label>
            <input type="text" inputMode="decimal" pattern="[0-9]*[.]?[0-9]*" value={CasingInstalled_mm} onChange={e => setCasingInstalled(decimal(e.target.value))} title={tooltips.CasingInstalled_mm} />
          </div>
          <div>
            <label title={tooltips.TargetDepth_m}>{t('Target Depth (m)')}</label>
            <input type="text" inputMode="decimal" pattern="[0-9]*[.]?[0-9]*" value={TargetDepth_m} onChange={e => setTargetDepth(decimal(e.target.value))} title={tooltips.TargetDepth_m} />
            <label title={tooltips.FinalDepth_m}>{t('Final Depth (m)')}</label>
            <input type="text" inputMode="decimal" pattern="[0-9]*[.]?[0-9]*" value={FinalDepth_m} onChange={e => setFinalDepth(decimal(e.target.value))} required title={tooltips.FinalDepth_m} />
            <label title={tooltips.Avg_SPT_N60}>{t('Average SPT N60')}</label>
            <input type="text" inputMode="decimal" pattern="[0-9]*[.]?[0-9]*" value={Avg_SPT_N60} onChange={e => setAvgSpt(decimal(e.target.value))} title={tooltips.Avg_SPT_N60} placeholder="28" />
          </div>
        </div>
      </div>

      <div style={{ marginTop: '1rem' }}>
        <h3>{t('Geotechnical Observations')}</h3>
        <div className="row">
          <div>
            <label title={tooltips.GroundwaterDepth_m}>{t('Groundwater Depth (m)')}</label>
            <input type="text" inputMode="decimal" pattern="[0-9]*[.]?[0-9]*" value={GroundwaterDepth_m} onChange={e => setGroundwaterDepth(decimal(e.target.value))} title={tooltips.GroundwaterDepth_m} />
            <label className="checkbox" title={tooltips.GroundwaterEncountered}>
              <input type="checkbox" checked={GroundwaterEncountered} onChange={e => setGroundwaterEncountered(e.target.checked)} />
              {t('Groundwater encountered')}
            </label>
            <label title={tooltips.USCS_Class}>{t('USCS Class')}</label>
            <select value={USCS_Class} onChange={e => setUSCS(e.target.value)} title={tooltips.USCS_Class}>
              {uscsOptions.map(code => (
                <option key={code} value={code}>{code}</option>
              ))}
            </select>
          </div>
          <div>
            <label title={tooltips.SoilDescription}>{t('Soil Description')}</label>
            <textarea value={SoilDescription} onChange={e => setSoilDescription(e.target.value)} title={tooltips.SoilDescription} placeholder={t('Silty clay, medium plasticity, with fine sand lenses')} />
          </div>
        </div>
      </div>

      <div className="actions" style={{ marginTop: '.75rem' }}>
        <button type="submit" disabled={isSubmitting}>{isSubmitting ? t('Submitting...') : t('Submit Borehole Log')}</button>
        <button type="button" onClick={resetForm} disabled={isSubmitting}>{t('Reset Form')}</button>
        <span>{status}</span>
      </div>
    </form>
  )
}
