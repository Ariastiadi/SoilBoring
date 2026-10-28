/** Engineering analyses: inputs per method, calculation on the server, results with charts. */
import { useEffect, useState } from 'react'
import { getDetails, listRecords, listReports, runAnalysis, saveRecord, type Rec } from '../api'
import { t, translateServer } from '../i18n'
import type { Intent } from '../nav'
import { FieldInput, RecordsPage, number, useSchemas } from '../records'
import { ResultView } from '../worksheets'
import { ScrollTable } from '../ui'
import { GEO_DEFAULTS, GeoResult, SlopeInputs, WallInputs, slopeFromData, wallFromData } from './AnalysesGeo'

type Inputs = Record<string, any>

const DEFAULTS: Record<string, Inputs> = {
  bearing: { B: '2', L: '2', Df: '1.5', c: '0', phi_deg: '30', gamma: '18', gamma_sat: '19', gw_depth: '', fs: '3' },
  pile: { diameter: '0.6', length: '20', pile_type: 'bored', fs_shaft: '2.5', fs_tip: '2.5' },
  settlement: { B: '2', L: '2', Df: '1.5', q: '100', gw_depth: '', layers: [] },
  liquefaction: { amax_g: '0.3', magnitude: '7.5', energy_ratio: '60', gw_depth: '' },
  bearing_table: { B_list: '1 1.5 2 2.5 3', Df_list: '1 1.5 2', LB: '1', c: '0', phi_deg: '30', gamma: '18', gamma_sat: '19', gw_depth: '', fs: '3' },
  site_class: { pga: '', ss: '', s1: '', tl: '20', site: '' },
  spt_correction: { energy_ratio: '60', borehole_diameter_mm: '100', rod_extra_m: '1.5', sampler_liners: 'no', gw_depth: '', gamma: '18' },
  ...GEO_DEFAULTS,
}

const LABELS: Record<string, string> = {
  B_list: 'Footing widths B (m), separated by spaces', Df_list: 'Founding depths Df (m), separated by spaces', LB: 'Length/width ratio L/B',
  pga: 'Bedrock PGA (g)', ss: 'Bedrock Ss, 0.2 s (g)', s1: 'Bedrock S1, 1 s (g)', tl: 'Long period TL (s)',
  borehole_diameter_mm: 'Borehole diameter (mm)', rod_extra_m: 'Rod above ground (m)',
  B: 'Footing width B (m)', L: 'Footing length L (m, empty = strip)', Df: 'Founding depth Df (m)', c: "Cohesion c (kPa)",
  phi_deg: 'Friction angle φ (°)', gamma: 'Unit weight γ (kN/m³)', gamma_sat: 'Saturated unit weight γsat (kN/m³)',
  gw_depth: 'Groundwater depth (m, empty = deep)', fs: 'Factor of safety', diameter: 'Pile diameter D (m)', length: 'Pile length L (m)',
  fs_shaft: 'Factor of safety, shaft', fs_tip: 'Factor of safety, tip', q: 'Net applied pressure q (kPa)',
  amax_g: 'Peak ground acceleration amax (g)', magnitude: 'Earthquake magnitude Mw', energy_ratio: 'SPT hammer energy ratio (%)',
}

const NEEDS_BOREHOLE = ['pile', 'liquefaction', 'spt_correction']

function NumberField({ name, inputs, set }: { name: string, inputs: Inputs, set: (k: string, v: string) => void }) {
  return (
    <div className="field">
      <label htmlFor={`a-${name}`}>{t(LABELS[name] || name)}</label>
      <input id={`a-${name}`} type="text" inputMode="decimal" value={inputs[name] ?? ''} onChange={e => set(name, e.target.value.replace(/,/g, '.'))} />
    </div>
  )
}

function TextField({ name, inputs, set }: { name: string, inputs: Inputs, set: (k: string, v: string) => void }) {
  return (
    <div className="field">
      <label htmlFor={`a-${name}`}>{t(LABELS[name] || name)}</label>
      <input id={`a-${name}`} type="text" inputMode="decimal" value={inputs[name] ?? ''} onChange={e => set(name, e.target.value)} />
    </div>
  )
}

