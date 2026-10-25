/**
 * Worksheets: calculation results (values, tables, charts), the example / calculate tools in
 * the forms, and the standards of each worksheet. Charts are drawn from the description the
 * server sends, so one renderer serves every test.
 */
import { useEffect, useMemo, useState } from 'react'
import { calcWorksheet, getCatalog, type CalcResult, type ChartAxis, type ChartSpec, type SheetInfo } from './api'
import { localValue, t, translateServer } from './i18n'
import { number } from './records'
import { ScrollTable } from './ui'

export function useCatalog(): SheetInfo[] | null {
  const [list, setList] = useState<SheetInfo[] | null>(null)
  useEffect(() => { getCatalog().then(setList).catch(() => setList([])) }, [])
  return list
}

export function sheetOf(catalog: SheetInfo[] | null, kind: 'field' | 'lab', key: string) {
  return catalog?.find(s => s.kind === kind && s.key === key) || null
}

// ---------------------------------------------------------------------------
// Chart
// ---------------------------------------------------------------------------

const COLORS = ['#23282d', '#1f5f8b', '#b42318', '#3c7a2e', '#a15c00', '#6b4c9a']

function niceStep(span: number) {
  const raw = span / 5
  const mag = Math.pow(10, Math.floor(Math.log10(raw)))
  const f = raw / mag
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * mag
}

type Scale = { map: (v: number) => number, ticks: number[], min: number, max: number }

function makeScale(values: number[], ax: ChartAxis, from: number, to: number): Scale {
  const vals = values.filter(v => Number.isFinite(v) && (!ax.log || v > 0))
  let min = vals.length ? Math.min(...vals) : 0
  let max = vals.length ? Math.max(...vals) : 1
  if (ax.log) {
    const lo = Math.floor(Math.log10(min || 1)), hi = Math.ceil(Math.log10(max || 10))
    min = Math.pow(10, lo); max = Math.pow(10, hi === lo ? hi + 1 : hi)
    const ticks: number[] = []
    for (let e = Math.log10(min); e <= Math.log10(max) + 1e-9; e++) ticks.push(Math.pow(10, e))
    const span = Math.log10(max) - Math.log10(min)
    const map = (v: number) => {
      const f = (Math.log10(Math.max(v, min)) - Math.log10(min)) / span
      return ax.reverse ? to - f * (to - from) : from + f * (to - from)
    }
    return { map, ticks, min, max }
  }
  if (min === max) { min -= 1; max += 1 }
  if (min > 0 && min < (max - min) * 0.6) min = 0
  const step = niceStep(max - min)
  min = Math.floor(min / step) * step
  max = Math.ceil(max / step) * step
  const ticks: number[] = []
  for (let v = min; v <= max + step * 1e-6; v += step) ticks.push(Math.round(v / step) * step)
  const map = (v: number) => {
    const f = (v - min) / (max - min)
    return ax.reverse ? to - f * (to - from) : from + f * (to - from)
  }
  return { map, ticks, min, max }
}

function tickLabel(v: number) {
  if (Math.abs(v) >= 1e5 || (Math.abs(v) > 0 && Math.abs(v) < 1e-3)) return v.toExponential(0)
  return number(Math.round(v * 1000) / 1000)
}

function heat(f: number) {
  // blue (low) → yellow → red (high)
  const stops = [[49, 54, 149], [69, 117, 180], [171, 217, 233], [254, 224, 144], [244, 109, 67], [165, 0, 38]]
  const x = Math.min(0.9999, Math.max(0, f)) * (stops.length - 1)
  const i = Math.floor(x), r = x - i
  const c = stops[i].map((v, k) => Math.round(v + (stops[i + 1][k] - v) * r))
  return `rgb(${c[0]},${c[1]},${c[2]})`
}

