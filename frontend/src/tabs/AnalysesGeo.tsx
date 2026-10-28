/** Retaining wall and slope stability analyses: inputs, live section sketch, result view. */
import { lang, t, translateServer } from '../i18n'
import { number } from '../records'
import { ResultView } from '../worksheets'
import type { Details, Rec } from '../api'
import './AnalysesGeo.css'

type Inputs = Record<string, any>
type Pt = [number, number]
type SetFn = (k: string, v: any) => void

/** Defaults reproduce the hand-checked cases: Das' cantilever wall example and the ACADS slope benchmark 1(a). */
export const GEO_DEFAULTS: Record<string, Inputs> = {
  retaining_wall: {
    method: 'rankine', wall_type: 'cantilever', H: '6.7', toe: '0.7', heel: '2.6', t_top: '0.5', t_bot: '0.7', back_batter: '0', D_base: '0.7',
    gamma_c: '23.58', gamma: '18', gamma_sat: '', phi: '30', c: '0', beta: '10', delta: '', q: '0', gw: '',
    found_phi: '20', found_c: '40', found_gamma: '19', D_front: '1.5', q_allow: '', passive: 'yes', kh: '0', kv: '0',
    fs_ot: '2', fs_sl: '1.5', fs_bc: '3', fs_ot_eq: '1.5', fs_sl_eq: '1.1', fs_bc_eq: '2',
  },
  slope: {
    mode: 'circular', geometry: 'simple', H: '10', beta: '26.57', bench_w: '0', bench_h: '',
    surface: [{ x: '20', y: '25' }, { x: '30', y: '25' }, { x: '50', y: '35' }, { x: '70', y: '35' }],
    layers: [{ bottom: '', gamma: '20', gamma_sat: '', c: '3', phi: '19.6' }],
    water: 'none', phreatic: [], ru: '', q: '0', q_offset: '0', kh: '0', n_slices: '40', depth_limit: '', fs_req: '',
    z: '3', m: '0.5', gamma: '18', gamma_sat: '20', c: '5', phi: '30',
  },
}

const LABELS: Record<string, string> = {
  H: 'Wall height H, base underside to stem top (m)', toe: 'Toe length (m)', heel: 'Heel length (m)', t_top: 'Stem thickness at the top (m)',
  t_bot: 'Stem thickness at the base (m)', back_batter: 'Back face batter, horizontal (m)', D_base: 'Base thickness (m)',
  gamma_c: 'Concrete unit weight (kN/m³)', gamma: 'Backfill unit weight γ (kN/m³)', gamma_sat: 'Backfill γsat (kN/m³, empty = γ + 1)',
  phi: "Backfill friction angle φ' (°)", c: "Backfill cohesion c' (kPa)", beta: 'Backfill slope β (°)', delta: "Wall friction δ (°, empty = 2/3 φ')",
  q: 'Surcharge q (kPa)', gw: 'Groundwater depth below the wall top (m, empty = none)',
  found_phi: "Foundation friction angle φ' (°)", found_c: "Foundation cohesion c' (kPa)", found_gamma: 'Foundation unit weight γ (kN/m³)',
  D_front: 'Depth of the base underside below the ground in front (m)', q_allow: 'Allowable bearing pressure (kPa, optional)',
  kh: 'Horizontal seismic coefficient kh', kv: 'Vertical seismic coefficient kv',
  fs_ot: 'Overturning, static', fs_sl: 'Sliding, static', fs_bc: 'Bearing, static', fs_ot_eq: 'Overturning, seismic', fs_sl_eq: 'Sliding, seismic', fs_bc_eq: 'Bearing, seismic',
}

