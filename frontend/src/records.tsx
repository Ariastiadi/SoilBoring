/**
 * Lists, forms and detail views built from the record definitions the server sends
 * (GET /api/schemas). Used by the commercial, field, laboratory, analysis and finance pages.
 */
import { createContext, Fragment, ReactNode, useContext, useEffect, useMemo, useState } from 'react'
import {
  deleteRecord, downloadFile, listRecords, saveRecord, uploadFile, userDirectory,
  type EntityDef, type FieldDef, type FileMeta, type Rec, type Schemas,
} from './api'
import { locale, t } from './i18n'
import { DateInput, Icon, PageHead, formatDate } from './ui'

export const SchemaContext = createContext<Schemas | null>(null)
export const useSchemas = () => useContext(SchemaContext)

// ---------------------------------------------------------------------------
// Small caches: lists used in drop-downs (clients, projects, rates, users)
// ---------------------------------------------------------------------------

const cache = new Map<string, Promise<Rec[]>>()
export function cachedList(entity: string): Promise<Rec[]> {
  if (!cache.has(entity)) {
    const p = listRecords(entity).catch(err => { cache.delete(entity); throw err })
    cache.set(entity, p)
  }
  return cache.get(entity)!
}
export function invalidate(entity?: string) {
  if (entity) cache.delete(entity)
  else cache.clear()
}
let users: Promise<Array<{ email: string, role: string }>> | null = null
function cachedUsers() {
  if (!users) users = userDirectory().catch(() => { users = null; return [] })
  return users
}

export function useList(entity: string | null, enabled = true) {
  const [rows, setRows] = useState<Rec[] | null>(null)
  useEffect(() => {
    let active = true
    if (!entity || !enabled) return
    cachedList(entity).then(r => { if (active) setRows(r) }).catch(() => { if (active) setRows([]) })
    return () => { active = false }
  }, [entity, enabled])
  return rows
}

// ---------------------------------------------------------------------------
// Formatting
// ---------------------------------------------------------------------------

export const money = (v: unknown) => {
  const n = typeof v === 'number' ? v : Number(v)
  if (v === null || v === undefined || v === '' || !Number.isFinite(n)) return '–'
  return 'Rp ' + n.toLocaleString(locale(), { maximumFractionDigits: 0 })
}
export const number = (v: unknown) => {
  const n = typeof v === 'number' ? v : Number(v)
  if (v === null || v === undefined || v === '' || !Number.isFinite(n)) return '–'
  return n.toLocaleString(locale(), { maximumFractionDigits: 3 })
}

export function optionLabel(f: FieldDef, value: unknown): string {
  const o = (f.options || []).find(o => o[0] === value)
  return o ? t(o[1]) : String(value ?? '')
}

export function RefName({ entity, id }: { entity: string, id?: string }) {
  const rows = useList(id ? entity : null)
  const schemas = useSchemas()
  if (!id) return <>–</>
  const row = rows?.find(r => r.id === id)
  const title = schemas?.[entity]?.title || 'name'
  return <>{row ? String(row[title] ?? row.name ?? id) : '…'}</>
}

export function display(f: FieldDef, value: unknown): ReactNode {
  if (value === null || value === undefined || value === '' || (Array.isArray(value) && !value.length)) return '–'
  switch (f.type) {
    case 'money': return money(value)
    case 'percent': return `${number(value)} %`
    case 'number': case 'int': return number(value)
    case 'date': return formatDate(String(value))
    case 'select': return optionLabel(f, value)
    case 'multiselect': return (value as string[]).map(v => optionLabel(f, v)).join(', ')
    case 'bool': return value ? t('Yes') : t('No')
    case 'ref': return <RefName entity={f.ref || ''} id={String(value)} />
    case 'files': return `${(value as unknown[]).length} ${t('files')}`
    case 'items': return `${(value as unknown[]).length} ${t('rows')}`
    default: return String(value)
  }
}

// ---------------------------------------------------------------------------
// Inputs
// ---------------------------------------------------------------------------