export function Chart({ spec }: { spec: ChartSpec }) {
  const W = 520, H = 360, L = 62, R = 16, T = 18, B = 50
  const pts = spec.kind === 'value' ? (spec.points || []).map(p => [p[0], p[1]] as [number, number]) : (spec.series || []).flatMap(s => s.points)
  if (!pts.length) return null
  // Depth on y with reverse: y grows downward on screen already, so reverse means "small at top".
  const xs = makeScale(pts.map(p => p[0]), spec.x, L, W - R)
  const yAxis = { ...spec.y, reverse: !spec.y.reverse }
  const ys = makeScale(pts.map(p => p[1]), yAxis, T, H - B)
  const values = (spec.points || []).map(p => p[2]).filter(v => Number.isFinite(v))
  const vmin = values.length ? Math.min(...values) : 0, vmax = values.length ? Math.max(...values) : 1
  const vf = (v: number) => spec.log_value && vmin > 0 ? (Math.log10(v) - Math.log10(vmin)) / ((Math.log10(vmax) - Math.log10(vmin)) || 1) : (v - vmin) / ((vmax - vmin) || 1)
  return (
    <figure className="ws-chart">
      <figcaption>{t(spec.title)}</figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label={t(spec.title)}>
        <rect x={L} y={T} width={W - L - R} height={H - T - B} fill="#fff" stroke="#cdd2c9" />
        {xs.ticks.map(v => (
          <g key={'x' + v}>
            <line x1={xs.map(v)} x2={xs.map(v)} y1={T} y2={H - B} stroke="#eef0eb" />
            <text x={xs.map(v)} y={H - B + 18} fontSize="13" textAnchor="middle" fill="#545b61">{tickLabel(v)}</text>
          </g>
        ))}
        {ys.ticks.map(v => (
          <g key={'y' + v}>
            <line x1={L} x2={W - R} y1={ys.map(v)} y2={ys.map(v)} stroke="#eef0eb" />
            <text x={L - 7} y={ys.map(v) + 4.5} fontSize="13" textAnchor="end" fill="#545b61">{tickLabel(v)}</text>
          </g>
        ))}
        <rect x={L} y={T} width={W - L - R} height={H - T - B} fill="none" stroke="#9aa19a" />
        {spec.kind === 'value'
          ? (spec.points || []).map((p, i) => <circle key={i} cx={xs.map(p[0])} cy={ys.map(p[1])} r="5" fill={heat(vf(p[2]))} stroke="rgba(0,0,0,.25)" />)
          : (spec.series || []).map((s, k) => {
            const color = COLORS[k % COLORS.length]
            const style = s.style || 'both'
            return (
              <g key={k}>
                {style !== 'points' && s.points.length > 1 && (
                  <polyline fill="none" stroke={color} strokeWidth="1.6" strokeDasharray={s.dash ? '5 4' : undefined}
                    points={s.points.map(p => `${xs.map(p[0])},${ys.map(p[1])}`).join(' ')} />
                )}
                {style !== 'line' && s.points.map((p, i) => <circle key={i} cx={xs.map(p[0])} cy={ys.map(p[1])} r="3.2" fill={k === 0 ? '#f5c400' : color} stroke="#23282d" strokeWidth="0.8" />)}
              </g>
            )
          })}
        <text x={L + (W - L - R) / 2} y={H - 8} fontSize="14" textAnchor="middle" fill="#23282d">{t(spec.x.label)}</text>
        <text x={16} y={T + (H - T - B) / 2} fontSize="14" textAnchor="middle" fill="#23282d" transform={`rotate(-90 16 ${T + (H - T - B) / 2})`}>{t(spec.y.label)}</text>
      </svg>
      {spec.kind === 'value' ? (
        <div className="ws-legend">
          <span>{t(spec.value_label || '')}</span>
          <span className="ws-ramp" />
          <span>{number(vmin)} – {number(vmax)}</span>
        </div>
      ) : (spec.series || []).length > 1 && (
        <div className="ws-legend">
          {(spec.series || []).map((s, k) => <span key={k}><i style={{ background: COLORS[k % COLORS.length] }} />{t(s.name)}</span>)}
        </div>
      )}
    </figure>
  )
}

// ---------------------------------------------------------------------------
// Result view
// ---------------------------------------------------------------------------

const cell = (v: any) => (typeof v === 'number' ? number(v) : v === null || v === undefined || v === '' ? '–' : translateServer(String(v)))

/** "Label = 88.29 kPa; Label = 4" → [["Label", "88.29 kPa"], ...] */
function summaryParts(summary: string): Array<[string, string]> {
  return summary.split('; ').map((part): [string, string] => {
    const i = part.indexOf(' = ')
    return i < 0 ? ['', part] : [part.slice(0, i), part.slice(i + 3)]
  }).filter(([, v]) => v !== '')
}

function KeyFigure({ label, value }: { label: string, value: string }) {
  const local = localValue(value)
  const m = /^(-?[\d.,]+(?:e[-+]?\d+)?)(?: (.+))?$/.exec(local)
  return (
    <div className="key-figure">
      <span className="key-label">{t(label)}</span>
      <span className="key-value">{m ? <>{m[1]}{m[2] && <small> {m[2]}</small>}</> : translateServer(local)}</span>
    </div>
  )
}

