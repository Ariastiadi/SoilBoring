/**
 * Client reports: a template per project type with an ordered section outline, sections filled
 * from the project's data, annexes, references from the standards catalogue, versions through the
 * approval flow, and the integrity seal printed with a QR code. The same document view prints the
 * staff preview and the issued report a client opens in the client portal.
 */
import { useEffect, useMemo, useState } from 'react'
import { apiGet, type CalcResult, type Rec } from '../api'
import { t, translateServer } from '../i18n'
import { useNav, type Intent } from '../nav'
import { RecordsPage, STATUS_TONE, number, useSchemas, type FormLayout, type FormTools } from '../records'
import { SealMark, formatSealCode } from '../seal'
import { Icon, ScrollTable, formatDate, todayIso } from '../ui'
import { ResultView } from '../worksheets'
import { PrintSheet } from './Business'
import './ClientReports.css'

// ---------------------------------------------------------------------------
// Types of the report content (built by the server, see client_reports.py)
// ---------------------------------------------------------------------------

export type Section = { key: string, title: string, source: string, text: string, include?: boolean }
type Layer = { top: number, base: number, uscs: string, description: string }
type Spt = { depth: number, n: number | null, reported: string, refusal: boolean }
type Borehole = {
  id: string, site: string, start: string, end: string, method: string, final_depth: number | null, gw_encountered: boolean,
  gw_depth: number | null, latitude: number | null, longitude: number | null, elevation: number | null, uscs: string, description: string,
  layers: Layer[], spt: Spt[], samples: Array<{ top: number, base: number | null, type: string, ref: string }>
}
type LabItem = {
  id: string, borehole_id: string, sample_ref: string, depth_top: number, depth_base: number | null, test_type: string, test_label: string,
  standard: string, values: Array<{ key: string, label: string, value: unknown }>, summary: string, authorised: boolean, seal_code: string, disclaimer: string
}
type Analysis = { id: string, title: string, type: string, type_label: string, borehole_id: string, summary: string, results: CalcResult }
type FieldItem = { id: string, code: string, method: string, method_label: string, date: string, summary: string, results: string, calc: CalcResult }
export type ReportContent = {
  document: {
    type: string, number: string, version: number, title: string, date: string, template: string, template_label: string, revision_note: string,
    prepared_by: string, reviewed_by: string, approved_by: string, sections: Section[],
    annexes: Array<{ kind: string, title: string, ref: string }>, references: Array<{ code: string, title: string }>, other_references: string
  }
  company: { name: string, address: string, phone: string, email: string, npwp: string, footer: string }
  project: { name: string, code: string, location: string, province: string, client: { name: string, address: string, contact_person: string } }
  data: {
    boreholes: Borehole[]
    cpt: Array<{ id: string, test_id: string, date: string, final_depth: number | null, max_qc: number | null, unit: string, summary: string }>
    field: FieldItem[], lab: LabItem[], analyses: Analysis[]
    scope: { boreholes: number, metres: number, spt: number, samples: number, undisturbed: number, core_runs: number, cpt: number, cpt_metres: number,
      field: Array<[string, number]>, lab: Array<[string, number]>, analyses: number }
    parameters: { spt: Array<{ uscs: string, count: number, refusals: number, min: number | null, max: number | null, mean: number | null }>,
      lab: Array<{ test: string, label: string, count: number, min: number, max: number, mean: number }> }
  }
}
export type SealView = { status: string, code: string, hash: string, date: string, issued_by?: string, intact?: boolean, superseded_by?: string, revoked_on?: string }
type Warning = { text: string, vars?: Record<string, string | number> }
type ContentView = { content: ReportContent, warnings: Warning[], seal: SealView | null, changed_since_issue: boolean }

export const ANNEX_KINDS: Record<string, string> = {
  borehole_log: 'Borehole log', cpt_plot: 'CPT plot', lab_sheet: 'Laboratory test sheet', field_sheet: 'Field worksheet',
  photos: 'Photographs', calibration: 'Calibration certificate', site_plan: 'Site plan / test location map', other: 'Other document',
}

const SOURCE_LABELS: Record<string, string> = {
  text: 'Text only', project: 'Project, client and location', scope: 'Quantities of work', field: 'Boreholes, CPT and field work',
  cpt: 'CPT results', lab: 'Laboratory results', subsurface: 'Strata, SPT and groundwater', parameters: 'SPT and lab statistics',
  analyses: 'Engineering analyses', tests: 'Field and laboratory tests',
}
const sourceLabel = (source: string) => t(SOURCE_LABELS[source.split(':')[0]] || source)

