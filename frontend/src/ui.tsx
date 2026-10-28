/** Small shared pieces of the interface: page heading, date field, icons. */
import { ReactNode, useEffect, useId, useRef, useState } from 'react'
import { t } from './i18n'

/** "2026-10-21" -> "21/10/2026"; anything else is shown as it is. */
export function formatDate(iso?: string | null): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || '')
  return m ? `${m[3]}/${m[2]}/${m[1]}` : (iso || '')
}

/** "21/10/2026" (or 21-10-2026, 21.10.2026) -> "2026-10-21"; '' when not a real date. */
export function parseDate(text: string): string {
  const m = /^\s*(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})\s*$/.exec(text)
  if (!m) return ''
  const [d, mo, y] = [Number(m[1]), Number(m[2]), Number(m[3])]
  const date = new Date(Date.UTC(y, mo - 1, d))
  if (date.getUTCFullYear() !== y || date.getUTCMonth() !== mo - 1 || date.getUTCDate() !== d) return ''
  return `${y}-${String(mo).padStart(2, '0')}-${String(d).padStart(2, '0')}`
}

export function todayIso(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

/**
 * Date typed as dd/mm/yyyy whatever the browser language, with a calendar button.
 * `value` and `onChange` use ISO dates (yyyy-mm-dd); '' while the text is not a full date.
 */
export function DateInput({ id, value, onChange, required, label, disabled }: {
  id?: string, value: string, onChange: (iso: string) => void, required?: boolean, label?: string, disabled?: boolean
}) {
  const [text, setText] = useState(formatDate(value))
  const [touched, setTouched] = useState(false)
  const picker = useRef<HTMLInputElement>(null)
  useEffect(() => {
    if (parseDate(text) !== value) setText(formatDate(value))
  }, [value]) // eslint-disable-line react-hooks/exhaustive-deps

  const type = (raw: string) => {
    let next = raw.replace(/[^\d/.-]/g, '')
    // Typing 21102026 becomes 21/10/2026.
    if (/^\d{8}$/.test(next)) next = `${next.slice(0, 2)}/${next.slice(2, 4)}/${next.slice(4)}`
    else if (/^\d{2}$/.test(next) && text.length < next.length) next += '/'
    else if (/^\d{2}\/\d{2}$/.test(next) && text.length < next.length) next += '/'
    setText(next)
    onChange(parseDate(next))
  }
  const invalid = touched && text.trim() !== '' && !parseDate(text)
  const open = () => {
    const el = picker.current
    if (!el) return
    try { (el as HTMLInputElement & { showPicker?: () => void }).showPicker?.() } catch { el.focus() }
  }
  return (
    <div className="date-input">
      <input id={id} type="text" inputMode="numeric" value={text} placeholder={t('dd/mm/yyyy')} maxLength={10}
        onChange={e => type(e.target.value)} onBlur={() => setTouched(true)} required={required}
        aria-invalid={invalid || undefined} aria-label={label} disabled={disabled} autoComplete="off" />
      <button type="button" onClick={open} aria-label={t('Open calendar')} title={t('Open calendar')} disabled={disabled}>
        <Icon name="calendar" />
      </button>
      <input ref={picker} type="date" tabIndex={-1} aria-hidden="true" value={value}
        onChange={e => { onChange(e.target.value); setText(formatDate(e.target.value)) }} />
    </div>
  )
}

/** Label + control + optional help text, with "required" marked in words. */
export function Field({ label, required, help, children, wide, htmlFor }: {
  label: ReactNode, required?: boolean, help?: ReactNode, children: ReactNode, wide?: boolean, htmlFor?: string
}) {
  const auto = useId()
  return (
    <div className={`field${wide ? ' wide' : ''}`}>
      <label htmlFor={htmlFor ?? auto}>{label}{required && <span className="tag-req">{t('required')}</span>}</label>
      {children}
      {help && <p className="help">{help}</p>}
    </div>
  )
}

export function PageHead({ title, description, actions, back }: { title: ReactNode, description?: ReactNode, actions?: ReactNode, back?: ReactNode }) {
  return (
    <header className="page-head">
      <div>
        {back}
        <h1>{title}</h1>
        {description && <p>{description}</p>}
      </div>
      {actions && <div className="actions">{actions}</div>}
    </header>
  )
}

const PATHS: Record<string, string> = {
  boreholes: 'M6 3v18M6 6h5M6 10h8M6 14h6M6 18h9M17 3v18',
  plus: 'M12 5v14M5 12h14',
  ai: 'M4 5h16v11H9l-5 4zM8 9h8M8 12h5',
  summary: 'M6 3h9l4 4v14H6zM9 11h7M9 15h7M9 7h3',
  chart: 'M4 20V4M4 20h16M8 16v-5M12 16V8M16 16v-3',
  more: 'M5 12h.01M12 12h.01M19 12h.01',
  users: 'M9 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7zM2.5 20c.6-3.4 3.2-5.5 6.5-5.5s5.9 2.1 6.5 5.5M16 4.6a3.5 3.5 0 0 1 0 6.8M18.5 14.8c1.6.8 2.7 2.6 3 5.2',
  activity: 'M3 12h4l3-8 4 16 3-8h4',
  info: 'M12 8h.01M11 12h1v5h1M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z',
  account: 'M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21c.8-4 4-6 8-6s7.2 2 8 6',
  logout: 'M15 4h4v16h-4M10 8l-4 4 4 4M6 12h10',
  language: 'M4 5h9M8.5 3v2M6 5c.5 3.5 2.6 6.4 6 8M11 5c-.7 3.8-3.3 7-7 8.5M13 21l4-9 4 9M14.4 18h5.2',
  calendar: 'M4 6h16v14H4zM4 10h16M8 3v4M16 3v4',
  back: 'M15 6l-6 6 6 6',
  map: 'M3 6l6-2 6 2 6-2v14l-6 2-6-2-6 2zM9 4v14M15 6v14',
  list: 'M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01',
  download: 'M12 4v11M7 10l5 5 5-5M5 20h14',
  filter: 'M4 5h16l-6 7v6l-4 2v-8z',
  close: 'M6 6l12 12M18 6L6 18',
  folder: 'M3 6h6l2 2h10v11H3z',
  building: 'M4 21V4h11v17M15 9h5v12M8 8h3M8 12h3M8 16h3M3 21h18',
  tag: 'M3 12V4h8l10 10-8 8zM7.5 8.5h.01',
  contract: 'M6 3h9l4 4v14H6zM9 13h7M9 17h4M14 3v5h5',
  cone: 'M12 3v12M8 15h8l-4 6zM9 7h6M9 11h6',
  flask: 'M9 3h6M10 3v6l-5 9a2 2 0 0 0 2 3h10a2 2 0 0 0 2-3l-5-9V3M7.5 14h9',
  print: 'M7 8V3h10v5M6 17H4v-7h16v7h-2M7 14h10v7H7z',
  sheet: 'M5 3h14v18H5zM5 8h14M5 13h14M10 8v13',
  pin: 'M12 21s-7-6.2-7-11.5A7 7 0 0 1 19 9.5C19 14.8 12 21 12 21zM12 12a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5z',
  book: 'M5 4h6a3 3 0 0 1 3 3v13a2.5 2.5 0 0 0-2.5-2.5H5zM19 4h-5M19 4v13.5h-5',
  sample: 'M9 3h6M10 3v15a2 2 0 0 0 4 0V3M10 9h4',
  trash: 'M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3',
  check: 'M4 12.5l5 5L20 6.5',
  truck: 'M3 6h11v10H3zM14 9h4l3 3v4h-7M7 19a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM17 19a2 2 0 1 0 0-4 2 2 0 0 0 0 4z',
  wrench: 'M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.5 2.5-2.4-.6-.6-2.4z',
  cart: 'M3 4h2l2.4 11h10.2L20 7H6.2M9 20a1 1 0 1 0 0-2 1 1 0 0 0 0 2zM17 20a1 1 0 1 0 0-2 1 1 0 0 0 0 2z',
  target: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM12 12h.01',
  rig: 'M8 21h8M12 21V3M9 3h6M7 8l5-5 5 5M10 12h4M10 16h4',
  calc: 'M5 3h14v18H5zM8 7h8M8 11h2M12 11h2M16 11v6M8 15h2M12 15h2M8 18h6',
  invoice: 'M6 3h12v18l-3-2-3 2-3-2-3 2zM9 8h6M9 12h6M9 16h3',
  settings: 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-1.8-.3 1.6 1.6 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.6 1.6 0 0 0-1-1.5 1.6 1.6 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.6 1.6 0 0 0 .3-1.8 1.6 1.6 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.6 1.6 0 0 0 1.5-1 1.6 1.6 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.6 1.6 0 0 0 1.8.3H9a1.6 1.6 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.6 1.6 0 0 0 1 1.5 1.6 1.6 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0-.3 1.8V9a1.6 1.6 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.6 1.6 0 0 0-1.5 1z',
}

export function Icon({ name, size = 18 }: { name: keyof typeof PATHS | string, size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      <path d={PATHS[name] || ''} />
    </svg>
  )
}

/** The app's mark: a short borehole column of three strata. */
export function BrandMark({ className = 'brand-mark' }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 26 34" aria-hidden="true" focusable="false">
      <rect x="1" y="1" width="24" height="32" rx="2" fill="#fff" stroke="#23282d" strokeWidth="1.5" />
      <rect x="4" y="4" width="18" height="7" fill="#e6d9b8" />
      <rect x="4" y="11" width="12" height="9" fill="#d9c7a7" />
      <rect x="4" y="20" width="18" height="10" fill="#e8c98f" />
      <path d="M4 11h18M4 20h18" stroke="#23282d" strokeWidth="1" />
      <rect x="4" y="4" width="18" height="26" fill="none" stroke="#23282d" strokeWidth="1" />
      <path d="M13 0v6" stroke="#ddb000" strokeWidth="3" />
    </svg>
  )
}