export function ResultView({ result, compact = false, notesOpen = false }: { result: CalcResult | null | undefined, compact?: boolean, notesOpen?: boolean }) {
  if (!result || !Object.keys(result).length) return null
  if (result.error) return <p className="notice error">{translateServer(result.error)}</p>
  const keys = result.summary ? summaryParts(result.summary) : []
  // A value already shown as a key figure is left out of the list below ("e0" and "Initial void ratio e0").
  const shown = keys.map(([l]) => l).filter(Boolean)
  const same = (label: string) => shown.some(k => label === k || label.endsWith(' ' + k) || label.startsWith(k + ' ('))
  // Values that could not be worked out for this sample (e.g. D10 above the hydrometer range) are left out.
  const rest = (result.values || []).filter(v => !same(v.label) && v.value !== null && v.value !== undefined && v.value !== '')
  const hasNotes = !!result.method || !!result.notes?.length
  return (
    <div className="ws-result">
      {keys.length > 0 && <div className="key-figures">{keys.map(([l, v], i) => <KeyFigure key={i} label={l} value={v} />)}</div>}
      {rest.length > 0 && (
        <dl className="facts-grid compact">
          {rest.map((v, i) => (
            <div key={i}><dt>{t(v.label)}{v.unit ? ` (${v.unit})` : ''}</dt><dd>{cell(v.value)}</dd></div>
          ))}
        </dl>
      )}
      {!compact && !!result.charts?.length && <div className="ws-charts">{result.charts.map((c, i) => <Chart key={i} spec={c} />)}</div>}
      {!compact && result.tables?.map((tb, i) => (
        <section key={i} className="ws-table">
          {tb.title && <h4>{t(tb.title)}{tb.rows.length > 12 && <span className="muted small"> · {tb.rows.length} {t('rows')}</span>}</h4>}
          <ScrollTable maxHeight={tb.rows.length > 14 ? '26rem' : undefined}>
            <table className="data-table">
              <thead><tr>{tb.columns.map((c, k) => <th key={k} className={typeof tb.rows[0]?.[k] === 'number' ? 'num' : ''}>{t(c)}</th>)}</tr></thead>
              <tbody>{tb.rows.map((r, k) => <tr key={k}>{r.map((v, j) => <td key={j} className={typeof v === 'number' ? 'num' : typeof v === 'string' && v.length <= 18 ? 'short' : ''}>{cell(v)}</td>)}</tr>)}</tbody>
            </table>
          </ScrollTable>
        </section>
      ))}
      {compact && result.method && <p className="help">{t('Method')}: {translateServer(result.method)}</p>}
      {!compact && hasNotes && (
        <details className="ws-notes" open={notesOpen}>
          <summary>{t('Method and calculation notes')}</summary>
          {result.method && <p className="help">{t('Method')}: {translateServer(result.method)}</p>}
          {!!result.notes?.length && <ul className="notes">{result.notes.map((n, i) => <li key={i}>{translateServer(n)}</li>)}</ul>}
        </details>
      )}
    </div>
  )
}

export function StandardsList({ sheet }: { sheet: SheetInfo | null }) {
  if (!sheet?.standards.length) return null
  return (
    <ul className="std-list">
      {sheet.standards.map(([code, title]) => <li key={code}><strong>{code}</strong> {title && <span className="muted">{t(title)}</span>}</li>)}
    </ul>
  )
}

// ---------------------------------------------------------------------------
// Form tools: fill with the example, calculate before saving
// ---------------------------------------------------------------------------

export function useSheetTools(kind: 'field' | 'lab', dataField: string, selector: string) {
  const catalog = useCatalog()
  return useMemo(() => {
    return (data: Record<string, any>, setData: (u: (prev: Record<string, any>) => Record<string, any>) => void, place: 'top' | 'bottom') => {
      const sheet = sheetOf(catalog, kind, data[selector])
      if (!sheet) return null
      if (place === 'top') {
        return (
          <div className="ws-head">
            <div>
              <span className="ws-code">{sheet.code}</span> <strong>{t(sheet.label)}</strong>
              {sheet.help && <p className="help" style={{ margin: '.2rem 0 0' }}>{t(sheet.help)}</p>}
            </div>
            <div className="actions">
              {Object.keys(sheet.example || {}).length > 0 && (
                <button type="button" onClick={() => setData(prev => ({
                  ...prev, [dataField]: JSON.parse(JSON.stringify(sheet.example)),
                  standard: prev.standard || sheet.standards.map(s => s[0]).join(', '),
                }))}>{t('Fill with example')}</button>
              )}
              {sheet.standards.length > 0 && !data.standard && (
                <button type="button" className="quiet" onClick={() => setData(prev => ({ ...prev, standard: sheet.standards.map(s => s[0]).join(', ') }))}>
                  {t('Use the standard')}
                </button>
              )}
            </div>
          </div>
        )
      }
      return sheet.calc ? <CalcPreview kind={kind} sheetKey={sheet.key} data={data[dataField] || {}} /> : null
    }
  }, [catalog, kind, dataField, selector])
}

function CalcPreview({ kind, sheetKey, data }: { kind: 'field' | 'lab' | 'cpt', sheetKey: string, data: Record<string, any> }) {
  const [result, setResult] = useState<CalcResult | null>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => { setResult(null) }, [sheetKey])
  const run = async () => {
    setBusy(true)
    try {
      setResult(await calcWorksheet(kind, sheetKey, data))
    } catch (e: any) {
      setResult({ error: e.message })
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="ws-preview">
      <div className="actions"><button type="button" onClick={() => { void run() }} disabled={busy}>{busy ? t('Calculating…') : t('Calculate')}</button>
        <span className="help">{t('Results are also calculated when you save.')}</span></div>
      {result && <div className="card" style={{ marginTop: '.75rem' }}><ResultView result={result} /></div>}
    </div>
  )
}

export function CptCalcPreview({ data }: { data: Record<string, any> }) {
  return <CalcPreview kind="cpt" sheetKey="cpt" data={data} />
}
