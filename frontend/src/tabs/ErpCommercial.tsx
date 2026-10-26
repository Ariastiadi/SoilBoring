/**
 * Commercial ERP pages (blueprint A.1): Pricing & Budgeting Decision with the project difficulty
 * index, client decision, weekly work plan with Gantt chart and S-curve, bank guarantee / SKBDN
 * requests, receivables with aging and NPAR, client cards, the pricing policy in the company
 * settings, and the commercial part of the management dashboard.
 *
 * The server calculates (backend/app/erp_commercial.py, /api/erp/commercial); these pages show
 * the results and give a live preview while a document is drafted.
 */
import { ReactNode, useEffect, useMemo, useState } from 'react'
import { apiGet, apiPost, type CalcResult, type FieldDef, type Rec } from '../api'
import { t } from '../i18n'
import { useNav, type Intent, type TabKey } from '../nav'
import {
  RecordFields, RecordForm, RecordsPage, STATUS_TONE, invalidate, money, number, optionLabel, useList, useSchemas,
  type FormLayout, type FormTools,
} from '../records'
import { DateInput, Icon, PageHead, ScrollTable, formatDate, todayIso } from '../ui'
import { ResultView } from '../worksheets'
import './erp-commercial.css'

// Status colours of the commercial records (only keys the shared table does not define yet).
const TONES: Record<string, string> = {
  issued: 'active', released: '', claimed: 'bad', expiring: 'warn', expired: 'bad', ok: 'ok', npar: 'bad', commercial: 'active',
  good: 'ok', watch: 'warn', poor: 'bad', new: '', spk: '', spmk: '', subcontract: '',
}
for (const [k, v] of Object.entries(TONES)) if (!(k in STATUS_TONE)) STATUS_TONE[k] = v

/** Suggested tab keys of these pages (the lead adds them to nav.ts). */
export const COMMERCIAL_TABS = {
  pbd: 'pbd', client_decisions: 'client_decisions', work_plans: 'work_plans', guarantees: 'guarantees',
  receivables: 'receivables', client_cards: 'client_cards', pricing_settings: 'pricing_settings',
} as const

function useGo() {
  const { go } = useNav()
  return (tab: string, intent?: Intent) => go(tab as TabKey, intent)
}

// ---------------------------------------------------------------------------
// Shared pieces
// ---------------------------------------------------------------------------

type Row = Record<string, any>
type Check = { level: 'info' | 'warn' | 'error', text: string, vars?: Record<string, string | number | null> }
type Factor = { key: string, factor: string, weight: number, levels: string[] }
export type PricingConfig = {
  factors: Factor[], factors_source: 'settings' | 'default'
  premiums: Array<{ index: number, premium_pct: number }>, premiums_source: 'settings' | 'default'
  approval_limits: Array<{ up_to: number | null, level: string }>
  max_cost_ratio_pct: number, default_margin_pct: number, npar_days: number, payment_days: number, guarantee_warning_days: number
  zones: Array<{ zone: string, no: number, provinces: string, index: number, codes: string[] }>
  province_zone: Record<string, string>, provinces: Array<[string, string]>, sections: Array<[string, string]>
}

let configPromise: Promise<PricingConfig> | null = null
function loadConfig(): Promise<PricingConfig> {
  if (!configPromise) configPromise = apiGet<PricingConfig>('/api/erp/commercial/config').catch(e => { configPromise = null; throw e })
  return configPromise
}
function useConfig(): PricingConfig | null {
  const [cfg, setCfg] = useState<PricingConfig | null>(null)
  useEffect(() => { let live = true; loadConfig().then(c => { if (live) setCfg(c) }).catch(() => undefined); return () => { live = false } }, [])
  return cfg
}

function useLive<T>(path: string | null, refresh: unknown = 0): { data: T | null, error: string } {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    let live = true
    if (!path) return
    setError('')
    apiGet<T>(path).then(d => { if (live) setData(d) }).catch(e => { if (live) setError(e.message) })
    return () => { live = false }
  }, [path, refresh])
  return { data, error }
}

const n = (v: unknown): number | null => {
  if (v === null || v === undefined || v === '') return null
  const x = Number(String(v).replace(',', '.'))
  return Number.isFinite(x) ? x : null
}
const pctText = (v: unknown) => (n(v) === null ? '–' : `${number(n(v))} %`)

function checkText(c: Check) {
  const vars: Record<string, string | number> = {}
  for (const [k, v] of Object.entries(c.vars || {})) vars[k] = k.endsWith('_idr') ? money(v) : typeof v === 'number' ? number(v) : String(v ?? '')
  return t(c.text, vars)
}

/** Remarks the server stored with a record ({level, text, vars}). */
export function CheckList({ checks }: { checks?: unknown }) {
  const list: Check[] = Array.isArray(checks) ? checks : []
  if (!list.length) return null
  const tone = list.some(c => c.level === 'error') ? 'error' : list.some(c => c.level === 'warn') ? 'warn' : ''
  return (
    <div className={`notice ${tone} ec-checks`} role="status">
      <strong>{t('Checks')}</strong>
      <ul>{list.map((c, i) => <li key={i} className={`ec-${c.level}`}>{checkText(c)}</li>)}</ul>
    </div>
  )
}

function Kpi({ label, value, sub, wide }: { label: string, value: ReactNode, sub?: ReactNode, wide?: boolean }) {
  return <div className="kpi"><h4>{label}</h4><p className={wide ? 'kpi-money' : undefined}>{value}</p>{sub && <span className="muted small">{sub}</span>}</div>
}

function Tone({ value, children }: { value: string, children: ReactNode }) {
  return <span className={`status ${STATUS_TONE[value] ?? ''}`}>{children}</span>
}

function useOption(entity: string, field: string, sub?: string) {
  const schemas = useSchemas()
  return (value: unknown) => {
    const top = schemas?.[entity]?.fields.find(f => f.name === field)
    const f: FieldDef | undefined = sub ? top?.fields?.find(s => s.name === sub) : top
    return f ? optionLabel(f, value) : String(value ?? '')
  }
}

/** A calculation result without some of its tables (those the page draws itself). */
function withoutTables(result: CalcResult | undefined, titles: string[]): CalcResult | undefined {
  if (!result) return result
  return { ...result, tables: (result.tables || []).filter(tb => !titles.includes(tb.title)) }
}

const RATING: Record<string, string> = { good: 'Pays on time', watch: 'Watch', poor: 'Poor payer', new: 'No payment history yet' }

// ---------------------------------------------------------------------------
// A.1.3 Project difficulty index (scored inside the PBD)
// ---------------------------------------------------------------------------

function weightedIndex(factors: Factor[], scores: Record<string, number | null>) {
  let sw = 0, sum = 0, manual = 0
  for (const f of factors) {
    const s = scores[f.key]
    if (s === null || s === undefined || !(f.weight > 0)) continue
    sw += f.weight
    sum += f.weight * s
    if (f.key !== 'zone') manual++
  }
  if (!manual || sw <= 0) return { score: null as number | null, index: null as number | null }
  const avg = Math.round((sum / sw) * 1e6) / 1e6
  return { score: Math.round(avg * 100) / 100, index: Math.max(1, Math.min(5, Math.floor(avg + 0.5))) }
}

function zoneOf(data: Record<string, any>, config: PricingConfig, projects: Rec[] | null) {
  const project = projects?.find(p => p.id === data.project_id)
  return String(data.zone || config.province_zone[data.province] || config.province_zone[project?.province] || '')
}

function DifficultyEditor({ data, setData, config, readOnly }: {
  data: Record<string, any>, setData?: (u: (p: Record<string, any>) => Record<string, any>) => void, config: PricingConfig, readOnly?: boolean
}) {
  const projects = useList('projects')
  const rows: Rec[] = Array.isArray(data.difficulty) ? data.difficulty : []
  const zone = zoneOf(data, config, projects)
  const zoneIndex = config.zones.find(z => z.zone === zone)?.index ?? null
  const scores: Record<string, number | null> = {}
  for (const f of config.factors) {
    const row = rows.find(r => r.key === f.key) || rows.find(r => String(r.factor || '').toLowerCase() === f.factor.toLowerCase())
    scores[f.key] = f.key === 'zone' && zoneIndex !== null ? zoneIndex : n(row?.score)
  }
  const { score, index } = weightedIndex(config.factors, scores)
  const premium = index ? config.premiums.find(p => p.index === index)?.premium_pct ?? null : null
  const set = (f: Factor, value: number | null) => setData?.(prev => {
    const list: Row[] = (Array.isArray(prev.difficulty) ? prev.difficulty : []).filter((r: Row) => r.key !== f.key)
    const old = (Array.isArray(prev.difficulty) ? prev.difficulty : []).find((r: Row) => r.key === f.key)
    if (value !== null) list.push({ key: f.key, factor: f.factor, score: value, note: old?.note || '' })
    const order = config.factors.map(x => x.key)
    list.sort((a, b) => order.indexOf(a.key) - order.indexOf(b.key))
    return { ...prev, difficulty: list }
  })
  const scored = config.factors.filter(f => scores[f.key] !== null).length
  return (
    <section className="card ec-difficulty" aria-label={t('Project difficulty index')}>
      <div className="ec-head">
        <div>
          <h3 className="card-title">{t('Project difficulty index')}</h3>
          <p className="help">{t('Score each factor from 1 (very easy) to 5 (very difficult). The region zone scores itself from the province. The weighted average, rounded, gives the index and the risk premium.')}</p>
          {config.factors_source === 'default' && <p className="help">{t('Company default factors and weights, to be confirmed by the pricing committee.')}</p>}
        </div>
        <div className="key-figures ec-index">
          <div className="key-figure"><span className="key-label">{t('Factors scored')}</span><span className="key-value">{scored}<small> / {config.factors.length}</small></span></div>
          <div className="key-figure"><span className="key-label">{t('Weighted score')}</span><span className="key-value">{score === null ? '–' : number(score)}</span></div>
          <div className="key-figure"><span className="key-label">{t('Difficulty index')}</span><span className="key-value">{index ?? '–'}</span></div>
          <div className="key-figure"><span className="key-label">{t('Risk premium')}</span><span className="key-value">{premium === null ? '–' : <>{number(premium)}<small> %</small></>}</span></div>
        </div>
      </div>
      <ol className="ec-factors">
        {config.factors.map(f => {
          const s = scores[f.key]
          const auto = f.key === 'zone'
          return (
            <li key={f.key}>
              <div className="ec-factor-name">
                <strong>{t(f.factor)}</strong>
                {f.weight !== 1 && <span className="muted small"> · {t('weight {w}', { w: number(f.weight) })}</span>}
              </div>
              <div className="ec-scale" role="group" aria-label={t(f.factor)}>
                {[1, 2, 3, 4, 5].map(v => (
                  <button key={v} type="button" aria-pressed={s === v} disabled={readOnly || (auto && zoneIndex !== null)}
                    title={f.levels[v - 1] ? t(f.levels[v - 1]) : undefined} onClick={() => set(f, s === v ? null : v)}>{v}</button>
                ))}
              </div>
              <p className="ec-level help">
                {auto ? (zone ? t('Zone {zone}: index {i}', { zone, i: zoneIndex ?? '–' }) : t('Choose the province or the zone (or set the province on the project).'))
                  : s ? t(f.levels[s - 1] || '') : <span className="muted">{t('Not scored yet')}</span>}
              </p>
            </li>
          )
        })}
      </ol>
    </section>
  )
}