/** Counts as horizontal bars, largest first (method mix, USCS classes). */
export function Breakdown({ title, entries, label = (k: string) => k, ordered = false, format = (n: number) => String(n), note }: {
  title: string, entries: Array<[string, number]>, label?: (key: string) => string,
  /** Keep the order given (e.g. depth ranges) instead of largest first. */
  ordered?: boolean, format?: (n: number) => string, note?: string
}) {
  const sorted = ordered ? entries : [...entries].sort((a, b) => b[1] - a[1])
  const max = Math.max(1, ...sorted.map(([, n]) => n))
  return (
    <section className="card">
      <h3>{title}</h3>
      <ul className="bars">
        {sorted.map(([key, n]) => (
          <li key={key}>
            <span>{label(key)}</span>
            <span className="bar" aria-hidden="true"><span style={{ width: `${(n / max) * 100}%` }} /></span>
            <span className="num">{format(n)}</span>
          </li>
        ))}
      </ul>
      {note && <p className="help" style={{ marginBottom: 0 }}>{note}</p>}
    </section>
  )
}

/** Rewrites every yyyy-mm-dd inside a text as dd/mm/yyyy. */
export const prettyDates = (text?: string | null) => (text || '').replace(/\d{4}-\d{2}-\d{2}/g, m => formatDate(m)).replace(/(\d{2}\/\d{2}\/\d{4}) (to|s\.d\.) (\d{2}\/\d{2}\/\d{4})/g, '$1 – $3')