export const SEAL_STATUS: Record<string, [string, string]> = {
  valid: ['Valid', 'ok'], superseded: ['Superseded by a newer issue', 'warn'], revoked: ['Revoked (withdrawn)', 'bad'],
  invalid: ['Not valid: the stored content does not match its seal', 'bad'],
}

const val = (v: unknown) => (typeof v === 'number' ? number(v) : typeof v === 'boolean' ? (v ? t('Yes') : t('No')) : String(v ?? '–'))
const metres = (v: number | null | undefined) => (v === null || v === undefined ? '–' : `${number(v)} m`)

// ---------------------------------------------------------------------------
// The document (staff print and client portal)
// ---------------------------------------------------------------------------

function DataTable({ head, rows, numeric = [] }: { head: string[], rows: Array<Array<React.ReactNode>>, numeric?: number[] }) {
  return (
    <table className="doc-table">
      <thead><tr>{head.map((h, i) => <th key={i} className={numeric.includes(i) ? 'num' : ''}>{h}</th>)}</tr></thead>
      <tbody>{rows.map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j} className={numeric.includes(j) ? 'num' : ''}>{c}</td>)}</tr>)}</tbody>
    </table>
  )
}

function LabTable({ items }: { items: LabItem[] }) {
  if (!items.length) return null
  const pending = items.some(x => !x.authorised)
  return <>
    <DataTable head={[t('Borehole'), t('Sample'), t('Depth (m)'), t('Test'), t('Results')]} numeric={[2]}
      rows={items.map(x => [x.borehole_id, x.sample_ref + (x.authorised ? '' : ' *'),
        `${number(x.depth_top)}${x.depth_base !== null && x.depth_base !== undefined ? `–${number(x.depth_base)}` : ''}`,
        <>{t(x.test_label)}{x.standard && <div className="doc-small">{x.standard}</div>}</>,
        <>{x.values.map(v => `${t(v.label)} ${val(v.value)}`).join('; ') || translateServer(x.summary) || '–'}
          {x.seal_code && <div className="doc-small">{t('Seal')} {x.seal_code}</div>}
          {x.disclaimer && <div className="doc-small">{translateServer(x.disclaimer)}</div>}</>])} />
    {pending && <p className="doc-small">* {t('Result not yet authorised by the laboratory.')}</p>}
  </>
}

