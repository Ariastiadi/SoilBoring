import { useEffect } from 'react'
import { createPortal } from 'react-dom'
import type { Details } from './api'
import { coreSizeLabel, methodLabel } from './options'
import { t } from './i18n'

type Row = Record<string, string | undefined>

// Graphic log patterns per USCS group (first symbol of dual symbols such as SP-SM).
type Pattern = 'clay' | 'silt' | 'sand' | 'gravel' | 'organic' | 'peat' | 'unknown'

function patternOf(uscs: string): Pattern {
  const first = (uscs || '').toUpperCase().split(/[-/ ]/)[0]
  if (first === 'PT') return 'peat'
  if (first === 'OL' || first === 'OH') return 'organic'
  if (first.startsWith('C')) return 'clay'
  if (first.startsWith('M')) return 'silt'
  if (first.startsWith('S')) return 'sand'
  if (first.startsWith('G')) return 'gravel'
  return 'unknown'
}

// Shown when a layer has no written description.
const USCS_NAMES: Record<Pattern, string> = {
  clay: 'Clay', silt: 'Silt', sand: 'Sand', gravel: 'Gravel', organic: 'Organic soil', peat: 'Peat', unknown: '',
}

const FILL: Record<Pattern, string> = {
  clay: '#d9c7a7', silt: '#e6d9b8', sand: '#f3e3a1', gravel: '#e8c98f', organic: '#b9b39a', peat: '#8d7b62', unknown: '#dddddd',
}

function PatternDefs() {
  return (
    <defs>
      <pattern id="p-clay" width="12" height="6" patternUnits="userSpaceOnUse">
        <rect width="12" height="6" fill={FILL.clay} /><line x1="0" y1="3" x2="12" y2="3" stroke="#6b5a3c" strokeWidth="0.8" />
      </pattern>
      <pattern id="p-silt" width="12" height="6" patternUnits="userSpaceOnUse">
        <rect width="12" height="6" fill={FILL.silt} /><line x1="1" y1="3" x2="6" y2="3" stroke="#6b5a3c" strokeWidth="0.8" />
        <circle cx="9" cy="3" r="0.7" fill="#6b5a3c" />
      </pattern>
      <pattern id="p-sand" width="8" height="8" patternUnits="userSpaceOnUse">
        <rect width="8" height="8" fill={FILL.sand} /><circle cx="2" cy="2" r="0.8" fill="#7a6430" /><circle cx="6" cy="6" r="0.8" fill="#7a6430" />
      </pattern>
      <pattern id="p-gravel" width="14" height="12" patternUnits="userSpaceOnUse">
        <rect width="14" height="12" fill={FILL.gravel} /><circle cx="4" cy="4" r="2.4" fill="none" stroke="#6b4f20" strokeWidth="0.8" />
        <circle cx="11" cy="9" r="2" fill="none" stroke="#6b4f20" strokeWidth="0.8" />
      </pattern>
      <pattern id="p-organic" width="12" height="8" patternUnits="userSpaceOnUse">
        <rect width="12" height="8" fill={FILL.organic} /><path d="M1 4 q2 -2 4 0 t4 0" fill="none" stroke="#3f3a2a" strokeWidth="0.8" />
      </pattern>
      <pattern id="p-peat" width="8" height="8" patternUnits="userSpaceOnUse">
        <rect width="8" height="8" fill={FILL.peat} /><line x1="0" y1="8" x2="8" y2="0" stroke="#3b2f20" strokeWidth="0.9" />
      </pattern>
      <pattern id="p-unknown" width="8" height="8" patternUnits="userSpaceOnUse">
        <rect width="8" height="8" fill={FILL.unknown} /><path d="M0 0 L8 8 M8 0 L0 8" stroke="#777" strokeWidth="0.5" />
      </pattern>
    </defs>
  )
}

const num = (v: unknown) => {
  const n = typeof v === 'number' ? v : parseFloat(String(v ?? ''))
  return Number.isFinite(n) ? n : null
}
const fmt = (v: number | null | undefined, dp = 2) => (v === null || v === undefined ? '' : v.toFixed(dp))