export const ROLE_LABELS: Record<string, string> = {
  admin: 'Administrator', manager: 'Project leader / commercial', general: 'Field user', lab: 'Laboratory', finance: 'Finance',
  client: 'Client (read only)',
}

/** A wide table that says so: a fade on the edge and a hint while columns are hidden to the right. */
export function ScrollTable({ children, maxHeight }: { children: ReactNode, maxHeight?: string }) {
  const ref = useRef<HTMLDivElement>(null)
  const [more, setMore] = useState(false)
  const [moved, setMoved] = useState(false)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const update = () => {
      setMore(el.scrollLeft + el.clientWidth < el.scrollWidth - 2)
      setMoved(el.scrollLeft > 2)
    }
    update()
    el.addEventListener('scroll', update, { passive: true })
    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(update) : null
    ro?.observe(el)
    return () => { el.removeEventListener('scroll', update); ro?.disconnect() }
  }, [])
  return (
    <div className={`scroll-x${more ? ' more-right' : ''}${moved ? ' moved' : ''}`}>
      {more && <p className="scroll-hint" aria-hidden="true">{t('Scroll sideways for more columns')} →</p>}
      <div className="scroll-frame">
        <div ref={ref} className="table-wrap" tabIndex={0} style={maxHeight ? { maxHeight, overflowY: 'auto' } : undefined}>{children}</div>
      </div>
    </div>
  )
}