const asNumberText = (v: string) => v.replace(/,/g, '.')
const asMoneyText = (v: string) => v.replace(/[^\d]/g, '')

function RefSelect({ f, value, onChange, id }: { f: FieldDef, value: string, onChange: (v: string) => void, id?: string }) {
  const rows = useList(f.ref)
  const schemas = useSchemas()
  const title = schemas?.[f.ref || '']?.title || 'name'
  return (
    <select id={id} value={value || ''} onChange={e => onChange(e.target.value)}>
      <option value="">{rows ? t('Select') : t('Loading…')}</option>
      {(rows || []).map(r => <option key={r.id} value={r.id}>{String(r[title] ?? r.id)}{r.code && title !== 'code' ? ` (${r.code})` : ''}</option>)}
    </select>
  )
}

function UserSelect({ value, onChange, id }: { value: string, onChange: (v: string) => void, id?: string }) {
  const [list, setList] = useState<Array<{ email: string, role: string }> | null>(null)
  useEffect(() => { cachedUsers().then(setList) }, [])
  return (
    <select id={id} value={value || ''} onChange={e => onChange(e.target.value)}>
      <option value="">{list ? t('Select') : t('Loading…')}</option>
      {value && list && !list.some(u => u.email === value) && <option value={value}>{value}</option>}
      {(list || []).map(u => <option key={u.email} value={u.email}>{u.email}</option>)}
    </select>
  )
}

export function FieldInput({ f, value, onChange, record, id }: {
  f: FieldDef, value: any, onChange: (v: any) => void, record: Record<string, any>, id?: string
}) {
  switch (f.type) {
    case 'longtext':
      return <textarea id={id} value={value ?? ''} maxLength={f.maxlen} rows={4} onChange={e => onChange(e.target.value)} />
    case 'number': case 'int': case 'percent':
      return <input id={id} type="text" inputMode="decimal" value={value ?? ''} onChange={e => onChange(asNumberText(e.target.value))} />
    case 'money':
      return (
        <div>
          <input id={id} type="text" inputMode="numeric" value={value ?? ''} onChange={e => onChange(asMoneyText(e.target.value))} />
          {value !== '' && value !== undefined && value !== null && <span className="help">{money(value)}</span>}
        </div>
      )
    case 'date':
      return <DateInput id={id} value={value || ''} onChange={onChange} />
    case 'email':
      return <input id={id} type="email" value={value ?? ''} onChange={e => onChange(e.target.value)} />
    case 'bool':
      return <input id={id} type="checkbox" checked={!!value} onChange={e => onChange(e.target.checked)} />
    case 'select': {
      const group = f.options_filter ? record[f.options_filter] : null
      const opts = (f.options || []).filter(o => !f.options_filter || o.length < 3 || o[2] === group)
      return (
        <select id={id} value={value ?? ''} onChange={e => onChange(e.target.value)}>
          <option value="">{t('Select')}</option>
          {opts.map(o => <option key={o[0]} value={o[0]}>{t(o[1])}</option>)}
        </select>
      )
    }
    case 'multiselect': {
      const current: string[] = Array.isArray(value) ? value : []
      return (
        <div className="checks">
          {(f.options || []).map(o => (
            <label key={o[0]} className="checkbox">
              <input type="checkbox" checked={current.includes(o[0])}
                onChange={e => onChange(e.target.checked ? [...current, o[0]] : current.filter(v => v !== o[0]))} />
              {t(o[1])}
            </label>
          ))}
        </div>
      )
    }
    case 'ref':
      return <RefSelect f={f} id={id} value={value} onChange={onChange} />
    case 'user':
      return <UserSelect id={id} value={value} onChange={onChange} />
    case 'items':
      return <ItemsEditor f={f} rows={Array.isArray(value) ? value : []} onChange={onChange} />
    case 'files':
      return <FilesEditor files={Array.isArray(value) ? value : []} onChange={onChange} />
    case 'json':
      if (f.variants_by && f.variants) {
        const sub = f.variants[record[f.variants_by]] || []
        if (!sub.length) return <p className="muted small">{t('Choose the test first.')}</p>
        const obj = value && typeof value === 'object' ? value : {}
        return (
          <div className="fields">
            {sub.map(s => (
              <div className="field" key={s.name}>
                <label htmlFor={`${id}-${s.name}`}>{t(s.label)}</label>
                <FieldInput f={s} id={`${id}-${s.name}`} value={obj[s.name]} record={obj} onChange={v => onChange({ ...obj, [s.name]: v })} />
                {s.help && <p className="help">{t(s.help)}</p>}
              </div>
            ))}
          </div>
        )
      }
      return null
    default:
      return <input id={id} type="text" value={value ?? ''} maxLength={f.maxlen} onChange={e => onChange(e.target.value)} />
  }
}