// ---------------------------------------------------------------------------
// A.1.1 Pricing & Budgeting Decision
// ---------------------------------------------------------------------------

function pbdPreview(data: Record<string, any>, rates: Rec[] | null, config: PricingConfig, projects: Rec[] | null) {
  const zone = zoneOf(data, config, projects)
  const zoneIndex = config.zones.find(z => z.zone === zone)?.index ?? null
  const scores: Record<string, number | null> = {}
  const rows: Rec[] = Array.isArray(data.difficulty) ? data.difficulty : []
  for (const f of config.factors) scores[f.key] = f.key === 'zone' && zoneIndex !== null ? zoneIndex : n(rows.find(r => r.key === f.key)?.score)
  const { index } = weightedIndex(config.factors, scores)
  const r = n(data.risk_pct_override) ?? (index ? config.premiums.find(p => p.index === index)?.premium_pct ?? 0 : 0)
  const m = n(data.margin_pct) ?? config.default_margin_pct
  let abp = 0
  let minPrice = 0
  const missing: string[] = []
  for (const line of (Array.isArray(data.costs) ? data.costs : []) as Rec[]) {
    const rate = rates?.find(x => x.id === line.rate_id)
    const cost = n(line.unit_cost) ?? n(rate?.cost_unit)
    const units = (n(line.qty) || 0) * (n(line.days) ?? 1)
    if (cost === null) missing.push(rate?.code || line.description || '?')
    abp += units * (cost || 0)
    minPrice += rate && n(rate.min_price) ? units * (n(rate.min_price) || 0) : units * (cost || 0)
  }
  abp = Math.round(abp)
  const raw = abp + Math.round(abp * r / 100) + Math.round(abp * m / 100)
  const step = Number(data.rounding || 1000)
  const bid = raw > 0 ? Math.ceil(raw / step - 1e-9) * step : 0
  return { abp, r, m, bid, index, minPrice: Math.round(minPrice), ratio: bid ? Math.round(abp / bid * 10000) / 100 : null, missing }
}

function PbdPreview({ data, setData, config }: { data: Record<string, any>, setData: (u: (p: Record<string, any>) => Record<string, any>) => void, config: PricingConfig }) {
  const rates = useList('rates')
  const projects = useList('projects')
  const p = pbdPreview(data, rates, config, projects)
  const fill = () => setData(prev => ({
    ...prev,
    costs: (Array.isArray(prev.costs) ? prev.costs : []).map((line: Rec) => {
      const rate = rates?.find(x => x.id === line.rate_id)
      return rate && n(line.unit_cost) === null && n(rate.cost_unit) !== null ? { ...line, unit_cost: rate.cost_unit, section: line.section || 'work' } : line
    }),
  }))
  const canFill = (Array.isArray(data.costs) ? data.costs : []).some((line: Rec) => line.rate_id && n(line.unit_cost) === null && n(rates?.find(x => x.id === line.rate_id)?.cost_unit) !== null)
  return (
    <section className="card ec-preview" aria-live="polite">
      <div className="ec-head">
        <h3 className="card-title">{t('Price preview')}</h3>
        <button type="button" className="small" disabled={!canFill} onClick={fill}><Icon name="calc" />{t('Fill unit costs from the price list (HPJ)')}</button>
      </div>
      <div className="kpis">
        <Kpi label={t('Project cost budget (ABP)')} value={money(p.abp)} wide />
        <Kpi label={t('Risk premium')} value={`${number(p.r)} %`} sub={money(Math.round(p.abp * p.r / 100))} />
        <Kpi label={t('Margin')} value={`${number(p.m)} %`} sub={money(Math.round(p.abp * p.m / 100))} />
        <Kpi label={t('Bid price (excl. VAT)')} value={money(p.bid)} wide />
        <Kpi label={t('Cost ratio ABP/revenue')} value={pctText(p.ratio)} sub={t('maximum {max} %', { max: number(config.max_cost_ratio_pct) })} />
      </div>
      {p.bid > 0 && p.bid < p.minPrice && <p className="notice error">{t('The bid price is below the minimum client price.')} ({money(p.minPrice)})</p>}
      {p.ratio !== null && p.ratio > config.max_cost_ratio_pct && <p className="notice warn">{t('The cost ratio is above the company maximum.')}</p>}
      {p.missing.length > 0 && <p className="notice warn">{t('No unit cost yet for: {items}', { items: p.missing.slice(0, 6).join(', ') })}</p>}
      <p className="help">{t('A preview while you type; the saved PBD is calculated on the server.')}</p>
    </section>
  )
}

function PbdDetail({ record, config }: { record: Rec, config: PricingConfig | null }) {
  const go = useGo()
  const quotes = useList('quotes')
  const linked = (quotes || []).filter(q => q.pbd_id === record.id)
  return (
    <>
      <div className="kpis ec-kpis">
        <Kpi label={t('Project cost budget (ABP)')} value={money(record.abp)} wide />
        <Kpi label={t('Risk premium')} value={pctText(record.risk_premium_pct)} sub={money(record.risk_amount)} />
        <Kpi label={t('Margin')} value={pctText(record.margin_pct)} sub={money(record.margin_amount)} />
        <Kpi label={t('Bid price (excl. VAT)')} value={money(record.bid_price)} wide sub={t('incl. VAT {amount}', { amount: money(record.bid_with_vat) })} />
        <Kpi label={t('Minimum client price')} value={money(record.min_client_price)} wide />
        <Kpi label={t('Cost ratio ABP/revenue')} value={pctText(record.cost_ratio_pct)} sub={t('maximum {max} %', { max: number(record.max_cost_ratio_pct) })} />
        <Kpi label={t('Approval authority')} value={<span className="ec-text-value">{record.approval_level ? t(record.approval_level) : '–'}</span>} />
      </div>
      <CheckList checks={record.checks} />
      {linked.length > 0 && (
        <p className="ec-links">{t('Quotations from this PBD')}: {linked.map(q => (
          <button key={q.id} type="button" className="quiet" onClick={() => go('quotes', { open: q.id })}>{q.number} · {money(q.total)}</button>
        ))}</p>
      )}
      {config && <DifficultyEditor data={record} config={config} readOnly />}
      <section className="card" style={{ marginTop: '1rem' }}>
        <h3 className="card-title">{t('Calculation')}</h3>
        <ResultView result={{ ...withoutTables(record.result, ['Difficulty factors']), summary: '', values: [] }} />
      </section>
    </>
  )
}

const PBD_LAYOUT: FormLayout = {
  first: ['date', 'project_id', 'procurement', 'scope', 'services', 'duration_weeks', 'margin_pct', 'risk_pct_override', 'costs'],
  groups: [
    { title: 'Proposal and location', fields: ['amendment', 'proposal_number', 'project_manager', 'province', 'zone', 'location', 'start_date'] },
    { title: 'Price settings', fields: ['tax_pct', 'rounding', 'conversion'] },
    { title: 'Committee reviews', fields: ['technical_review', 'legal_review', 'risk_review'] },
  ],
  hide: () => ['difficulty'],
}
const PBD_HIDE_VIEW = ['difficulty', 'costs', 'result', 'checks', 'abp', 'risk_amount', 'margin_amount', 'bid_price', 'bid_with_vat',
  'min_client_price', 'cost_ratio_pct', 'max_cost_ratio_pct', 'approval_level', 'difficulty_score', 'difficulty_index', 'risk_premium_pct', 'margin_pct']