function SourceContent({ source, c }: { source: string, c: ReportContent }) {
  const d = c.data
  const [kind, keysText] = source.split(':')
  const keys = (keysText || '').split(',').filter(Boolean)
  if (kind === 'project') {
    const pts = d.boreholes.filter(b => b.latitude !== null && b.longitude !== null)
    const span = (xs: number[]) => (xs.length ? `${number(Math.min(...xs))} … ${number(Math.max(...xs))}` : '–')
    return (
      <table className="doc-meta"><tbody>
        <tr><td>{t('Project')}</td><td>{c.project.name} {c.project.code && `(${c.project.code})`}</td></tr>
        <tr><td>{t('Client')}</td><td>{c.project.client.name || '–'}</td></tr>
        <tr><td>{t('Location')}</td><td>{[c.project.location, c.project.province].filter(Boolean).join(', ') || '–'}</td></tr>
        {pts.length > 0 && <tr><td>{t('Test points')}</td><td>{t('Latitude {lat}, longitude {lon}', { lat: span(pts.map(b => b.latitude!)), lon: span(pts.map(b => b.longitude!)) })}</td></tr>}
      </tbody></table>
    )
  }
  if (kind === 'scope') {
    const s = d.scope
    const rows: Array<[string, string]> = [
      [t('Boreholes'), `${s.boreholes} (${number(s.metres)} m)`], [t('SPT'), String(s.spt)],
      [t('Samples'), t('{n}, of which {u} undisturbed', { n: s.samples, u: s.undisturbed })],
      ...(s.core_runs ? [[t('Core runs'), String(s.core_runs)] as [string, string]] : []),
      ...(s.cpt ? [[t('CPT / sondir'), `${s.cpt} (${number(s.cpt_metres)} m)`] as [string, string]] : []),
      ...s.field.map(([label, n]) => [t(label), String(n)] as [string, string]),
      ...s.lab.map(([label, n]) => [t(label), String(n)] as [string, string]),
      ...(s.analyses ? [[t('Engineering analyses'), String(s.analyses)] as [string, string]] : []),
    ]
    return <DataTable head={[t('Work'), t('Quantity')]} rows={rows} numeric={[1]} />
  }
  if (kind === 'field') {
    return <>
      {d.boreholes.length > 0 && <DataTable head={[t('Borehole'), t('Dates'), t('Method'), t('Depth'), t('Groundwater'), t('Coordinates')]} numeric={[3, 4]}
        rows={d.boreholes.map(b => [b.id, `${formatDate(b.start)}${b.end && b.end !== b.start ? ' – ' + formatDate(b.end) : ''}`, b.method || '–',
          metres(b.final_depth), b.gw_encountered ? metres(b.gw_depth) : t('Not encountered'),
          b.latitude !== null && b.longitude !== null ? `${b.latitude}, ${b.longitude}` : '–'])} />}
      {d.cpt.length > 0 && <DataTable head={[t('Test ID'), t('Date'), t('Final depth (m)'), t('Max qc')]} numeric={[2, 3]}
        rows={d.cpt.map(x => [x.test_id, formatDate(x.date), number(x.final_depth), x.max_qc === null ? '–' : `${number(x.max_qc)} ${x.unit}`])} />}
      {d.field.length > 0 && <DataTable head={[t('Line / point ID'), t('Method'), t('Date'), t('Result')]}
        rows={d.field.map(f => [f.code, t(f.method_label), formatDate(f.date), translateServer(f.summary) || f.results || '–'])} />}
      {!d.boreholes.length && !d.cpt.length && !d.field.length && <p className="doc-small">{t('No field work recorded for this project yet.')}</p>}
    </>
  }
  if (kind === 'cpt') {
    if (!d.cpt.length) return null
    return <DataTable head={[t('Test ID'), t('Final depth (m)'), t('Max qc'), t('Result')]} numeric={[1, 2]}
      rows={d.cpt.map(x => [x.test_id, number(x.final_depth), x.max_qc === null ? '–' : `${number(x.max_qc)} ${x.unit}`, translateServer(x.summary) || '–'])} />
  }
  if (kind === 'lab') return <LabTable items={d.lab} />
  if (kind === 'subsurface') {
    return <>{d.boreholes.map(b => (
      <div key={b.id} className="doc-keep">
        <p className="doc-sub"><strong>{b.id}</strong>{b.site && ` · ${b.site}`} · {t('Final depth')} {metres(b.final_depth)} · {t('Groundwater')} {b.gw_encountered ? metres(b.gw_depth) : t('Not encountered')}</p>
        {b.layers.length ? <DataTable head={[t('Depth (m)'), 'USCS', t('Description'), 'N-SPT']}
          rows={b.layers.map(l => [`${number(l.top)}–${number(l.base)}`, l.uscs || '–', l.description || '–',
            b.spt.filter(s => s.depth >= l.top && s.depth < l.base).map(s => s.reported.replace(/^N=/, '')).join(', ') || '–'])} />
          : <p className="doc-small">{b.description || t('No depth data yet')}</p>}
      </div>
    ))}</>
  }
  if (kind === 'parameters') {
    const p = d.parameters
    return <>
      {p.spt.length > 0 && <>
        <p className="doc-sub">{t('SPT N per soil class (refusals counted separately)')}</p>
        <DataTable head={['USCS', t('Tests'), t('Min'), t('Max'), t('Mean'), t('Refusals')]} numeric={[1, 2, 3, 4, 5]}
          rows={p.spt.map(r => [r.uscs, r.count, number(r.min), number(r.max), number(r.mean), r.refusals])} />
      </>}
      {p.lab.length > 0 && <>
        <p className="doc-sub">{t('Laboratory results')}</p>
        <DataTable head={[t('Test'), t('Parameter'), 'n', t('Min'), t('Max'), t('Mean')]} numeric={[2, 3, 4, 5]}
          rows={p.lab.map(r => [t(r.test), t(r.label), r.count, number(r.min), number(r.max), number(r.mean)])} />
      </>}
      <p className="doc-small">{t('Design values are chosen by the engineer from these ranges; they are not averages to be used directly.')}</p>
    </>
  }
  if (kind === 'analyses') {
    const items = d.analyses.filter(a => keys.includes('*') || keys.includes(a.type))
    return <>{items.map(a => (
      <div key={a.id} className="doc-keep">
        <p className="doc-sub"><strong>{a.title}</strong> · {t(a.type_label)}{a.borehole_id && ` · ${a.borehole_id}`}</p>
        <ResultView result={a.results} notesOpen full />
      </div>
    ))}</>
  }
  if (kind === 'tests') {
    const field = d.field.filter(f => keys.includes(f.method))
    const lab = d.lab.filter(x => keys.includes(x.test_type))
    return <>
      {field.map(f => (
        <div key={f.id} className="doc-keep">
          <p className="doc-sub"><strong>{t(f.method_label)}</strong> · {f.code} · {formatDate(f.date)}</p>
          {f.calc && Object.keys(f.calc).length ? <ResultView result={f.calc} full /> : <p className="doc-text">{f.results || translateServer(f.summary)}</p>}
        </div>
      ))}
      <LabTable items={lab} />
    </>
  }
  return null
}