function ItemsEditor({ f, rows, onChange }: { f: FieldDef, rows: Array<Record<string, any>>, onChange: (rows: Array<Record<string, any>>) => void }) {
  const subs = f.fields || []
  const rates = useList(subs.some(s => s.type === 'ref' && s.ref === 'rates') ? 'rates' : null)
  const [paste, setPaste] = useState<string | null>(null)
  const set = (i: number, key: string, v: any) => onChange(rows.map((r, j) => (j === i ? { ...r, [key]: v } : r)))
  const pick = (i: number, rateId: string) => {
    const rate = rates?.find(r => r.id === rateId)
    onChange(rows.map((r, j) => (j === i ? { ...r, rate_id: rateId, ...(rate ? { description: rate.description, unit: rate.unit, unit_price: rate.price } : {}) } : r)))
  }
  const editable = subs.filter(s => s.type !== 'ref' || s.ref === 'rates')
  const pasteCols = editable.filter(s => s.type !== 'ref')
  const applyPaste = () => {
    const lines = (paste || '').split(/\r?\n/).map(l => l.trim()).filter(Boolean)
    const parsed = lines.map(line => {
      const cells = line.split(/\t|;/)
      const row: Record<string, any> = {}
      pasteCols.forEach((s, k) => { if (cells[k] !== undefined) row[s.name] = s.type === 'number' || s.type === 'percent' ? asNumberText(cells[k].trim()) : s.type === 'money' ? asMoneyText(cells[k]) : cells[k].trim() })
      return row
    }).filter(r => Object.values(r).some(v => v !== ''))
    onChange([...rows, ...parsed].slice(0, f.max_items))
    setPaste(null)
  }
  const total = subs.some(s => s.name === 'unit_price') ? rows.reduce((sum, r) => sum + (Number(r.qty) || 0) * (Number(r.unit_price) || 0), 0) : null
  return (
    <div>
      <div className="table-scroll">
        <table className="grid-table">
          <thead>
            <tr>
              {editable.map(s => <th key={s.name}>{t(s.label)}</th>)}
              {total !== null && <th className="num">{t('Amount')}</th>}
              <th style={{ width: '2.5rem' }} />
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && <tr><td colSpan={editable.length + 2} className="muted" style={{ padding: '.6rem' }}>{t('No rows yet.')}</td></tr>}
            {rows.map((r, i) => (
              <tr key={i}>
                {editable.map(s => (
                  <td key={s.name}>
                    {s.type === 'ref' && s.ref === 'rates' ? (
                      <select value={r.rate_id || ''} onChange={e => pick(i, e.target.value)} aria-label={t(s.label)}>
                        <option value="">–</option>
                        {(rates || []).map(rt => <option key={rt.id} value={rt.id}>{rt.code} {rt.description}</option>)}
                      </select>
                    ) : (
                      <FieldInput f={s} value={r[s.name]} record={r} onChange={v => set(i, s.name, v)} />
                    )}
                  </td>
                ))}
                {total !== null && <td className="num nowrap" style={{ paddingTop: '.6rem' }}>{money((Number(r.qty) || 0) * (Number(r.unit_price) || 0))}</td>}
                <td><button type="button" className="quiet danger-quiet small" aria-label={t('Remove row')} onClick={() => onChange(rows.filter((_, j) => j !== i))}>×</button></td>
              </tr>
            ))}
          </tbody>
          {total !== null && rows.length > 0 && (
            <tfoot><tr><td colSpan={editable.length} style={{ textAlign: 'right', fontWeight: 600 }}>{t('Subtotal')}</td><td className="num nowrap" style={{ fontWeight: 600 }}>{money(total)}</td><td /></tr></tfoot>
          )}
        </table>
      </div>
      <div className="actions" style={{ marginTop: '.5rem' }}>
        <button type="button" onClick={() => onChange([...rows, {}].slice(0, f.max_items))} disabled={rows.length >= f.max_items}><Icon name="plus" />{t('Add row')}</button>
        <button type="button" className="quiet" onClick={() => setPaste(paste === null ? '' : null)}>{t('Paste from Excel')}</button>
      </div>
      {paste !== null && (
        <div className="field" style={{ marginTop: '.5rem' }}>
          <label>{t('Paste rows (columns: {cols})', { cols: pasteCols.map(s => t(s.label)).join(', ') })}</label>
          <textarea rows={5} value={paste} onChange={e => setPaste(e.target.value)} />
          <div className="actions"><button type="button" className="primary" onClick={applyPaste}>{t('Add these rows')}</button><button type="button" onClick={() => setPaste(null)}>{t('Cancel')}</button></div>
        </div>
      )}
    </div>
  )
}