const DEFAULT_TERMS = () => [
  { name: t('Down payment'), percent: 30 }, { name: t('Field work completed'), percent: 30 }, { name: t('Final report accepted'), percent: 40 },
]

export function PbdPage({ intent }: { intent?: Intent }) {
  const config = useConfig()
  const go = useGo()
  const schemas = useSchemas()
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const tools: FormTools = (data, setData, place) => place === 'bottom' && config ? (
    <>
      <DifficultyEditor data={data} setData={setData} config={config} />
      <PbdPreview data={data} setData={setData} config={config} />
    </>
  ) : null
  const quote = async (r: Rec) => {
    setBusy(true)
    setError('')
    try {
      const q = await apiPost<Rec>(`/api/erp/commercial/pbd/${encodeURIComponent(r.id)}/quotation`, {})
      invalidate('quotes')
      go('quotes', { open: q.id })
    } catch (e: any) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <>
      {error && <p className="notice error" role="alert">{error}</p>}
      <RecordsPage entityName="pbd" openId={intent?.open} startNew={intent?.newWith}
        description={t('Pricing & Budgeting Decision: project cost budget from the price list, difficulty index and risk premium, margin and bid price, for the pricing committee.')}
        defaults={{ date: todayIso(), procurement: 'tender', scope: 'partial', tax_pct: 11, rounding: '1000', conversion: 'spread',
          margin_pct: config?.default_margin_pct ?? 30, costs: [] }}
        formTools={tools} formLayout={PBD_LAYOUT} hideInView={PBD_HIDE_VIEW}
        actions={r => r.wf_status === 'approved' ? <>
          {schemas?.quotes?.can_create && <button type="button" disabled={busy} onClick={() => { void quote(r) }}><Icon name="invoice" />{t('Create quotation')}</button>}
          {schemas?.client_decisions?.can_create && <button type="button" onClick={() => go('client_decisions', { newWith: {
            pbd_id: r.id, project_id: r.project_id, date: todayIso(), procurement: r.procurement, location: r.location, payment_terms: DEFAULT_TERMS(),
            duration_basis: 'calendar', duration_days: r.duration_weeks ? r.duration_weeks * 7 : '' } })}>{t('Client decision')}</button>}
          {schemas?.work_plans?.can_create && <button type="button" onClick={() => go('work_plans', { newWith: {
            pbd_id: r.id, project_id: r.project_id, date: todayIso(), start_date: r.start_date || '' } })}>{t('Weekly work plan')}</button>}
        </> : null}
        extra={r => <PbdDetail record={r} config={config} />} />
    </>
  )
}

// ---------------------------------------------------------------------------
// A.1.2 Client decision
// ---------------------------------------------------------------------------

function PbdBrief({ pbdId }: { pbdId: string }) {
  const pbds = useList('pbd')
  const p = pbds?.find(x => x.id === pbdId)
  if (!pbdId || !p) return null
  return (
    <div className="ec-brief">
      <strong>{p.number}</strong>
      <span>{t('Proposed price')}: {money(p.bid_price)}</span>
      <span>{t('Minimum client price')}: {money(p.min_client_price)}</span>
      <span>{t('Difficulty index')}: {p.difficulty_index ?? '–'} · {t('Risk premium')}: {pctText(p.risk_premium_pct)}</span>
      {p.wf_status !== 'approved' && <span className="ec-warn-text">{t('The PBD is not approved yet.')}</span>}
    </div>
  )
}

function ClientBrief({ projectId }: { projectId: string }) {
  const projects = useList('projects')
  const clients = useList('clients')
  const go = useGo()
  const p = projects?.find(x => x.id === projectId)
  const c = clients?.find(x => x.id === p?.client_id)
  if (!c) return null
  return (
    <div className="ec-brief">
      <strong>{c.name}</strong>
      {(c.contact_person || c.contact_title) && <span>{[c.contact_person, c.contact_title].filter(Boolean).join(', ')}</span>}
      {(c.phone || c.email) && <span>{[c.phone, c.email].filter(Boolean).join(' · ')}</span>}
      {c.address && <span className="ec-pre">{c.address}</span>}
      <button type="button" className="small quiet" onClick={() => go('client_cards', { open: c.id })}>{t('Client card')}</button>
    </div>
  )
}

const CD_LAYOUT: FormLayout = {
  first: ['date', 'pbd_id', 'project_id', 'procurement', 'decided_price', 'price_max', 'payment_terms', 'scope_description'],
  groups: [
    { title: 'Location and field situation', fields: ['location', 'field_situation'] },
    { title: 'Service quality level', fields: ['service_levels'] },
    { title: 'Schedule', fields: ['duration_days', 'duration_basis', 'start_date', 'end_date', 'report_date'] },
    { title: 'Terms and conditions', fields: ['terms'] },
    { title: 'Document numbers', fields: ['amendment', 'proposal_number', 'offering_no', 'spk_no', 'contract_no', 'project_manager'] },
  ],
}

export function ClientDecisionsPage({ intent }: { intent?: Intent }) {
  const go = useGo()
  const schemas = useSchemas()
  const pbds = useList('pbd')
  const tools: FormTools = (data, _setData, place) => place === 'top' && (data.pbd_id || data.project_id) ? (
    <div className="ec-briefs"><PbdBrief pbdId={data.pbd_id} /><ClientBrief projectId={data.project_id || pbds?.find(p => p.id === data.pbd_id)?.project_id} /></div>
  ) : null
  return (
    <RecordsPage entityName="client_decisions" openId={intent?.open} startNew={intent?.newWith}
      description={t('Client decision: project, client and offer price approved by the pricing committee, by tender or direct appointment, with service level, field situation, terms and payment terms.')}
      defaults={{ date: todayIso(), duration_basis: 'calendar', payment_terms: DEFAULT_TERMS() }}
      formTools={tools} formLayout={CD_LAYOUT}
      hideInView={['result', 'checks', 'payment_terms', 'proposed_price', 'price_min', 'decided_price', 'price_max', 'approval_level']}
      actions={r => r.wf_status === 'approved' && schemas?.contracts?.can_create ? (
        <button type="button" onClick={() => go('contracts', { newWith: {
          project_id: r.project_id, pbd_id: r.pbd_id || '', kind: 'contract', status: 'draft', number: r.contract_no || '',
          value: r.decided_price ? Math.round(r.decided_price * 1.11) : '', start_date: r.start_date || '', end_date: r.end_date || '',
          terms: (r.payment_terms || []).map((x: Rec) => ({ name: x.name, percent: x.percent, condition: x.condition || '' })),
        } })}><Icon name="contract" />{t('Create contract')}</button>
      ) : null}
      extra={r => (
        <>
          <div className="kpis ec-kpis">
            <Kpi label={t('Decided offer price')} value={money(r.decided_price)} wide />
            <Kpi label={t('Proposed price from the PBD')} value={money(r.proposed_price)} wide />
            <Kpi label={t('Minimum client price')} value={money(r.price_min)} wide />
            <Kpi label={t('Highest price (owner\'s estimate)')} value={money(r.price_max)} wide />
            <Kpi label={t('Approval authority')} value={<span className="ec-text-value">{r.approval_level ? t(r.approval_level) : '–'}</span>} />
          </div>
          <CheckList checks={r.checks} />
          <div className="ec-briefs"><ClientBrief projectId={r.project_id} /></div>
          {(r.result?.tables || []).length > 0 && <section className="card" style={{ marginBottom: '1rem' }}><ResultView result={r.result} /></section>}
        </>
      )} />
  )
}

// ---------------------------------------------------------------------------
// A.1.6 Weekly work plan: Gantt chart, S-curve, budget drawdown
// ---------------------------------------------------------------------------

function weekStart(start: string, week: number) {
  const d = new Date(start + 'T00:00:00')
  if (Number.isNaN(d.getTime())) return ''
  d.setDate(d.getDate() + 7 * (week - 1))
  return formatDate(d.toISOString().slice(0, 10)).slice(0, 5)
}

