/**
 * Borehole drawn to depth scale: a graphic log whose width follows grain size, next to
 * SPT N plotted against depth (the layout of a classic graphic log with a downhole plot).
 */
import { FILL, GRAIN_WIDTH, PATTERN_ORDER, PatternDefs, USCS_NAMES, patternOf } from './soil'
import { t } from './i18n'

export type StripLayer = { top: number, base: number, uscs: string }
export type StripSpt = { depth: number, n?: number | null, penetration_mm?: number | null }

/** Mini column for lists: strata to scale, width by grain size; dashed when nothing is logged. */
export function StrataStrip({ layers, depth, title }: { layers: StripLayer[], depth: number | null, title?: string }) {
  const W = 30
  const H = 46
  const deepest = Math.max(depth || 0, ...layers.map(l => l.base), 0.01)
  const y = (d: number) => (d / deepest) * H
  return (
    <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} role="img" aria-label={title} style={{ flex: 'none', display: 'block' }}>
      <title>{title}</title>
      <rect x="0.5" y="0.5" width={W - 1} height={H - 1} fill="#fff" stroke={layers.length ? '#8a8f86' : '#a9aea6'}
        strokeDasharray={layers.length ? undefined : '3 2'} />
      {layers.map((l, i) => {
        const p = patternOf(l.uscs)
        const w = (W - 2) * GRAIN_WIDTH[p]
        return <rect key={i} x={1} y={Math.max(1, y(l.top))} width={w} height={Math.max(1, y(l.base) - y(l.top))} fill={FILL[p]} stroke="#6f746c" strokeWidth="0.5" />
      })}
    </svg>
  )
}

const fmt = (v: number) => (Number.isInteger(v) ? String(v) : v.toFixed(2).replace(/0$/, ''))

