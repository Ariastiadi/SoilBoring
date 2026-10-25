/**
 * Commercial operations (projects, clients, quotations, contracts), field work beyond
 * boreholes (CPT, geophysics, geology, survey), laboratory, reports and finance.
 */
import { ReactNode, useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { getDepthOverview, listRecords, listReports, type DepthOverview, type FieldDef, type Rec } from '../api'
import { lang, t, translateServer } from '../i18n'
import { useNav, type Intent, type TabKey } from '../nav'
import {
  RecordFields, RecordForm, RecordsPage, RecordTable, STATUS_TONE, display, invalidate, money, number, optionLabel,
  useList, useSchemas,
} from '../records'
import { Icon, PageHead, formatDate, todayIso } from '../ui'

const COMMERCIAL_ROLES = ['admin', 'manager', 'finance']

// ---------------------------------------------------------------------------
// Projects: the hub of commercial operations
// ---------------------------------------------------------------------------

const STEPS = ['tender', 'contract', 'ongoing', 'reporting', 'completed']

function Stepper({ status }: { status: string }) {
  const index = STEPS.indexOf(status)
  return (
    <ol className="stepper" aria-label={t('Project stage')}>
      {STEPS.map((s, i) => (
        <li key={s} className={i < index ? 'done' : i === index ? 'current' : ''} aria-current={i === index ? 'step' : undefined}>
          <span className="step-no">{i + 1}</span>{t(STEP_LABELS[s])}
        </li>
      ))}
      {status === 'cancelled' && <li className="current">{t('Cancelled')}</li>}
    </ol>
  )
}
const STEP_LABELS: Record<string, string> = { tender: 'Tender', contract: 'Contract', ongoing: 'Ongoing', reporting: 'Reporting', completed: 'Completed' }

type Section = { key: string, title: string, tab: TabKey, rows: Rec[], entity: string, cols: string[], add?: Record<string, unknown> }

function HubSection({ s }: { s: Section }) {
  const { go } = useNav()
  const schemas = useSchemas()
  const entity = schemas?.[s.entity]
  if (!entity || !entity.can_read) return null
  const cols = s.cols.map(c => entity.fields.find(f => f.name === c)).filter(Boolean) as FieldDef[]
  return (
    <section className="hub-section">
      <div className="hub-head">
        <h3>{t(s.title)} <span className="muted">{s.rows.length}</span></h3>
        {entity.can_create && s.add && (
          <button type="button" className="small" onClick={() => go(s.tab, { newWith: s.add })}><Icon name="plus" />{t('Add')}</button>
        )}
      </div>
      {s.rows.length > 0 && <RecordTable entity={entity} rows={s.rows} cols={cols} onOpen={r => go(s.tab, { open: r.id })} />}
    </section>
  )
}

function ProjectHub({ project }: { project: Rec }) {
  const { go, role } = useNav()
  const commercial = COMMERCIAL_ROLES.includes(role)
  const [data, setData] = useState<Record<string, Rec[]> | null>(null)
  const [boreholes, setBoreholes] = useState<Rec[]>([])
  const [overview, setOverview] = useState<DepthOverview>({})

  useEffect(() => {
    let active = true
    const entities = ['cpt', 'field_activities', 'analyses', 'project_reports', ...(commercial ? ['quotes', 'contracts', 'invoices'] : [])]
    Promise.all([
      listReports().catch(() => []),
      getDepthOverview().catch(() => ({})),
      listRecords('lab_tests').catch(() => []),
      ...entities.map(e => listRecords(e, project.id).catch(() => [])),
    ]).then(([logs, ov, lab, ...lists]) => {
      if (!active) return
      const mine = (logs as Rec[]).filter(r => String(r.ProjectName || '').trim().toLowerCase() === String(project.name || '').trim().toLowerCase())
      const ids = new Set(mine.map(r => String(r.BoreholeID).toLowerCase()))
      const out: Record<string, Rec[]> = { lab_tests: (lab as Rec[]).filter(t2 => ids.has(String(t2.borehole_id || '').toLowerCase())) }
      entities.forEach((e, i) => { out[e] = lists[i] as Rec[] })
      setBoreholes(mine)
      setOverview(ov as DepthOverview)
      setData(out)
    })
    return () => { active = false }
  }, [project.id, project.name, commercial])

  if (!data) return <p className="muted">{t('Loading…')}</p>
  const invoiced = (data.invoices || []).filter(i => i.status !== 'cancelled')
  const total = invoiced.reduce((s, i) => s + (i.total || 0), 0)
  const paid = invoiced.reduce((s, i) => s + (i.paid || 0), 0)
  const outstanding = invoiced.reduce((s, i) => s + (i.outstanding || 0), 0)
  const meters = boreholes.reduce((s, r) => s + (parseFloat(r.FinalDepth_m) || 0), 0)
  const withDepth = boreholes.filter(r => (overview[r.BoreholeID]?.layers.length || 0) > 0).length

  const sections: Section[] = [
    { key: 'cpt', title: 'CPT / sondir', tab: 'cpt', entity: 'cpt', rows: data.cpt, cols: ['test_id', 'date', 'final_depth'], add: { project_id: project.id } },
    { key: 'fa', title: 'Other field work', tab: 'fieldwork', entity: 'field_activities', rows: data.field_activities, cols: ['code', 'type', 'method', 'date'], add: { project_id: project.id } },
    { key: 'lab', title: 'Laboratory tests', tab: 'lab', entity: 'lab_tests', rows: data.lab_tests, cols: ['sample_ref', 'borehole_id', 'test_type', 'status'] },
    { key: 'an', title: 'Engineering analyses', tab: 'analyses', entity: 'analyses', rows: data.analyses, cols: ['title', 'type', 'summary'], add: { project_id: project.id } },
    { key: 'rep', title: 'Reports & recommendations', tab: 'reports', entity: 'project_reports', rows: data.project_reports, cols: ['number', 'title', 'status', 'date'], add: { project_id: project.id, title: t('Soil investigation report') + ' – ' + project.name, date: todayIso() } },
    ...(commercial ? [
      { key: 'q', title: 'Quotations', tab: 'quotes' as TabKey, entity: 'quotes', rows: data.quotes, cols: ['number', 'date', 'status', 'total'], add: { project_id: project.id, date: todayIso() } },
      { key: 'c', title: 'Contracts', tab: 'contracts' as TabKey, entity: 'contracts', rows: data.contracts, cols: ['number', 'date', 'status', 'value'], add: { project_id: project.id } },
      { key: 'i', title: 'Invoices', tab: 'invoices' as TabKey, entity: 'invoices', rows: data.invoices, cols: ['number', 'date', 'payment_status', 'total', 'outstanding'], add: { project_id: project.id, date: todayIso() } },
    ] : []),
  ]

  return (
    <div className="hub">
      <Stepper status={project.status} />
      <div className="kpis" style={{ margin: '1rem 0' }}>
        <div className="kpi"><h4>{t('Boreholes')}</h4><p>{boreholes.length}</p></div>
        <div className="kpi"><h4>{t('Metres drilled')}</h4><p>{number(Math.round(meters * 10) / 10)}</p></div>
        <div className="kpi"><h4>{t('With depth data')}</h4><p>{withDepth}/{boreholes.length}</p></div>
        <div className="kpi"><h4>{t('Lab tests done')}</h4><p>{data.lab_tests.filter(x => x.status === 'done').length}/{data.lab_tests.length}</p></div>
        {commercial && <>
          <div className="kpi"><h4>{t('Invoiced')}</h4><p className="kpi-money">{money(total)}</p></div>
          <div className="kpi"><h4>{t('Outstanding')}</h4><p className="kpi-money">{money(outstanding)}</p><span className="muted small">{t('Paid {amount}', { amount: money(paid) })}</span></div>
        </>}
      </div>
      <section className="hub-section">
        <div className="hub-head">
          <h3>{t('Boreholes')} <span className="muted">{boreholes.length}</span></h3>
          <button type="button" className="small" onClick={() => go('new', { newWith: { ProjectName: project.name } })}><Icon name="plus" />{t('Add')}</button>
        </div>
        {boreholes.length > 0 ? (
          <div className="table-wrap">
            <table className="data-table">
              <thead><tr><th>{t('Borehole')}</th><th>{t('Dates')}</th><th className="num">{t('Depth')}</th><th>{t('Status')}</th></tr></thead>
              <tbody>
                {boreholes.map(r => {
                  const ov = overview[r.BoreholeID]
                  return (
                    <tr key={r.BoreholeID} className="clickable" onClick={() => go('boreholes', { borehole: r.BoreholeID })}>
                      <td><strong>{r.BoreholeID}</strong><div className="bh-sub">{r.SiteName}</div></td>
                      <td className="nowrap">{formatDate(r.StartDate)}</td>
                      <td className="num">{number(r.FinalDepth_m)} m</td>
                      <td>{ov?.layers.length ? t('{n} layers, {m} SPT', { n: ov.layers.length, m: ov.spt.length }) : t('No depth data yet')}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        ) : <p className="muted small">{t('Borehole logs whose Project is "{name}" appear here.', { name: project.name })}</p>}
      </section>
      {sections.map(s => <HubSection key={s.key} s={s} />)}
    </div>
  )
}

export function ProjectsPage({ intent }: { intent?: Intent }) {
  const [status, setStatus] = useState('active')
  const filter = useMemo(() => (r: Rec) => status === 'all' || (status === 'active' ? !['completed', 'cancelled'].includes(r.status) : r.status === status), [status])
  return (
    <RecordsPage entityName="projects" openId={intent?.open} startNew={intent?.newWith}
      description={t('Every project from tender to final report: field work, laboratory, analyses, reports, contracts and invoices in one place.')}
      filter={filter}
      defaults={{ status: 'tender', start_date: todayIso() }}
      toolbar={<Segments value={status} onChange={setStatus} label={t('Show projects')} options={[['active', 'Active'], ['tender', 'Tender'], ['completed', 'Completed'], ['all', 'All']]} />}
      extra={r => <ProjectHub project={r} />} />
  )
}

function Segments({ value, onChange, options, label }: { value: string, onChange: (v: string) => void, options: Array<[string, string]>, label: string }) {
  return (
    <div className="segmented" role="group" aria-label={label}>
      {options.map(([k, l]) => <button key={k} type="button" aria-pressed={value === k} onClick={() => onChange(k)}>{t(l)}</button>)}
    </div>
  )
}

export function ClientsPage({ intent }: { intent?: Intent }) {
  const projects = useList('projects')
  const { go } = useNav()
  const schemas = useSchemas()
  return (
    <RecordsPage entityName="clients" openId={intent?.open} startNew={intent?.newWith}
      description={t('Contractors, state-owned companies, private owners and government agencies you work for.')}
      extra={r => {
        const mine = (projects || []).filter(p => p.client_id === r.id)
        const entity = schemas?.projects
        return (
          <section className="hub-section">
            <div className="hub-head">
              <h3>{t('Projects')} <span className="muted">{mine.length}</span></h3>
              {entity?.can_create && <button type="button" className="small" onClick={() => go('projects', { newWith: { client_id: r.id } })}><Icon name="plus" />{t('Add')}</button>}
            </div>
            {entity && mine.length > 0 && <RecordTable entity={entity} rows={mine} cols={entity.fields.filter(f => ['code', 'name', 'status', 'start_date'].includes(f.name))} onOpen={p => go('projects', { open: p.id })} />}
          </section>
        )
      }} />
  )
}

// ---------------------------------------------------------------------------
// Printable documents (quotation, invoice, report)
// ---------------------------------------------------------------------------

function useSettings() {
  const rows = useList('settings')
  return rows?.[0] || null
}

function PrintSheet({ title, onClose, children }: { title: string, onClose: () => void, children: ReactNode }) {
  useEffect(() => {
    document.body.classList.add('printing-borelog')
    const before = document.title
    document.title = title
    return () => { document.body.classList.remove('printing-borelog'); document.title = before }
  }, [title])
  return createPortal(
    <div className="borelog-root">
      <div className="borelog-toolbar no-print">
        <button type="button" className="primary" onClick={() => window.print()}>{t('Print / save as PDF')}</button>
        <button type="button" onClick={onClose}>{t('Close')}</button>
        <span>{t('In the print window choose "Save as PDF" and paper size A4.')}</span>
      </div>
      <article className="borelog-page doc-page">{children}</article>
    </div>,
    document.body,
  )
}

function Letterhead({ settings, title, number, date }: { settings: Rec | null, title: string, number?: string, date?: string }) {
  return (
    <header className="doc-head">
      <div>
        <div className="doc-company">{settings?.company_name || t('Company name not set')}</div>
        <div className="doc-small" style={{ whiteSpace: 'pre-wrap' }}>{settings?.address}</div>
        <div className="doc-small">{[settings?.phone, settings?.email].filter(Boolean).join('  ')}</div>
        {settings?.npwp && <div className="doc-small">NPWP {settings.npwp}</div>}
      </div>
      <div style={{ textAlign: 'right' }}>
        <div className="doc-title">{title}</div>
        {number && <div><strong>{number}</strong></div>}
        {date && <div>{formatDate(date)}</div>}
      </div>
    </header>
  )
}

const ONES_ID = ['', 'satu', 'dua', 'tiga', 'empat', 'lima', 'enam', 'tujuh', 'delapan', 'sembilan', 'sepuluh', 'sebelas']
function terbilang(n: number): string {
  n = Math.floor(Math.abs(n))
  if (n < 12) return ONES_ID[n]
  if (n < 20) return `${terbilang(n - 10)} belas`
  if (n < 100) return `${terbilang(Math.floor(n / 10))} puluh ${terbilang(n % 10)}`.trim()
  if (n < 200) return `seratus ${terbilang(n - 100)}`.trim()
  if (n < 1000) return `${terbilang(Math.floor(n / 100))} ratus ${terbilang(n % 100)}`.trim()
  if (n < 2000) return `seribu ${terbilang(n - 1000)}`.trim()
  const units: Array<[number, string]> = [[1e12, 'triliun'], [1e9, 'miliar'], [1e6, 'juta'], [1e3, 'ribu']]
  for (const [v, w] of units) if (n >= v) return `${terbilang(Math.floor(n / v))} ${w} ${terbilang(n % v)}`.trim()
  return ''
}
const ONES_EN = ['', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten', 'eleven', 'twelve', 'thirteen', 'fourteen', 'fifteen', 'sixteen', 'seventeen', 'eighteen', 'nineteen']
const TENS_EN = ['', '', 'twenty', 'thirty', 'forty', 'fifty', 'sixty', 'seventy', 'eighty', 'ninety']
function inWords(n: number): string {
  n = Math.floor(Math.abs(n))
  if (n < 20) return ONES_EN[n]
  if (n < 100) return `${TENS_EN[Math.floor(n / 10)]}${n % 10 ? '-' + ONES_EN[n % 10] : ''}`
  if (n < 1000) return `${ONES_EN[Math.floor(n / 100)]} hundred ${inWords(n % 100)}`.trim()
  const units: Array<[number, string]> = [[1e12, 'trillion'], [1e9, 'billion'], [1e6, 'million'], [1e3, 'thousand']]
  for (const [v, w] of units) if (n >= v) return `${inWords(Math.floor(n / v))} ${w} ${inWords(n % v)}`.trim()
  return ''
}
export const amountInWords = (n: number) => {
  if (!n) return lang() === 'id' ? 'nol rupiah' : 'zero rupiah'
  const words = lang() === 'id' ? terbilang(n) : inWords(n)
  return `${words} rupiah`.replace(/\s+/g, ' ')
}

function ItemsTable({ items }: { items: Rec[] }) {
  return (
    <table className="doc-table">
      <thead><tr><th>#</th><th>{t('Description')}</th><th>{t('Unit')}</th><th className="num">{t('Quantity')}</th><th className="num">{t('Unit price')}</th><th className="num">{t('Amount')}</th></tr></thead>
      <tbody>
        {items.map((r, i) => (
          <tr key={i}><td>{i + 1}</td><td>{r.description}</td><td>{r.unit}</td><td className="num">{number(r.qty)}</td><td className="num">{money(r.unit_price)}</td><td className="num">{money((r.qty || 0) * (r.unit_price || 0))}</td></tr>
        ))}
      </tbody>
    </table>
  )
}

function Signature({ settings, place }: { settings: Rec | null, place?: string }) {
  return (
    <div className="doc-sign">
      <div>{place ? `${place}, ` : ''}{formatDate(todayIso())}</div>
      <div>{settings?.company_name}</div>
      <div className="doc-sign-space" />
      <div><strong>{settings?.signatory || '……………………'}</strong></div>
      <div>{settings?.signatory_title}</div>
    </div>
  )
}

function ProjectLine({ projectId }: { projectId: string }) {
  const projects = useList('projects')
  const clients = useList('clients')
  const p = projects?.find(x => x.id === projectId)
  const c = clients?.find(x => x.id === p?.client_id)
  return (
    <div className="doc-to">
      <div className="doc-small">{t('Addressed to')}</div>
      <div><strong>{c?.name || '–'}</strong></div>
      {c?.address && <div className="doc-small" style={{ whiteSpace: 'pre-wrap' }}>{c.address}</div>}
      {c?.contact_person && <div className="doc-small">{t('Attn.')} {c.contact_person}</div>}
      <div style={{ marginTop: '2mm' }}>{t('Project')}: <strong>{p ? `${p.name} (${p.code})` : '–'}</strong></div>
    </div>
  )
}

function QuoteSheet({ quote, onClose }: { quote: Rec, onClose: () => void }) {
  const settings = useSettings()
  return (
    <PrintSheet title={quote.number} onClose={onClose}>
      <Letterhead settings={settings} title={t('Quotation')} number={quote.number} date={quote.date} />
      <ProjectLine projectId={quote.project_id} />
      <ItemsTable items={quote.items || []} />
      <table className="doc-totals">
        <tbody>
          {quote.discount_pct ? <tr><td>{t('Discount ({p}%)', { p: quote.discount_pct })}</td><td className="num">− {money((quote.items || []).reduce((s: number, r: Rec) => s + r.qty * r.unit_price, 0) - quote.subtotal)}</td></tr> : null}
          <tr><td>{t('Subtotal')}</td><td className="num">{money(quote.subtotal)}</td></tr>
          <tr><td>{t('VAT / PPN ({p}%)', { p: quote.tax_pct })}</td><td className="num">{money(quote.tax)}</td></tr>
          <tr className="doc-grand"><td>{t('Total')}</td><td className="num">{money(quote.total)}</td></tr>
        </tbody>
      </table>
      <p className="doc-small"><em>{amountInWords(quote.total)}</em></p>
      {quote.valid_until && <p>{t('This quotation is valid until {date}.', { date: formatDate(quote.valid_until) })}</p>}
      {quote.notes && <p style={{ whiteSpace: 'pre-wrap' }}>{quote.notes}</p>}
      <Signature settings={settings} />
    </PrintSheet>
  )
}

function InvoiceSheet({ invoice, onClose }: { invoice: Rec, onClose: () => void }) {
  const settings = useSettings()
  const due = invoice.total - invoice.pph
  return (
    <PrintSheet title={invoice.number} onClose={onClose}>
      <Letterhead settings={settings} title={t('Invoice')} number={invoice.number} date={invoice.date} />
      <ProjectLine projectId={invoice.project_id} />
      {invoice.term && <p>{t('Payment term')}: <strong>{invoice.term}</strong></p>}
      <ItemsTable items={invoice.items || []} />
      <table className="doc-totals">
        <tbody>
          <tr><td>{t('Subtotal')}</td><td className="num">{money(invoice.subtotal)}</td></tr>
          <tr><td>{t('VAT / PPN ({p}%)', { p: invoice.tax_pct })}</td><td className="num">{money(invoice.tax)}</td></tr>
          <tr className="doc-grand"><td>{t('Total')}</td><td className="num">{money(invoice.total)}</td></tr>
          {invoice.pph ? <tr><td>{t('Less PPh 23 ({p}%) withheld by the client', { p: invoice.pph_pct })}</td><td className="num">− {money(invoice.pph)}</td></tr> : null}
          {invoice.pph ? <tr className="doc-grand"><td>{t('Amount to transfer')}</td><td className="num">{money(due)}</td></tr> : null}
        </tbody>
      </table>
      <p className="doc-small"><em>{amountInWords(invoice.pph ? due : invoice.total)}</em></p>
      {invoice.due_date && <p>{t('Please pay by {date}.', { date: formatDate(invoice.due_date) })}</p>}
      {settings?.bank && <div className="doc-box"><div className="doc-small">{t('Payment to')}</div><div style={{ whiteSpace: 'pre-wrap' }}>{settings.bank}</div></div>}
      {invoice.notes && <p style={{ whiteSpace: 'pre-wrap' }}>{invoice.notes}</p>}
      <Signature settings={settings} />
    </PrintSheet>
  )
}

export function QuotesPage({ intent }: { intent?: Intent }) {
  const [printing, setPrinting] = useState<Rec | null>(null)
  return (
    <>
      <RecordsPage entityName="quotes" openId={intent?.open} startNew={intent?.newWith}
        description={t('Price offers for tenders, built from the price list; VAT and totals are calculated.')}
        defaults={{ date: todayIso(), status: 'draft', tax_pct: 11, discount_pct: 0 }}
        actions={r => <button type="button" onClick={() => setPrinting(r)}>{t('Print')}</button>} />
      {printing && <QuoteSheet quote={printing} onClose={() => setPrinting(null)} />}
    </>
  )
}

export function ContractsPage({ intent }: { intent?: Intent }) {
  const { go } = useNav()
  const invoices = useList('invoices')
  return (
    <RecordsPage entityName="contracts" openId={intent?.open} startNew={intent?.newWith}
      description={t('Signed work contracts with their payment terms and documents.')}
      defaults={{ status: 'draft', terms: [{ name: t('Down payment'), percent: 30 }, { name: t('Field work completed'), percent: 40 }, { name: t('Final report accepted'), percent: 30 }] }}
      extra={c => {
        const terms: Rec[] = c.terms || []
        const sum = terms.reduce((s, x) => s + (x.percent || 0), 0)
        const mine = (invoices || []).filter(i => i.contract_id === c.id && i.status !== 'cancelled')
        return (
          <section className="hub-section">
            <div className="hub-head"><h3>{t('Payment terms')}</h3></div>
            {Math.abs(sum - 100) > 0.01 && terms.length > 0 && <p className="notice warn">{t('The terms add up to {p}%, not 100%.', { p: number(sum) })}</p>}
            <div className="table-wrap">
              <table className="data-table">
                <thead><tr><th>{t('Term')}</th><th className="num">{t('Share (%)')}</th><th className="num">{t('Amount')}</th><th>{t('Invoice')}</th><th /></tr></thead>
                <tbody>
                  {terms.map((term, i) => {
                    const amount = Math.round((c.value || 0) * (term.percent || 0) / 100)
                    const inv = mine.find(x => x.term === term.name)
                    return (
                      <tr key={i}>
                        <td>{term.name}<div className="bh-sub">{term.condition}</div></td>
                        <td className="num">{number(term.percent)}</td>
                        <td className="num nowrap">{money(amount)}</td>
                        <td>{inv ? <button type="button" className="quiet" onClick={() => go('invoices', { open: inv.id })}>{inv.number} <span className={`status ${STATUS_TONE[inv.payment_status] || ''}`}>{optionLabelOf('payment_status', inv.payment_status)}</span></button> : <span className="muted">–</span>}</td>
                        <td>{!inv && (
                          <button type="button" className="small" onClick={() => go('invoices', { newWith: {
                            project_id: c.project_id, contract_id: c.id, term: term.name, date: todayIso(), status: 'draft', tax_pct: 11, pph_pct: 2,
                            items: [{ description: `${term.name} (${number(term.percent)}%) – ${c.number}`, unit: 'ls', qty: 1, unit_price: Math.round(amount / 1.11) }],
                          } })}>{t('Create invoice')}</button>
                        )}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
            <p className="help">{t('The contract value includes VAT; a new invoice takes the term amount without VAT as its price, so the total with 11% VAT matches the term.')}</p>
          </section>
        )
      }} />
  )
}

const optionLabelOf = (field: string, value: string) => {
  const map: Record<string, string> = { unpaid: 'Unpaid', partial: 'Partly paid', paid: 'Paid', overdue: 'Overdue' }
  return field === 'payment_status' ? t(map[value] || value) : value
}

export function InvoicesPage({ intent }: { intent?: Intent }) {
  const [printing, setPrinting] = useState<Rec | null>(null)
  const rows = useList('invoices')
  const outstanding = (rows || []).reduce((s, i) => s + (i.outstanding || 0), 0)
  const overdue = (rows || []).filter(i => i.payment_status === 'overdue')
  return (
    <>
      {!intent?.open && rows && rows.length > 0 && (
        <div className="kpis" style={{ marginBottom: '1rem' }}>
          <div className="kpi"><h4>{t('Outstanding')}</h4><p className="kpi-money">{money(outstanding)}</p></div>
          <div className="kpi"><h4>{t('Overdue invoices')}</h4><p>{overdue.length}</p></div>
          <div className="kpi"><h4>{t('Paid this year')}</h4><p className="kpi-money">{money((rows || []).reduce((s, i) => s + (i.payments || []).filter((p: Rec) => String(p.date).startsWith(todayIso().slice(0, 4))).reduce((a: number, p: Rec) => a + (p.amount || 0), 0), 0))}</p></div>
        </div>
      )}
      <RecordsPage entityName="invoices" openId={intent?.open} startNew={intent?.newWith}
        description={t('Invoices per contract term, payments received and what is still outstanding.')}
        defaults={{ date: todayIso(), status: 'draft', tax_pct: 11, pph_pct: 2 }}
        actions={r => <button type="button" onClick={() => setPrinting(r)}>{t('Print')}</button>} />
      {printing && <InvoiceSheet invoice={printing} onClose={() => setPrinting(null)} />}
    </>
  )
}

export function RatesPage({ intent }: { intent?: Intent }) {
  return <RecordsPage entityName="rates" openId={intent?.open} startNew={intent?.newWith}
    description={t('Unit prices used in quotations and invoices.')} />
}

export function SettingsPage() {
  const schemas = useSchemas()
  const rows = useList('settings')
  const [saved, setSaved] = useState(false)
  const entity = schemas?.settings
  if (!entity || !rows) return <p className="muted">{t('Loading…')}</p>
  return (
    <div style={{ maxWidth: 820 }}>
      <PageHead title={t('Company settings')} description={t('Printed on quotations, invoices and reports.')} />
      {saved && <p className="notice ok" role="status">{t('Saved.')}</p>}
      {entity.can_create ? (
        <RecordForm entity={entity} record={rows[0] || null} defaults={{ company_name: '' }} onSaved={() => { invalidate('settings'); setSaved(true) }} />
      ) : rows[0] ? <section className="card"><RecordFields entity={entity} record={rows[0]} /></section> : <p className="muted">{t('Nothing here yet.')}</p>}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Field work: CPT and other disciplines
// ---------------------------------------------------------------------------

const KG_CM2_TO_MPA = 0.0980665

function CptPlot({ test }: { test: Rec }) {
  const rows: Rec[] = (test.readings || []).filter((r: Rec) => r.depth !== null && r.qc !== null).sort((a: Rec, b: Rec) => a.depth - b.depth)
  if (rows.length < 2) return <p className="muted">{t('Enter at least two readings to draw the CPT profile.')}</p>
  const depth = Math.max(...rows.map(r => r.depth), test.final_depth || 0, 1)
  const H = Math.max(360, Math.min(900, depth * 30))
  const top = 34
  const y = (d: number) => top + (d / depth) * H
  const qcMax = Math.max(...rows.map(r => r.qc), 10)
  const qcScale = Math.ceil(qcMax / 50) * 50
  const fsRows = rows.filter(r => r.fs !== null && r.fs !== undefined)
  const fsMax = Math.max(...fsRows.map(r => r.fs), 0.5)
  const fsScale = Math.ceil(fsMax * 2) / 2
  const rf = fsRows.filter(r => r.qc > 0).map(r => ({ depth: r.depth, rf: (r.fs / r.qc) * 100 }))
  const panels = [
    { title: 'qc (kg/cm²)', x: 50, w: 240, max: qcScale, pts: rows.map(r => [r.qc, r.depth]) },
    { title: 'fs (kg/cm²)', x: 320, w: 160, max: fsScale, pts: fsRows.map(r => [r.fs, r.depth]) },
    { title: 'Rf (%)', x: 510, w: 140, max: 10, pts: rf.map(r => [Math.min(r.rf, 10), r.depth]) },
  ]
  const ticks: number[] = []
  const step = depth > 30 ? 5 : depth > 12 ? 2 : 1
  for (let d = 0; d <= depth + 1e-9; d += step) ticks.push(Number(d.toFixed(2)))
  return (
    <div className="profile-wrap">
      <svg className="profile-svg" width={680} height={top + H + 24} viewBox={`0 0 680 ${top + H + 24}`} role="img" aria-label={t('CPT profile')}>
        {ticks.map(d => (
          <g key={d}>
            <line x1={50} x2={650} y1={y(d)} y2={y(d)} stroke="#e1e4dd" />
            <text x={44} y={y(d) + 4} fontSize="11" textAnchor="end" fill="#545b61">{d}</text>
          </g>
        ))}
        {panels.map(p => (
          <g key={p.title}>
            <text x={p.x} y={14} fontSize="12" fontWeight="600" fill="#23282d">{p.title}</text>
            <rect x={p.x} y={top} width={p.w} height={H} fill="none" stroke="#cdd2c9" />
            {[0, 0.5, 1].map(f => <text key={f} x={p.x + p.w * f} y={top - 5} fontSize="10" textAnchor="middle" fill="#545b61">{number(p.max * f)}</text>)}
            <polyline fill="none" stroke={p.title.startsWith('qc') ? '#23282d' : '#1f5f8b'} strokeWidth="1.4"
              points={p.pts.map(([v, d]) => `${p.x + Math.min(1, v / p.max) * p.w},${y(d)}`).join(' ')} />
          </g>
        ))}
        {test.gw_depth !== null && test.gw_depth !== undefined && test.gw_depth <= depth && (
          <path d={`M${36} ${y(test.gw_depth) - 8} l10 0 l-5 8 z`} fill="#1f5f8b"><title>{t('Groundwater {d} m', { d: test.gw_depth })}</title></path>
        )}
      </svg>
      <p className="help">{t('Depth in m. Maximum qc {qc} kg/cm² ({mpa} MPa) at {d} m.', {
        qc: number(Math.max(...rows.map(r => r.qc))), mpa: number(Math.round(Math.max(...rows.map(r => r.qc)) * KG_CM2_TO_MPA * 100) / 100),
        d: number(rows.reduce((a, b) => (b.qc > a.qc ? b : a)).depth),
      })}</p>
    </div>
  )
}

export function CptPage({ intent }: { intent?: Intent }) {
  return <RecordsPage entityName="cpt" openId={intent?.open} startNew={intent?.newWith}
    description={t('Cone penetration tests (sondir): readings of cone resistance qc and sleeve friction fs with depth. Readings can be pasted from Excel.')}
    defaults={{ date: todayIso(), equipment: 'mechanical' }}
    extra={r => <section className="card" style={{ marginBottom: '1rem' }}><h3>{t('CPT profile')}</h3><CptPlot test={r} /></section>} />
}

export function FieldWorkPage({ intent }: { intent?: Intent }) {
  const [type, setType] = useState('all')
  const filter = useMemo(() => (r: Rec) => type === 'all' || r.type === type, [type])
  return (
    <RecordsPage entityName="field_activities" openId={intent?.open} startNew={intent?.newWith} filter={filter}
      description={t('Geophysics lines, geological observations and survey points, with their results and files.')}
      toolbar={<Segments value={type} onChange={setType} label={t('Discipline')} options={[['all', 'All'], ['geophysics', 'Geophysics'], ['geology', 'Geology'], ['survey', 'Geodesy & mapping']]} />}
      defaults={{ date: todayIso(), type: type === 'all' ? 'geophysics' : type }} />
  )
}

// ---------------------------------------------------------------------------
// Laboratory
// ---------------------------------------------------------------------------

export function LabPage({ intent }: { intent?: Intent }) {
  const [status, setStatus] = useState('open')
  const filter = useMemo(() => (r: Rec) => status === 'all' || (status === 'open' ? r.status !== 'done' : r.status === 'done'), [status])
  return (
    <RecordsPage entityName="lab_tests" openId={intent?.open} startNew={intent?.newWith} filter={filter}
      description={t('Samples from the boreholes and their test results. Results feed the engineering analyses.')}
      toolbar={<Segments value={status} onChange={setStatus} label={t('Show tests')} options={[['open', 'In progress'], ['done', 'Done'], ['all', 'All']]} />}
      defaults={{ received: todayIso(), status: 'received' }} />
  )
}

// ---------------------------------------------------------------------------
// Reports & recommendations
// ---------------------------------------------------------------------------

function ReportSheet({ report, onClose }: { report: Rec, onClose: () => void }) {
  const settings = useSettings()
  const schemas = useSchemas()
  const [d, setD] = useState<{ project?: Rec, client?: Rec, logs: Rec[], ov: DepthOverview, cpt: Rec[], fa: Rec[], lab: Rec[], an: Rec[] } | null>(null)
  useEffect(() => {
    Promise.all([
      listRecords('projects'), listRecords('clients'), listReports(), getDepthOverview().catch(() => ({})),
      listRecords('cpt', report.project_id), listRecords('field_activities', report.project_id), listRecords('lab_tests'), listRecords('analyses', report.project_id),
    ]).then(([projects, clients, logs, ov, cpt, fa, lab, an]) => {
      const project = projects.find(p => p.id === report.project_id)
      const client = clients.find(c => c.id === project?.client_id)
      const mine = (logs as Rec[]).filter(r => String(r.ProjectName || '').toLowerCase() === String(project?.name || '').toLowerCase())
      const ids = new Set(mine.map(r => String(r.BoreholeID).toLowerCase()))
      setD({ project, client, logs: mine, ov: ov as DepthOverview, cpt, fa, lab: lab.filter(x => ids.has(String(x.borehole_id).toLowerCase()) && x.status === 'done'), an })
    }).catch(() => setD({ logs: [], ov: {}, cpt: [], fa: [], lab: [], an: [] }))
  }, [report.project_id])
  const labDef = schemas?.lab_tests
  const resultsOf = (x: Rec) => {
    const f = labDef?.fields.find(ff => ff.name === 'results')
    const sub = f?.variants?.[x.test_type] || []
    return sub.filter(s => x.results?.[s.name] !== null && x.results?.[s.name] !== undefined).map(s => `${t(s.label)} ${display(s, x.results[s.name])}`).join('; ')
  }
  const testType = labDef?.fields.find(ff => ff.name === 'test_type')
  const anType = schemas?.analyses?.fields.find(ff => ff.name === 'type')
  const faMethod = schemas?.field_activities?.fields.find(ff => ff.name === 'method')
  let n = 0
  const h = (title: string) => <h2>{++n}. {title}</h2>
  return (
    <PrintSheet title={report.number} onClose={onClose}>
      <Letterhead settings={settings} title={t('Report')} number={report.number} date={report.date} />
      <h1 className="doc-h1">{report.title}</h1>
      <table className="doc-meta"><tbody>
        <tr><td>{t('Project')}</td><td>{d?.project ? `${d.project.name} (${d.project.code})` : '…'}</td></tr>
        <tr><td>{t('Client')}</td><td>{d?.client?.name || '–'}</td></tr>
        <tr><td>{t('Location')}</td><td>{d?.project?.location || '–'}</td></tr>
        <tr><td>{t('Status')}</td><td>{optionLabel(schemas!.project_reports.fields.find(f => f.name === 'status')!, report.status)}</td></tr>
      </tbody></table>
      {report.summary && <>{h(t('Summary'))}<p className="doc-text">{report.summary}</p></>}
      {report.scope && <>{h(t('Scope of work'))}<p className="doc-text">{report.scope}</p></>}
      {d && d.logs.length > 0 && <>
        {h(t('Boreholes'))}
        <table className="doc-table">
          <thead><tr><th>{t('Borehole')}</th><th>{t('Dates')}</th><th className="num">{t('Depth')}</th><th className="num">{t('Groundwater')}</th><th>USCS</th><th className="num">{t('Avg N')}</th><th>{t('Strata')}</th></tr></thead>
          <tbody>{d.logs.map(r => (
            <tr key={r.BoreholeID}><td className="nowrap">{r.BoreholeID}</td><td>{formatDate(r.StartDate)}</td><td className="num nowrap">{number(r.FinalDepth_m)} m</td><td className="num nowrap">{r.GroundwaterDepth_m ? `${number(r.GroundwaterDepth_m)} m` : '–'}</td><td>{r.USCS_Class}</td><td className="num">{r.Avg_SPT_N60 ? number(r.Avg_SPT_N60) : '–'}</td>
              <td>{(d.ov[r.BoreholeID]?.layers || []).map(l => `${l.top}–${l.base} m ${l.uscs}`).join('; ') || '–'}</td></tr>
          ))}</tbody>
        </table>
      </>}
      {d && d.cpt.length > 0 && <>
        {h(t('CPT / sondir'))}
        <table className="doc-table">
          <thead><tr><th>{t('Test ID')}</th><th>{t('Date')}</th><th className="num">{t('Final depth (m)')}</th><th className="num">{t('Max qc (kg/cm²)')}</th></tr></thead>
          <tbody>{d.cpt.map(c => <tr key={c.id}><td>{c.test_id}</td><td>{formatDate(c.date)}</td><td className="num">{number(c.final_depth)}</td><td className="num">{number(Math.max(0, ...(c.readings || []).map((r: Rec) => r.qc || 0)))}</td></tr>)}</tbody>
        </table>
      </>}
      {d && d.fa.length > 0 && <>
        {h(t('Other field work'))}
        <table className="doc-table">
          <thead><tr><th>{t('Line / point ID')}</th><th>{t('Method')}</th><th>{t('Date')}</th><th>{t('Results')}</th></tr></thead>
          <tbody>{d.fa.map(a => <tr key={a.id}><td>{a.code}</td><td>{faMethod ? optionLabel(faMethod, a.method) : a.method}</td><td>{formatDate(a.date)}</td><td style={{ whiteSpace: 'pre-wrap' }}>{a.results}</td></tr>)}</tbody>
        </table>
      </>}
      {d && d.lab.length > 0 && <>
        {h(t('Laboratory results'))}
        <table className="doc-table">
          <thead><tr><th>{t('Borehole')}</th><th>{t('Sample')}</th><th className="num">{t('Depth (m)')}</th><th>{t('Test')}</th><th>{t('Results')}</th></tr></thead>
          <tbody>{d.lab.map(x => <tr key={x.id}><td>{x.borehole_id}</td><td>{x.sample_ref}</td><td className="num">{number(x.depth_top)}{x.depth_base ? `–${number(x.depth_base)}` : ''}</td><td>{testType ? optionLabel(testType, x.test_type) : x.test_type}</td><td>{resultsOf(x)}</td></tr>)}</tbody>
        </table>
      </>}
      {d && d.an.length > 0 && <>
        {h(t('Engineering analyses'))}
        <table className="doc-table">
          <thead><tr><th>{t('Analysis')}</th><th>{t('Borehole')}</th><th>{t('Result')}</th></tr></thead>
          <tbody>{d.an.map(a => <tr key={a.id}><td>{a.title}<div className="doc-small">{anType ? optionLabel(anType, a.type) : a.type}</div></td><td>{a.borehole_id || '–'}</td><td>{translateServer(a.summary || '')}</td></tr>)}</tbody>
        </table>
        <p className="doc-small">{t('Methods: bearing capacity after Meyerhof/Vesic, pile capacity after Decourt (SPT), consolidation settlement with the 2:1 stress spread, liquefaction after Idriss & Boulanger (2014).')}</p>
      </>}
      {report.recommendations && <>{h(t('Recommendations'))}<p className="doc-text">{report.recommendations}</p></>}
      <div className="doc-approvals">
        {[['Prepared by', report.prepared_by], ['Reviewed by', report.reviewed_by], ['Approved by', report.approved_by]].map(([label, who]) => (
          <div key={label}><div className="doc-small">{t(label)}</div><div className="doc-sign-space" /><div>{who || '……………………'}</div></div>
        ))}
      </div>
      {settings?.report_footer && <p className="doc-small doc-footer">{settings.report_footer}</p>}
    </PrintSheet>
  )
}

export function ReportsPage({ intent }: { intent?: Intent }) {
  const [printing, setPrinting] = useState<Rec | null>(null)
  return (
    <>
      <RecordsPage entityName="project_reports" openId={intent?.open} startNew={intent?.newWith}
        description={t('The report to the client: it collects the boreholes, CPT, other field work, lab results and analyses of the project, with your summary and recommendations.')}
        defaults={{ date: todayIso(), status: 'draft' }}
        actions={r => <button type="button" onClick={() => setPrinting(r)}>{t('Print report')}</button>} />
      {printing && <ReportSheet report={printing} onClose={() => setPrinting(null)} />}
    </>
  )
}