function hasData(source: string, c: ReportContent) {
  const d = c.data
  const [kind, keysText] = source.split(':')
  const keys = (keysText || '').split(',')
  switch (kind) {
    case 'project': case 'scope': case 'field': return true
    case 'cpt': return d.cpt.length > 0
    case 'lab': return d.lab.length > 0
    case 'subsurface': return d.boreholes.length > 0
    case 'parameters': return d.parameters.spt.length > 0 || d.parameters.lab.length > 0
    case 'analyses': return d.analyses.some(a => keys.includes('*') || keys.includes(a.type))
    case 'tests': return d.field.some(f => keys.includes(f.method)) || d.lab.some(x => keys.includes(x.test_type))
    default: return false
  }
}

export function ReportDocument({ content, seal, onClose }: { content: ReportContent, seal?: SealView | null, onClose: () => void }) {
  const c = content
  const doc = c.document
  // A section without text and without data for this project is left out of the print.
  const sections = doc.sections.filter(s => (s.text || '').trim() || (s.source !== 'text' && hasData(s.source, c)))
  const title = `${doc.number}${doc.version > 1 ? ` v${doc.version}` : ''}`
  return (
    <PrintSheet title={title} onClose={onClose}>
      <header className="doc-head">
        <div>
          <div className="doc-company">{c.company.name || t('Company name not set')}</div>
          <div className="doc-small" style={{ whiteSpace: 'pre-wrap' }}>{c.company.address}</div>
          <div className="doc-small">{[c.company.phone, c.company.email].filter(Boolean).join('  ')}</div>
          {c.company.npwp && <div className="doc-small">NPWP {c.company.npwp}</div>}
        </div>
        <div style={{ textAlign: 'right' }}>
          <div className="doc-title">{t('Report')}</div>
          <div><strong>{doc.number}</strong></div>
          <div>{t('Version {v}', { v: doc.version })} · {formatDate(doc.date)}</div>
        </div>
      </header>
      <h1 className="doc-h1">{doc.title}</h1>
      <table className="doc-meta"><tbody>
        <tr><td>{t('Project')}</td><td>{c.project.name}{c.project.code && ` (${c.project.code})`}</td></tr>
        <tr><td>{t('Client')}</td><td>{c.project.client.name || '–'}</td></tr>
        <tr><td>{t('Location')}</td><td>{c.project.location || '–'}</td></tr>
        {doc.template_label && <tr><td>{t('Project type')}</td><td>{t(doc.template_label)}</td></tr>}
        {doc.version > 1 && <tr><td>{t('Revision')}</td><td style={{ whiteSpace: 'pre-wrap' }}>{doc.revision_note}</td></tr>}
      </tbody></table>
      {seal ? <SealMark code={seal.code} hash={seal.hash} /> : <p className="doc-small doc-draft">{t('Draft: not issued. The integrity seal is added when the report is approved.')}</p>}
      {sections.length > 2 && (
        <nav className="doc-toc" aria-label={t('Contents')}>
          <strong>{t('Contents')}</strong>
          <ol>{sections.map(s => <li key={s.key + s.title}>{t(s.title)}</li>)}
            {(doc.references.length > 0 || doc.other_references) && <li>{t('References')}</li>}
            {doc.annexes.length > 0 && <li>{t('Annexes')}</li>}</ol>
        </nav>
      )}
      {sections.map((s, i) => (
        <section key={s.key + i} className="doc-section">
          <h2>{i + 1}. {t(s.title)}</h2>
          {s.source !== 'text' && <SourceContent source={s.source} c={c} />}
          {s.text && <p className="doc-text">{s.text}</p>}
        </section>
      ))}
      {(doc.references.length > 0 || doc.other_references) && (
        <section className="doc-section">
          <h2>{sections.length + 1}. {t('References')}</h2>
          <ol className="doc-refs">
            {doc.references.map(r => <li key={r.code}><strong>{r.code}</strong>{r.title && ` – ${t(r.title)}`}</li>)}
            {(doc.other_references || '').split(/\r?\n/).filter(x => x.trim()).map((x, i) => <li key={'o' + i}>{x}</li>)}
          </ol>
        </section>
      )}
      {doc.annexes.length > 0 && (
        <section className="doc-section">
          <h2>{sections.length + (doc.references.length > 0 || doc.other_references ? 2 : 1)}. {t('Annexes')}</h2>
          <table className="doc-table"><tbody>
            {doc.annexes.map((a, i) => <tr key={i}><td className="nowrap">{t('Annex {x}', { x: String.fromCharCode(65 + (i % 26)) + (i >= 26 ? Math.floor(i / 26) : '') })}</td><td>{a.title}</td><td>{t(ANNEX_KINDS[a.kind] || a.kind)}</td></tr>)}
          </tbody></table>
        </section>
      )}
      <div className="doc-approvals">
        {[['Prepared by', doc.prepared_by], ['Reviewed by', doc.reviewed_by], ['Approved by', doc.approved_by]].map(([label, who]) => (
          <div key={label}><div className="doc-small">{t(label)}</div><div className="doc-sign-space" /><div>{who || '……………………'}</div></div>
        ))}
      </div>
      {c.company.footer && <p className="doc-small doc-footer">{c.company.footer}</p>}
    </PrintSheet>
  )
}