const SLOPE_LABELS: Record<string, string> = {
  H: 'Slope height H (m)', beta: 'Slope angle β (°)', bench_w: 'Bench width (m, 0 = none)', bench_h: 'Bench height above the toe (m, empty = H/2)',
  ru: 'Pore pressure ratio ru', q: 'Surcharge on the crest q (kPa)', q_offset: 'Surcharge starts behind the crest edge at (m)',
  kh: 'Horizontal seismic coefficient kh', n_slices: 'Number of slices (30–50)', depth_limit: 'Maximum slip depth below the toe (m, empty = H)',
  fs_req: 'Required FS (empty = 1.5, or 1.1 with kh)', z: 'Depth of the slip plane z (m)', m: 'Water height ratio m (0 dry – 1 at surface)',
  gamma: 'Unit weight γ (kN/m³)', gamma_sat: 'Saturated unit weight γsat (kN/m³)', c: "Cohesion c' (kPa)", phi: "Friction angle φ' (°)",
}

function Num({ name, inputs, set, labels }: { name: string, inputs: Inputs, set: SetFn, labels: Record<string, string> }) {
  return (
    <div className="field">
      <label htmlFor={`g-${name}`}>{t(labels[name] || name)}</label>
      <input id={`g-${name}`} type="text" inputMode="decimal" value={inputs[name] ?? ''} onChange={e => set(name, e.target.value.replace(/,/g, '.'))} />
    </div>
  )
}

function Choice({ name, label, inputs, set, options }: { name: string, label: string, inputs: Inputs, set: SetFn, options: Array<[string, string]> }) {
  return (
    <div className="field">
      <label htmlFor={`g-${name}`}>{t(label)}</label>
      <select id={`g-${name}`} value={inputs[name] ?? options[0][0]} onChange={e => set(name, e.target.value)}>
        {options.map(([v, l]) => <option key={v} value={v}>{t(l)}</option>)}
      </select>
    </div>
  )
}

const f = (v: any, d = 0) => {
  const n = v === '' || v === null || v === undefined ? NaN : Number(v)
  return Number.isFinite(n) ? n : d
}

// ---------------------------------------------------------------------------
// Retaining wall
// ---------------------------------------------------------------------------

function wallSketch(i: Inputs): SectionSpec | null {
  const H = f(i.H), toe = f(i.toe), heel = f(i.heel), tt = f(i.t_top), tb = f(i.t_bot), bat = f(i.back_batter), D = f(i.D_base)
  if (!(H > D && D > 0 && tt > 0 && tb >= tt)) return null
  const B = toe + tb + heel, xb = toe + tb, xbt = xb - bat, xft = xbt - tt
  const slope = Math.tan((f(i.beta) * Math.PI) / 180)
  const far = B + Math.max(1, 0.6 * H)
  const gw = i.gw === '' || i.gw === undefined ? null : H - f(i.gw)
  const polygons: SectionSpec['polygons'] = [
    { role: 'concrete', points: [[0, 0], [B, 0], [B, D], [0, D]] },
    { role: 'concrete', points: [[toe, D], [xb, D], [xbt, H], [xft, H]] },
  ]
  if (B > xb) polygons.push({ role: 'soil', points: [[xb, D], [B, D], [B, H + (B - xbt) * slope], [xbt, H]] })
  const lines: SectionSpec['lines'] = [
    { role: 'ground', points: [[xbt, H], [far, H + (far - xbt) * slope]] },
    { role: 'ground', points: [[-Math.max(1, 0.4 * H), f(i.D_front, D)], [0, f(i.D_front, D)]] },
  ]
  if (gw !== null && gw > 0) lines.push({ role: 'water', points: [[xbt, gw], [far, gw]] })
  return { polygons, lines, labels: [{ at: [B / 2, -0.04 * Math.max(B, H)], text: `B = ${number(B)} m` }] }
}