// Column layout in SVG units (1 unit ≈ 0.19 mm on A4 portrait).
const W = 1000
const COL = {
  depth: [0, 75], graphic: [75, 140], desc: [140, 520], samples: [520, 610], spt: [610, 860], core: [860, 1000],
} as const
const H = 1150 // drawing height per page
const N_MAX = 50

function pagesFor(maxDepth: number): Array<[number, number]> {
  if (maxDepth <= 20) {
    const span = Math.max(5, Math.ceil(maxDepth / 5) * 5)
    return [[0, span]]
  }
  const span = 15
  const out: Array<[number, number]> = []
  for (let top = 0; top < maxDepth; top += span) out.push([top, top + span])
  return out
}

function Header({ report, page, pages }: { report: Row, page: number, pages: number }) {
  const gw = String(report.GroundwaterEncountered).toLowerCase() === 'true'
  const cells: Array<[string, string | undefined]> = [
    [t('Project'), report.ProjectName],
    [t('Borehole'), report.BoreholeID],
    [t('Site / Zone'), report.SiteName],
    [t('Coordinates'), report.Latitude && report.Longitude ? `${report.Latitude}, ${report.Longitude}` : ''],
    [t('Ground level (mRL)'), report.GroundElevation_mRL],
    [t('Dates'), `${report.StartDate || ''} – ${report.EndDate || ''}`],
    [t('Method'), report.DrillingMethod ? methodLabel(report.DrillingMethod) : report.DrillingMethod],
    [t('Rig'), report.DrillRig],
    [t('Core size'), report.CoreSize ? coreSizeLabel(report.CoreSize) : ''],
    [t('Contractor'), report.Contractor],
    [t('Logged by'), report.LoggingGeologist],
    [t('Groundwater'), gw ? `${report.GroundwaterDepth_m || '?'} m` : t('Not encountered')],
    [t('Final depth'), report.FinalDepth_m ? `${report.FinalDepth_m} m` : ''],
    [t('Sheet'), `${page} / ${pages}`],
  ]
  return (
    <table className="borelog-head">
      <tbody>
        {Array.from({ length: Math.ceil(cells.length / 4) }, (_, r) => (
          <tr key={r}>
            {cells.slice(r * 4, r * 4 + 4).map(([k, v]) => (
              <td key={k}><span>{k}</span><strong>{v || '–'}</strong></td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function Sheet({ report, details, range, page, pages }: { report: Row, details: Details, range: [number, number], page: number, pages: number }) {
  const [top, bottom] = range
  const span = bottom - top
  const y = (d: number) => ((d - top) / span) * H
  const inRange = (a: number, b: number) => b > top && a < bottom
  const clampY = (d: number) => y(Math.min(Math.max(d, top), bottom))
  const ticks = []
  const step = span <= 10 ? 0.5 : 1
  for (let d = Math.ceil(top / step) * step; d <= bottom + 1e-9; d += step) ticks.push(Number(d.toFixed(2)))
  const gwDepth = String(report.GroundwaterEncountered).toLowerCase() === 'true' ? num(report.GroundwaterDepth_m) : null
  const sptX = (n: number) => COL.spt[0] + 10 + (Math.min(n, N_MAX) / N_MAX) * (COL.spt[1] - COL.spt[0] - 20)
  const spt = details.spt.filter(s => s.depth >= top && s.depth <= bottom)

  return (
    <section className="borelog-page">
      <h2>{t('Borehole log')} {report.BoreholeID}</h2>
      <Header report={report} page={page} pages={pages} />
      <div className="borelog-body">
        <svg viewBox={`0 -40 ${W} ${H + 60}`} preserveAspectRatio="none" className="borelog-svg">
          <PatternDefs />
          {/* column titles */}
          {([
            ['depth', t('Depth (m)')], ['graphic', t('Log')], ['desc', t('Description')], ['samples', t('Samples')],
            ['spt', `SPT N (0–${N_MAX})`], ['core', 'TCR / RQD %'],
          ] as Array<[keyof typeof COL, string]>).map(([k, label]) => (
            k === 'depth' ? (
              <text key={k} x={(COL[k][0] + COL[k][1]) / 2} y={-22} fontSize="12" textAnchor="middle" fontWeight="600">
                <tspan x={(COL[k][0] + COL[k][1]) / 2}>{t('Depth')}</tspan>
                <tspan x={(COL[k][0] + COL[k][1]) / 2} dy="14">(m)</tspan>
              </text>
            ) : (
              <text key={k} x={(COL[k][0] + COL[k][1]) / 2} y={-14} fontSize="15" textAnchor="middle" fontWeight="600">{label}</text>
            )
          ))}
          {Object.values(COL).map(([x0], i) => <line key={i} x1={x0} y1={-40} x2={x0} y2={H} stroke="#333" strokeWidth="1" />)}
          <rect x="0" y="-40" width={W} height={H + 40} fill="none" stroke="#333" strokeWidth="1.5" />
          <line x1="0" y1="0" x2={W} y2="0" stroke="#333" />
          {/* depth ticks */}
          {ticks.map(d => (
            <g key={d}>
              <line x1={COL.depth[1] - (Number.isInteger(d) ? 14 : 7)} y1={y(d)} x2={COL.depth[1]} y2={y(d)} stroke="#333" />
              {Number.isInteger(d) && <text x={COL.depth[1] - 18} y={y(d) + 5} fontSize="14" textAnchor="end">{d}</text>}
              {Number.isInteger(d) && <line x1={COL.spt[0]} y1={y(d)} x2={COL.spt[1]} y2={y(d)} stroke="#eee" />}
            </g>
          ))}
          {/* strata */}
          {details.layers.filter(l => inRange(l.top, l.base)).map((l, i) => (
            <g key={i}>
              <rect x={COL.graphic[0]} y={clampY(l.top)} width={COL.graphic[1] - COL.graphic[0]} height={clampY(l.base) - clampY(l.top)}
                fill={`url(#p-${patternOf(l.uscs)})`} stroke="#333" strokeWidth="0.8" />
              <line x1={COL.desc[0]} y1={clampY(l.base)} x2={COL.desc[1]} y2={clampY(l.base)} stroke="#333" strokeWidth="0.8" />
              {l.base <= bottom && <text x={COL.desc[1] - 6} y={clampY(l.base) - 4} fontSize="12" textAnchor="end" fill="#555">{fmt(l.base)}</text>}
            </g>
          ))}
          {/* groundwater */}
          {gwDepth !== null && gwDepth >= top && gwDepth <= bottom && (
            <g>
              <path d={`M${COL.graphic[1] + 4} ${y(gwDepth) - 12} l12 0 l-6 10 z`} fill="#1d4ed8" />
              <line x1={COL.graphic[0]} y1={y(gwDepth)} x2={COL.graphic[1] + 30} y2={y(gwDepth)} stroke="#1d4ed8" strokeDasharray="6 4" />
            </g>
          )}
          {/* samples */}
          {details.samples.filter(s => inRange(s.top, s.base ?? s.top + 0.3)).map((s, i) => (
            <g key={i}>
              <rect x={COL.samples[0] + 8} y={clampY(s.top)} width="14" height={Math.max(4, clampY(s.base ?? s.top + 0.3) - clampY(s.top))}
                fill={s.type === 'U' || s.type === 'UT' || s.type === 'TW' || s.type === 'P' ? '#111' : '#fff'} stroke="#111" />
              <text x={COL.samples[0] + 28} y={clampY(s.top) + 12} fontSize="12">{s.ref || s.type}</text>
            </g>
          ))}
          {/* SPT graph */}
          {[10, 20, 30, 40, 50].map(n => (
            <g key={n}>
              <line x1={sptX(n)} y1={0} x2={sptX(n)} y2={H} stroke="#eee" />
              <text x={sptX(n)} y={H + 16} fontSize="11" textAnchor="middle" fill="#555">{n}</text>
            </g>
          ))}
          {spt.length > 1 && (
            <polyline fill="none" stroke="#b91c1c" strokeWidth="1.5"
              points={spt.map(s => `${sptX((s.inc1 || 0) + (s.inc2 || 0))},${y(s.depth)}`).join(' ')} />
          )}
          {spt.map((s, i) => {
            const n = (s.inc1 || 0) + (s.inc2 || 0)
            const refusal = s.penetration_mm !== null && s.penetration_mm !== undefined && s.penetration_mm < 300
            return (
              <g key={i}>
                <circle cx={sptX(n)} cy={y(s.depth)} r="4.5" fill={refusal ? '#fff' : '#b91c1c'} stroke="#b91c1c" strokeWidth="1.5" />
                <text x={Math.min(sptX(n) + 8, COL.spt[1] - 4)} y={y(s.depth) - 6} fontSize="12" textAnchor={sptX(n) + 60 > COL.spt[1] ? 'end' : 'start'}>
                  {refusal ? `${n}/${s.penetration_mm}mm` : n}
                </text>
              </g>
            )
          })}
          {/* core runs */}
          {details.core.filter(c => inRange(c.top, c.base)).map((c, i) => {
            const y0 = clampY(c.top), y1 = clampY(c.base)
            const width = COL.core[1] - COL.core[0] - 20
            return (
              <g key={i}>
                <rect x={COL.core[0] + 10} y={y0} width={width} height={y1 - y0} fill="none" stroke="#999" />
                {c.tcr !== null && <rect x={COL.core[0] + 10} y={y0} width={(width * c.tcr) / 100} height={(y1 - y0) / 2} fill="#94a3b8" />}
                {c.rqd !== null && <rect x={COL.core[0] + 10} y={(y0 + y1) / 2} width={(width * c.rqd) / 100} height={(y1 - y0) / 2} fill="#334155" />}
                <text x={COL.core[0] + 14} y={y0 + 13} fontSize="11">{c.tcr ?? '–'} / {c.rqd ?? '–'}</text>
              </g>
            )
          })}
          {/* end of hole */}
          {(() => {
            const fd = num(report.FinalDepth_m)
            return fd !== null && fd >= top && fd <= bottom ? (
              <g>
                <line x1="0" y1={y(fd)} x2={COL.desc[1]} y2={y(fd)} stroke="#111" strokeWidth="2.5" />
                <text x={COL.desc[0] + 8} y={y(fd) + 18} fontSize="13" fontWeight="600">{t('End of borehole at {d} m', { d: fmt(fd) })}</text>
              </g>
            ) : null
          })()}
        </svg>
        {/* descriptions as HTML so long text wraps */}
        {details.layers.filter(l => inRange(l.top, l.base)).map((l, i) => {
          const y0 = clampY(l.top), y1 = clampY(l.base)
          return (
            <div key={i} className="borelog-desc" style={{
              left: `${(COL.desc[0] / W) * 100}%`, width: `${((COL.desc[1] - COL.desc[0]) / W) * 100}%`,
              top: `${((y0 + 40) / (H + 60)) * 100}%`, height: `${((y1 - y0) / (H + 60)) * 100}%`,
            }}>
              {l.uscs && <strong>{l.uscs}: </strong>}{l.description || (l.uscs ? t(USCS_NAMES[patternOf(l.uscs)]) : '')}
            </div>
          )
        })}
      </div>
      <p className="borelog-legend">
        {t('Legend')}: ● SPT N · ○ {t('refusal (blows / penetration)')} · ▼ {t('groundwater')} · ■ {t('undisturbed sample')} · □ {t('disturbed sample')} · {t('core bar: light = TCR, dark = RQD')}
      </p>
    </section>
  )
}

export default function BoreLog({ report, details, onClose }: { report: Row, details: Details, onClose: () => void }) {
  const maxDepth = Math.max(
    num(report.FinalDepth_m) ?? 0,
    ...details.layers.map(l => l.base),
    ...details.spt.map(s => s.depth + 0.45),
    ...details.core.map(c => c.base),
    ...details.samples.map(s => s.base ?? s.top),
    1,
  )
  const pages = pagesFor(maxDepth)

  useEffect(() => {
    document.body.classList.add('printing-borelog')
    return () => document.body.classList.remove('printing-borelog')
  }, [])

  // Rendered next to the app (not inside it), so printing can hide everything else.
  return createPortal(
    <div className="borelog-root">
      <div className="borelog-toolbar no-print">
        <button onClick={() => window.print()}>{t('Print / save as PDF')}</button>
        <button onClick={onClose}>{t('Close')}</button>
        <span>{t('In the print window choose "Save as PDF" and paper size A4.')}</span>
      </div>
      {pages.map((range, i) => (
        <Sheet key={i} report={report} details={details} range={range} page={i + 1} pages={pages.length} />
      ))}
    </div>,
    document.body,
  )
}