export function Profile({ layers, spt, finalDepth, groundwater, samples = [] }: {
  layers: StripLayer[]
  spt: StripSpt[]
  finalDepth: number | null
  groundwater: number | null
  samples?: Array<{ top: number, type: string, ref?: string }>
}) {
  const deepest = Math.max(finalDepth || 0, ...layers.map(l => l.base), ...spt.map(s => s.depth), 1)
  const pxPerM = Math.min(40, Math.max(14, 620 / deepest))
  const TOP = 46
  const H = Math.ceil(deepest * pxPerM)
  const y = (d: number) => TOP + d * pxPerM
  // Columns: depth axis | graphic log | USCS | samples | SPT plot
  const X = { axis: 40, log: 52, logW: 110, uscs: 172, samp: 214, plot: 262, plotW: 300 }
  const width = X.plot + X.plotW + 64
  const nMax = Math.max(50, ...spt.map(s => s.n ?? 0))
  const nScale = Math.ceil(nMax / 10) * 10
  const nx = (n: number) => X.plot + (Math.min(n, nScale) / nScale) * X.plotW
  const step = deepest > 40 ? 5 : deepest > 15 ? 2 : 1
  const ticks: number[] = []
  for (let d = 0; d <= deepest + 1e-9; d += step) ticks.push(Number(d.toFixed(2)))
  const used = PATTERN_ORDER.filter(p => layers.some(l => patternOf(l.uscs) === p))
  const points = spt.filter(s => s.n !== null && s.n !== undefined).sort((a, b) => a.depth - b.depth)

  return (
    <div>
      <div className="profile-wrap">
        <svg className="profile-svg" width={width} height={TOP + H + 30} viewBox={`0 0 ${width} ${TOP + H + 30}`} role="img"
          aria-label={t('Borehole profile: soil layers and SPT N by depth')}>
          <PatternDefs prefix="pf" />
          {/* headings */}
          <text x={X.log} y={16} fontSize="12" fontWeight="600" fill="#23282d">{t('Graphic log')}</text>
          <text x={X.plot} y={16} fontSize="12" fontWeight="600" fill="#23282d">{t('SPT N (blows / 300 mm)')}</text>
          {/* depth grid */}
          {ticks.map(d => (
            <g key={d}>
              <line x1={X.axis} x2={X.plot + X.plotW} y1={y(d)} y2={y(d)} stroke="#e1e4dd" />
              <text x={X.axis - 6} y={y(d) + 4} fontSize="11" textAnchor="end" fill="#545b61">{fmt(d)}</text>
            </g>
          ))}
          <text x={10} y={TOP + H / 2} fontSize="11" fill="#545b61" transform={`rotate(-90 10 ${TOP + H / 2})`} textAnchor="middle">{t('Depth (m)')}</text>
          <line x1={X.axis} x2={X.axis} y1={TOP} y2={TOP + H} stroke="#8a8f86" />
          {/* graphic log, width by grain size */}
          <rect x={X.log} y={TOP} width={X.logW} height={H} fill="#fff" stroke="#cdd2c9" strokeDasharray={layers.length ? undefined : '4 3'} />
          {layers.map((l, i) => {
            const p = patternOf(l.uscs)
            const h = Math.max(1, y(l.base) - y(l.top))
            return (
              <g key={i}>
                <rect x={X.log} y={y(l.top)} width={X.logW * GRAIN_WIDTH[p]} height={h} fill={`url(#pf-${p})`} stroke="#23282d" strokeWidth="0.8">
                  <title>{`${fmt(l.top)}–${fmt(l.base)} m ${l.uscs}`}</title>
                </rect>
                {h > 13 && l.uscs && <text x={X.uscs} y={y(l.top) + Math.min(h / 2 + 4, 16)} fontSize="12" fontWeight="600" fill="#23282d">{l.uscs}</text>}
              </g>
            )
          })}
          {!layers.length && <text x={X.log + 8} y={TOP + 20} fontSize="11" fill="#7b8288">{t('No layers yet')}</text>}
          {/* groundwater */}
          {groundwater !== null && groundwater <= deepest && (
            <g>
              <path d={`M${X.log + X.logW + 2} ${y(groundwater) - 9} l10 0 l-5 8 z`} fill="#1f5f8b" />
              <line x1={X.log} x2={X.log + X.logW} y1={y(groundwater)} y2={y(groundwater)} stroke="#1f5f8b" strokeDasharray="5 3" />
              <title>{t('Groundwater {d} m', { d: fmt(groundwater) })}</title>
            </g>
          )}
          {/* final depth */}
          {finalDepth !== null && (
            <g>
              <line x1={X.axis} x2={X.plot + X.plotW} y1={y(finalDepth)} y2={y(finalDepth)} stroke="#23282d" strokeWidth="1.5" />
              <text x={X.plot + X.plotW} y={y(finalDepth) - 4} fontSize="11" textAnchor="end" fill="#23282d">{t('End of hole {d} m', { d: fmt(finalDepth) })}</text>
            </g>
          )}
          {/* samples */}
          {samples.map((s, i) => (
            <g key={i}>
              <rect x={X.samp} y={y(s.top) - 4} width="10" height="8" fill={['U', 'UT', 'TW', 'P'].includes(s.type) ? '#23282d' : '#fff'} stroke="#23282d" />
              <title>{`${s.type} ${s.ref || ''} @ ${fmt(s.top)} m`}</title>
            </g>
          ))}
          {/* SPT plot */}
          <rect x={X.plot} y={TOP} width={X.plotW} height={H} fill="none" stroke="#cdd2c9" />
          {Array.from({ length: nScale / 10 + 1 }, (_, i) => i * 10).map(n => (
            <g key={n}>
              <line x1={nx(n)} x2={nx(n)} y1={TOP} y2={TOP + H} stroke={n === 0 ? '#8a8f86' : '#eef0eb'} />
              <text x={nx(n)} y={TOP - 6} fontSize="10" textAnchor="middle" fill="#545b61">{n}</text>
            </g>
          ))}
          {points.length > 1 && (
            <polyline fill="none" stroke="#23282d" strokeWidth="1.5" points={points.map(s => `${nx(s.n ?? 0)},${y(s.depth)}`).join(' ')} />
          )}
          {points.map((s, i) => {
            const refusal = s.penetration_mm !== null && s.penetration_mm !== undefined && s.penetration_mm < 300
            return (
              <g key={i}>
                <circle cx={nx(s.n ?? 0)} cy={y(s.depth)} r="4.5" fill={refusal ? '#fff' : '#f5c400'} stroke="#23282d" strokeWidth="1.5" />
                <text x={nx(s.n ?? 0) + 8} y={y(s.depth) + 4} fontSize="11" fill="#23282d">{refusal ? `${s.n}/${s.penetration_mm}` : s.n}</text>
              </g>
            )
          })}
          {!points.length && <text x={X.plot + 8} y={TOP + 20} fontSize="11" fill="#7b8288">{t('No SPT yet')}</text>}
        </svg>
      </div>
      <div className="profile-legend">
        {used.map(p => (
          <span key={p}>
            <svg viewBox="0 0 22 12" aria-hidden="true"><PatternDefs prefix={`lg-${p}`} /><rect width="22" height="12" fill={`url(#lg-${p}-${p})`} /></svg>
            {t(USCS_NAMES[p])}
          </span>
        ))}
        {samples.length > 0 && <span><svg viewBox="0 0 22 12" aria-hidden="true" style={{ border: 0 }}><rect x="6" y="2" width="10" height="8" fill="#23282d" /></svg>{t('Undisturbed sample')}</span>}
        {samples.length > 0 && <span><svg viewBox="0 0 22 12" aria-hidden="true" style={{ border: 0 }}><rect x="6" y="2" width="10" height="8" fill="#fff" stroke="#23282d" /></svg>{t('Disturbed sample')}</span>}
        <span>{t('Column width shows grain size: fine soils narrow, coarse soils wide.')}</span>
        <span>{t('Hollow SPT point: test stopped early (refusal).')}</span>
      </div>
    </div>
  )
}