function VsLayers({ rows, onChange }: { rows: Inputs[], onChange: (r: Inputs[]) => void }) {
  const cols: Array<[string, string]> = [['top', 'From (m)'], ['base', 'To (m)'], ['vs', 'Vs (m/s)']]
  return (
    <div className="field wide">
      <label>{t('Shear wave velocity layers (optional)')}</label>
      <div className="table-scroll">
        <table className="grid-table" style={{ minWidth: 360 }}>
          <thead><tr>{cols.map(([, l]) => <th key={l}>{t(l)}</th>)}<th /></tr></thead>
          <tbody>{rows.map((row, i) => (
            <tr key={i}>
              {cols.map(([k, l]) => <td key={k}><input aria-label={`${t(l)} ${i + 1}`} inputMode="decimal" value={row[k] ?? ''} onChange={e => onChange(rows.map((r, j) => j === i ? { ...r, [k]: e.target.value.replace(/,/g, '.') } : r))} /></td>)}
              <td><button type="button" className="quiet danger-quiet small" aria-label={t('Remove row')} onClick={() => onChange(rows.filter((_, j) => j !== i))}>×</button></td>
            </tr>
          ))}</tbody>
        </table>
      </div>
      <div className="actions" style={{ marginTop: '.5rem' }}>
        <button type="button" onClick={() => onChange([...rows, { top: rows.length ? rows[rows.length - 1].base : '0', base: '', vs: '' }])}>{t('Add row')}</button>
      </div>
    </div>
  )
}

function AmaxFromSiteClass({ projectId, onPick }: { projectId: string, onPick: (v: number) => void }) {
  const [found, setFound] = useState<Rec | null>(null)
  useEffect(() => {
    listRecords('analyses').then(list => {
      const mine = list.filter(a => a.type === 'site_class' && (!projectId || a.project_id === projectId) && a.results?.values)
      setFound(mine[0] || null)
    }).catch(() => setFound(null))
  }, [projectId])
  const pga = found?.results?.values?.find((v: Rec) => String(v.label).startsWith('PGA_M'))?.value
  if (pga === undefined || pga === null) return null
  return (
    <div className="field wide">
      <button type="button" className="small" onClick={() => onPick(pga)}>{t('Use PGA_M = {v} g from "{title}"', { v: pga, title: found!.title })}</button>
    </div>
  )
}

const LAYER_COLS: Array<[string, string]> = [['top', 'From (m)'], ['base', 'To (m)'], ['gamma', 'γ (kN/m³)'], ['gamma_sat', 'γsat (kN/m³)'], ['Cc', 'Cc'], ['Cr', 'Cr'], ['e0', 'e0'], ['sigma_p', "σ'p (kPa)"]]

function SettlementLayers({ rows, onChange }: { rows: Inputs[], onChange: (r: Inputs[]) => void }) {
  return (
    <div className="field wide">
      <label>{t('Soil layers from the ground surface (all layers, Cc = 0 for layers that do not compress)')}</label>
      <div className="table-scroll">
        <table className="grid-table">
          <thead><tr>{LAYER_COLS.map(([k, l]) => <th key={k}>{t(l)}</th>)}<th /></tr></thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                {LAYER_COLS.map(([k]) => (
                  <td key={k}><input type="text" inputMode="decimal" value={r[k] ?? ''} aria-label={k}
                    onChange={e => onChange(rows.map((x, j) => (j === i ? { ...x, [k]: e.target.value.replace(/,/g, '.') } : x)))} /></td>
                ))}
                <td><button type="button" className="quiet danger-quiet small" aria-label={t('Remove row')} onClick={() => onChange(rows.filter((_, j) => j !== i))}>×</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="actions" style={{ marginTop: '.5rem' }}>
        <button type="button" onClick={() => onChange([...rows, { top: rows.length ? rows[rows.length - 1].base : '0', gamma: '17', Cc: '0', e0: '1' }])}>{t('Add row')}</button>
      </div>
    </div>
  )
}

