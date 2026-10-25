/**
 * Worksheet list (by document number), standards, coordinates and Google Earth export,
 * the sample register with laboratory instructions, and the summary of laboratory results.
 */
import { useEffect, useMemo, useState } from 'react'
import {
  convertCoordinates, downloadPointsKml, downloadProjectKml, getSamples, listRecords, saveRecord,
  type CoordOut, type Rec, type SampleRow, type SheetInfo,
} from '../api'
import { t } from '../i18n'
import { useNav, type Intent, type TabKey } from '../nav'
import { display, invalidate, number, optionLabel, useList, useSchemas } from '../records'
import { Icon, PageHead, formatDate, todayIso } from '../ui'
import { useCatalog } from '../worksheets'

const GROUPS: Array<[string, string]> = [
  ['01', 'General'], ['02', 'Survey'], ['03', 'Geotechnical'], ['04', 'Geophysics'], ['05', 'Laboratory'], ['06', 'Geology'],
]

function downloadText(name: string, text: string, type = 'text/csv') {
  const url = URL.createObjectURL(new Blob(['﻿' + text], { type: `${type};charset=utf-8` }))
  const a = document.createElement('a')
  a.href = url
  a.download = name
  a.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

const csvCell = (v: unknown) => {
  const s = v === null || v === undefined ? '' : String(v)
  return /[",;\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
}
const toCsv = (rows: unknown[][]) => rows.map(r => r.map(csvCell).join(',')).join('\r\n')

// ---------------------------------------------------------------------------
// Worksheet list
// ---------------------------------------------------------------------------

export function WorksheetCatalogPage() {
  const catalog = useCatalog()
  const { go } = useNav()
  const fieldRows = useList('field_activities')
  const labRows = useList('lab_tests')
  const count = (s: SheetInfo) => s.kind === 'field' ? (fieldRows || []).filter(r => r.method === s.key).length
    : s.kind === 'lab' ? (labRows || []).filter(r => r.test_type === s.key).length : null
  const open = (s: SheetInfo, example: boolean) => {
    if (s.kind === 'page') { go(s.link as TabKey); return }
    const withData = example && Object.keys(s.example || {}).length ? { [s.kind === 'field' ? 'data' : 'raw']: s.example } : {}
    const intent: Intent = s.kind === 'field'
      ? { newWith: { type: s.group, method: s.key, standard: s.standards.map(x => x[0]).join(', '), ...withData } }
      : { newWith: { test_type: s.key, standard: s.standards.map(x => x[0]).join(', '), ...withData } }
    go(s.kind === 'field' ? 'fieldwork' : 'lab', intent)
  }
  if (!catalog) return <p className="muted">{t('Loading…')}</p>
  const sorted = [...catalog].sort((a, b) => a.code.localeCompare(b.code, undefined, { numeric: true }))
  return (
    <div className="page">
      <PageHead title={t('Worksheet list')}
        description={t('Every field and laboratory worksheet by document number. Open a blank one, or one filled with example data to see how it works.')} />
      {GROUPS.map(([code, label]) => {
        const items = sorted.filter(s => s.code.startsWith(code + '.'))
        if (!items.length) return null
        return (
          <section key={code} className="card" style={{ marginBottom: '1rem' }}>
            <h3><span className="ws-code">{code}.</span> {t(label)}</h3>
            <div className="table-wrap">
              <table className="data-table ws-catalog">
                <thead><tr><th>{t('Number')}</th><th>{t('Worksheet')}</th><th>{t('Standards')}</th><th className="num">{t('Records')}</th><th /></tr></thead>
                <tbody>
                  {items.map(s => {
                    const n = count(s)
                    return (
                      <tr key={s.kind + s.key}>
                        <td className="nowrap">{s.code}</td>
                        <td><strong>{t(s.label)}</strong>{s.calc && <span className="chip">{t('calculated')}</span>}</td>
                        <td className="small">{s.standards.map(x => x[0]).join(', ') || '–'}</td>
                        <td className="num">{n === null ? '' : n}</td>
                        <td className="nowrap" style={{ textAlign: 'right' }}>
                          {s.kind === 'page' ? (
                            <button type="button" className="small" onClick={() => open(s, false)}>{t('Open')}</button>
                          ) : <>
                            <button type="button" className="small" onClick={() => open(s, false)}>{t('Blank')}</button>{' '}
                            {Object.keys(s.example || {}).length > 0 && <button type="button" className="small quiet" onClick={() => open(s, true)}>{t('Example')}</button>}
                          </>}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </section>
        )
      })}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Standards
// ---------------------------------------------------------------------------

export function StandardsPage() {
  const catalog = useCatalog()
  const [q, setQ] = useState('')
  if (!catalog) return <p className="muted">{t('Loading…')}</p>
  const sorted = [...catalog].filter(s => s.standards.length).sort((a, b) => a.code.localeCompare(b.code, undefined, { numeric: true }))
  const query = q.trim().toLowerCase()
  const match = (s: SheetInfo) => !query || (t(s.label) + ' ' + s.standards.flat().join(' ')).toLowerCase().includes(query)
  return (
    <div className="page">
      <PageHead title={t('Standards')} description={t('The SNI and ASTM standards each kind of work follows. They are filled in on new worksheets and printed with them.')} />
      <div className="toolbar"><input type="search" value={q} onChange={e => setQ(e.target.value)} placeholder={t('Search')} aria-label={t('Search')} /></div>
      {GROUPS.map(([code, label]) => {
        const items = sorted.filter(s => s.code.startsWith(code + '.') && match(s))
        if (!items.length) return null
        return (
          <section key={code} className="card" style={{ marginBottom: '1rem' }}>
            <h3><span className="ws-code">{code}.</span> {t(label)}</h3>
            <table className="data-table">
              <thead><tr><th>{t('Number')}</th><th>{t('Work')}</th><th>{t('Standard')}</th><th>{t('Subject')}</th></tr></thead>
              <tbody>
                {items.flatMap(s => s.standards.map(([std, title], i) => (
                  <tr key={s.key + std}>
                    {i === 0 && <td rowSpan={s.standards.length} className="nowrap">{s.code}</td>}
                    {i === 0 && <td rowSpan={s.standards.length}>{t(s.label)}</td>}
                    <td className="nowrap"><strong>{std}</strong></td>
                    <td>{t(title)}</td>
                  </tr>
                )))}
              </tbody>
            </table>
          </section>
        )
      })}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Coordinates and Google Earth
// ---------------------------------------------------------------------------

const parseNum = (s: string | undefined) => {
  if (s === undefined) return null
  const v = Number(s.trim().replace(/\s/g, '').replace(',', '.'))
  return s.trim() === '' || !Number.isFinite(v) ? null : v
}

export function CoordinatesPage() {
  const [mode, setMode] = useState<'geo' | 'utm'>('geo')
  const [text, setText] = useState('')
  const [zone, setZone] = useState('48')
  const [hem, setHem] = useState('S')
  const [rows, setRows] = useState<CoordOut[] | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const projects = useList('projects')
  const [project, setProject] = useState('')
  const convert = async () => {
    setError('')
    const lines = text.split(/\r?\n/).map(l => l.trim()).filter(Boolean)
    const input = lines.map((line, i) => {
      const c = line.split(/\t|;|,(?=\s*-?\d)/).map(x => x.trim())
      const hasName = c.length >= 3 && parseNum(c[0]) === null
      const [name, a, b, e] = hasName ? c : [`P${i + 1}`, ...c]
      return mode === 'geo'
        ? { name, latitude: parseNum(a), longitude: parseNum(b), elevation: parseNum(e) }
        : { name, easting: parseNum(a), northing: parseNum(b), zone: Number(zone), hemisphere: hem, elevation: parseNum(e) }
    })
    if (!input.length) { setError(t('Paste at least one row.')); return }
    setBusy(true)
    try { setRows(await convertCoordinates(input)) } catch (e: any) { setError(e.message) } finally { setBusy(false) }
  }
  const good = (rows || []).filter(r => !r.error)
  const csv = () => downloadText('coordinates.csv', toCsv([
    ['Name', 'Latitude', 'Longitude', 'Zone', 'Easting', 'Northing', 'Elevation'],
    ...good.map(r => [r.name, r.latitude, r.longitude, `${r.zone}${r.hemisphere}`, r.easting, r.northing, r.elevation ?? '']),
  ]))
  const kml = () => downloadPointsKml(t('Points'), good.map(r => ({
    name: r.name || '', latitude: Number(r.latitude), longitude: Number(r.longitude), elevation: r.elevation ?? null, folder: t('Points'),
  }))).catch(e => setError(e.message))
  return (
    <div className="page">
      <PageHead title={t('Coordinates & Google Earth')}
        description={t('Convert latitude/longitude (WGS84) to UTM and back, and download points for Google Earth.')} />
      <section className="card" style={{ marginBottom: '1rem' }}>
        <h3>{t('Project points in Google Earth')}</h3>
        <p className="help">{t('Boreholes, CPT and field worksheets of the project that have coordinates, in one KML file.')}</p>
        <div className="actions">
          <select value={project} onChange={e => setProject(e.target.value)} aria-label={t('Project')}>
            <option value="">{t('Select')}</option>
            {(projects || []).map(p => <option key={p.id} value={p.id}>{p.code} {p.name}</option>)}
          </select>
          <button type="button" disabled={!project} onClick={() => { setError(''); downloadProjectKml(project).catch(e => setError(e.message)) }}>
            <Icon name="download" />{t('Download KML')}
          </button>
        </div>
      </section>
      <section className="card">
        <h3>{t('Coordinate converter')}</h3>
        <div className="segmented" role="group" aria-label={t('Input')} style={{ marginBottom: '.75rem' }}>
          <button type="button" aria-pressed={mode === 'geo'} onClick={() => setMode('geo')}>{t('Latitude / longitude → UTM')}</button>
          <button type="button" aria-pressed={mode === 'utm'} onClick={() => setMode('utm')}>{t('UTM → latitude / longitude')}</button>
        </div>
        {mode === 'utm' && (
          <div className="fields" style={{ maxWidth: 420 }}>
            <div className="field"><label htmlFor="c-zone">{t('UTM zone')}</label><input id="c-zone" value={zone} inputMode="numeric" onChange={e => setZone(e.target.value.replace(/\D/g, ''))} /></div>
            <div className="field"><label htmlFor="c-hem">{t('Hemisphere')}</label>
              <select id="c-hem" value={hem} onChange={e => setHem(e.target.value)}><option value="S">{t('South')}</option><option value="N">{t('North')}</option></select></div>
          </div>
        )}
        <div className="field">
          <label htmlFor="c-text">{mode === 'geo' ? t('Rows: name, latitude, longitude, elevation (elevation optional)') : t('Rows: name, easting, northing, elevation (elevation optional)')}</label>
          <textarea id="c-text" rows={7} value={text} onChange={e => setText(e.target.value)}
            placeholder={mode === 'geo' ? 'BH-01\t-6.2001\t106.8452\t12.5' : 'BH-01\t704312.4\t9314321.8\t12.5'} />
          <p className="help">{t('Paste from Excel (tab separated) or type one point per line. Decimal degrees; south latitudes are negative.')}</p>
        </div>
        <div className="actions">
          <button type="button" className="primary" onClick={() => { void convert() }} disabled={busy}>{t('Convert')}</button>
          {good.length > 0 && <>
            <button type="button" onClick={csv}><Icon name="download" />CSV</button>
            <button type="button" onClick={() => { void kml() }}><Icon name="download" />KML (Google Earth)</button>
          </>}
        </div>
        {error && <p className="notice error">{error}</p>}
        {rows && (
          <div className="table-wrap" style={{ marginTop: '1rem' }}>
            <table className="data-table">
              <thead><tr><th>{t('Name')}</th><th className="num">{t('Latitude')}</th><th className="num">{t('Longitude')}</th><th>{t('Zone')}</th><th className="num">{t('Easting (m)')}</th><th className="num">{t('Northing (m)')}</th><th>DMS</th></tr></thead>
              <tbody>{rows.map((r, i) => r.error
                ? <tr key={i}><td>{r.name}</td><td colSpan={6} className="bad">{r.error}</td></tr>
                : <tr key={i}><td>{r.name}</td><td className="num">{r.latitude}</td><td className="num">{r.longitude}</td><td>{r.zone}{r.hemisphere}</td>
                  <td className="num">{number(r.easting)}</td><td className="num">{number(r.northing)}</td><td className="small nowrap">{r.dms}</td></tr>)}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Sample register and laboratory instruction
// ---------------------------------------------------------------------------

export function SampleRegisterPage() {
  const schemas = useSchemas()
  const testField = schemas?.lab_tests?.fields.find(f => f.name === 'test_type')
  const projects = useList('projects')
  const [project, setProject] = useState('')
  const [rows, setRows] = useState<SampleRow[] | null>(null)
  const [picked, setPicked] = useState<Record<string, boolean>>({})
  const [tests, setTests] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [labels, setLabels] = useState<SampleRow[] | null>(null)
  const projectName = projects?.find(p => p.id === project)?.name || ''
  const load = () => { setRows(null); getSamples(projectName || undefined).then(setRows).catch(e => setError(e.message)) }
  useEffect(load, [projectName])
  const key = (s: SampleRow) => `${s.borehole_id}|${s.top}|${s.ref}`
  const chosen = (rows || []).filter(s => picked[key(s)])
  const canCreate = !!schemas?.lab_tests?.can_create
  const instruct = async () => {
    setBusy(true); setError(''); setNotice('')
    let made = 0
    try {
      for (const s of chosen) {
        for (const test of tests) {
          if (s.tests.some(x => x.test_type === test)) continue
          await saveRecord('lab_tests', {
            borehole_id: s.borehole_id, sample_ref: s.ref || `${s.type}-${s.top}`, depth_top: s.top, depth_base: s.base,
            test_type: test, status: 'requested', received: todayIso(), project_id: project || '',
          })
          made++
        }
      }
      invalidate('lab_tests')
      setNotice(t('{n} laboratory tests requested.', { n: made }))
      setPicked({})
      load()
    } catch (e: any) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="page">
      <PageHead title={t('Sample register')}
        description={t('Every sample taken in the boreholes. Tick samples and tests to send a laboratory instruction; the tests then appear in Laboratory tests as requested.')} />
      <div className="toolbar">
        <select value={project} onChange={e => setProject(e.target.value)} aria-label={t('Project')}>
          <option value="">{t('All projects')}</option>
          {(projects || []).map(p => <option key={p.id} value={p.id}>{p.code} {p.name}</option>)}
        </select>
        <span className="muted">{rows ? t('{n} samples', { n: rows.length }) : t('Loading…')}</span>
      </div>
      {notice && <p className="notice ok">{notice}</p>}
      {error && <p className="notice error">{error}</p>}
      {canCreate && chosen.length > 0 && (
        <section className="card ws-instruct">
          <h3>{t('Laboratory instruction for {n} samples', { n: chosen.length })}</h3>
          <div className="checks">
            {(testField?.options || []).map(o => (
              <label key={o[0]} className="checkbox">
                <input type="checkbox" checked={tests.includes(o[0])} onChange={e => setTests(e.target.checked ? [...tests, o[0]] : tests.filter(x => x !== o[0]))} />
                {t(o[1])}
              </label>
            ))}
          </div>
          <div className="actions" style={{ marginTop: '.5rem' }}>
            <button type="button" className="primary" disabled={busy || !tests.length} onClick={() => { void instruct() }}>{t('Request tests')}</button>
            <button type="button" onClick={() => setLabels(chosen)}><Icon name="print" />{t('Print sample labels')}</button>
          </div>
        </section>
      )}
      {labels && <SampleLabels samples={labels} onClose={() => setLabels(null)} />}
      {rows && (
        <div className="table-wrap">
          <table className="data-table">
            <thead><tr>
              <th style={{ width: '2rem' }}><input type="checkbox" aria-label={t('Select all')} checked={rows.length > 0 && chosen.length === rows.length}
                onChange={e => setPicked(e.target.checked ? Object.fromEntries(rows.map(r => [key(r), true])) : {})} /></th>
              <th>{t('Borehole')}</th><th>{t('Sample')}</th><th>{t('Type')}</th><th className="num">{t('From (m)')}</th><th className="num">{t('To (m)')}</th><th>{t('Laboratory tests')}</th>
            </tr></thead>
            <tbody>
              {rows.length === 0 && <tr><td colSpan={7} className="muted">{t('No samples recorded in the boreholes yet. Samples are added in a borehole under depth data.')}</td></tr>}
              {rows.map(s => (
                <tr key={key(s)}>
                  <td><input type="checkbox" aria-label={`${s.borehole_id} ${s.ref}`} checked={!!picked[key(s)]} onChange={e => setPicked({ ...picked, [key(s)]: e.target.checked })} /></td>
                  <td className="nowrap"><strong>{s.borehole_id}</strong><div className="bh-sub">{s.project}</div></td>
                  <td>{s.ref || '–'}</td><td>{s.type}</td>
                  <td className="num">{number(s.top)}</td><td className="num">{number(s.base)}</td>
                  <td>{s.tests.length ? s.tests.map(x => (
                    <span key={x.id} className={`chip status-${x.status}`}>{testField ? optionLabel(testField, x.test_type) : x.test_type}</span>
                  )) : <span className="muted">–</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Summary of laboratory results
// ---------------------------------------------------------------------------

export function LabSummaryPage() {
  const schemas = useSchemas()
  const entity = schemas?.lab_tests
  const resultsField = entity?.fields.find(f => f.name === 'results')
  const testField = entity?.fields.find(f => f.name === 'test_type')
  const projects = useList('projects')
  const [project, setProject] = useState('')
  const [tests, setTests] = useState<Rec[] | null>(null)
  useEffect(() => { listRecords('lab_tests').then(setTests).catch(() => setTests([])) }, [])
  const projectName = projects?.find(p => p.id === project)?.name || ''
  const [boreholes, setBoreholes] = useState<Set<string> | null>(null)
  useEffect(() => {
    if (!projectName) { setBoreholes(null); return }
    getSamples(projectName).then(list => setBoreholes(new Set(list.map(s => s.borehole_id.toLowerCase())))).catch(() => setBoreholes(new Set()))
  }, [projectName])
  const model = useMemo(() => {
    const done = (tests || []).filter(x => x.results && Object.keys(x.results).length
      && (!project || x.project_id === project || boreholes?.has(String(x.borehole_id).toLowerCase())))
    const types = (testField?.options || []).map(o => o[0]).filter(tt => done.some(x => x.test_type === tt))
    const cols = types.flatMap(tt => (resultsField?.variants?.[tt] || []).filter(f => done.some(x => x.test_type === tt && x.results?.[f.name] !== undefined && x.results?.[f.name] !== null))
      .map(f => ({ tt, f })))
    const groups = new Map<string, { bh: string, sample: string, top: number, base: number | null, res: Record<string, Rec> }>()
    for (const x of done) {
      const k = `${x.borehole_id}|${x.sample_ref}|${x.depth_top}`
      if (!groups.has(k)) groups.set(k, { bh: x.borehole_id, sample: x.sample_ref, top: x.depth_top, base: x.depth_base, res: {} })
      groups.get(k)!.res[x.test_type] = x.results
    }
    const rows = [...groups.values()].sort((a, b) => a.bh.localeCompare(b.bh) || a.top - b.top)
    return { cols, rows }
  }, [tests, project, boreholes, resultsField, testField])
  const exportCsv = () => downloadText('lab-summary.csv', toCsv([
    ['Borehole', 'Sample', 'From (m)', 'To (m)', ...model.cols.map(c => t(c.f.label))],
    ...model.rows.map(r => [r.bh, r.sample, r.top, r.base ?? '', ...model.cols.map(c => r.res[c.tt]?.[c.f.name] ?? '')]),
  ]))
  return (
    <div className="page">
      <PageHead title={t('Summary of laboratory results')}
        description={t('All finished laboratory results per sample in one table, for the report. Export to Excel (CSV) or print.')}
        actions={<>
          <button type="button" onClick={exportCsv} disabled={!model.rows.length}><Icon name="download" />CSV</button>
          <button type="button" onClick={() => window.print()} disabled={!model.rows.length}><Icon name="print" />{t('Print')}</button>
        </>} />
      <div className="toolbar">
        <select value={project} onChange={e => setProject(e.target.value)} aria-label={t('Project')}>
          <option value="">{t('All projects')}</option>
          {(projects || []).map(p => <option key={p.id} value={p.id}>{p.code} {p.name}</option>)}
        </select>
        <span className="muted">{tests ? t('{n} samples', { n: model.rows.length }) : t('Loading…')}</span>
      </div>
      {tests && !model.rows.length && <p className="muted">{t('No finished laboratory results yet.')}</p>}
      {model.rows.length > 0 && (
        <div className="table-wrap lab-summary">
          <table className="data-table">
            <thead>
              <tr>
                <th rowSpan={2}>{t('Borehole')}</th><th rowSpan={2}>{t('Sample')}</th><th rowSpan={2} className="num">{t('Depth (m)')}</th>
                {Object.entries(model.cols.reduce<Record<string, number>>((acc, c) => { acc[c.tt] = (acc[c.tt] || 0) + 1; return acc }, {})).map(([tt, n]) => (
                  <th key={tt} colSpan={n} className="group">{testField ? optionLabel(testField, tt) : tt}</th>
                ))}
              </tr>
              <tr>{model.cols.map(c => <th key={c.tt + c.f.name} className="num">{t(c.f.label)}</th>)}</tr>
            </thead>
            <tbody>
              {model.rows.map(r => (
                <tr key={`${r.bh}|${r.sample}|${r.top}`}>
                  <td className="nowrap"><strong>{r.bh}</strong></td><td>{r.sample}</td>
                  <td className="num nowrap">{number(r.top)}{r.base !== null && r.base !== undefined ? `–${number(r.base)}` : ''}</td>
                  {model.cols.map(c => <td key={c.tt + c.f.name} className="num">{r.res[c.tt] ? display(c.f, r.res[c.tt][c.f.name]) : ''}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="help">{t('Printed on')} {formatDate(todayIso())}</p>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Sample labels with a QR code (chain of custody)
// ---------------------------------------------------------------------------

export const sampleCode = (s: { borehole_id: string, ref: string, top: number | null, base: number | null }) =>
  `${s.borehole_id}/${s.ref || 'S'}/${s.top ?? ''}-${s.base ?? ''}`

function SampleLabels({ samples, onClose }: { samples: SampleRow[], onClose: () => void }) {
  const [codes, setCodes] = useState<Record<string, string>>({})
  useEffect(() => {
    let active = true
    import('qrcode').then(async mod => {
      const out: Record<string, string> = {}
      for (const s of samples) out[sampleCode(s)] = await mod.default.toDataURL(`SB:${sampleCode(s)}`, { margin: 1, width: 160 })
      if (active) setCodes(out)
    })
    return () => { active = false }
  }, [samples])
  useEffect(() => {
    document.body.classList.add('printing-borelog')
    return () => document.body.classList.remove('printing-borelog')
  }, [])
  return (
    <div className="borelog-root">
      <div className="borelog-toolbar no-print">
        <button type="button" className="primary" onClick={() => window.print()}>{t('Print / save as PDF')}</button>
        <button type="button" onClick={onClose}>{t('Close')}</button>
        <span>{t('Stick a label on each sample tube or bag; the laboratory scans or types the code.')}</span>
      </div>
      <article className="borelog-page label-sheet">
        {samples.map(s => (
          <div key={sampleCode(s)} className="sample-label">
            {codes[sampleCode(s)] ? <img src={codes[sampleCode(s)]} alt="" /> : <div className="qr-wait" />}
            <div>
              <div className="label-bh">{s.borehole_id}</div>
              <div className="label-ref">{s.ref || '–'} · {s.type}</div>
              <div>{number(s.top)}{s.base !== null && s.base !== undefined ? `–${number(s.base)}` : ''} m</div>
              <div className="label-small">{s.project}</div>
              <div className="label-small">{sampleCode(s)}</div>
            </div>
          </div>
        ))}
      </article>
    </div>
  )
}