const ACCEPT = '.pdf,.jpg,.jpeg,.png,.csv,.txt,.zip,.xlsx,.docx'

function FilesEditor({ files, onChange }: { files: FileMeta[], onChange: (f: FileMeta[]) => void }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const add = async (list: FileList | null) => {
    if (!list?.length) return
    setBusy(true)
    setError('')
    const added: FileMeta[] = []
    try {
      for (const file of Array.from(list)) added.push(await uploadFile(file))
    } catch (e: any) {
      setError(e.message)
    } finally {
      onChange([...files, ...added])
      setBusy(false)
    }
  }
  return (
    <div>
      <FileList files={files} onRemove={f => onChange(files.filter(x => x.id !== f.id))} />
      <label className="button-like" style={{ marginTop: '.4rem' }}>
        <Icon name="plus" />{busy ? t('Uploading…') : t('Add files')}
        <input type="file" multiple accept={ACCEPT} className="sr-only" disabled={busy} onChange={e => { void add(e.target.files); e.target.value = '' }} />
      </label>
      <p className="help">{t('PDF, JPEG, PNG, CSV, TXT, ZIP, XLSX or DOCX, up to 5 MB each.')}</p>
      {error && <p className="notice error">{error}</p>}
    </div>
  )
}

export function FileList({ files, onRemove }: { files: FileMeta[], onRemove?: (f: FileMeta) => void }) {
  if (!files?.length) return <p className="muted small" style={{ margin: 0 }}>{t('No files yet.')}</p>
  return (
    <ul className="file-list">
      {files.map(f => (
        <li key={f.id}>
          <button type="button" className="quiet" onClick={() => { downloadFile(f).catch(e => alert(e.message)) }}>
            <Icon name="download" />{f.name}
          </button>
          <span className="muted small">{Math.max(1, Math.round(f.size / 1024))} KB</span>
          {onRemove && <button type="button" className="quiet danger-quiet small" aria-label={t('Remove')} onClick={() => onRemove(f)}>×</button>}
        </li>
      ))}
    </ul>
  )
}

// ---------------------------------------------------------------------------
// Form
// ---------------------------------------------------------------------------

function initial(entity: EntityDef, record?: Rec | null, defaults?: Record<string, any>) {
  const out: Record<string, any> = {}
  for (const f of entity.fields) {
    if (f.readonly) continue
    const v = record ? record[f.name] : (defaults?.[f.name] ?? f.default)
    out[f.name] = v === null || v === undefined ? (f.type === 'items' || f.type === 'files' || f.type === 'multiselect' ? [] : f.type === 'json' ? {} : '') : v
  }
  return out
}