export function WallInputs({ inputs, set }: { inputs: Inputs, set: SetFn }) {
  const sketch = wallSketch(inputs)
  const nums = (keys: string[]) => keys.map(k => <Num key={k} name={k} inputs={inputs} set={set} labels={LABELS} />)
  return <>
    <Choice name="wall_type" label="Wall type" inputs={inputs} set={set} options={[['cantilever', 'Cantilever (reinforced concrete)'], ['gravity', 'Gravity (mass concrete or masonry)']]} />
    <Choice name="method" label="Earth pressure" inputs={inputs} set={set} options={[['rankine', 'Rankine (vertical plane through the heel)'], ['coulomb', 'Coulomb (with wall friction δ)']]} />
    <details className="field wide form-group" open>
      <summary>{t('Wall geometry')}</summary>
      <div className="geo-split">
        <div className="fields">{nums(['H', 'D_base', 'toe', 'heel', 't_top', 't_bot', 'back_batter', 'gamma_c'])}</div>
        {sketch && <div className="geo-preview"><SectionView spec={sketch} compact /><p className="help">{t('Section preview, to scale. Base width B = toe + stem base + heel.')}</p></div>}
      </div>
    </details>
    <details className="field wide form-group" open>
      <summary>{t('Backfill')}</summary>
      <div className="fields">{nums(['gamma', 'gamma_sat', 'phi', 'c', 'beta', 'delta', 'q', 'gw'])}</div>
    </details>
    <details className="field wide form-group" open>
      <summary>{t('Foundation soil under the base')}</summary>
      <div className="fields">
        {nums(['found_phi', 'found_c', 'found_gamma', 'D_front', 'q_allow'])}
        <Choice name="passive" label="Passive resistance in front of the toe" inputs={inputs} set={set} options={[['no', 'Not counted (conservative)'], ['yes', 'Counted']]} />
      </div>
    </details>
    <details className="field wide form-group" open={f(inputs.kh) > 0 || undefined}>
      <summary>{t('Seismic load (pseudo-static)')}</summary>
      <div className="fields">
        {nums(['kh', 'kv'])}
        <p className="help wide">{t('kh is often taken as about half of PGA_M (in g) for walls that may move a little. Leave 0 for the static case only.')}</p>
      </div>
    </details>
    <details className="field wide form-group">
      <summary>{t('Required factors of safety')}</summary>
      <div className="fields">
        {nums(['fs_ot', 'fs_sl', 'fs_bc', 'fs_ot_eq', 'fs_sl_eq', 'fs_bc_eq'])}
        <p className="help wide">{t('Defaults follow common practice with SNI 8460:2017; change them to the project specification. Eccentricity limits: B/6 static, B/4 seismic.')}</p>
      </div>
    </details>
    <p className="help wide">{t('The default values reproduce the cantilever wall example in Das, Principles of Foundation Engineering (FS overturning 2.98, sliding 2.73, bearing 3.03).')}</p>
  </>
}

// ---------------------------------------------------------------------------
// Slope
// ---------------------------------------------------------------------------

/** Ground polyline as the server builds it (simple geometry) or as entered. */
export function slopeGround(i: Inputs): Pt[] | null {
  if (i.geometry === 'points') {
    const pts = (i.surface || []).filter((p: Inputs) => p.x !== '' && p.y !== '' && p.x !== undefined && p.y !== undefined)
      .map((p: Inputs) => [Number(p.x), Number(p.y)] as Pt).filter((p: Pt) => p.every(Number.isFinite))
    return pts.length >= 2 ? pts : null
  }
  const H = f(i.H), beta = f(i.beta)
  if (!(H > 0 && beta > 0 && beta < 90)) return null
  const run = 1 / Math.tan((beta * Math.PI) / 180)
  const xt = Math.max(H, 5), bw = f(i.bench_w), bh = i.bench_h === '' || i.bench_h === undefined ? H / 2 : f(i.bench_h)
  const tail = Math.max(1.5 * H, 10)
  if (bw > 0 && bh > 0 && bh < H) {
    const x1 = xt + bh * run, x2 = x1 + bw, xc = x2 + (H - bh) * run
    return [[0, 0], [xt, 0], [x1, bh], [x2, bh], [xc, H], [xc + tail, H]]
  }
  const xc = xt + H * run
  return [[0, 0], [xt, 0], [xc, H], [xc + tail, H]]
}

