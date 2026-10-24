import { useEffect, useMemo, useRef, useState } from 'react'
import {
  deletePhoto, getActivity, getDetails, photoBlob, saveDetails, uploadPhoto,
  type AuditEvent, type Details, type PhotoMeta,
} from './api'
import BoreLog from './BoreLog'
import { USCS_OPTIONS } from './options'
import { locale, t } from './i18n'

type Row = Record<string, string | undefined>
type Section = 'layers' | 'spt' | 'samples' | 'core' | 'photos' | 'history'

// Editing keeps every cell as text; numbers are parsed when saving.
type Cell = Record<string, string>
type Draft = { layers: Cell[], spt: Cell[], samples: Cell[], core: Cell[] }

const SAMPLE_TYPES: Array<[string, string]> = [
  ['U', 'Undisturbed (open drive / UDS)'],
  ['UT', 'Undisturbed thin wall tube'],
  ['TW', 'Thin-walled push (Shelby)'],
  ['P', 'Piston'],
  ['D', 'Disturbed'],
  ['B', 'Bulk'],
  ['SPTLS', 'SPT liner / split spoon'],
  ['C', 'Core'],
  ['W', 'Water'],
]

const EMPTY: Record<keyof Draft, Cell> = {
  layers: { top: '', base: '', uscs: '', description: '' },
  spt: { depth: '', seat: '', inc1: '', inc2: '', penetration_mm: '', remarks: '' },
  samples: { top: '', base: '', type: 'U', ref: '', remarks: '' },
  core: { top: '', base: '', tcr: '', scr: '', rqd: '', remarks: '' },
}

const s = (v: unknown) => (v === null || v === undefined ? '' : String(v))

function toDraft(d: Details): Draft {
  return {
    layers: d.layers.map(l => ({ top: s(l.top), base: s(l.base), uscs: l.uscs, description: l.description })),
    spt: d.spt.map(x => ({
      depth: s(x.depth), seat: s(x.seat), inc1: s(x.inc1), inc2: s(x.inc2), penetration_mm: s(x.penetration_mm), remarks: x.remarks,
    })),
    samples: d.samples.map(x => ({ top: s(x.top), base: s(x.base), type: x.type, ref: x.ref, remarks: x.remarks })),
    core: d.core.map(x => ({ top: s(x.top), base: s(x.base), tcr: s(x.tcr), scr: s(x.scr), rqd: s(x.rqd), remarks: x.remarks })),
  }
}

const n = (v: string) => (v.trim() === '' ? null : Number(v.replace(',', '.')))
const req = (v: string) => n(v) ?? NaN

function fromDraft(d: Draft) {
  return {
    layers: d.layers.map(l => ({ top: req(l.top), base: req(l.base), uscs: l.uscs, description: l.description })),
    spt: d.spt.map(x => ({
      depth: req(x.depth), seat: req(x.seat), inc1: req(x.inc1), inc2: n(x.inc2), penetration_mm: n(x.penetration_mm), remarks: x.remarks,
    })),
    samples: d.samples.map(x => ({ top: req(x.top), base: n(x.base), type: x.type, ref: x.ref, remarks: x.remarks })),
    core: d.core.map(x => ({ top: req(x.top), base: req(x.base), tcr: n(x.tcr), scr: n(x.scr), rqd: n(x.rqd), remarks: x.remarks })),
  }
}