// ---------------------------------------------------------------------------
// Editors in the report form: sections, annexes, references
// ---------------------------------------------------------------------------

type Template = { key: string, label: string, sections: Section[] }
let templateCache: Promise<{ templates: Template[] }> | null = null
const loadTemplates = () => (templateCache ||= apiGet<{ templates: Template[] }>('/api/client-reports/templates').catch(e => { templateCache = null; throw e }))

function SectionsEditor({ data, setData }: { data: Record<string, any>, setData: (u: (p: Record<string, any>) => Record<string, any>) => void }) {
  const [templates, setTemplates] = useState<Template[]>([])
  useEffect(() => { loadTemplates().then(r => setTemplates(r.templates)).catch(() => {}) }, [])
  const rows: Section[] = Array.isArray(data.sections) ? data.sections : []
  const set = (next: Section[]) => setData(p => ({ ...p, sections: next }))
  const edit = (i: number, patch: Partial<Section>) => set(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)))
  const move = (i: number, by: number) => {
    const j = i + by
    if (j < 0 || j >= rows.length) return
    const next = [...rows]
    ;[next[i], next[j]] = [next[j], next[i]]
    set(next)
  }
  const template = templates.find(x => x.key === data.template)
  const fill = (tpl: Template, keep: Section[]) => {
    const old = new Map(keep.map(r => [r.key, r.text]))
    set(tpl.sections.map(s => ({ ...s, text: old.get(s.key) || (s.text ? t(s.text) : '') })))
  }
  // A new report gets the outline of its project type straight away (texts in the interface language).
  useEffect(() => {
    if (template && !rows.length) fill(template, [])
  }, [template?.key]) // eslint-disable-line react-hooks/exhaustive-deps
  const apply = () => {
    if (!template) return
    if (rows.length && !window.confirm(t('Replace the sections with the outline of "{name}"? Text already written in sections with the same name is kept.', { name: t(template.label) }))) return
    fill(template, rows)
  }
  return (
    <section className="rep-editor">
      <div className="rep-editor-head">
        <h3>{t('Sections')} <span className="muted">{rows.length}</span></h3>
        <div className="actions">
          {template && <button type="button" onClick={apply}>{rows.length ? t('Apply outline again') : t('Use the outline of this project type')}</button>}
          <button type="button" onClick={() => set([...rows, { key: `custom${rows.length + 1}`, title: '', source: 'text', include: true, text: '' }])}><Icon name="plus" />{t('Add section')}</button>
        </div>
      </div>
      {!rows.length && <p className="help">{data.template ? t('Save the report or use the outline: the sections of the project type are added.') : t('Choose the project type above to get its section outline, or add sections by hand.')}</p>}
      <ol className="rep-sections">
        {rows.map((s, i) => (
          <li key={i} className={s.include === false ? 'off' : ''}>
            <div className="rep-section-head">
              <span className="rep-no">{i + 1}</span>
              <label className="sr-only" htmlFor={`sec-title-${i}`}>{t('Section')} {i + 1}</label>
              <input id={`sec-title-${i}`} value={t(s.title) === s.title ? s.title : t(s.title)} maxLength={200}
                onChange={e => edit(i, { title: e.target.value })} />
              <label className="checkbox"><input type="checkbox" checked={s.include !== false} onChange={e => edit(i, { include: e.target.checked })} />{t('Include')}</label>
              <span className="rep-tools">
                <button type="button" className="quiet small" aria-label={t('Move up')} disabled={i === 0} onClick={() => move(i, -1)}>↑</button>
                <button type="button" className="quiet small" aria-label={t('Move down')} disabled={i === rows.length - 1} onClick={() => move(i, 1)}>↓</button>
                <button type="button" className="quiet danger-quiet small" aria-label={t('Remove section')} onClick={() => set(rows.filter((_, j) => j !== i))}>×</button>
              </span>
            </div>
            <p className="help rep-source">{s.source === 'text' ? t('Text only') : t('Filled from the project: {what}. Your text is printed after it.', { what: sourceLabel(s.source) })}</p>
            {s.include !== false && (
              <>
                <label className="sr-only" htmlFor={`sec-text-${i}`}>{t('Text')}</label>
                <textarea id={`sec-text-${i}`} rows={s.source === 'text' ? 4 : 2} maxLength={8000} value={s.text || ''} onChange={e => edit(i, { text: e.target.value })}
                  placeholder={s.source === 'text' ? t('Write this section.') : t('Comments on the data (optional).')} />
              </>
            )}
          </li>
        ))}
      </ol>
    </section>
  )
}