const groundAt = (g: Pt[], x: number) => {
  if (x <= g[0][0]) return g[0][1]
  for (let k = 1; k < g.length; k++) if (x <= g[k][0]) return g[k - 1][1] + (g[k][1] - g[k - 1][1]) * (x - g[k - 1][0]) / ((g[k][0] - g[k - 1][0]) || 1)
  return g[g.length - 1][1]
}

function slopeSketch(i: Inputs): SectionSpec | null {
  const g = slopeGround(i)
  if (!g) return null
  const lines: SectionSpec['lines'] = [{ role: 'ground', points: g }]
  const polygons: SectionSpec['polygons'] = []
  const yMin = Math.min(...g.map(p => p[1])) - Math.max(2, 0.4 * (Math.max(...g.map(p => p[1])) - Math.min(...g.map(p => p[1]))))
  const layers: Inputs[] = i.layers || []
  let top = Math.max(...g.map(p => p[1])) + 1
  layers.forEach((l, k) => {
    const bot = k === layers.length - 1 || l.bottom === '' || l.bottom === undefined ? yMin : Math.max(yMin, f(l.bottom, yMin))
    if (bot >= top) return
    const xs = new Set<number>(g.map(p => p[0]))
    for (let s = 1; s < g.length; s++) for (const lv of [top, bot]) {
      const [a, b] = [g[s - 1], g[s]]
      if ((a[1] - lv) * (b[1] - lv) < 0) xs.add(a[0] + (lv - a[1]) / (b[1] - a[1]) * (b[0] - a[0]))
    }
    const sorted = [...xs].sort((a, b) => a - b)
    const upper = sorted.map(x => [x, Math.min(Math.max(groundAt(g, x), bot), top)] as Pt)
    polygons.push({ role: `layer${k % 5}`, points: [...upper, [sorted[sorted.length - 1], bot], [sorted[0], bot]] })
    top = bot
  })
  if (i.water === 'phreatic') {
    const w = (i.phreatic || []).filter((p: Inputs) => p.x !== '' && p.y !== '').map((p: Inputs) => [Number(p.x), Number(p.y)] as Pt).filter((p: Pt) => p.every(Number.isFinite))
    if (w.length >= 2) lines.push({ role: 'water', points: w })
  }
  return { polygons, lines }
}

function PointTable({ label, rows, onChange, cols }: { label: string, rows: Inputs[], onChange: (r: Inputs[]) => void, cols: Array<[string, string]> }) {
  return (
    <div className="field wide">
      <label>{t(label)}</label>
      <div className="table-scroll">
        <table className="grid-table geo-grid">
          <thead><tr><th>#</th>{cols.map(([k, l]) => <th key={k}>{t(l)}</th>)}<th /></tr></thead>
          <tbody>{rows.map((row, i) => (
            <tr key={i}>
              <td className="muted">{i + 1}</td>
              {cols.map(([k, l]) => <td key={k}><input aria-label={`${t(l)} ${i + 1}`} inputMode="decimal" value={row[k] ?? ''}
                onChange={e => onChange(rows.map((r, j) => j === i ? { ...r, [k]: e.target.value.replace(/,/g, '.') } : r))} /></td>)}
              <td><button type="button" className="quiet danger-quiet small" aria-label={t('Remove row')} onClick={() => onChange(rows.filter((_, j) => j !== i))}>×</button></td>
            </tr>
          ))}</tbody>
        </table>
      </div>
      <div className="actions" style={{ marginTop: '.5rem' }}>
        <button type="button" onClick={() => onChange([...rows, Object.fromEntries(cols.map(([k]) => [k, '']))])}>{t('Add row')}</button>
      </div>
    </div>
  )
}

const LAYER_COLS: Array<[string, string]> = [['bottom', 'Bottom elevation (m)'], ['gamma', 'γ (kN/m³)'], ['gamma_sat', 'γsat (kN/m³)'], ['c', "c' (kPa)"], ['phi', "φ' (°)"]]
const XY: Array<[string, string]> = [['x', 'x (m)'], ['y', 'y (m)']]