/** Checks in the browser so mistakes show next to the table, before saving. */
function problems(d: ReturnType<typeof fromDraft>, finalDepth: number | null): { errors: string[], warnings: string[] } {
  const out: string[] = []
  const warnings: string[] = []
  const bad = (v: number | null) => v !== null && (!Number.isFinite(v) || v < 0)
  d.layers.forEach((l, i) => {
    if (bad(l.top) || bad(l.base) || !(l.base > l.top)) out.push(t('Layer {i}: top and base must be numbers and base deeper than top.', { i: i + 1 }))
  })
  const sorted = [...d.layers].sort((a, b) => a.top - b.top)
  sorted.forEach((l, i) => {
    if (i > 0 && l.top < sorted[i - 1].base - 1e-9) out.push(t('Layers {a} and {b} overlap.', { a: `${sorted[i - 1].top}-${sorted[i - 1].base}`, b: `${l.top}-${l.base}` }))
  })
  d.spt.forEach((x, i) => {
    if (bad(x.depth) || !Number.isFinite(x.depth) || !Number.isFinite(x.seat) || !Number.isFinite(x.inc1)) out.push(t('SPT {i}: depth, seating and first test blows are required.', { i: i + 1 }))
  })
  d.samples.forEach((x, i) => {
    if (!Number.isFinite(x.top) || (x.base !== null && !(x.base > x.top))) out.push(t('Sample {i}: check its depths.', { i: i + 1 }))
  })
  d.core.forEach((x, i) => {
    if (!(x.base > x.top)) out.push(t('Core run {i}: base must be deeper than top.', { i: i + 1 }))
    if (x.tcr !== null && x.scr !== null && x.scr > x.tcr) out.push(t('Core run {i}: SCR cannot be more than TCR.', { i: i + 1 }))
    if (x.scr !== null && x.rqd !== null && x.rqd > x.scr) out.push(t('Core run {i}: RQD cannot be more than SCR.', { i: i + 1 }))
  })
  if (finalDepth !== null) {
    const deepest = Math.max(0, ...d.layers.map(l => l.base), ...d.core.map(c => c.base), ...d.spt.map(x => x.depth))
    if (deepest > finalDepth + 0.5) warnings.push(t('Some entries are deeper than the final depth ({d} m).', { d: finalDepth }))
  }
  return { errors: out, warnings }
}

function Field({ value, onChange, type = 'number', disabled, placeholder }: {
  value: string, onChange: (v: string) => void, type?: string, disabled?: boolean, placeholder?: string
}) {
  return (
    <input value={value} type={type} inputMode={type === 'number' ? 'decimal' : undefined} step="any"
      onChange={e => onChange(e.target.value)} disabled={disabled} placeholder={placeholder} />
  )
}