export function RecordForm({ entity, record, defaults, onSaved, onCancel, hide = [] }: {
  entity: EntityDef, record?: Rec | null, defaults?: Record<string, any>, onSaved: (r: Rec) => void, onCancel?: () => void, hide?: string[]
}) {
  const [data, setData] = useState<Record<string, any>>(() => initial(entity, record, defaults))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const set = (name: string, v: any) => setData(prev => ({ ...prev, [name]: v }))
  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      const body: Record<string, any> = { ...data }
      if (record?.updated_at) body.expected_updated_at = record.updated_at
      const saved = await saveRecord(entity.name, body, entity.singleton ? undefined : record?.id)
      invalidate(entity.name)
      onSaved(saved)
    } catch (err: any) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }
  const fields = entity.fields.filter(f => !f.readonly && !hide.includes(f.name))
  const wide = (f: FieldDef) => ['longtext', 'items', 'files', 'json', 'multiselect'].includes(f.type)
  return (
    <form onSubmit={submit} className="card" noValidate>
      <div className="fields">
        {fields.map(f => (
          <div key={f.name} className={`field${wide(f) ? ' wide' : ''}`}>
            {f.type === 'bool' ? (
              <label className="checkbox"><FieldInput f={f} value={data[f.name]} record={data} onChange={v => set(f.name, v)} id={`r-${f.name}`} />{t(f.label)}</label>
            ) : (
              <>
                <label htmlFor={`r-${f.name}`}>{t(f.label)}{f.required && f.name !== entity.number_field && <span className="tag-req">{t('required')}</span>}</label>
                <FieldInput f={f} value={data[f.name]} record={data} onChange={v => set(f.name, v)} id={`r-${f.name}`} />
              </>
            )}
            {f.help && <p className="help">{t(f.help)}</p>}
          </div>
        ))}
      </div>
      {error && <p className="notice error" role="alert">{error}</p>}
      <div className="actions" style={{ marginTop: '1rem' }}>
        <button type="submit" className="primary" disabled={busy}>{busy ? t('Saving…') : t('Save')}</button>
        {onCancel && <button type="button" onClick={onCancel} disabled={busy}>{t('Cancel')}</button>}
      </div>
    </form>
  )
}

// ---------------------------------------------------------------------------
// Read-only view
// ---------------------------------------------------------------------------