export function SlopeInputs({ inputs, set }: { inputs: Inputs, set: SetFn }) {
  const nums = (keys: string[]) => keys.map(k => <Num key={k} name={k} inputs={inputs} set={set} labels={SLOPE_LABELS} />)
  if (inputs.mode === 'infinite') {
    return <>
      <Choice name="mode" label="Method" inputs={inputs} set={set} options={[['circular', 'Circular slip (Bishop, grid search)'], ['infinite', 'Infinite slope with seepage']]} />
      {nums(['beta', 'z', 'm', 'gamma', 'gamma_sat', 'c', 'phi', 'kh', 'fs_req'])}
      <p className="help wide">{t('For long natural slopes with a shallow slip parallel to the surface, e.g. residual soil over rock.')}</p>
    </>
  }
  const sketch = slopeSketch(inputs)
  const layers: Inputs[] = inputs.layers || []
  return <>
    <Choice name="mode" label="Method" inputs={inputs} set={set} options={[['circular', 'Circular slip (Bishop, grid search)'], ['infinite', 'Infinite slope with seepage']]} />
    <Choice name="geometry" label="Slope geometry" inputs={inputs} set={set} options={[['simple', 'Height and angle (with an optional bench)'], ['points', 'Ground surface points']]} />
    <details className="field wide form-group" open>
      <summary>{t('Geometry and soil layers')}</summary>
      <div className="geo-split">
        <div className="fields">
          {inputs.geometry === 'points'
            ? <PointTable label="Ground surface from the toe side (left) to the crest (right)" rows={inputs.surface || []} onChange={r => set('surface', r)} cols={XY} />
            : nums(['H', 'beta', 'bench_w', 'bench_h'])}
        </div>
        {sketch && <div className="geo-preview"><SectionView spec={sketch} compact /><p className="help">{t('Section preview, to scale. The toe is at elevation 0 for the height-and-angle geometry.')}</p></div>}
      </div>
      <PointTable label="Soil layers from the top down (up to 5; the last layer has no bottom)" rows={layers}
        onChange={r => set('layers', r.slice(0, 5))} cols={LAYER_COLS} />
    </details>
    <details className="field wide form-group" open={inputs.water !== 'none' || undefined}>
      <summary>{t('Groundwater')}</summary>
      <div className="fields">
        <Choice name="water" label="Pore pressure" inputs={inputs} set={set} options={[['none', 'Dry (no pore pressure)'], ['phreatic', 'Phreatic line'], ['ru', 'Pore pressure ratio ru']]} />
        {inputs.water === 'ru' && nums(['ru'])}
        {inputs.water === 'phreatic' && <PointTable label="Phreatic line points from left to right" rows={inputs.phreatic || []} onChange={r => set('phreatic', r)} cols={XY} />}
      </div>
    </details>
    <details className="field wide form-group" open={f(inputs.q) > 0 || f(inputs.kh) > 0 || undefined}>
      <summary>{t('Loads and search')}</summary>
      <div className="fields">{nums(['q', 'q_offset', 'kh', 'n_slices', 'depth_limit', 'fs_req'])}</div>
    </details>
    <p className="help wide">{t('The default values reproduce the ACADS benchmark 1(a): homogeneous 2:1 slope, 10 m high, c\' = 3 kPa, φ\' = 19.6°, γ = 20 kN/m³; referee FS = 1.00.')}</p>
  </>
}

// ---------------------------------------------------------------------------
// Fill from the field and laboratory data
// ---------------------------------------------------------------------------

export function wallFromData(lab: Rec[]): { patch: Inputs, hint: string } {
  const shear = lab.find(x => (x.test_type === 'direct_shear' || x.test_type === 'triaxial') && x.results?.phi != null)
  const dens = lab.find(x => (x.test_type === 'density' || x.test_type === 'moisture') && x.results?.gamma_bulk)
  const patch: Inputs = {}
  if (shear) { patch.found_phi = String(shear.results.phi); patch.found_c = String(shear.results.c ?? 0) }
  if (dens) patch.found_gamma = String(dens.results.gamma_bulk)
  return {
    patch,
    hint: shear ? t('Foundation c\' and φ\' taken from sample {s} ({d} m). Backfill properties stay as entered.', { s: shear.sample_ref, d: shear.depth_top })
      : t('No shear test for this borehole yet; the foundation soil is unchanged.'),
  }
}

