/** AGS4 import: choose a file, check it (preview with errors, warnings and duplicates), then import. */
import { useState } from 'react'
import { apiPost } from '../api'
import { t, translateServer } from '../i18n'
import { number } from '../records'
import { Icon } from '../ui'
import './AgsImport.css'

type Msg = { text: string, params?: Record<string, string> }
type BoreholePlan = {
  id: string, status: 'new' | 'exists' | 'error', action: 'create' | 'overwrite' | 'skip' | 'error', messages: Msg[],
  layers: number, spt: number, samples: number, core: number, groundwater: number | null, lab: number, lab_total: number,
}
type Preview = {
  format: string, edition: string, producer: string, project: { file: string, used: string },
  groups: Array<{ group: string, rows: number, use: string }>, errors: Msg[], warnings: Msg[], boreholes: BoreholePlan[],
  totals: { create: number, overwrite: number, skip: number, error: number, lab_create: number, lab_overwrite: number },
  can_import: boolean,
}
type Done = { created: number, updated: number, skipped: number, failed: number, lab_created: number, lab_updated: number, problems: Msg[] }

const MAX_BYTES = 4_000_000

/** A server message in the interface language; its values (group names, reasons) are translated too. */
export function say(m: Msg): string {
  const params = Object.fromEntries(Object.entries(m.params || {}).map(([k, v]) => [k, translateServer(String(v))]))
  return t(m.text, params)
}

const ACTION: Record<BoreholePlan['action'], [string, string]> = {
  create: ['New', 'ok'], overwrite: ['Overwrite', 'warn'], skip: ['Skip: already exists', ''], error: ['Not importable', 'bad'],
}