export function RecordFields({ entity, record, hide = [] }: { entity: EntityDef, record: Rec, hide?: string[] }) {
  const simple = entity.fields.filter(f => !['items', 'files', 'json', 'longtext'].includes(f.type) && !hide.includes(f.name) && f.name in record)
  const long = entity.fields.filter(f => f.type === 'longtext' && record[f.name] && !hide.includes(f.name))
  const items = entity.fields.filter(f => f.type === 'items' && !hide.includes(f.name) && (record[f.name] || []).length)
  const json = entity.fields.filter(f => f.type === 'json' && f.variants && !hide.includes(f.name))
  const files = entity.fields.filter(f => f.type === 'files' && !hide.includes(f.name))
  return (
    <div className="record-view">
      <dl className="facts-grid">
        {simple.map(f => (
          <div key={f.name}><dt>{t(f.label)}</dt><dd>{display(f, record[f.name])}</dd></div>
        ))}
        {json.map(f => (f.variants?.[record[f.variants_by || '']] || []).map(s => (
          <div key={s.name}><dt>{t(s.label)}</dt><dd>{display(s, (record[f.name] || {})[s.name])}</dd></div>
        )))}
      </dl>
      {long.map(f => (
        <section key={f.name} style={{ marginTop: '1rem' }}>
          <h3>{t(f.label)}</h3>
          <p style={{ whiteSpace: 'pre-wrap', margin: 0 }}>{record[f.name]}</p>
        </section>
      ))}
      {items.map(f => (
        <section key={f.name} style={{ marginTop: '1rem' }}>
          <h3>{t(f.label)}</h3>
          <div className="table-wrap">
            <table className="data-table">
              <thead><tr>{(f.fields || []).filter(s => s.type !== 'ref').map(s => <th key={s.name} className={['number', 'money', 'percent'].includes(s.type) ? 'num' : ''}>{t(s.label)}</th>)}</tr></thead>
              <tbody>
                {(record[f.name] as any[]).slice(0, 300).map((row, i) => (
                  <tr key={i}>{(f.fields || []).filter(s => s.type !== 'ref').map(s => <td key={s.name} className={['number', 'money', 'percent'].includes(s.type) ? 'num' : ''}>{display(s, row[s.name])}</td>)}</tr>
                ))}
              </tbody>
            </table>
          </div>
          {(record[f.name] as any[]).length > 300 && <p className="muted small">{t('Showing the first 300 rows.')}</p>}
        </section>
      ))}
      {files.map(f => (
        <section key={f.name} style={{ marginTop: '1rem' }}>
          <h3>{t(f.label)}</h3>
          <FileList files={record[f.name] || []} />
        </section>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// A page: list, open a record, create / edit / delete
// ---------------------------------------------------------------------------

export type DetailExtra = (record: Rec, reload: () => void) => ReactNode

export function RecordsPage({ entityName, description, defaults, filter, extra, columns, back, title, hideInForm }: {
  entityName: string
  description?: string
  defaults?: Record<string, any>
  filter?: (r: Rec) => boolean
  extra?: DetailExtra
  columns?: string[]
  back?: { label: string, onClick: () => void }
  title?: string
  hideInForm?: string[]
}) {
  const schemas = useSchemas()
  const entity = schemas?.[entityName]
  const [rows, setRows] = useState<Rec[] | null>(null)
  const [error, setError] = useState('')
  const [open, setOpen] = useState<Rec | null>(null)
  const [mode, setMode] = useState<'list' | 'view' | 'edit' | 'new'>('list')
  const [search, setSearch] = useState('')
  const [notice, setNotice] = useState('')

  const load = () => {
    setError('')
    listRecords(entityName).then(setRows).catch(e => setError(e.message))
  }
  useEffect(load, [entityName])

  const shown = useMemo(() => {
    const q = search.trim().toLowerCase()
    return (rows || []).filter(r => (!filter || filter(r)) && (!q || JSON.stringify(r).toLowerCase().includes(q)))
  }, [rows, search, filter])

  if (!entity) return <p className="muted">{t('Loading…')}</p>
  if (!entity.can_read) return <p className="notice warn">{t('Your role cannot open this page')}</p>

  const cols = (columns ? columns.map(c => entity.fields.find(f => f.name === c)) : entity.fields.filter(f => f.list)).filter(Boolean) as FieldDef[]
  const heading = title || t(entity.label)
  const backButton = back && <button type="button" className="quiet back" onClick={back.onClick}><Icon name="back" />{back.label}</button>
  const toList = () => { setMode('list'); setOpen(null) }
  const listBack = <button type="button" className="quiet back" onClick={toList}><Icon name="back" />{heading}</button>

  if (mode === 'new' || (mode === 'edit' && open)) {
    return (
      <div>
        <PageHead back={listBack} title={mode === 'new' ? t('New {what}', { what: t(entity.label_one).toLowerCase() }) : t('Edit {what}', { what: String(open?.[entity.title] ?? '') })} />
        <RecordForm entity={entity} record={mode === 'edit' ? open : null} defaults={defaults} hide={hideInForm}
          onCancel={() => setMode(open ? 'view' : 'list')}
          onSaved={r => { setOpen(r); setMode('view'); setNotice(t('Saved.')); load() }} />
      </div>
    )
  }

  if (mode === 'view' && open) {
    const remove = async () => {
      if (!window.confirm(t('Delete {what}?', { what: String(open[entity.title] ?? '') }))) return
      try {
        await deleteRecord(entityName, open.id)
        invalidate(entityName)
        setNotice(t('Deleted'))
        toList()
        load()
      } catch (e: any) {
        setError(e.message)
      }
    }
    const reload = () => { listRecords(entityName).then(list => { setRows(list); const fresh = list.find(r => r.id === open.id); if (fresh) setOpen(fresh) }) }
    return (
      <div>
        <PageHead back={listBack} title={String(open[entity.title] ?? t(entity.label_one))}
          description={t(entity.label_one)}
          actions={open._can_edit && <>
            <button type="button" className="quiet danger-quiet" onClick={remove}>{t('Delete')}</button>
            <button type="button" className="primary" onClick={() => { setMode('edit'); setNotice('') }}>{t('Edit')}</button>
          </>} />
        {notice && <p className="notice ok" role="status">{notice}</p>}
        {error && <p className="notice error">{error}</p>}
        {extra?.(open, reload)}
        <section className="card"><RecordFields entity={entity} record={open} /></section>
      </div>
    )
  }

  return (
    <div>
      <PageHead back={backButton} title={heading} description={description}
        actions={entity.can_create && <button type="button" className="primary" onClick={() => { setMode('new'); setNotice('') }}><Icon name="plus" />{t('New {what}', { what: t(entity.label_one).toLowerCase() })}</button>} />
      {notice && <p className="notice ok" role="status">{notice}</p>}
      {error && <p className="notice error">{error}</p>}
      <div className="toolbar" style={{ marginTop: 0 }}>
        <input type="search" value={search} onChange={e => setSearch(e.target.value)} placeholder={t('Search')} aria-label={t('Search')} />
      </div>
      {!rows ? <p className="muted">{t('Loading…')}</p> : !shown.length ? (
        <div className="card">
          <p style={{ marginTop: 0 }}>{rows.length ? t('Nothing found.') : t('Nothing here yet.')}</p>
          {!rows.length && entity.can_create && <button type="button" className="primary" onClick={() => setMode('new')}>{t('New {what}', { what: t(entity.label_one).toLowerCase() })}</button>}
        </div>
      ) : (
        <RecordTable entity={entity} rows={shown} cols={cols} onOpen={r => { setOpen(r); setMode('view'); setNotice('') }} />
      )}
    </div>
  )
}

export function RecordTable({ entity, rows, cols, onOpen }: { entity: EntityDef, rows: Rec[], cols?: FieldDef[], onOpen: (r: Rec) => void }) {
  const columns = cols || entity.fields.filter(f => f.list)
  const numeric = (f: FieldDef) => ['money', 'number', 'percent', 'int'].includes(f.type)
  return (
    <div className="table-wrap">
      <table className="bh-table record-table">
        <thead><tr>{columns.map(f => <th key={f.name} className={numeric(f) ? 'num' : ''}>{t(f.label)}</th>)}</tr></thead>
        <tbody>
          {rows.map(r => (
            <tr key={r.id} onClick={() => onOpen(r)}>
              {columns.map((f, i) => (
                <td key={f.name} className={numeric(f) ? 'num nowrap' : ''}>
                  {i === 0 ? (
                    <button type="button" className="quiet" style={{ padding: 0, minHeight: 0, color: 'inherit' }} onClick={e => { e.stopPropagation(); onOpen(r) }}>
                      <span className="bh-id">{display(f, r[f.name])}</span>
                    </button>
                  ) : f.type === 'select' && STATUS_TONE[String(r[f.name])] !== undefined ? (
                    <span className={`status ${STATUS_TONE[String(r[f.name])]}`}>{display(f, r[f.name])}</span>
                  ) : display(f, r[f.name])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export const STATUS_TONE: Record<string, string> = {
  tender: 'active', contract: 'active', ongoing: 'active', reporting: 'warn', completed: 'ok', cancelled: '',
  draft: '', sent: 'active', won: 'ok', lost: '', signed: 'ok', amended: 'warn', closed: '',
  received: '', testing: 'warn', done: 'ok', review: 'warn', approved: 'ok',
  unpaid: 'warn', partial: 'warn', paid: 'ok', overdue: 'bad',
}

export function Labeled({ label, children }: { label: string, children: ReactNode }) {
  return <div><dt>{label}</dt><dd>{children}</dd></div>
}

export { Fragment }