export function slopeFromData(inputs: Inputs, d: Details | null, lab: Rec[], gw: any): { patch: Inputs, hint: string } {
  if (!d?.layers.length) return { patch: {}, hint: t('This borehole has no strata yet.') }
  const g = slopeGround(inputs)
  const crest = g ? Math.max(...g.map(p => p[1])) : f(inputs.H, 0)
  const strata = d.layers.slice(0, 5)
  let found = 0
  const layers = strata.map((l, k) => {
    const inside = (x: Rec) => x.depth_top >= l.top && x.depth_top < l.base
    const shear = lab.find(x => (x.test_type === 'direct_shear' || x.test_type === 'triaxial') && inside(x) && x.results?.phi != null)
    const dens = lab.find(x => (x.test_type === 'density' || x.test_type === 'moisture') && inside(x) && x.results?.gamma_bulk)
    if (shear) found++
    const clay = /^(C|M|O|PT)/i.test(l.uscs || '')
    const gamma = dens?.results?.gamma_bulk ?? (clay ? 17 : 18)
    return {
      bottom: k === strata.length - 1 ? '' : String(Math.round((crest - l.base) * 100) / 100),
      gamma: String(gamma), gamma_sat: String(Math.round((gamma + 1) * 100) / 100),
      c: shear ? String(shear.results.c ?? 0) : '', phi: shear ? String(shear.results.phi) : '',
    }
  })
  const patch: Inputs = { layers }
  const depth = gw === '' || gw === null || gw === undefined ? null : Number(gw)
  if (g && depth !== null && Number.isFinite(depth)) {
    const level = crest - depth
    const xs = g.map(p => p[0])
    patch.water = 'phreatic'
    patch.phreatic = xs.map(x => ({ x: String(Math.round(x * 100) / 100), y: String(Math.round(Math.min(level, groundAt(g, x)) * 100) / 100) }))
  }
  return {
    patch,
    hint: t('Layers from the strata of the borehole, taken as drilled at the crest; c\' and φ\' from {n} shear test(s). Fill the empty cells and check the elevations.', { n: found }),
  }
}

// ---------------------------------------------------------------------------
// Section drawing (equal scale)
// ---------------------------------------------------------------------------

export type SectionSpec = {
  polygons?: Array<{ role: string, points: Pt[] }>
  lines?: Array<{ role: string, points: Pt[] }>
  arrows?: Array<{ role: string, from: Pt, to: Pt, label?: string, value?: number | null, unit?: string }>
  marks?: Array<{ role: string, at: Pt }>
  labels?: Array<{ at: Pt, text: string }>
}

const FILL: Record<string, [string, string]> = {
  concrete: ['#c9ccc5', '#5f666c'], soil: ['#eadcb8', '#b59b62'], pressure: ['rgba(180,35,24,.14)', '#b42318'],
  bearing: ['rgba(31,95,139,.14)', '#1f5f8b'],
  layer0: ['#efe3c2', '#c9b88e'], layer1: ['#dfc9a0', '#b9a073'], layer2: ['#d3c1a6', '#a8957a'], layer3: ['#c9b48a', '#9c865c'], layer4: ['#bfae94', '#8d7c62'],
}
const STROKE: Record<string, { c: string, w: number, d?: string }> = {
  ground: { c: '#23282d', w: 1.8 }, water: { c: '#1f5f8b', w: 1.4, d: '6 4' }, plane: { c: '#545b61', w: 1, d: '4 3' },
  circle: { c: '#b42318', w: 2.4 }, circle2: { c: '#d08a12', w: 1.1, d: '5 4' }, slice: { c: '#8a7d63', w: 0.5 },
  radius: { c: '#b42318', w: 0.7, d: '3 3' },
}
const ARROW: Record<string, string> = { force: '#b42318', weight: '#23282d', load: '#1f5f8b' }
const LEGEND: Record<string, string> = {
  concrete: 'Concrete', soil: 'Soil moving with the wall', pressure: 'Active pressure (horizontal)', bearing: 'Base pressure',
  water: 'Water level', plane: 'Pressure plane', circle: 'Critical circle', circle2: 'Next circles',
}