export default function AgsImport({ onClose, onImported }: { onClose: () => void, onImported: () => void }) {
  const [file, setFile] = useState<File | null>(null)
  const [content, setContent] = useState('')
  const [project, setProject] = useState('')
  const [duplicate, setDuplicate] = useState<'skip' | 'overwrite'>('skip')
  const [lab, setLab] = useState(true)
  const [preview, setPreview] = useState<Preview | null>(null)
  const [done, setDone] = useState<Done | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const body = (text: string) => ({ filename: file?.name || '', content: text, project_name: project.trim(), on_duplicate: duplicate, include_lab: lab })

  const choose = async (f: File | null) => {
    setFile(f); setPreview(null); setDone(null); setError(''); setContent('')
    if (!f) return
    if (f.size > MAX_BYTES) { setError(t('The file is too large (at most 4 MB)')); return }
    const text = await f.text()
    setContent(text)
    await check(text)
  }

  const check = async (text = content, keepDone = false) => {
    if (!text) { setError(t('Choose an AGS4 file first.')); return }
    setBusy(true); setError('')
    if (!keepDone) setDone(null)
    try {
      setPreview(await apiPost<Preview>('/api/import/ags/preview', body(text)))
    } catch (e: any) {
      setPreview(null); setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  const run = async () => {
    if (!preview?.can_import) return
    setBusy(true); setError('')
    try {
      const out = await apiPost<Done>('/api/import/ags', body(content))
      setDone(out); onImported()
    } catch (e: any) {
      setError(e.message); setBusy(false); return
    }
    // The preview again, now that the boreholes exist (they show as skipped or to overwrite).
    await check(content, true)
  }

  const totals = preview?.totals
  const labCount = (totals?.lab_create || 0) + (totals?.lab_overwrite || 0)
  return (
    <section className="card ags-import" aria-label={t('Import AGS4 file')}>
      <div className="ags-import-head">
        <h2>{t('Import AGS4 file')}</h2>
        <button type="button" className="quiet" onClick={onClose} aria-label={t('Close')}><Icon name="close" />{t('Close')}</button>
      </div>
      <p className="help">{t('Reads the boreholes (LOCA), strata (GEOL), SPT (ISPT), samples (SAMP), core runs (CORE), groundwater (WSTG) and the main laboratory groups. Nothing is stored until you press Import.')}</p>
      <div className="fields">
        <div className="field">
          <label htmlFor="ags-file">{t('AGS4 file (.ags)')}</label>
          <input id="ags-file" type="file" accept=".ags,.AGS,.txt,text/plain" onChange={e => { void choose(e.target.files?.[0] || null) }} />
        </div>
        <div className="field">
          <label htmlFor="ags-project">{t('Project name')}</label>
          <input id="ags-project" value={project} placeholder={preview?.project.file || t('From the file')} onChange={e => setProject(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="ags-dup">{t('Boreholes that already exist')}</label>
          <select id="ags-dup" value={duplicate} onChange={e => setDuplicate(e.target.value as 'skip' | 'overwrite')}>
            <option value="skip">{t('Skip them')}</option>
            <option value="overwrite">{t('Overwrite them with the file')}</option>
          </select>
        </div>
        <label className="checkbox ags-check">
          <input type="checkbox" checked={lab} onChange={e => setLab(e.target.checked)} />{t('Import laboratory results')}
        </label>
      </div>
      <div className="actions" style={{ marginTop: '.9rem' }}>
        <button type="button" onClick={() => { void check() }} disabled={busy || !content}><Icon name="check" />{t('Check again')}</button>
        <button type="button" className="primary" onClick={() => { void run() }} disabled={busy || !preview?.can_import}>
          <Icon name="folder" />{preview ? t('Import {n} boreholes', { n: (totals?.create || 0) + (totals?.overwrite || 0) }) : t('Import')}
        </button>
        {busy && <span className="muted small" role="status">{t('Working…')}</span>}
      </div>
      {error && <p className="notice error" role="alert">{error}</p>}
      {done && (
        <p className="notice ok" role="status">
          {t('Imported: {c} new, {u} overwritten, {s} skipped, {f} not imported; laboratory results {lc} new, {lu} updated.', {
            c: done.created, u: done.updated, s: done.skipped, f: done.failed, lc: done.lab_created, lu: done.lab_updated })}
        </p>
      )}
      {done?.problems?.length ? <ul className="notes">{done.problems.map((m, i) => <li key={i}>{say(m)}</li>)}</ul> : null}
      {preview && (
        <div className="ags-preview">
          <p className="muted small">
            {[preview.format, preview.edition && t('edition {e}', { e: preview.edition }), preview.producer, t('project: {p}', { p: preview.project.used })]
              .filter(Boolean).join(' · ')}
          </p>
          <div className="key-figures">
            {([['New boreholes', totals?.create], ['Overwrite', totals?.overwrite], ['Skipped', totals?.skip], ['Not importable', totals?.error],
              ['Laboratory results', labCount]] as Array<[string, number | undefined]>).map(([label, n]) => (
              <div key={label} className="key-figure"><span className="key-label">{t(label)}</span><span className="key-value">{n ?? 0}</span></div>
            ))}
          </div>
          {preview.errors.length > 0 && (
            <div className="notice error">
              <strong>{t('Errors in the file ({n})', { n: preview.errors.length })}</strong>
              <ul className="ags-msgs">{preview.errors.map((m, i) => <li key={i}>{say(m)}</li>)}</ul>
            </div>
          )}
          {preview.warnings.length > 0 && (
            <details className="notice warn ags-warn">
              <summary>{t('Warnings ({n})', { n: preview.warnings.length })}</summary>
              <ul className="ags-msgs">{preview.warnings.map((m, i) => <li key={i}>{say(m)}</li>)}</ul>
            </details>
          )}
          <h3>{t('Boreholes')}</h3>
          <div className="table-scroll">
            <table className="data-table ags-table">
              <thead>
                <tr>
                  <th>{t('Borehole')}</th><th>{t('Action')}</th><th className="num">{t('Strata')}</th><th className="num">SPT</th>
                  <th className="num">{t('Samples')}</th><th className="num">{t('Core runs')}</th><th className="num">{t('Groundwater (m)')}</th>
                  <th className="num">{t('Lab results')}</th>
                </tr>
              </thead>
              <tbody>
                {preview.boreholes.map(b => {
                  const [label, tone] = ACTION[b.action]
                  return (
                    <tr key={b.id}>
                      <td className="ags-id">
                        <strong>{b.id}</strong>
                        {b.messages.length > 0 && <ul className="ags-msgs small">{b.messages.map((m, i) => <li key={i}>{say(m)}</li>)}</ul>}
                      </td>
                      <td data-label={t('Action')}><span className={`status ${tone}`}>{t(label)}</span></td>
                      <td className="num" data-label={t('Strata')}>{b.layers}</td>
                      <td className="num" data-label="SPT">{b.spt}</td>
                      <td className="num" data-label={t('Samples')}>{b.samples}</td>
                      <td className="num" data-label={t('Core runs')}>{b.core}</td>
                      <td className="num" data-label={t('Groundwater (m)')}>{b.groundwater === null ? '–' : number(b.groundwater)}</td>
                      <td className="num" data-label={t('Lab results')}>{b.lab_total ? `${b.lab}/${b.lab_total}` : '–'}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          <details className="ags-groups">
            <summary>{t('Groups in the file ({n})', { n: preview.groups.length })}</summary>
            <ul>
              {preview.groups.map(g => (
                <li key={g.group}><code>{g.group}</code> <span className="muted">{t('{n} rows', { n: g.rows })}</span> → {t(g.use)}</li>
              ))}
            </ul>
          </details>
        </div>
      )}
    </section>
  )
}