type Candidate = { kind: string, name: string, detail: string, ref: string }

function AnnexEditor({ data, setData }: { data: Record<string, any>, setData: (u: (p: Record<string, any>) => Record<string, any>) => void }) {
  const rows: Array<{ kind: string, title: string, ref: string }> = Array.isArray(data.annexes) ? data.annexes : []
  const [cands, setCands] = useState<Candidate[] | null>(null)
  const [picked, setPicked] = useState<Set<number>>(new Set())
  const [error, setError] = useState('')
  const set = (next: typeof rows) => setData(p => ({ ...p, annexes: next }))
  const titleOf = (c: Candidate) => [t(ANNEX_KINDS[c.kind] || c.kind), c.detail ? t(c.detail) : '', c.name].filter(Boolean).join(' ')
  const load = () => {
    if (!data.project_id) { setError(t('Choose the project first.')); return }
    setError('')
    apiGet<Candidate[]>(`/api/client-reports/annex-candidates/${encodeURIComponent(data.project_id)}`)
      .then(list => { setCands(list); setPicked(new Set()) }).catch(e => setError(e.message))
  }
  const have = new Set(rows.map(r => r.kind + '|' + r.ref))
  return (
    <section className="rep-editor">
      <div className="rep-editor-head">
        <h3>{t('Annexes')} <span className="muted">{rows.length}</span></h3>
        <div className="actions">
          <button type="button" onClick={load}>{t('Pick from the project')}</button>
          <button type="button" onClick={() => set([...rows, { kind: 'other', title: '', ref: '' }])}><Icon name="plus" />{t('Add annex')}</button>
        </div>
      </div>
      {error && <p className="notice error">{error}</p>}
      {cands && (
        <div className="rep-pick">
          {cands.length === 0 ? <p className="help">{t('Nothing recorded for this project yet.')}</p> : (
            <ul className="rep-pick-list">
              {cands.map((c, i) => {
                const done = have.has(c.kind + '|' + c.ref)
                return (
                  <li key={i}><label className="checkbox">
                    <input type="checkbox" disabled={done} checked={done || picked.has(i)}
                      onChange={e => setPicked(p => { const n = new Set(p); if (e.target.checked) n.add(i); else n.delete(i); return n })} />
                    {titleOf(c)}
                  </label></li>
                )
              })}
            </ul>
          )}
          <div className="actions">
            <button type="button" className="primary" disabled={!picked.size} onClick={() => {
              set([...rows, ...[...picked].sort((a, b) => a - b).map(i => ({ kind: cands[i].kind, title: titleOf(cands[i]), ref: cands[i].ref }))])
              setCands(null)
            }}>{t('Add {n} annexes', { n: picked.size })}</button>
            <button type="button" onClick={() => setCands(null)}>{t('Close')}</button>
          </div>
        </div>
      )}
      {rows.length > 0 && (
        <ol className="rep-annexes">
          {rows.map((a, i) => (
            <li key={i}>
              <span className="rep-no">{String.fromCharCode(65 + (i % 26))}</span>
              <label className="sr-only" htmlFor={`ax-kind-${i}`}>{t('Annex')}</label>
              <select id={`ax-kind-${i}`} value={a.kind} onChange={e => set(rows.map((r, j) => (j === i ? { ...r, kind: e.target.value } : r)))}>
                {Object.entries(ANNEX_KINDS).map(([k, l]) => <option key={k} value={k}>{t(l)}</option>)}
              </select>
              <label className="sr-only" htmlFor={`ax-title-${i}`}>{t('Title')}</label>
              <input id={`ax-title-${i}`} value={a.title} maxLength={200} placeholder={t('Title')} onChange={e => set(rows.map((r, j) => (j === i ? { ...r, title: e.target.value } : r)))} />
              <button type="button" className="quiet danger-quiet small" aria-label={t('Remove')} onClick={() => set(rows.filter((_, j) => j !== i))}>×</button>
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}

function ReferencesPicker({ data, setData }: { data: Record<string, any>, setData: (u: (p: Record<string, any>) => Record<string, any>) => void }) {
  const schemas = useSchemas()
  const options = (schemas?.project_reports?.fields.find(f => f.name === 'references')?.options || []) as Array<[string, string]>
  const chosen: string[] = Array.isArray(data.references) ? data.references : []
  const [q, setQ] = useState('')
  const set = (next: string[]) => setData(p => ({ ...p, references: next }))
  const query = q.trim().toLowerCase()
  const shown = options.filter(([code, title]) => !chosen.includes(code) && (!query || `${code} ${title} ${t(title)}`.toLowerCase().includes(query)))
  return (
    <section className="rep-editor">
      <div className="rep-editor-head"><h3>{t('References (standards)')} <span className="muted">{chosen.length}</span></h3></div>
      {chosen.length > 0 && (
        <ul className="rep-chips">
          {chosen.map(code => {
            const title = options.find(o => o[0] === code)?.[1]
            return <li key={code}><span><strong>{code}</strong>{title && ` ${t(title)}`}</span>
              <button type="button" className="quiet small" aria-label={t('Remove {what}', { what: code })} onClick={() => set(chosen.filter(c => c !== code))}>×</button></li>
          })}
        </ul>
      )}
      <input type="search" value={q} onChange={e => setQ(e.target.value)} placeholder={t('Search standards (e.g. SPT, D2487, SNI 8460)')} aria-label={t('Search standards')} />
      <ScrollTable maxHeight="15rem">
        <ul className="rep-ref-list">
          {shown.slice(0, 120).map(([code, title]) => (
            <li key={code}><button type="button" className="quiet" onClick={() => set([...chosen, code])}>
              <Icon name="plus" /><span><strong>{code}</strong> <span className="muted">{t(title)}</span></span></button></li>
          ))}
        </ul>
      </ScrollTable>
      <p className="help">{t('Printed as the list of references. Textbooks and other documents go under Other references.')}</p>
      <div className="field" style={{ marginTop: '.6rem' }}>
        <label htmlFor="rep-other-refs">{t('Other references')}</label>
        <textarea id="rep-other-refs" rows={3} maxLength={4000} value={data.other_references || ''} onChange={e => setData(p => ({ ...p, other_references: e.target.value }))} />
        <p className="help">{t('Textbooks, papers and earlier reports, one per line.')}</p>
      </div>
    </section>
  )
}

const reportTools: FormTools = (data, setData, place) => place === 'bottom' ? (
  <div className="rep-editors">
    <SectionsEditor data={data} setData={setData} />
    <AnnexEditor data={data} setData={setData} />
    <ReferencesPicker data={data} setData={setData} />
  </div>
) : null

// ---------------------------------------------------------------------------
// The page
// ---------------------------------------------------------------------------

function SealStatus({ seal }: { seal: SealView }) {
  const [label, tone] = SEAL_STATUS[seal.status] || [seal.status, '']
  return <span className={`status ${tone}`}>{t(label)}</span>
}

function ReportPanel({ report }: { report: Rec }) {
  const [view, setView] = useState<ContentView | null>(null)
  const [rows, setRows] = useState<Rec[] | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    let live = true
    apiGet<ContentView>(`/api/client-reports/${report.id}/content`).then(v => { if (live) setView(v) }).catch(e => { if (live) setError(e.message) })
    apiGet<Rec[]>('/api/records/project_reports').then(r => { if (live) setRows(r) }).catch(() => {})
    return () => { live = false }
  }, [report.id, report.updated_at, report.wf_status])
  const family = (rows || []).filter(r => (r.family_id || r.id) === (report.family_id || report.id)).sort((a, b) => (a.version || 1) - (b.version || 1))
  const sections: Section[] = (report.sections || []).filter((s: Section) => s.include !== false)
  return (
    <section className="card rep-panel">
      <div className="rep-panel-grid">
        <div>
          <h3 className="card-title">{t('Issue and seal')}</h3>
          {error && <p className="notice error">{error}</p>}
          {view?.seal ? <>
            <p style={{ margin: '0 0 .4rem' }}><SealStatus seal={view.seal} /></p>
            <SealMark code={view.seal.code} compact />
            <p className="help">{t('Issued {date} by {who}.', { date: formatDate(view.seal.date), who: view.seal.issued_by || '–' })}</p>
            {view.changed_since_issue && <p className="notice warn">{t('Project data changed after this report was issued. The issued content stays as it was; make a new version to include the changes.')}</p>}
          </> : <p className="help">{t('Not issued yet. When the report is approved, its content is frozen and sealed with SHA-256; the code and a QR code are printed on it.')}</p>}
          {view && view.warnings.length > 0 && (
            <ul className="rep-warnings">{view.warnings.map((w, i) => <li key={i}>{t(w.text, w.vars ? Object.fromEntries(Object.entries(w.vars).map(([k, v]) => [k, typeof v === 'string' ? t(v) : v])) : undefined)}</li>)}</ul>
          )}
        </div>
        <div>
          <h3 className="card-title">{t('Versions')}</h3>
          <ul className="rep-versions">
            {family.map(r => (
              <li key={r.id} className={r.id === report.id ? 'current' : ''}>
                <strong>v{r.version || 1}</strong> <span>{formatDate(r.date)}</span>
                <span className={`status ${STATUS_TONE[r.status] ?? ''}`}>{t(STATUS_LABELS[r.status] || r.status)}</span>
                {r.seal_code && <span className="muted small">{formatSealCode(r.seal_code)}</span>}
                {r.revision_note && <div className="help" style={{ margin: 0 }}>{r.revision_note}</div>}
              </li>
            ))}
          </ul>
        </div>
      </div>
      {sections.length > 0 && (
        <details className="rep-outline">
          <summary>{t('Outline')} · {sections.length}</summary>
          <ol>{sections.map((s, i) => <li key={i}>{t(s.title)} <span className="muted small">· {s.source === 'text' ? t('Text only') : sourceLabel(s.source)}{s.source === 'text' && !String(s.text || '').trim() ? ` · ${t('no text yet')}` : ''}</span></li>)}</ol>
        </details>
      )}
    </section>
  )
}

const STATUS_LABELS: Record<string, string> = { draft: 'Draft', review: 'In review', approved: 'Approved', sent: 'Sent to client', superseded: 'Superseded by a newer version' }

const LAYOUT: FormLayout = {
  first: ['template', 'project_id', 'title', 'date', 'number', 'supersedes_id', 'revision_note'],
  hide: data => [
    'sections', 'annexes', 'references', 'other_references',
    ...(data.template ? ['summary', 'scope', 'recommendations'] : []),
    ...(data.supersedes_id ? [] : ['supersedes_id', 'revision_note']),
  ],
}

const COPY_FIELDS = ['project_id', 'title', 'template', 'sections', 'annexes', 'references', 'other_references', 'summary', 'scope', 'recommendations', 'prepared_by', 'files', 'number']

export function ReportsPage({ intent }: { intent?: Intent }) {
  const { go } = useNav()
  const schemas = useSchemas()
  const [printing, setPrinting] = useState<{ content: ReportContent, seal: SealView | null } | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const print = async (r: Rec) => {
    setBusy(true); setError('')
    try {
      const v = await apiGet<ContentView>(`/api/client-reports/${r.id}/content`)
      setPrinting({ content: v.content, seal: v.seal && r.wf_status === 'approved' ? v.seal : null })
    } catch (e: any) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }
  const newVersion = async (r: Rec) => {
    setError('')
    // A version still being drafted is opened instead of starting another one.
    const all = await apiGet<Rec[]>('/api/records/project_reports').catch(() => [] as Rec[])
    const open = all.find(x => (x.family_id || x.id) === (r.family_id || r.id) && x.id !== r.id && x.wf_status !== 'approved')
    if (open) { go('reports', { open: open.id }); return }
    const copy: Record<string, unknown> = Object.fromEntries(COPY_FIELDS.map(k => [k, r[k]]))
    go('reports', { newWith: { ...copy, date: todayIso(), supersedes_id: r.id, revision_note: '' } })
  }
  const defaults = useMemo(() => ({ date: todayIso(), template: 'general' }), [])
  return (
    <>
      {error && <p className="notice error">{error}</p>}
      <RecordsPage entityName="project_reports" openId={intent?.open} startNew={intent?.newWith}
        description={t('The report to the client: an outline per project type, filled from the project\'s boreholes, CPT, lab results and analyses, with your text. Approved reports are sealed and can be checked by the client.')}
        defaults={defaults} formLayout={LAYOUT} formTools={reportTools}
        hideInView={['sections', 'annexes', 'references', 'family_id', 'superseded_by', 'seal_hash', 'seal_code', 'sealed_at', 'summary', 'scope', 'recommendations']}
        actions={r => <>
          <button type="button" disabled={busy} onClick={() => { void print(r) }}><Icon name="print" />{t('Print report')}</button>
          {r.wf_status === 'approved' && r.status !== 'superseded' && schemas?.project_reports?.can_create &&
            <button type="button" onClick={() => { void newVersion(r) }}>{t('New version')}</button>}
        </>}
        extra={r => <ReportPanel report={r} />} />
      {printing && <ReportDocument content={printing.content} seal={printing.seal} onClose={() => setPrinting(null)} />}
    </>
  )
}