export function SectionView({ spec, compact = false }: { spec: SectionSpec, compact?: boolean }) {
  const all: Pt[] = [
    ...(spec.polygons || []).flatMap(p => p.points), ...(spec.lines || []).flatMap(l => l.points),
    ...(spec.arrows || []).flatMap(a => [a.from, a.to]), ...(spec.marks || []).filter(m => m.role !== 'grid').map(m => m.at),
  ]
  if (all.length < 2) return null
  const minX = Math.min(...all.map(p => p[0])), maxX = Math.max(...all.map(p => p[0]))
  const minY = Math.min(...all.map(p => p[1])), maxY = Math.max(...all.map(p => p[1]))
  const dx = Math.max(maxX - minX, 1e-6), dy = Math.max(maxY - minY, 1e-6)
  const W = compact ? 360 : 640, pad = compact ? 12 : 26
  const Hpx = Math.min(compact ? 300 : 520, Math.max(compact ? 140 : 220, (dy / dx) * (W - 2 * pad) + 2 * pad))
  const s = Math.min((W - 2 * pad) / dx, (Hpx - 2 * pad) / dy)
  const ox = (W - s * dx) / 2, oy = (Hpx - s * dy) / 2
  const X = (x: number) => ox + (x - minX) * s
  const Y = (y: number) => Hpx - oy - (y - minY) * s
  const path = (pts: Pt[]) => pts.map(p => `${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join(' ')
  const fs = compact ? 10 : 15
  const roles = new Set<string>([...(spec.polygons || []).map(p => p.role), ...(spec.lines || []).map(l => l.role)])
  return (
    <figure className={`geo-section${compact ? ' compact' : ''}`}>
      <svg viewBox={`0 0 ${W} ${Hpx.toFixed(0)}`} width="100%" role="img" aria-label={t('Cross-section')}>
        <rect x="0" y="0" width={W} height={Hpx} fill="#fbfbf9" />
        {(spec.polygons || []).map((p, i) => {
          const [fill, stroke] = FILL[p.role] || ['#eee', '#999']
          return <polygon key={'p' + i} points={path(p.points)} fill={fill} stroke={stroke} strokeWidth={p.role.startsWith('layer') ? 0.6 : 1} />
        })}
        {(spec.marks || []).filter(m => m.role === 'grid').map((m, i) => <circle key={'g' + i} cx={X(m.at[0])} cy={Y(m.at[1])} r="1.4" fill="#9aa19a" />)}
        {(spec.lines || []).map((l, i) => {
          const st = STROKE[l.role] || { c: '#555', w: 1 }
          return <polyline key={'l' + i} points={path(l.points)} fill="none" stroke={st.c} strokeWidth={st.w} strokeDasharray={st.d} strokeLinejoin="round" />
        })}
        {(spec.arrows || []).map((a, i) => {
          const c = ARROW[a.role] || '#23282d'
          const x1 = X(a.from[0]), y1 = Y(a.from[1]), x2 = X(a.to[0]), y2 = Y(a.to[1])
          const ang = Math.atan2(y2 - y1, x2 - x1), h = compact ? 6 : 8
          const head = `${x2},${y2} ${x2 - h * Math.cos(ang - 0.4)},${y2 - h * Math.sin(ang - 0.4)} ${x2 - h * Math.cos(ang + 0.4)},${y2 - h * Math.sin(ang + 0.4)}`
          return (
            <g key={'a' + i}>
              <line x1={x1} y1={y1} x2={x2} y2={y2} stroke={c} strokeWidth="1.6" />
              <polygon points={head} fill={c} />
              {a.label && <text x={x1 + 4} y={y1 - 4} fontSize={fs} fill={c}>{a.label}{a.value != null ? ` = ${number(a.value)} ${a.unit || ''}` : ''}</text>}
            </g>
          )
        })}
        {(spec.marks || []).filter(m => m.role !== 'grid').map((m, i) => {
          const x = X(m.at[0]), y = Y(m.at[1])
          if (m.role === 'centre') return <g key={'m' + i}><circle cx={x} cy={y} r="4" fill="#b42318" /><line x1={x - 7} x2={x + 7} y1={y} y2={y} stroke="#b42318" /><line x1={x} x2={x} y1={y - 7} y2={y + 7} stroke="#b42318" /></g>
          if (m.role === 'third') return <line key={'m' + i} x1={x} x2={x} y1={y - 5} y2={y + 5} stroke="#1f5f8b" strokeWidth="1.2" />
          if (m.role === 'resultant') return <polygon key={'m' + i} points={`${x},${y - 1} ${x - 5},${y + 8} ${x + 5},${y + 8}`} fill="#1f5f8b" />
          return null
        })}
        {(spec.labels || []).map((l, i) => <text key={'t' + i} x={X(l.at[0])} y={Y(l.at[1]) + (compact ? 12 : 15)} fontSize={fs} textAnchor="middle" fill="#23282d">{l.text}</text>)}
      </svg>
      {!compact && (
        <figcaption className="geo-legend">
          {Object.entries(LEGEND).filter(([k]) => roles.has(k)).map(([k, l]) => {
            const fill = FILL[k]?.[0], line = STROKE[k]
            return <span key={k}><i style={fill ? { background: fill, borderColor: FILL[k][1] } : { background: 'transparent', borderTop: `2px ${line?.d ? 'dashed' : 'solid'} ${line?.c}`, height: 0 }} />{t(l)}</span>
          })}
          {(spec.marks || []).some(m => m.role === 'third') && <span><i className="tick" />{t('Middle third of the base')}</span>}
        </figcaption>
      )}
    </figure>
  )
}

// ---------------------------------------------------------------------------
// Result
// ---------------------------------------------------------------------------

export function GeoResult({ result }: { result: Record<string, any> }) {
  const checks: Rec[] = result.checks || []
  const pass = result.status === 'pass'
  return (
    <div className="geo-result">
      {checks.length > 0 && (
        <div className="geo-checks" role="list">
          {checks.map((c, i) => (
            <div key={i} role="listitem" className={`geo-check ${c.ok ? 'ok' : 'bad'}`}>
              <span className={`status ${c.ok ? 'ok' : 'bad'}`}>{c.ok ? t('OK') : t('Not OK')}</span>
              <span className="geo-check-name">{t(c.check)} <small className="muted">· {t(c.case)}</small></span>
              <strong className="geo-check-value">{c.value === null || c.value === undefined ? '∞' : number(c.value)}{c.unit ? ` ${c.unit}` : ''}</strong>
              <small className="muted">{t('required')} {lang() === 'id' ? String(c.required).replace(/(\d)\.(\d)/g, '$1,$2') : c.required}</small>
            </div>
          ))}
        </div>
      )}
      {result.classification && <p className={`notice ${pass ? 'ok' : 'warn'}`}>{translateServer(result.classification)}</p>}
      {result.section && <SectionView spec={result.section} />}
      <ResultView result={result} notesOpen />
      {Array.isArray(result.standards) && result.standards.length > 0 && (
        <details className="ws-notes">
          <summary>{t('Standards and references')}</summary>
          <ul className="std-list">{result.standards.map(([code, title]: [string, string]) => <li key={code}><strong>{code}</strong> <span className="muted">{t(title)}</span></li>)}</ul>
        </details>
      )}
    </div>
  )
}