const num = (v: any) => (v === '' || v === null || v === undefined ? undefined : Number(v))

function AnalysisForm({ record, defaults, onSaved, onCancel }: { record: Rec | null, defaults?: Record<string, any>, onSaved: (r: Rec) => void, onCancel: () => void }) {
  const schemas = useSchemas()
  const entity = schemas?.analyses
  const [meta, setMeta] = useState<Inputs>(() => ({
    title: record?.title ?? '', project_id: record?.project_id ?? defaults?.project_id ?? '', borehole_id: record?.borehole_id ?? defaults?.borehole_id ?? '',
    type: record?.type ?? defaults?.type ?? 'bearing', engineer: record?.engineer ?? '', notes: record?.notes ?? '',
  }))
  const [inputs, setInputs] = useState<Inputs>(() => ({ ...DEFAULTS[record?.type ?? defaults?.type ?? 'bearing'], ...(record?.inputs || {}) }))
  const [boreholes, setBoreholes] = useState<Rec[]>([])
  const [result, setResult] = useState<Record<string, any> | null>(record?.results || null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [hint, setHint] = useState('')

  useEffect(() => { listReports().then(setBoreholes).catch(() => {}) }, [])
  const set = (k: string, v: any) => setInputs(prev => ({ ...prev, [k]: v }))
  const setType = (type: string) => { setMeta(m => ({ ...m, type })); setInputs({ ...DEFAULTS[type] }); setResult(null) }

  const borehole = boreholes.find(b => b.BoreholeID === meta.borehole_id)
  const payload = () => {
    const out: Inputs = { ...inputs }
    if (NEEDS_BOREHOLE.includes(meta.type)) out.borehole_id = meta.borehole_id
    return out
  }

  // Fill from the field and lab data of the chosen borehole.
  const fillFromData = async () => {
    if (!meta.borehole_id) { setHint(t('Choose a borehole first.')); return }
    setHint('')
    const lab = (await listRecords('lab_tests').catch(() => [] as Rec[])).filter(x => String(x.borehole_id).toLowerCase() === meta.borehole_id.toLowerCase() && x.status === 'done')
    const gw = borehole && String(borehole.GroundwaterEncountered).toLowerCase() !== 'false' ? borehole.GroundwaterDepth_m : ''
    if (meta.type === 'bearing') {
      const shear = lab.find(x => x.test_type === 'direct_shear' || x.test_type === 'triaxial')
      const dens = lab.find(x => (x.test_type === 'density' || x.test_type === 'moisture') && x.results?.gamma_bulk)
      setInputs(prev => ({
        ...prev,
        ...(shear ? { c: String(shear.results?.c ?? prev.c), phi_deg: String(shear.results?.phi ?? prev.phi_deg) } : {}),
        ...(dens?.results?.gamma_bulk ? { gamma: String(dens.results.gamma_bulk) } : {}),
        gw_depth: gw ?? prev.gw_depth,
      }))
      setHint(shear ? t('c and φ taken from sample {s} ({d} m).', { s: shear.sample_ref, d: shear.depth_top }) : t('No shear test for this borehole yet; c and φ are unchanged.'))
    } else if (meta.type === 'settlement') {
      const d = await getDetails(meta.borehole_id).catch(() => null)
      if (!d?.layers.length) { setHint(t('This borehole has no strata yet.')); return }
      const cons = lab.filter(x => x.test_type === 'consolidation')
      const dens = lab.filter(x => (x.test_type === 'density' || x.test_type === 'moisture') && x.results?.gamma_bulk)
      const layers = d.layers.map(l => {
        const c = cons.find(x => x.depth_top >= l.top && x.depth_top < l.base)
        const g = dens.find(x => x.depth_top >= l.top && x.depth_top < l.base)
        const clay = /^(C|M|O|PT)/i.test(l.uscs || '')
        return {
          top: String(l.top), base: String(l.base), gamma: String(g?.results?.gamma_bulk ?? (clay ? 16 : 18)),
          gamma_sat: String(g?.results?.gamma_bulk ? g.results.gamma_bulk + 1 : clay ? 17 : 19),
          Cc: String(c?.results?.cc ?? (clay ? '' : 0)), Cr: c?.results?.cr != null ? String(c.results.cr) : '',
          e0: String(c?.results?.e0 ?? (clay ? '' : 0.6)), sigma_p: c?.results?.pc != null ? String(c.results.pc) : '',
        }
      })
      setInputs(prev => ({ ...prev, layers, gw_depth: gw ?? prev.gw_depth }))
      setHint(cons.length ? t('Cc, Cr, e0 and σ\'p taken from {n} consolidation test(s). Fill the empty cells.', { n: cons.length }) : t('No consolidation test yet: enter Cc and e0 for the clay layers.'))
    } else if (meta.type === 'liquefaction') {
      setInputs(prev => ({ ...prev, gw_depth: gw ?? prev.gw_depth }))
      setHint(t('Fines and plasticity come from the grain size and Atterberg tests of the borehole when available.'))
    } else if (meta.type === 'retaining_wall') {
      const { patch, hint: h } = wallFromData(lab)
      setInputs(prev => ({ ...prev, ...patch }))
      setHint(h)
    } else if (meta.type === 'slope') {
      const d = await getDetails(meta.borehole_id).catch(() => null)
      const { patch, hint: h } = slopeFromData({ ...inputs, mode: 'circular' }, d, lab, gw)
      setInputs(prev => ({ ...prev, ...patch, mode: 'circular' }))
      setHint(h)
    }
  }

  const calculate = async () => {
    setBusy(true)
    setError('')
    try {
      setResult(await runAnalysis(meta.type, clean(payload())))
    } catch (e: any) {
      setError(e.message)
      setResult(null)
    } finally {
      setBusy(false)
    }
  }
  const save = async () => {
    if (!meta.title.trim()) { setError(t('{label} is required.', { label: t('Title') })); return }
    setBusy(true)
    setError('')
    try {
      const body: Inputs = { ...meta, inputs: clean(payload()) }
      if (record?.updated_at) body.expected_updated_at = record.updated_at
      onSaved(await saveRecord('analyses', body, record?.id))
    } catch (e: any) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  const typeField = entity?.fields.find(f => f.name === 'type')
  const projectField = entity?.fields.find(f => f.name === 'project_id')
  const engineerField = entity?.fields.find(f => f.name === 'engineer')
  return (
    <div className="card">
      <div className="fields">
        <div className="field">
          <label htmlFor="a-title">{t('Title')}<span className="tag-req">{t('required')}</span></label>
          <input id="a-title" value={meta.title} onChange={e => setMeta(m => ({ ...m, title: e.target.value }))} />
        </div>
        <div className="field">
          <label htmlFor="a-type">{t('Analysis')}</label>
          {typeField && <FieldInput f={typeField} id="a-type" value={meta.type} record={meta} onChange={v => setType(v || 'bearing')} />}
        </div>
        <div className="field">
          <label htmlFor="a-project">{t('Project')}</label>
          {projectField && <FieldInput f={projectField} id="a-project" value={meta.project_id} record={meta} onChange={v => setMeta(m => ({ ...m, project_id: v }))} />}
        </div>
        <div className="field">
          <label htmlFor="a-bh">{t('Borehole')}{NEEDS_BOREHOLE.includes(meta.type) && <span className="tag-req">{t('required')}</span>}</label>
          <div className="actions" style={{ flexWrap: 'nowrap' }}>
            <select id="a-bh" value={meta.borehole_id} onChange={e => setMeta(m => ({ ...m, borehole_id: e.target.value }))} style={{ flex: 1, minWidth: 0 }}>
              <option value="">{t('Select')}</option>
              {boreholes.map(b => <option key={b.BoreholeID} value={b.BoreholeID}>{b.BoreholeID} – {b.ProjectName}</option>)}
            </select>
            {meta.type !== 'pile' && <button type="button" className="small" onClick={() => { void fillFromData() }}>{t('Use field and lab data')}</button>}
          </div>
        </div>
      </div>
      {hint && <p className="notice" role="status">{hint}</p>}
      <h3 style={{ marginTop: '1.25rem' }}>{t('Inputs')}</h3>
      <div className="fields">
        {meta.type === 'bearing' && ['B', 'L', 'Df', 'c', 'phi_deg', 'gamma', 'gamma_sat', 'gw_depth', 'fs'].map(k => <NumberField key={k} name={k} inputs={inputs} set={set} />)}
        {meta.type === 'pile' && <>
          {['diameter', 'length'].map(k => <NumberField key={k} name={k} inputs={inputs} set={set} />)}
          <div className="field">
            <label htmlFor="a-ptype">{t('Pile type')}</label>
            <select id="a-ptype" value={inputs.pile_type} onChange={e => set('pile_type', e.target.value)}>
              <option value="bored">{t('Bored pile')}</option>
              <option value="driven">{t('Driven pile')}</option>
            </select>
          </div>
          {['fs_shaft', 'fs_tip'].map(k => <NumberField key={k} name={k} inputs={inputs} set={set} />)}
          <p className="help wide">{t('Uses the strata and SPT of the chosen borehole.')}</p>
        </>}
        {meta.type === 'settlement' && <>
          {['B', 'L', 'Df', 'q', 'gw_depth'].map(k => <NumberField key={k} name={k} inputs={inputs} set={set} />)}
          <SettlementLayers rows={inputs.layers || []} onChange={rows => set('layers', rows)} />
        </>}
        {meta.type === 'liquefaction' && <>
          {['amax_g', 'magnitude', 'energy_ratio', 'gw_depth'].map(k => <NumberField key={k} name={k} inputs={inputs} set={set} />)}
          <p className="help wide">{t('Uses the SPT and strata of the chosen borehole. SNI 1726:2019 gives amax for the site class (PGA × FPGA).')}</p>
          <AmaxFromSiteClass projectId={meta.project_id} onPick={v => set('amax_g', String(v))} />
        </>}
        {meta.type === 'bearing_table' && ['B_list', 'Df_list', 'LB', 'c', 'phi_deg', 'gamma', 'gamma_sat', 'gw_depth', 'fs'].map(k => <TextField key={k} name={k} inputs={inputs} set={set} />)}
        {meta.type === 'site_class' && <>
          {['pga', 'ss', 's1', 'tl'].map(k => <NumberField key={k} name={k} inputs={inputs} set={set} />)}
          <div className="field">
            <label htmlFor="a-site">{t('Site class')}</label>
            <select id="a-site" value={inputs.site || ''} onChange={e => set('site', e.target.value)}>
              <option value="">{t('From the data (SPT or Vs)')}</option>
              {['SA', 'SB', 'SC', 'SD', 'SE'].map(x => <option key={x} value={x}>{x}</option>)}
            </select>
          </div>
          <VsLayers rows={inputs.vs_layers || []} onChange={rows => set('vs_layers', rows)} />
          <p className="help wide">{t('PGA, Ss and S1 are bedrock (SB) values for the site from the 2024 national seismic hazard maps. With a borehole, N̄ of the top 30 m is used; with Vs layers (downhole or crosshole), Vs30 is used.')}</p>
        </>}
        {meta.type === 'retaining_wall' && <WallInputs inputs={inputs} set={set} />}
        {meta.type === 'slope' && <SlopeInputs inputs={inputs} set={set} />}
        {meta.type === 'spt_correction' && <>
          {['energy_ratio', 'borehole_diameter_mm', 'rod_extra_m', 'gamma', 'gw_depth'].map(k => <NumberField key={k} name={k} inputs={inputs} set={set} />)}
          <div className="field">
            <label htmlFor="a-liner">{t('Sampler')}</label>
            <select id="a-liner" value={inputs.sampler_liners || 'no'} onChange={e => set('sampler_liners', e.target.value)}>
              <option value="no">{t('Without liners')}</option>
              <option value="yes">{t('With liners (standard)')}</option>
            </select>
          </div>
          <p className="help wide">{t('Uses the SPT of the chosen borehole. The energy ratio comes from the hammer energy measurement of the rig.')}</p>
        </>}
        <div className="field">
          <label htmlFor="a-eng">{t('Engineer')}</label>
          {engineerField && <FieldInput f={engineerField} id="a-eng" value={meta.engineer} record={meta} onChange={v => setMeta(m => ({ ...m, engineer: v }))} />}
        </div>
        <div className="field wide">
          <label htmlFor="a-notes">{t('Notes')}</label>
          <textarea id="a-notes" rows={3} value={meta.notes} onChange={e => setMeta(m => ({ ...m, notes: e.target.value }))} />
        </div>
      </div>
      {error && <p className="notice error" role="alert">{error}</p>}
      <div className="actions" style={{ marginTop: '1rem' }}>
        <button type="button" onClick={() => { void calculate() }} disabled={busy}>{t('Calculate')}</button>
        <button type="button" className="primary" onClick={() => { void save() }} disabled={busy}>{t('Save analysis')}</button>
        <button type="button" className="quiet" onClick={onCancel} disabled={busy}>{t('Cancel')}</button>
      </div>
      {result && <div style={{ marginTop: '1.25rem' }}><AnalysisResult type={meta.type} result={result} /></div>}
    </div>
  )
}

function clean(inputs: Inputs): Inputs {
  const out: Inputs = {}
  for (const [k, v] of Object.entries(inputs)) {
    if (k === 'layers' && Array.isArray(v)) {
      out.layers = v.map(row => Object.fromEntries(Object.entries(row).filter(([, x]) => x !== '' && x !== null).map(([kk, x]) => [kk, Number(x)])))
    } else if (k === 'vs_layers' && Array.isArray(v)) {
      out.vs_layers = v.filter(row => row.top !== '' && row.base !== '' && row.vs !== '').map(row => ({ top: Number(row.top), base: Number(row.base), vs: Number(row.vs) }))
    } else if ((k === 'surface' || k === 'phreatic') && Array.isArray(v)) {
      out[k] = v.filter(row => row.x !== '' && row.y !== '').map(row => ({ x: Number(row.x), y: Number(row.y) }))
    } else if (['pile_type', 'borehole_id', 'B_list', 'Df_list', 'site', 'sampler_liners', 'method', 'wall_type', 'passive', 'mode', 'geometry', 'water'].includes(k)) {
      out[k] = v
    } else if (v !== '' && v !== null && v !== undefined) {
      out[k] = num(v)
    }
  }
  return out
}

function niceStep(max: number) {
  const raw = max / 4
  const mag = Math.pow(10, Math.floor(Math.log10(raw)))
  const f = raw / mag
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * mag
}

function LineChart({ points, xLabel, yLabel, refLine, invertY = true }: {
  points: Array<[number, number]>, xLabel: string, yLabel: string, refLine?: number, invertY?: boolean
}) {
  if (points.length < 2) return null
  const W = 460, H = 300, L = 46, R = 26, T = 16, B = 34
  const xs = points.map(p => p[0]), ys = points.map(p => p[1])
  const xStep = niceStep(Math.max(...xs, refLine ?? 0) || 1)
  const yStep = niceStep(Math.max(...ys) || 1)
  const xMax = Math.ceil((Math.max(...xs, refLine ?? 0) || 1) / xStep) * xStep
  const yMax = Math.ceil((Math.max(...ys) || 1) / yStep) * yStep
  const PW = W - L - R, PH = H - T - B
  const x = (v: number) => L + (v / xMax) * PW
  const y = (v: number) => (invertY ? T + (v / yMax) * PH : H - B - (v / yMax) * PH)
  const xTicks = Array.from({ length: Math.round(xMax / xStep) + 1 }, (_, i) => i * xStep)
  const yTicks = Array.from({ length: Math.round(yMax / yStep) + 1 }, (_, i) => i * yStep)
  return (
    <svg width="100%" style={{ maxWidth: W }} viewBox={`0 0 ${W} ${H}`} className="profile-svg" role="img" aria-label={`${yLabel} / ${xLabel}`}>
      <rect x={L} y={T} width={PW} height={PH} fill="#fff" stroke="#cdd2c9" />
      {yTicks.map(v => (
        <g key={'y' + v}>
          <line x1={L} x2={L + PW} y1={y(v)} y2={y(v)} stroke="#eef0eb" />
          <text x={L - 6} y={y(v) + 4} fontSize="10" textAnchor="end" fill="#545b61">{number(Math.round(v * 100) / 100)}</text>
        </g>
      ))}
      {xTicks.map(v => (
        <g key={'x' + v}>
          <line x1={x(v)} x2={x(v)} y1={T} y2={T + PH} stroke="#eef0eb" />
          <text x={x(v)} y={H - B + 14} fontSize="10" textAnchor="middle" fill="#545b61">{number(Math.round(v * 100) / 100)}</text>
        </g>
      ))}
      <rect x={L} y={T} width={PW} height={PH} fill="none" stroke="#cdd2c9" />
      {refLine !== undefined && <line x1={x(refLine)} x2={x(refLine)} y1={T} y2={H - B} stroke="#b42318" strokeDasharray="4 3" />}
      <polyline fill="none" stroke="#23282d" strokeWidth="1.6" points={points.map(p => `${x(p[0])},${y(p[1])}`).join(' ')} />
      {points.map((p, i) => <circle key={i} cx={x(p[0])} cy={y(p[1])} r="3.5" fill="#f5c400" stroke="#23282d" />)}
      <text x={L + PW / 2} y={H - 4} fontSize="11" textAnchor="middle" fill="#23282d">{xLabel}</text>
      <text x={12} y={T + PH / 2} fontSize="11" textAnchor="middle" fill="#23282d" transform={`rotate(-90 12 ${T + PH / 2})`}>{yLabel}</text>
    </svg>
  )
}

export function AnalysisResult({ type, result }: { type: string, result: Record<string, any> }) {
  if (result.checks || result.section) return <GeoResult result={result} />
  if (Array.isArray(result.values) || Array.isArray(result.tables)) return <ResultView result={result} notesOpen />
  const notes: string[] = result.notes || []
  return (
    <div>
      <p className="result-line"><strong>{translateServer(result.summary)}</strong></p>
      {type === 'bearing' && (
        <dl className="facts-grid">
          {[['Nc', result.factors?.Nc], ['Nq', result.factors?.Nq], ['Nγ', result.factors?.Ngamma], ['qu (kPa)', result.qu],
            ['q_allow (kPa)', result.q_allow], ['q_net,allow (kPa)', result.q_net_allow], ["q' overburden (kPa)", result.q_overburden], ["γ' (kN/m³)", result.gamma_eff]].map(([k, v]) => (
            <div key={String(k)}><dt>{k}</dt><dd>{number(v)}</dd></div>
          ))}
        </dl>
      )}
      {type === 'pile' && <>
        <dl className="facts-grid">
          {[['Qp (kN)', result.Qp], ['Qs (kN)', result.Qs], ['Qult (kN)', result.Qult], ['Q_allow (kN)', result.Qallow], ['Np', result.tip?.Np], ['K (kPa)', result.tip?.K]].map(([k, v]) => (
            <div key={String(k)}><dt>{k}</dt><dd>{number(v)}</dd></div>
          ))}
        </dl>
        {(result.profile || []).length > 1 && (
          <figure style={{ margin: '1rem 0' }}>
            <LineChart points={(result.profile as Rec[]).map(r => [r.Qallow, r.length] as [number, number])} xLabel={t('Q_allow (kN)')} yLabel={t('Pile length (m)')} />
            <figcaption className="help">{t('Allowable capacity for each pile length.')}</figcaption>
          </figure>
        )}
      </>}
      {type === 'settlement' && (
        <ScrollTable>
          <table className="data-table">
            <thead><tr><th className="num">{t('Depth (m)')}</th><th className="num">σ'v0 (kPa)</th><th className="num">Δσ (kPa)</th><th>{t('State')}</th><th className="num">{t('Settlement (mm)')}</th></tr></thead>
            <tbody>{(result.sublayers || []).map((r: Rec, i: number) => (
              <tr key={i}><td className="num">{number(r.mid_depth)}</td><td className="num">{number(r.sigma_v0_eff)}</td><td className="num">{number(r.delta_sigma)}</td><td>{r.state}</td><td className="num">{number(r.settlement_mm)}</td></tr>
            ))}</tbody>
          </table>
        </ScrollTable>
      )}
      {type === 'liquefaction' && <>
        {(result.rows || []).filter((r: Rec) => r.FS !== null && r.FS !== undefined).length > 1 && (
          <figure style={{ margin: '1rem 0' }}>
            <LineChart points={(result.rows as Rec[]).filter(r => r.FS !== null && r.FS !== undefined).map(r => [Math.min(r.FS, 3), r.depth] as [number, number])}
              xLabel={t('Factor of safety (capped at 3)')} yLabel={t('Depth (m)')} refLine={1} />
            <figcaption className="help">{t('Red line: FS = 1. Points left of it are expected to liquefy.')}</figcaption>
          </figure>
        )}
        <ScrollTable>
          <table className="data-table">
            <thead><tr><th className="num">{t('Depth (m)')}</th><th className="num">N</th><th className="num">(N1)60cs</th><th className="num">CSR</th><th className="num">CRR</th><th className="num">FS</th><th>{t('Result')}</th></tr></thead>
            <tbody>{(result.rows || []).map((r: Rec, i: number) => (
              <tr key={i}>
                <td className="num">{number(r.depth)}</td><td className="num">{number(r.n)}</td><td className="num">{number(r.N1_60cs)}</td>
                <td className="num">{number(r.CSR)}</td><td className="num">{number(r.CRR)}</td><td className="num">{number(r.FS)}</td>
                <td><span className={`status ${r.status === 'liquefiable' ? 'bad' : r.status === 'marginal' ? 'warn' : r.status === 'not liquefiable' ? 'ok' : ''}`}>{LIQ_STATUS[r.status] ? t(LIQ_STATUS[r.status]) : translateServer(r.status)}</span>{r.remark && <div className="bh-sub">{translateServer(r.remark)}</div>}</td>
              </tr>
            ))}</tbody>
          </table>
        </ScrollTable>
      </>}
      {result.method && <p className="help">{t('Method')}: {translateServer(result.method)}</p>}
      {notes.length > 0 && <ul className="notes">{notes.map((n, i) => <li key={i}>{translateServer(n)}</li>)}</ul>}
    </div>
  )
}

const LIQ_STATUS: Record<string, string> = { liquefiable: 'Liquefiable', marginal: 'Marginal', 'not liquefiable': 'Not liquefiable' }

export default function AnalysesPage({ intent }: { intent?: Intent }) {
  return (
    <RecordsPage entityName="analyses" openId={intent?.open} startNew={intent?.newWith}
      description={t('Bearing capacity, pile capacity, settlement, liquefaction, retaining walls and slope stability from the field and laboratory data. Preliminary estimates to be checked by a geotechnical engineer.')}
      renderForm={props => <AnalysisForm {...props} />}
      extra={r => r.results && Object.keys(r.results).length ? <section className="card" style={{ marginBottom: '1rem' }}><h3>{t('Results')}</h3><AnalysisResult type={r.type} result={r.results} /></section> : null} />
  )
}