function EditableTable({ kind, rows, setRows, canEdit, columns }: {
  kind: keyof Draft
  rows: Cell[]
  setRows: (rows: Cell[]) => void
  canEdit: boolean
  columns: Array<{ key: string, label: string, type?: 'number' | 'text' | 'uscs' | 'sampletype' | 'long', width?: string }>
}) {
  const update = (i: number, key: string, value: string) => setRows(rows.map((r, j) => (j === i ? { ...r, [key]: value } : r)))
  const add = () => {
    const last = rows[rows.length - 1]
    const next = { ...EMPTY[kind] }
    // Continue where the previous row ended (strata and core runs follow each other).
    if (last && (kind === 'layers' || kind === 'core') && last.base) next.top = last.base
    if (last && kind === 'spt' && last.depth) next.depth = String(Number((Number(last.depth) + 1.5).toFixed(2)))
    setRows([...rows, next])
  }
  return (
    <div className="table-scroll">
      <table className="grid-table">
        <thead>
          <tr>
            {columns.map(c => <th key={c.key} style={{ width: c.width }}>{c.label}</th>)}
            {kind === 'spt' && <th style={{ width: '4.5rem' }}>N</th>}
            {canEdit && <th style={{ width: '3rem' }} />}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && (
            <tr><td colSpan={columns.length + 2} style={{ color: 'var(--muted)', padding: '.6rem' }}>{t('No rows yet.')}</td></tr>
          )}
          {rows.map((r, i) => (
            <tr key={i}>
              {columns.map(c => (
                <td key={c.key}>
                  {c.type === 'uscs' ? (
                    <select value={r[c.key]} onChange={e => update(i, c.key, e.target.value)} disabled={!canEdit}>
                      <option value="">–</option>
                      {(r[c.key] && !USCS_OPTIONS.includes(r[c.key]) ? [r[c.key], ...USCS_OPTIONS] : USCS_OPTIONS).map(o => <option key={o} value={o}>{o}</option>)}
                    </select>
                  ) : c.type === 'sampletype' ? (
                    <select value={r[c.key]} onChange={e => update(i, c.key, e.target.value)} disabled={!canEdit}>
                      {SAMPLE_TYPES.map(([code, label]) => <option key={code} value={code}>{code} – {t(label)}</option>)}
                    </select>
                  ) : c.type === 'long' ? (
                    <textarea value={r[c.key]} onChange={e => update(i, c.key, e.target.value)} disabled={!canEdit} rows={2} />
                  ) : (
                    <Field value={r[c.key]} onChange={v => update(i, c.key, v)} type={c.type === 'text' ? 'text' : 'number'} disabled={!canEdit} />
                  )}
                </td>
              ))}
              {kind === 'spt' && (
                <td style={{ paddingTop: '.6rem', whiteSpace: 'nowrap' }}>
                  {(() => {
                    const total = (n(r.inc1) ?? 0) + (n(r.inc2) ?? 0)
                    const pen = n(r.penetration_mm)
                    return pen !== null && pen < 300 ? `${total}/${pen}mm` : String(total)
                  })()}
                </td>
              )}
              {canEdit && (
                <td><button type="button" className="button-danger" aria-label={t('Remove row')} onClick={() => setRows(rows.filter((_, j) => j !== i))}>×</button></td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
      {canEdit && <button type="button" className="button-secondary" style={{ marginTop: '.5rem' }} onClick={add}>+ {t('Add row')}</button>}
    </div>
  )
}

/** Downscales a photo in the browser (max 1600 px, JPEG) so uploads stay small on mobile data. */
async function compress(file: File): Promise<{ data: string, type: string }> {
  const bitmap = await createImageBitmap(file)
  const scale = Math.min(1, 1600 / Math.max(bitmap.width, bitmap.height))
  const canvas = document.createElement('canvas')
  canvas.width = Math.round(bitmap.width * scale)
  canvas.height = Math.round(bitmap.height * scale)
  canvas.getContext('2d')!.drawImage(bitmap, 0, 0, canvas.width, canvas.height)
  bitmap.close?.()
  const blob: Blob = await new Promise((resolve, reject) => canvas.toBlob(b => (b ? resolve(b) : reject(new Error('encode failed'))), 'image/jpeg', 0.82))
  const buf = new Uint8Array(await blob.arrayBuffer())
  let bin = ''
  for (let i = 0; i < buf.length; i += 0x8000) bin += String.fromCharCode(...buf.subarray(i, i + 0x8000))
  return { data: btoa(bin), type: 'image/jpeg' }
}

function Photos({ boreholeId, photos, canEdit, onChanged }: { boreholeId: string, photos: PhotoMeta[], canEdit: boolean, onChanged: () => void }) {
  const [urls, setUrls] = useState<Record<string, string>>({})
  const [caption, setCaption] = useState('')
  const [depth, setDepth] = useState('')
  const [status, setStatus] = useState('')
  const [busy, setBusy] = useState(false)
  const [zoom, setZoom] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    let active = true
    const made: string[] = []
    photos.forEach(p => {
      photoBlob(p.id).then(b => {
        const u = URL.createObjectURL(b)
        made.push(u)
        if (active) setUrls(prev => ({ ...prev, [p.id]: u }))
        else URL.revokeObjectURL(u)
      }).catch(() => {})
    })
    return () => { active = false; made.forEach(u => URL.revokeObjectURL(u)) }
  }, [photos])

  const onUpload = async () => {
    const files = Array.from(fileRef.current?.files || [])
    if (!files.length) { setStatus(t('Choose one or more photos first.')); return }
    setBusy(true)
    try {
      for (const [i, file] of files.entries()) {
        setStatus(t('Uploading {i} of {n}…', { i: i + 1, n: files.length }))
        const { data, type } = await compress(file)
        await uploadPhoto({ borehole_id: boreholeId, content_type: type, data_base64: data, caption: caption || file.name.replace(/\.[^.]+$/, ''), depth: n(depth) })
      }
      setStatus(t('Photos uploaded.'))
      setCaption('')
      setDepth('')
      if (fileRef.current) fileRef.current.value = ''
      onChanged()
    } catch (e: any) {
      setStatus(`${t('Error')}: ${e.message}`)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      {canEdit && (
        <div className="card" style={{ marginBottom: '1rem', display: 'grid', gap: '.5rem' }}>
          <label>{t('Core box or field photos (taken with the camera or chosen from the gallery)')}
            <input ref={fileRef} type="file" accept="image/*" multiple capture="environment" />
          </label>
          <div className="row">
            <div><label>{t('Caption')}<input value={caption} onChange={e => setCaption(e.target.value)} maxLength={200} placeholder={t('e.g. Core box 1, 25.0–28.0 m')} /></label></div>
            <div><label>{t('Depth (m, optional)')}<Field value={depth} onChange={setDepth} /></label></div>
          </div>
          <div className="actions" style={{ alignItems: 'center' }}>
            <button type="button" onClick={onUpload} disabled={busy}>{t('Upload')}</button>
            <span>{status}</span>
          </div>
        </div>
      )}
      {photos.length === 0 ? <p style={{ color: 'var(--muted)' }}>{t('No photos yet.')}</p> : (
        <div className="photo-grid">
          {photos.map(p => (
            <figure key={p.id}>
              {urls[p.id] ? <img src={urls[p.id]} alt={p.caption} onClick={() => setZoom(urls[p.id])} /> : <div style={{ height: 140 }} />}
              <figcaption>
                {p.caption}{p.depth !== null ? ` · ${p.depth} m` : ''}
                {canEdit && (
                  <button type="button" className="button-danger" style={{ float: 'right', padding: '.1rem .45rem' }}
                    onClick={async () => {
                      if (!window.confirm(t('Delete this photo?'))) return
                      try { await deletePhoto(p.id); onChanged() } catch (e: any) { setStatus(e.message) }
                    }}>×</button>
                )}
              </figcaption>
            </figure>
          ))}
        </div>
      )}
      {zoom && <div className="lightbox" onClick={() => setZoom(null)}><img src={zoom} alt="" /></div>}
    </div>
  )
}

const ACTION_LABELS: Record<string, string> = {
  'log.created': 'Log created',
  'log.updated': 'Log edited',
  'log.deleted': 'Log deleted',
  'depth_data.updated': 'Depth data saved',
  'photo.added': 'Photo added',
  'photo.deleted': 'Photo deleted',
}

export function describeEvent(e: AuditEvent): string {
  const label = t(ACTION_LABELS[e.action] || e.action)
  if (!e.changes) return label
  const parts = Object.entries(e.changes).map(([k, v]) => {
    if (Array.isArray(v) && v.length === 2) return `${k}: ${s(v[0]) || '–'} → ${s(v[1]) || '–'}`
    return k
  })
  return `${label} (${parts.join('; ')})`
}

export function formatTime(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString(locale())
}

function History({ boreholeId }: { boreholeId: string }) {
  const [events, setEvents] = useState<AuditEvent[] | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    getActivity(boreholeId, 100).then(setEvents).catch(e => setError(e.message))
  }, [boreholeId])
  if (error) return <p className="notice error">{error}</p>
  if (!events) return <p>{t('Loading…')}</p>
  if (!events.length) return <p style={{ color: 'var(--muted)' }}>{t('No changes recorded yet.')}</p>
  return (
    <ul style={{ paddingLeft: '1.1rem' }}>
      {events.map((e, i) => (
        <li key={i} style={{ marginBottom: '.35rem' }}>
          <span style={{ color: 'var(--muted)' }}>{formatTime(e.at)}</span> · <strong>{e.user}</strong> · {describeEvent(e)}
        </li>
      ))}
    </ul>
  )
}

export default function BoreholeDetail({ report, canEdit, onClose }: { report: Row, canEdit: boolean, onClose: () => void }) {
  const id = report.BoreholeID || ''
  const [details, setDetails] = useState<Details | null>(null)
  const [draft, setDraft] = useState<Draft | null>(null)
  const [section, setSection] = useState<Section>('layers')
  const [status, setStatus] = useState('')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const [printing, setPrinting] = useState(false)

  const load = async () => {
    try {
      const d = await getDetails(id)
      setDetails(d)
      setDraft(prev => prev ?? toDraft(d))
      setError('')
    } catch (e: any) {
      setError(e.message)
    }
  }
  useEffect(() => { void load() }, [id]) // eslint-disable-line react-hooks/exhaustive-deps

  const parsed = useMemo(() => (draft ? fromDraft(draft) : null), [draft])
  const finalDepth = report.FinalDepth_m ? Number(report.FinalDepth_m) : null
  const checks = parsed ? problems(parsed, Number.isFinite(finalDepth as number) ? finalDepth : null) : { errors: [], warnings: [] }
  const issues = [...checks.errors, ...checks.warnings]
  const dirty = details && draft ? JSON.stringify(toDraft(details)) !== JSON.stringify(draft) : false

  const save = async () => {
    if (!parsed || saving) return
    if (checks.errors.length) {
      setStatus(t('Fix the problems listed above first.'))
      return
    }
    setSaving(true)
    setStatus(t('Saving…'))
    try {
      const saved = await saveDetails(id, parsed)
      setDetails(saved)
      setDraft(toDraft(saved))
      setStatus(t('Saved.'))
    } catch (e: any) {
      setStatus(`${t('Error')}: ${e.message}`)
    } finally {
      setSaving(false)
    }
  }

  const close = () => {
    if (dirty && !window.confirm(t('You have unsaved changes. Close anyway?'))) return
    onClose()
  }

  const sections: Array<[Section, string, number | null]> = [
    ['layers', t('Strata'), draft?.layers.length ?? null],
    ['spt', 'SPT', draft?.spt.length ?? null],
    ['samples', t('Samples'), draft?.samples.length ?? null],
    ['core', t('Core runs'), draft?.core.length ?? null],
    ['photos', t('Photos'), details?.photos.length ?? null],
    ['history', t('History'), null],
  ]

  return (
    <div className="card">
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: '.5rem', flexWrap: 'wrap', alignItems: 'center' }}>
        <div>
          <h2 style={{ margin: 0 }}>{t('Borehole')} {id}</h2>
          <div style={{ color: 'var(--muted)', fontSize: '.9rem' }}>
            {report.ProjectName} · {report.SiteName} · {t('final depth')} {report.FinalDepth_m || '–'} m
          </div>
        </div>
        <div className="actions" style={{ flexWrap: 'wrap' }}>
          <button type="button" onClick={() => setPrinting(true)} disabled={!details}>{t('Bore log (print / PDF)')}</button>
          <button type="button" className="button-secondary" onClick={close}>{t('Back to list')}</button>
        </div>
      </div>
      {error && <p className="notice error">{error}</p>}
      <div className="subtabs" role="tablist">
        {sections.map(([key, label, count]) => (
          <button key={key} type="button" className={section === key ? 'active' : ''} onClick={() => setSection(key)}>
            {label}{count !== null ? ` (${count})` : ''}
          </button>
        ))}
      </div>
      {!draft || !details ? <p>{t('Loading…')}</p> : (
        <>
          {section === 'layers' && (
            <EditableTable kind="layers" rows={draft.layers} setRows={rows => setDraft({ ...draft, layers: rows })} canEdit={canEdit}
              columns={[
                { key: 'top', label: t('From (m)'), width: '6rem' },
                { key: 'base', label: t('To (m)'), width: '6rem' },
                { key: 'uscs', label: 'USCS', type: 'uscs', width: '6rem' },
                { key: 'description', label: t('Soil / rock description'), type: 'long' },
              ]} />
          )}
          {section === 'spt' && (
            <>
              <p style={{ color: 'var(--muted)', fontSize: '.85rem', marginTop: 0 }}>
                {t('Blows per 150 mm: seating, then the two test increments. N = test increments. For refusal (e.g. 50 blows) enter the test penetration reached in mm.')}
              </p>
              <EditableTable kind="spt" rows={draft.spt} setRows={rows => setDraft({ ...draft, spt: rows })} canEdit={canEdit}
                columns={[
                  { key: 'depth', label: t('Depth (m)'), width: '6rem' },
                  { key: 'seat', label: t('Seating'), width: '5rem' },
                  { key: 'inc1', label: t('Test 1'), width: '5rem' },
                  { key: 'inc2', label: t('Test 2'), width: '5rem' },
                  { key: 'penetration_mm', label: t('Refusal at (mm)'), width: '6.5rem' },
                  { key: 'remarks', label: t('Remarks'), type: 'text' },
                ]} />
            </>
          )}
          {section === 'samples' && (
            <EditableTable kind="samples" rows={draft.samples} setRows={rows => setDraft({ ...draft, samples: rows })} canEdit={canEdit}
              columns={[
                { key: 'top', label: t('From (m)'), width: '6rem' },
                { key: 'base', label: t('To (m)'), width: '6rem' },
                { key: 'type', label: t('Type'), type: 'sampletype', width: '14rem' },
                { key: 'ref', label: t('Ref.'), type: 'text', width: '6rem' },
                { key: 'remarks', label: t('Remarks'), type: 'text' },
              ]} />
          )}
          {section === 'core' && (
            <EditableTable kind="core" rows={draft.core} setRows={rows => setDraft({ ...draft, core: rows })} canEdit={canEdit}
              columns={[
                { key: 'top', label: t('From (m)'), width: '6rem' },
                { key: 'base', label: t('To (m)'), width: '6rem' },
                { key: 'tcr', label: 'TCR %', width: '5rem' },
                { key: 'scr', label: 'SCR %', width: '5rem' },
                { key: 'rqd', label: 'RQD %', width: '5rem' },
                { key: 'remarks', label: t('Remarks'), type: 'text' },
              ]} />
          )}
          {section === 'photos' && <Photos boreholeId={id} photos={details.photos} canEdit={canEdit} onChanged={() => { void getDetails(id).then(setDetails) }} />}
          {section === 'history' && <History boreholeId={id} />}

          {['layers', 'spt', 'samples', 'core'].includes(section) && (
            <>
              {issues.length > 0 && (
                <div className="notice warn">
                  <ul style={{ margin: 0, paddingLeft: '1.1rem' }}>{issues.map((p, i) => <li key={i}>{p}</li>)}</ul>
                </div>
              )}
              {canEdit ? (
                <div className="actions" style={{ marginTop: '.75rem', alignItems: 'center' }}>
                  <button type="button" onClick={save} disabled={saving || !dirty}>{t('Save depth data')}</button>
                  {dirty && <span style={{ color: 'var(--muted)' }}>{t('Unsaved changes')}</span>}
                  <span>{status}</span>
                </div>
              ) : (
                <p style={{ color: 'var(--muted)' }}>{t('Only the person who submitted this log, or an admin, can change it.')}</p>
              )}
              {details.updated_at && (
                <p style={{ color: 'var(--muted)', fontSize: '.8rem' }}>
                  {t('Last saved {when} by {who}', { when: formatTime(details.updated_at), who: details.updated_by || '–' })}
                </p>
              )}
            </>
          )}
        </>
      )}
      {printing && details && draft && parsed && (
        <BoreLog report={report} details={checks.errors.length ? details : ({ ...details, ...parsed } as Details)}
          onClose={() => setPrinting(false)} />
      )}
    </div>
  )
}