/** Activities against weeks; the bar fills with the share done. Scrolls sideways on a phone. */
export function GanttChart({ activities, startDate, reportWeek }: { activities: Rec[], startDate?: string, reportWeek?: number | null }) {
  const groupLabel = useOption('work_plans', 'activities', 'group')
  const acts = (activities || []).filter(a => (n(a.start_week) || 0) >= 1)
  if (!acts.length) return <p className="muted small">{t('Add activities with a start and end week to draw the Gantt chart.')}</p>
  const last = Math.max(...acts.map(a => Math.max(n(a.end_week) || 0, n(a.start_week) || 1)), reportWeek || 0)
  const weeks = Array.from({ length: Math.min(last, 156) }, (_, i) => i + 1)
  return (
    <div className="ec-gantt-wrap" role="region" aria-label={t('Gantt chart')} tabIndex={0}>
      <table className="ec-gantt">
        <thead>
          <tr>
            <th scope="col" className="ec-gantt-label">{t('Activity')}</th>
            {weeks.map(w => (
              <th key={w} scope="col" className={w === reportWeek ? 'ec-now' : undefined}>
                <span>{w}</span>{startDate && <small>{weekStart(startDate, w)}</small>}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {acts.map((a, i) => {
            const s = n(a.start_week) || 1
            const e = Math.max(s, n(a.end_week) || s)
            const done = Math.max(0, Math.min(100, n(a.progress_pct) || 0))
            const filled = done / 100 * (e - s + 1)
            const tip = `${a.activity || ''}: ${t('week {s}–{e}', { s, e })}${n(a.weight_pct) !== null ? ` · ${t('weight {w}', { w: `${number(a.weight_pct)} %` })}` : ''} · ${t('{p} % done', { p: number(done) })}`
            return (
              <tr key={i}>
                <th scope="row" className="ec-gantt-label">
                  <span className="ec-gantt-name">{a.activity || '–'}</span>
                  <small className="muted">{[a.group ? groupLabel(a.group) : '', n(a.weight_pct) !== null ? `${number(a.weight_pct)} %` : ''].filter(Boolean).join(' · ')}</small>
                </th>
                {weeks.map(w => {
                  const inside = w >= s && w <= e
                  const fill = Math.max(0, Math.min(1, filled - (w - s)))
                  return (
                    <td key={w} className={w === reportWeek ? 'ec-now' : undefined}>
                      {inside && (
                        <span className={`ec-bar${w === s ? ' ec-start' : ''}${w === e ? ' ec-end' : ''}`} title={tip}>
                          {fill > 0 && <span className="ec-done" style={{ width: `${fill * 100}%` }} />}
                        </span>
                      )}
                    </td>
                  )
                })}
              </tr>
            )
          })}
        </tbody>
      </table>
      <p className="ec-legend small muted">
        <span><i className="ec-key-plan" />{t('Planned')}</span><span><i className="ec-key-done" />{t('Done')}</span>
        {reportWeek ? <span><i className="ec-key-now" />{t('Reported week')}</span> : null}
      </p>
    </div>
  )
}

function GanttTools({ data, setData }: { data: Record<string, any>, setData: (u: (p: Record<string, any>) => Record<string, any>) => void }) {
  const pbds = useList('pbd')
  const [msg, setMsg] = useState('')
  const pbd = pbds?.find(p => p.id === data.pbd_id)
  const acts: Rec[] = (Array.isArray(data.activities) ? data.activities : []).filter((a: Rec) => n(a.start_week) !== null)
  const build = async () => {
    const existing: Rec[] = Array.isArray(data.weeks) ? data.weeks : []
    if (existing.some(w => n(w.planned_pct) !== null || n(w.budget_plan) !== null) && !window.confirm(t('Replace the planned progress and the budget plan of the weekly rows?'))) return
    setMsg('')
    try {
      const rows = await apiPost<Rec[]>('/api/erp/commercial/work-plans/weeks', {
        activities: acts.map(a => ({ ...a, start_week: n(a.start_week), end_week: n(a.end_week) ?? n(a.start_week), weight_pct: n(a.weight_pct) })),
        budget: n(pbd?.abp),
      })
      setData(prev => {
        const old: Rec[] = Array.isArray(prev.weeks) ? prev.weeks : []
        const merged = rows.map(r => ({ ...(old.find(o => n(o.week) === r.week) || {}), week: r.week, planned_pct: r.planned_pct, budget_plan: r.budget_plan ?? '' }))
        const extra = old.filter(o => !rows.some(r => r.week === n(o.week)))
        return { ...prev, weeks: [...merged, ...extra] }
      })
      setMsg(pbd?.abp ? t('Weekly rows filled; the PBD budget {amount} is spread like the planned progress.', { amount: money(pbd.abp) }) : t('Weekly rows filled from the Gantt chart.'))
    } catch (e: any) {
      setMsg(e.message)
    }
  }
  return (
    <section className="card ec-gantt-tools">
      <div className="ec-head">
        <h3 className="card-title">{t('Gantt chart')}</h3>
        <button type="button" className="small" disabled={!acts.length} onClick={() => { void build() }}><Icon name="calendar" />{t('Fill the weekly rows from the Gantt chart')}</button>
      </div>
      <GanttChart activities={acts} startDate={data.start_date} />
      {msg && <p className="help" role="status">{msg}</p>}
    </section>
  )
}

const WP_LAYOUT: FormLayout = {
  first: ['date', 'project_id', 'pbd_id', 'start_date', 'activities', 'weeks'],
  groups: [{ title: 'More details', fields: ['site_manager', 'files', 'notes'] }],
}

export function WorkPlansPage({ intent }: { intent?: Intent }) {
  const tools: FormTools = (data, setData, place) => place === 'bottom' ? <GanttTools data={data} setData={setData} /> : null
  return (
    <RecordsPage entityName="work_plans" openId={intent?.open} startNew={intent?.newWith}
      description={t('Weekly work plan and budget drawdown: Gantt chart of the activities, weekly budget plan, drawdown requests and realised cost, checked against the PBD.')}
      defaults={{ date: todayIso(), activities: [], weeks: [] }}
      formTools={tools} formLayout={WP_LAYOUT}
      hideInView={['result', 'checks', 'activities', 'weeks', 'total_plan', 'total_drawdown', 'total_realised', 'pbd_budget', 'planned_to_date',
        'actual_to_date', 'deviation', 'cost_ratio_pct', 'revenue', 'duration_weeks', 'pbd_weeks', 'report_week']}
      extra={r => (
        <>
          <div className="kpis ec-kpis">
            <Kpi label={t('Budget plan')} value={money(r.total_plan)} wide sub={r.pbd_budget ? t('PBD budget {amount}', { amount: money(r.pbd_budget) }) : undefined} />
            <Kpi label={t('Drawdown requested')} value={money(r.total_drawdown)} wide />
            <Kpi label={t('Realised cost')} value={money(r.total_realised)} wide />
            <Kpi label={t('Progress to date')} value={r.report_week ? `${number(r.actual_to_date)} %` : '–'}
              sub={r.report_week ? t('plan {p} % · week {w}', { p: number(r.planned_to_date), w: r.report_week }) : t('No week reported yet')} />
            <Kpi label={t('Deviation')} value={r.deviation === null || r.deviation === undefined ? '–' : `${r.deviation > 0 ? '+' : ''}${number(r.deviation)}`}
              sub={t('percentage points')} />
            <Kpi label={t('Cost ratio ABP/revenue')} value={pctText(r.cost_ratio_pct)} />
          </div>
          <CheckList checks={r.checks} />
          <section className="card" style={{ marginBottom: '1rem' }}>
            <h3 className="card-title">{t('Gantt chart')}</h3>
            <GanttChart activities={r.activities || []} startDate={r.start_date} reportWeek={r.report_week} />
          </section>
          <section className="card" style={{ marginBottom: '1rem' }}>
            <h3 className="card-title">{t('S-curve and budget')}</h3>
            <ResultView result={withoutTables(r.result, ['Activities (Gantt)'])} />
          </section>
        </>
      )} />
  )
}

// ---------------------------------------------------------------------------
// A.1.9 Bank guarantees and SKBDN
// ---------------------------------------------------------------------------

const daysUntil = (iso?: string) => {
  if (!iso) return null
  const d = new Date(iso + 'T00:00:00').getTime(), now = new Date(todayIso() + 'T00:00:00').getTime()
  return Number.isFinite(d) ? Math.round((d - now) / 86400000) : null
}

function ExpiringGuarantees({ onOpen }: { onOpen: (id: string) => void }) {
  const rows = useList('guarantees')
  const config = useConfig()
  const typeLabel = useOption('guarantees', 'type')
  const warn = config?.guarantee_warning_days ?? 30
  const list = (rows || []).filter(g => g.status === 'issued').map(g => ({ g, days: daysUntil(g.expiry_date) }))
    .filter(x => x.days !== null && x.days <= warn).sort((a, b) => (a.days ?? 0) - (b.days ?? 0))
  if (!list.length) return null
  return (
    <div className="notice warn ec-checks" role="status">
      <strong>{t('Guarantees expiring within {n} days', { n: warn })}</strong>
      <ul>
        {list.map(({ g, days }) => (
          <li key={g.id}>
            <button type="button" className="quiet" onClick={() => onOpen(g.id)}>{g.number}</button> · {typeLabel(g.type)} · {money(g.amount)} · {formatDate(g.expiry_date)}
            {' '}({(days ?? 0) < 0 ? t('expired {n} days ago', { n: -(days ?? 0) }) : t('{n} days left', { n: days ?? 0 })})
          </li>
        ))}
      </ul>
    </div>
  )
}

export function GuaranteesPage({ intent }: { intent?: Intent }) {
  const [openId, setOpenId] = useState<string | undefined>(intent?.open)
  const [round, setRound] = useState(0)
  return (
    <RecordsPage key={round} entityName="guarantees" openId={openId} startNew={round ? null : intent?.newWith}
      description={t('Requests to finance for bank guarantees (performance, advance payment, bid, maintenance) and SKBDN, from the contract data.')}
      defaults={{ date: todayIso(), status: 'requested', type: 'performance' }}
      toolbar={<ExpiringGuarantees onOpen={id => { setOpenId(id); setRound(r => r + 1) }} />}
      formLayout={{
        first: ['date', 'type', 'direction', 'project_id', 'contract_id', 'required_pct', 'amount', 'beneficiary', 'status'],
        groups: [
          { title: 'Bank and validity', fields: ['bank', 'guarantee_no', 'issue_date', 'expiry_date', 'claim_days'] },
          { title: 'Bank fee and collateral', fields: ['fee_pct', 'collateral_pct'] },
        ],
      }}
      hideInView={['checks']}
      extra={r => {
        const days = daysUntil(r.expiry_date)
        return (
          <>
            <div className="kpis ec-kpis">
              <Kpi label={t('Guarantee amount')} value={money(r.amount)} wide sub={r.pct_of_contract ? t('{p} % of the contract value', { p: number(r.pct_of_contract) }) : undefined} />
              <Kpi label={t('Valid until')} value={r.expiry_date ? formatDate(r.expiry_date) : '–'}
                sub={days === null || ['released', 'claimed', 'cancelled'].includes(r.status) ? undefined : days < 0 ? t('expired {n} days ago', { n: -days }) : t('{n} days left', { n: days })} />
              {r.fee_amount ? <Kpi label={t('Bank fee')} value={money(r.fee_amount)} wide /> : null}
              {r.collateral_amount ? <Kpi label={t('Cash collateral')} value={money(r.collateral_amount)} wide /> : null}
            </div>
            <CheckList checks={r.checks} />
          </>
        )
      }} />
  )
}

// ---------------------------------------------------------------------------
// A.1.10 Receivables: aging, NPAR, collection notes
// ---------------------------------------------------------------------------

type Bucket = { key: string, label: string, amount: number, count: number }
type ArInvoice = {
  id: string, number: string, project_id: string, project: string, client_id: string, client: string, date: string, due_date: string,
  term: string, total: number, paid: number, outstanding: number, days_since_invoice: number, days_past_due: number,
  bucket: string, age_bucket: string, owner: 'npar' | 'commercial', last_note: Rec | null, notes_count: number
}
export type Receivables = {
  as_of: string, npar_days: number
  totals: { invoiced: number, paid: number, outstanding: number, overdue: number, npar: number, open_invoices: number }
  buckets: Bucket[], age_buckets: Bucket[]
  by_client: Array<{ client_id: string, client: string, outstanding: number, npar: number } & Record<string, number | string>>
  invoices: ArInvoice[], npar: ArInvoice[]
}

function AgingBars({ title, buckets, note }: { title: string, buckets: Bucket[], note?: string }) {
  const total = buckets.reduce((s, b) => s + b.amount, 0)
  const max = Math.max(1, ...buckets.map(b => b.amount))
  return (
    <section className="card ec-aging">
      <h3 className="card-title">{title}</h3>
      {note && <p className="help">{note}</p>}
      <ul className="ec-bars">
        {buckets.map((b, i) => (
          <li key={b.key} className={i === buckets.length - 1 && b.amount > 0 ? 'ec-late' : undefined}>
            <span className="ec-bars-label">{t(b.label)}</span>
            <span className="bar" aria-hidden="true"><span style={{ width: `${(b.amount / max) * 100}%` }} /></span>
            <span className="num">{money(b.amount)}<small className="muted"> · {b.count} · {total ? number(Math.round(b.amount / total * 1000) / 10) : 0} %</small></span>
          </li>
        ))}
      </ul>
    </section>
  )
}

function CollectionNoteForm({ invoiceId, onDone, onCancel }: { invoiceId: string, onDone: () => void, onCancel: () => void }) {
  const actionLabel = useOption('invoices', 'collection_notes', 'action')
  const schemas = useSchemas()
  const options = schemas?.invoices?.fields.find(f => f.name === 'collection_notes')?.fields?.find(f => f.name === 'action')?.options || []
  const [form, setForm] = useState({ date: todayIso(), action: 'call', note: '', next_date: '' })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const save = async () => {
    if (!form.note.trim()) { setError(t('Write what was agreed or done.')); return }
    setBusy(true)
    setError('')
    try {
      await apiPost(`/api/erp/commercial/invoices/${encodeURIComponent(invoiceId)}/collection-notes`, { ...form, next_date: form.next_date || null })
      invalidate('invoices')
      onDone()
    } catch (e: any) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="ec-note-form">
      <div className="fields">
        <div className="field"><label htmlFor={`cn-d-${invoiceId}`}>{t('Date')}</label><DateInput id={`cn-d-${invoiceId}`} value={form.date} onChange={v => setForm({ ...form, date: v })} /></div>
        <div className="field">
          <label htmlFor={`cn-a-${invoiceId}`}>{t('Action')}</label>
          <select id={`cn-a-${invoiceId}`} value={form.action} onChange={e => setForm({ ...form, action: e.target.value })}>
            {options.map(o => <option key={o[0]} value={o[0]}>{actionLabel(o[0])}</option>)}
          </select>
        </div>
        <div className="field wide"><label htmlFor={`cn-n-${invoiceId}`}>{t('Note')}</label><input id={`cn-n-${invoiceId}`} maxLength={500} value={form.note} onChange={e => setForm({ ...form, note: e.target.value })} /></div>
        <div className="field"><label htmlFor={`cn-x-${invoiceId}`}>{t('Follow up on')}</label><DateInput id={`cn-x-${invoiceId}`} value={form.next_date} onChange={v => setForm({ ...form, next_date: v })} /></div>
      </div>
      {error && <p className="notice error">{error}</p>}
      <div className="actions">
        <button type="button" className="primary small" disabled={busy} onClick={() => { void save() }}>{busy ? t('Saving…') : t('Save note')}</button>
        <button type="button" className="small" onClick={onCancel}>{t('Cancel')}</button>
      </div>
    </div>
  )
}

function InvoiceTable({ rows, onChanged, showClient = true }: { rows: ArInvoice[], onChanged: () => void, showClient?: boolean }) {
  const go = useGo()
  const actionLabel = useOption('invoices', 'collection_notes', 'action')
  const bucketLabel = (k: string) => t(AGING_LABELS[k] || k)
  const [noteFor, setNoteFor] = useState<string | null>(null)
  if (!rows.length) return <p className="muted small">{t('No open invoices.')}</p>
  return (
    <ScrollTable>
      <table className="data-table ec-ar-table">
        <thead>
          <tr>
            <th>{t('Invoice')}</th>{showClient && <th>{t('Client')}</th>}<th>{t('Project')}</th><th>{t('Invoice date')}</th>
            <th className="num">{t('Days since invoice')}</th><th>{t('Overdue')}</th><th className="num">{t('Outstanding')}</th>
            <th>{t('Handled by')}</th><th>{t('Last collection note')}</th><th />
          </tr>
        </thead>
        <tbody>
          {rows.map(r => (
            <FragmentRow key={r.id} open={noteFor === r.id} colSpan={showClient ? 10 : 9}
              form={<CollectionNoteForm invoiceId={r.id} onCancel={() => setNoteFor(null)} onDone={() => { setNoteFor(null); onChanged() }} />}>
              <td><button type="button" className="quiet ec-link" onClick={() => go('invoices', { open: r.id })}>{r.number}</button><div className="bh-sub">{r.term}</div></td>
              {showClient && <td>{r.client || '–'}</td>}
              <td>{r.project || '–'}</td>
              <td className="nowrap">{formatDate(r.date)}<div className="bh-sub">{t('due {date}', { date: formatDate(r.due_date) })}</div></td>
              <td className="num">{r.days_since_invoice}</td>
              <td className="nowrap"><Tone value={r.bucket === 'current' ? 'ok' : r.bucket === 'over_90' ? 'expired' : 'expiring'}>{bucketLabel(r.bucket)}</Tone></td>
              <td className="num nowrap">{money(r.outstanding)}</td>
              <td><Tone value={r.owner}>{r.owner === 'npar' ? t('NPAR committee') : t('Commercial & operations')}</Tone></td>
              <td className="ec-note-cell">{r.last_note ? <>{formatDate(r.last_note.date)} · {actionLabel(r.last_note.action)}: {r.last_note.note}
                {r.last_note.next_date ? <div className="bh-sub">{t('follow up {date}', { date: formatDate(r.last_note.next_date) })}</div> : null}</> : <span className="muted">–</span>}</td>
              <td><button type="button" className="small" onClick={() => setNoteFor(noteFor === r.id ? null : r.id)}>{t('Add note')}</button></td>
            </FragmentRow>
          ))}
        </tbody>
      </table>
    </ScrollTable>
  )
}

function FragmentRow({ children, open, form, colSpan }: { children: ReactNode, open: boolean, form: ReactNode, colSpan: number }) {
  return (
    <>
      <tr>{children}</tr>
      {open && <tr className="ec-form-row"><td colSpan={colSpan}>{form}</td></tr>}
    </>
  )
}

const AGING_LABELS: Record<string, string> = {
  current: 'Not yet due', d1_30: '1–30 days overdue', d31_60: '31–60 days overdue', d61_90: '61–90 days overdue', over_90: 'More than 90 days overdue',
}

export function ReceivablesPage() {
  const go = useGo()
  const [asOf, setAsOf] = useState(todayIso())
  const [round, setRound] = useState(0)
  const [view, setView] = useState<'npar' | 'open' | 'clients'>('open')
  const { data, error } = useLive<Receivables>(`/api/erp/commercial/receivables?as_of=${encodeURIComponent(asOf || todayIso())}`, round)
  return (
    <div className="page">
      <PageHead title={t('Receivables')} description={t('Aging of the invoices sent and not yet paid. After {n} days from the invoice date, collection moves from commercial & operations to the NPAR committee.', { n: data?.npar_days ?? 90 })} />
      <div className="toolbar">
        <div className="field ec-asof"><label htmlFor="ar-asof">{t('As of')}</label><DateInput id="ar-asof" value={asOf} onChange={v => setAsOf(v || todayIso())} /></div>
      </div>
      {error && <p className="notice error">{error}</p>}
      {!data ? <p className="muted">{t('Loading…')}</p> : (
        <>
          <div className="kpis ec-kpis">
            <Kpi label={t('Outstanding')} value={money(data.totals.outstanding)} wide sub={t('{n} open invoices', { n: data.totals.open_invoices })} />
            <Kpi label={t('Overdue')} value={money(data.totals.overdue)} wide />
            <Kpi label={t('NPAR (more than {n} days)', { n: data.npar_days })} value={money(data.totals.npar)} wide sub={t('{n} invoices', { n: data.npar.length })} />
            <Kpi label={t('Invoiced')} value={money(data.totals.invoiced)} wide sub={t('Paid {amount}', { amount: money(data.totals.paid) })} />
          </div>
          <div className="ec-two">
            <AgingBars title={t('Aging by due date')} buckets={data.buckets} />
            <AgingBars title={t('Aging since the invoice date')} buckets={data.age_buckets} note={t('The matrix of the receivables policy: who handles the collection follows this age.')} />
          </div>
          <div className="segmented ec-tabs" role="group" aria-label={t('Show')}>
            <button type="button" aria-pressed={view === 'open'} onClick={() => setView('open')}>{t('Open invoices')} <span className="count">{data.invoices.length}</span></button>
            <button type="button" aria-pressed={view === 'npar'} onClick={() => setView('npar')}>{t('NPAR list')} <span className="count">{data.npar.length}</span></button>
            <button type="button" aria-pressed={view === 'clients'} onClick={() => setView('clients')}>{t('By client')} <span className="count">{data.by_client.length}</span></button>
          </div>
          {view === 'open' && <InvoiceTable rows={data.invoices} onChanged={() => setRound(r => r + 1)} />}
          {view === 'npar' && (data.npar.length ? <InvoiceTable rows={data.npar} onChanged={() => setRound(r => r + 1)} /> : <p className="muted">{t('No receivables for the NPAR committee.')}</p>)}
          {view === 'clients' && (
            <ScrollTable>
              <table className="data-table">
                <thead><tr><th>{t('Client')}</th><th className="num">{t('Outstanding')}</th>{Object.keys(AGING_LABELS).map(k => <th key={k} className="num">{t(AGING_LABELS[k])}</th>)}<th className="num">{t('NPAR')}</th></tr></thead>
                <tbody>
                  {data.by_client.map(c => (
                    <tr key={c.client_id} className="clickable" onClick={() => go('client_cards', { open: c.client_id })}>
                      <td><button type="button" className="quiet ec-link" onClick={e => { e.stopPropagation(); go('client_cards', { open: c.client_id }) }}>{c.client || '–'}</button></td>
                      <td className="num nowrap">{money(c.outstanding)}</td>
                      {Object.keys(AGING_LABELS).map(k => <td key={k} className="num nowrap">{money(c[k])}</td>)}
                      <td className="num nowrap">{money(c.npar)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </ScrollTable>
          )}
        </>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// A.1.11 Client cards
// ---------------------------------------------------------------------------

export type ClientCardData = {
  as_of: string
  client: Rec & { since_year: number | null }
  stats: {
    projects: number, projects_by_status: Record<string, number>, contract_value: number, invoiced: number, paid: number,
    outstanding: number, overdue: number, npar: number, avg_days_to_pay: number | null, paid_invoices: number,
    on_time_rate_pct: number | null, invoices_due: number, late_open: number, rating: string
  }
  services: Record<string, number>, provinces: Record<string, number>
  projects: Array<{ id: string, code: string, name: string, status: string, province: string, services: string[], start_date: string,
    contract_value: number | null, invoiced: number, paid: number, outstanding: number, progress_pct: number | null }>
  aging: Bucket[], age_buckets: Bucket[], invoices: ArInvoice[], npar: ArInvoice[]
  pipeline: { pbd: Rec[], quotes: Rec[], client_decisions: Rec[] }
}

/** The client card (statistics, payment behaviour, receivables, pipeline); also usable under a client record. */
export function ClientCard({ clientId }: { clientId: string }) {
  const go = useGo()
  const [round, setRound] = useState(0)
  const { data, error } = useLive<ClientCardData>(`/api/erp/commercial/clients/${encodeURIComponent(clientId)}/card`, round)
  const statusLabel = useOption('projects', 'status')
  const serviceLabel = useOption('projects', 'services')
  const provinceLabel = useOption('projects', 'province')
  const wfLabel = useOption('pbd', 'wf_status')
  const quoteStatus = useOption('quotes', 'status')
  const typeLabel = useOption('clients', 'type')
  if (error) return <p className="notice error">{error}</p>
  if (!data) return <p className="muted">{t('Loading…')}</p>
  const s = data.stats
  const c = data.client
  return (
    <div className="ec-card">
      <section className="card ec-client-head">
        <div>
          <h2 className="ec-client-name">{c.name}</h2>
          <p className="muted">{[typeLabel(c.type), c.since_year ? t('client since {year}', { year: c.since_year }) : ''].filter(Boolean).join(' · ')}</p>
          {(c.contact_person || c.phone || c.email) && <p>{[c.contact_person, c.contact_title].filter(Boolean).join(', ')}{(c.phone || c.email) && <><br />{[c.phone, c.email].filter(Boolean).join(' · ')}</>}</p>}
          {c.address && <p className="ec-pre small">{c.address}</p>}
        </div>
        <div className="ec-rating">
          <span className="muted small">{t('Payment record')}</span>
          <Tone value={s.rating}>{t(RATING[s.rating] || s.rating)}</Tone>
          <button type="button" className="small quiet" onClick={() => go('clients', { open: c.id })}>{t('Open the client record')}</button>
        </div>
      </section>
      <div className="kpis ec-kpis">
        <Kpi label={t('Projects')} value={s.projects} sub={Object.entries(s.projects_by_status).map(([k, v]) => `${statusLabel(k)} ${v}`).join(' · ')} />
        <Kpi label={t('Contract value')} value={money(s.contract_value)} wide />
        <Kpi label={t('Invoiced')} value={money(s.invoiced)} wide sub={t('Paid {amount}', { amount: money(s.paid) })} />
        <Kpi label={t('Outstanding')} value={money(s.outstanding)} wide sub={s.npar ? t('NPAR {amount}', { amount: money(s.npar) }) : undefined} />
        <Kpi label={t('Average days to pay')} value={s.avg_days_to_pay === null ? '–' : number(s.avg_days_to_pay)} sub={t('{n} invoices paid', { n: s.paid_invoices })} />
        <Kpi label={t('Paid on time')} value={pctText(s.on_time_rate_pct)} sub={t('of {n} invoices due', { n: s.invoices_due })} />
      </div>
      {(Object.keys(data.services).length > 0 || Object.keys(data.provinces).length > 0) && (
        <p className="ec-chips">
          {Object.entries(data.services).map(([k, v]) => <span key={k} className="ec-chip">{serviceLabel(k)} · {v}</span>)}
          {Object.entries(data.provinces).map(([k, v]) => <span key={k} className="ec-chip ec-chip-alt">{provinceLabel(k)} · {v}</span>)}
        </p>
      )}
      <section className="hub-section">
        <div className="hub-head"><h3>{t('Projects')} <span className="muted">{data.projects.length}</span></h3></div>
        {data.projects.length ? (
          <ScrollTable>
            <table className="data-table">
              <thead><tr><th>{t('Project')}</th><th>{t('Status')}</th><th>{t('Province')}</th><th className="num">{t('Contract value')}</th>
                <th className="num">{t('Invoiced')}</th><th className="num">{t('Paid')}</th><th className="num">{t('Outstanding')}</th><th className="num">{t('Progress')}</th></tr></thead>
              <tbody>
                {data.projects.map(p => (
                  <tr key={p.id} className="clickable" onClick={() => go('projects', { open: p.id })}>
                    <td><strong>{p.name}</strong><div className="bh-sub">{p.code}{p.services.length ? ` · ${p.services.map(serviceLabel).join(', ')}` : ''}</div></td>
                    <td><Tone value={p.status}>{statusLabel(p.status)}</Tone></td>
                    <td>{p.province ? provinceLabel(p.province) : '–'}</td>
                    <td className="num nowrap">{money(p.contract_value)}</td>
                    <td className="num nowrap">{money(p.invoiced)}</td>
                    <td className="num nowrap">{money(p.paid)}</td>
                    <td className="num nowrap">{money(p.outstanding)}</td>
                    <td className="num">{pctText(p.progress_pct)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </ScrollTable>
        ) : <p className="muted small">{t('No projects yet.')}</p>}
      </section>
      <section className="hub-section">
        <div className="hub-head"><h3>{t('Open invoices')} <span className="muted">{data.invoices.length}</span></h3></div>
        <InvoiceTable rows={data.invoices} showClient={false} onChanged={() => setRound(r => r + 1)} />
      </section>
      {(data.pipeline.pbd.length + data.pipeline.quotes.length + data.pipeline.client_decisions.length) > 0 && (
        <section className="hub-section">
          <div className="hub-head"><h3>{t('Pipeline')}</h3></div>
          <ul className="ec-plain">
            {data.pipeline.pbd.map(r => <li key={r.id}><button type="button" className="quiet ec-link" onClick={() => go('pbd', { open: r.id })}>{r.number}</button> · {t('PBD')} · {money(r.bid_price)} · <Tone value={r.wf_status || 'draft'}>{wfLabel(r.wf_status || 'draft')}</Tone></li>)}
            {data.pipeline.client_decisions.map(r => <li key={r.id}><button type="button" className="quiet ec-link" onClick={() => go('client_decisions', { open: r.id })}>{r.number}</button> · {t('Client decision')} · {money(r.decided_price ?? r.proposed_price)} · <Tone value={r.wf_status || 'draft'}>{wfLabel(r.wf_status || 'draft')}</Tone></li>)}
            {data.pipeline.quotes.map(r => <li key={r.id}><button type="button" className="quiet ec-link" onClick={() => go('quotes', { open: r.id })}>{r.number}</button> · {t('Quotation')} · {money(r.total)} · <Tone value={r.status}>{quoteStatus(r.status)}</Tone></li>)}
          </ul>
        </section>
      )}
    </div>
  )
}

type ClientRecap = {
  id: string, name: string, type: string, since_year: number | null, projects: number, contract_value: number, invoiced: number, paid: number,
  outstanding: number, overdue: number, npar: number, avg_days_to_pay: number | null, on_time_rate_pct: number | null, rating: string
}

export function ClientCardsPage({ intent }: { intent?: Intent }) {
  const [openId, setOpenId] = useState<string | null>(intent?.open || null)
  const [search, setSearch] = useState('')
  const { data, error } = useLive<ClientRecap[]>(openId ? null : '/api/erp/commercial/clients')
  useEffect(() => { setOpenId(intent?.open || null) }, [intent?.open])
  const shown = useMemo(() => (data || []).filter(c => !search.trim() || String(c.name).toLowerCase().includes(search.trim().toLowerCase())), [data, search])
  if (openId) {
    return (
      <div className="page">
        <PageHead back={<button type="button" className="quiet back" onClick={() => setOpenId(null)}><Icon name="back" />{t('Client cards')}</button>} title={t('Client card')} />
        <ClientCard clientId={openId} />
      </div>
    )
  }
  const totals = (data || []).reduce((a, c) => ({ value: a.value + c.contract_value, out: a.out + c.outstanding, npar: a.npar + c.npar }), { value: 0, out: 0, npar: 0 })
  return (
    <div className="page">
      <PageHead title={t('Client cards')} description={t('Client recap: contract value, invoices, payments and payment record of each client.')} />
      {error && <p className="notice error">{error}</p>}
      {data && (
        <div className="kpis ec-kpis">
          <Kpi label={t('Clients')} value={data.length} />
          <Kpi label={t('Contract value')} value={money(totals.value)} wide />
          <Kpi label={t('Outstanding')} value={money(totals.out)} wide />
          <Kpi label={t('NPAR')} value={money(totals.npar)} wide />
        </div>
      )}
      <div className="toolbar"><input type="search" value={search} onChange={e => setSearch(e.target.value)} placeholder={t('Search')} aria-label={t('Search')} /></div>
      {!data ? <p className="muted">{t('Loading…')}</p> : !shown.length ? <p className="muted">{t('Nothing found.')}</p> : (
        <ScrollTable>
          <table className="data-table">
            <thead><tr><th>{t('Client')}</th><th className="num">{t('Projects')}</th><th className="num">{t('Contract value')}</th><th className="num">{t('Invoiced')}</th>
              <th className="num">{t('Outstanding')}</th><th className="num">{t('NPAR')}</th><th className="num">{t('Average days to pay')}</th><th className="num">{t('Paid on time')}</th><th>{t('Payment record')}</th></tr></thead>
            <tbody>
              {shown.map(c => (
                <tr key={c.id} className="clickable" onClick={() => setOpenId(c.id)}>
                  <td><button type="button" className="quiet ec-link" onClick={e => { e.stopPropagation(); setOpenId(c.id) }}>{c.name}</button>{c.since_year ? <div className="bh-sub">{t('since {year}', { year: c.since_year })}</div> : null}</td>
                  <td className="num">{c.projects}</td>
                  <td className="num nowrap">{money(c.contract_value)}</td>
                  <td className="num nowrap">{money(c.invoiced)}</td>
                  <td className="num nowrap">{money(c.outstanding)}</td>
                  <td className="num nowrap">{c.npar ? money(c.npar) : '–'}</td>
                  <td className="num">{c.avg_days_to_pay === null ? '–' : number(c.avg_days_to_pay)}</td>
                  <td className="num">{pctText(c.on_time_rate_pct)}</td>
                  <td><Tone value={c.rating}>{t(RATING[c.rating] || c.rating)}</Tone></td>
                </tr>
              ))}
            </tbody>
          </table>
        </ScrollTable>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Pricing policy in the company settings
// ---------------------------------------------------------------------------

const PRICING_FIELDS = ['difficulty_factors', 'risk_premium_table', 'default_margin_pct', 'max_cost_ratio_pct', 'approval_limits', 'npar_days',
  'default_payment_days', 'guarantee_warning_days']

export function PricingSettingsPage() {
  const schemas = useSchemas()
  const rows = useList('settings')
  const config = useConfig()
  const [saved, setSaved] = useState(false)
  const [round, setRound] = useState(0)
  const entity = schemas?.settings
  if (!entity || !rows) return <p className="muted">{t('Loading…')}</p>
  const hide = entity.fields.map(f => f.name).filter(name => !PRICING_FIELDS.includes(name))
  const tools: FormTools = (data, setData, place) => place === 'top' && config ? (
    <div className="ec-head" style={{ marginBottom: '.75rem' }}>
      <p className="help" style={{ margin: 0 }}>{t('Empty tables use the company defaults shown on this page, to be confirmed by the pricing committee. Fill them in to change them.')}</p>
      <button type="button" className="small" onClick={() => setData(prev => ({
        ...prev,
        difficulty_factors: (prev.difficulty_factors || []).length ? prev.difficulty_factors : config.factors.map(f => ({
          key: f.key, factor: t(f.factor), weight: f.weight, ...Object.fromEntries(f.levels.map((l, i) => [`level_${i + 1}`, t(l)])),
        })),
        risk_premium_table: (prev.risk_premium_table || []).length ? prev.risk_premium_table : config.premiums.map(p => ({ index: p.index, premium_pct: p.premium_pct })),
        approval_limits: (prev.approval_limits || []).length ? prev.approval_limits : config.approval_limits.map(a => ({ up_to: a.up_to ?? '', level: t(a.level) })),
      }))}>{t('Copy the company defaults into the empty tables')}</button>
    </div>
  ) : null
  return (
    <div className="page" style={{ maxWidth: 980 }}>
      <PageHead title={t('Pricing policy')} description={t('Project difficulty factors, risk premium by difficulty index, margin, maximum cost ratio, approval authority and receivables rules.')} />
      {saved && <p className="notice ok" role="status">{t('Saved.')}</p>}
      {!rows[0] && <p className="notice warn">{t('Enter the company name in the company settings first.')}</p>}
      {entity.can_create ? (
        <RecordForm key={round} entity={entity} record={rows[0] || null} defaults={{ company_name: '' }} hide={hide} tools={tools}
          onSaved={() => { invalidate('settings'); configPromise = null; setSaved(true); setRound(r => r + 1) }} />
      ) : rows[0] ? <section className="card"><RecordFields entity={entity} record={rows[0]} hide={hide} /></section> : null}
      {config && (
        <section className="card" style={{ marginTop: '1rem' }}>
          <h3 className="card-title">{t('Policy in force')}</h3>
          <div className="ec-two">
            <div>
              <h4>{t('Risk premium by difficulty index')}</h4>
              <table className="data-table"><thead><tr><th>{t('Difficulty index')}</th><th className="num">{t('Risk premium')}</th></tr></thead>
                <tbody>{config.premiums.map(p => <tr key={p.index}><td>{p.index}</td><td className="num">{number(p.premium_pct)} %</td></tr>)}</tbody></table>
              <p className="help">{config.premiums_source === 'default' ? t('Company defaults, to be confirmed by the pricing committee.') : t('From the company settings.')}</p>
              <h4>{t('Approval authority by bid value')}</h4>
              <ul className="ec-plain">{config.approval_limits.map((a, i) => <li key={i}>{a.up_to ? t('below {amount}', { amount: money(a.up_to) }) : t('above that')}: <strong>{t(a.level)}</strong></li>)}</ul>
              <p className="help">{t('Margin {m} % · maximum cost ratio {r} % · NPAR after {d} days', { m: number(config.default_margin_pct), r: number(config.max_cost_ratio_pct), d: config.npar_days })}</p>
            </div>
            <div>
              <h4>{t('Region zones')}</h4>
              <ScrollTable>
                <table className="data-table"><thead><tr><th>{t('Zone')}</th><th>{t('Provinces')}</th><th className="num">{t('Index')}</th></tr></thead>
                  <tbody>{config.zones.map(z => <tr key={z.zone}><td>{z.zone}</td><td>{t(z.provinces)}</td><td className="num">{z.index}</td></tr>)}</tbody></table>
              </ScrollTable>
              <p className="help">{t('Sulawesi Tenggara is placed in zone K and the new Papua provinces in zone N, to be confirmed.')}</p>
            </div>
          </div>
        </section>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// A.1.14 Commercial part of the management dashboard
// ---------------------------------------------------------------------------

export type CommercialOverview = {
  as_of: string
  pipeline: { pbd: Record<string, { count: number, value: number }>, client_decisions: Record<string, { count: number, value: number }>,
    quotes: Record<string, { count: number, value: number }>, projects: Record<string, number> }
  contracts: { count: number, value: number, by_kind: Record<string, { count: number, value: number }> }
  receivables: Receivables['totals'], aging: Bucket[], age_buckets: Bucket[], npar: ArInvoice[]
  by_client: Receivables['by_client']
  projects_budget: Array<{ id: string, number: string, project_id: string, project: string, wf_status: string, pbd_budget: number | null,
    plan_budget: number, drawdown: number, realised: number, report_week: number | null, duration_weeks: number | null,
    planned_pct: number, actual_pct: number, deviation_pct: number | null, cost_ratio_pct: number | null }>
  clients_by_service: Array<{ key: string, label: string, clients: number, projects: number, contract_value: number }>
  clients_by_province: Array<{ key: string, label: string, zone: string, clients: number, projects: number, contract_value: number }>
  guarantees: { active: number, amount: number, expiring: Array<{ id: string, number: string, type: string, direction: string, project_id: string,
    expiry_date: string, days: number | null, amount: number | null, status: string }> }
  cost_ratio: { average_pct: number | null, max_pct: number, approved_pbd: number }
}

function Pipeline({ items }: { items: Array<[string, number, number | null]> }) {
  return (
    <ul className="ec-pipeline">
      {items.map(([label, count, value]) => (
        <li key={label}><span className="ec-pipeline-n">{count}</span><span>{label}</span>{value !== null && <span className="small">{money(value)}</span>}</li>
      ))}
    </ul>
  )
}

/** The commercial part of the management dashboard; `onOpen` goes to a page by its suggested tab key. */
export function CommercialOverviewPanel({ onOpen }: { onOpen?: (tab: string, intent?: Intent) => void }) {
  const { data, error } = useLive<CommercialOverview>('/api/erp/commercial/overview')
  const statusLabel = useOption('projects', 'status')
  const typeLabel = useOption('guarantees', 'type')
  const wfLabel = useOption('pbd', 'wf_status')
  const quoteStatus = useOption('quotes', 'status')
  if (error) return <p className="notice error">{error}</p>
  if (!data) return <p className="muted">{t('Loading…')}</p>
  const link = (tab: string, label: string) => onOpen ? <button type="button" className="small quiet" onClick={() => onOpen(tab)}>{label}</button> : null
  const sum = (o: Record<string, { count: number, value: number }>, keys: string[]) => keys.reduce((a, k) => ({ count: a.count + (o[k]?.count || 0), value: a.value + (o[k]?.value || 0) }), { count: 0, value: 0 })
  const pbdOpen = sum(data.pipeline.pbd, ['draft', 'returned', 'submitted', 'reviewed'])
  const pbdApproved = sum(data.pipeline.pbd, ['approved'])
  const cdApproved = sum(data.pipeline.client_decisions, ['approved'])
  const quotesSent = sum(data.pipeline.quotes, ['sent'])
  const quotesWon = sum(data.pipeline.quotes, ['won'])
  const quotesLost = sum(data.pipeline.quotes, ['lost'])
  const r = data.receivables
  return (
    <div className="ec-overview">
      <section className="hub-section">
        <div className="hub-head"><h3>{t('Commercial pipeline')}</h3>{link('pbd', t('Pricing & Budgeting Decisions'))}</div>
        <Pipeline items={[
          [t('PBD in preparation or approval'), pbdOpen.count, pbdOpen.value],
          [t('PBD approved'), pbdApproved.count, pbdApproved.value],
          [t('Client decisions approved'), cdApproved.count, cdApproved.value],
          [t('Quotations sent'), quotesSent.count, quotesSent.value],
          [t('Quotations won'), quotesWon.count, quotesWon.value],
          [t('Quotations lost'), quotesLost.count, quotesLost.value],
        ]} />
        <p className="ec-chips">{Object.entries(data.pipeline.projects).map(([k, v]) => <span key={k} className="ec-chip">{statusLabel(k)} · {v}</span>)}</p>
        <p className="help">
          {Object.entries(data.pipeline.pbd).map(([k, v]) => `${wfLabel(k)} ${v.count}`).join(' · ')}
          {Object.keys(data.pipeline.quotes).length ? ` — ${t('Quotations')}: ${Object.entries(data.pipeline.quotes).map(([k, v]) => `${quoteStatus(k)} ${v.count}`).join(' · ')}` : ''}
        </p>
      </section>
      <section className="hub-section">
        <div className="hub-head"><h3>{t('Contracts and receivables')}</h3>{link('receivables', t('Receivables'))}</div>
        <div className="kpis">
          <Kpi label={t('Contract value (signed)')} value={money(data.contracts.value)} wide sub={t('{n} contracts', { n: data.contracts.count })} />
          <Kpi label={t('Invoiced')} value={money(r.invoiced)} wide sub={t('Paid {amount}', { amount: money(r.paid) })} />
          <Kpi label={t('Outstanding')} value={money(r.outstanding)} wide sub={t('overdue {amount}', { amount: money(r.overdue) })} />
          <Kpi label={t('NPAR')} value={money(r.npar)} wide sub={t('{n} invoices', { n: data.npar.length })} />
          <Kpi label={t('Average cost ratio ABP/revenue')} value={pctText(data.cost_ratio.average_pct)} sub={t('maximum {max} % · {n} approved PBD', { max: number(data.cost_ratio.max_pct), n: data.cost_ratio.approved_pbd })} />
        </div>
      </section>
      <div className="ec-two">
        <AgingBars title={t('Aging by due date')} buckets={data.aging} />
        <AgingBars title={t('Aging since the invoice date')} buckets={data.age_buckets} />
      </div>
      {data.npar.length > 0 && (
        <section className="hub-section">
          <div className="hub-head"><h3>{t('NPAR list')} <span className="muted">{data.npar.length}</span></h3></div>
          <ul className="ec-plain">
            {data.npar.slice(0, 8).map(i => <li key={i.id}><strong>{i.client || '–'}</strong> · {i.number} · {money(i.outstanding)} · {t('{n} days since invoice', { n: i.days_since_invoice })}</li>)}
          </ul>
        </section>
      )}
      {data.projects_budget.length > 0 && (
        <section className="hub-section">
          <div className="hub-head"><h3>{t('Project budget and realisation')}</h3>{link('work_plans', t('Weekly work plans'))}</div>
          <ScrollTable>
            <table className="data-table">
              <thead><tr><th>{t('Project')}</th><th className="num">{t('PBD budget')}</th><th className="num">{t('Budget plan')}</th><th className="num">{t('Realised cost')}</th>
                <th className="num">{t('Planned')}</th><th className="num">{t('Actual')}</th><th className="num">{t('Deviation')}</th><th className="num">{t('Cost ratio')}</th></tr></thead>
              <tbody>
                {data.projects_budget.map(p => (
                  <tr key={p.id} className={onOpen ? 'clickable' : undefined} onClick={() => onOpen?.('work_plans', { open: p.id })}>
                    <td><strong>{p.project || '–'}</strong><div className="bh-sub">{p.number}{p.report_week ? ` · ${t('week {w} of {n}', { w: p.report_week, n: p.duration_weeks ?? '–' })}` : ''}</div></td>
                    <td className="num nowrap">{money(p.pbd_budget)}</td>
                    <td className="num nowrap">{money(p.plan_budget)}</td>
                    <td className="num nowrap">{money(p.realised)}</td>
                    <td className="num">{pctText(p.planned_pct)}</td>
                    <td className="num">{pctText(p.actual_pct)}</td>
                    <td className={`num${(p.deviation_pct ?? 0) < -5 ? ' ec-bad' : ''}`}>{p.deviation_pct === null ? '–' : number(p.deviation_pct)}</td>
                    <td className="num">{pctText(p.cost_ratio_pct)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </ScrollTable>
        </section>
      )}
      <div className="ec-two">
        <section className="card">
          <h3 className="card-title">{t('Clients by service')}</h3>
          <StatTable rows={data.clients_by_service.map(x => ({ label: t(x.label), clients: x.clients, projects: x.projects, value: x.contract_value }))} />
        </section>
        <section className="card">
          <h3 className="card-title">{t('Clients by province')}</h3>
          <StatTable rows={data.clients_by_province.map(x => ({ label: x.key ? `${x.label}${x.zone ? ` (${t('zone')} ${x.zone})` : ''}` : t(x.label), clients: x.clients, projects: x.projects, value: x.contract_value }))} />
        </section>
      </div>
      <section className="hub-section">
        <div className="hub-head"><h3>{t('Bank guarantees and SKBDN')}</h3>{link('guarantees', t('Bank guarantees & SKBDN'))}</div>
        <p>{t('{n} in force, together {amount}.', { n: data.guarantees.active, amount: money(data.guarantees.amount) })}</p>
        {data.guarantees.expiring.length > 0 && (
          <ul className="ec-plain">
            {data.guarantees.expiring.map(g => (
              <li key={g.id}><Tone value={g.status}>{g.number}</Tone> · {typeLabel(g.type)} · {money(g.amount)} · {formatDate(g.expiry_date)}
                {' '}({(g.days ?? 0) < 0 ? t('expired {n} days ago', { n: -(g.days ?? 0) }) : t('{n} days left', { n: g.days ?? 0 })})</li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}

function StatTable({ rows }: { rows: Array<{ label: string, clients: number, projects: number, value: number }> }) {
  if (!rows.length) return <p className="muted small">{t('No projects yet.')}</p>
  return (
    <ScrollTable>
      <table className="data-table">
        <thead><tr><th /><th className="num">{t('Clients')}</th><th className="num">{t('Projects')}</th><th className="num">{t('Contract value')}</th></tr></thead>
        <tbody>{rows.map(r => <tr key={r.label}><td>{r.label}</td><td className="num">{r.clients}</td><td className="num">{r.projects}</td><td className="num nowrap">{money(r.value)}</td></tr>)}</tbody>
      </table>
    </ScrollTable>
  )
}
