/**
 * Interface language: Bahasa Indonesia (default) or English.
 *
 * Texts are written in English in the code and wrapped in t('...'); the Indonesian
 * translation is looked up in ./i18n-id.ts. A missing entry simply shows the English text.
 * Placeholders such as {n} are filled from the second argument.
 */
import { ID } from './i18n-id'

export type Lang = 'id' | 'en'
const KEY = 'soilboring-lang'

function initial(): Lang {
  try {
    const saved = localStorage.getItem(KEY)
    if (saved === 'id' || saved === 'en') return saved
  } catch {
    // storage blocked
  }
  return 'id'
}

let current: Lang = initial()

export function lang(): Lang {
  return current
}

/** Switches the language; the page reloads so every screen picks it up. */
export function setLang(next: Lang) {
  if (next === current) return
  current = next
  try { localStorage.setItem(KEY, next) } catch { /* ignore */ }
  window.location.reload()
}

export function t(text: string, vars?: Record<string, string | number>): string {
  let out = current === 'id' ? (ID[text] ?? text) : text
  if (vars) {
    for (const [k, v] of Object.entries(vars)) out = out.split(`{${k}}`).join(String(v))
  }
  return out
}

/** Locale for numbers and dates. */
export function locale(): string {
  return current === 'id' ? 'id-ID' : 'en-GB'
}

if (typeof document !== 'undefined') document.documentElement.lang = current

// Field names the server uses in its messages.
const FIELD_NAMES: Record<string, string> = {
  BoreholeID: 'Borehole ID', ProjectName: 'Project', SiteName: 'Site / Zone', StartDate: 'Start Date', EndDate: 'End Date',
  FinalDepth_m: 'Final Depth (m)', TargetDepth_m: 'Target Depth (m)', GroundwaterDepth_m: 'Groundwater Depth (m)',
  BoreholeDiameter_mm: 'Borehole Diameter (mm)', CasingInstalled_mm: 'Casing Installed (mm)', Avg_SPT_N60: 'Average SPT N60',
  Latitude: 'Latitude', Longitude: 'Longitude', GroundElevation_mRL: 'Ground Elevation (mRL)', Contractor: 'Contractor',
  LoggingGeologist: 'Logging Geologist', DrillRig: 'Drill Rig / Plant', SoilDescription: 'Soil Description', Remarks: 'Remarks',
  CoreSize: 'Core Size (wireline)', USCS_Class: 'USCS', DrillingMethod: 'Drilling Method', email: 'Email', password: 'Password',
  top: 'From (m)', base: 'To (m)', depth: 'Depth (m)', seat: 'Seating', inc1: 'Test 1', inc2: 'Test 2', penetration_mm: 'Refusal at (mm)',
  ref: 'Ref.', remarks: 'Remarks', caption: 'Caption', layers: 'Strata', spt: 'SPT', samples: 'Samples', core: 'Core runs',
  description: 'Soil / rock description', tcr: 'TCR %', scr: 'SCR %', rqd: 'RQD %', type: 'Type',
}
const field = (name: string) => (FIELD_NAMES[name] ? t(FIELD_NAMES[name]) : name)
/** Readable name of a stored field (FinalDepth_m -> "Final Depth (m)" in the interface language). */
export const fieldLabel = field

// Messages with values in them, as the server writes them.
const PATTERNS: Array<[RegExp, (m: RegExpMatchArray) => string]> = [
  [/^A borehole with ID '(.+)' already exists$/, m => t("A borehole with ID '{id}' already exists", { id: m[1] })],
  [/^Invalid (.+); use YYYY-MM-DD$/, m => t('{field} is not a valid date', { field: field(m[1]) })],
  [/^Password must be at least (\d+) characters$/, m => t('Password must be at least {n} characters', { n: m[1] })],
  [/^You can only \w+ logs you submitted$/, () => t('You can only edit logs you submitted')],
  [/^(\w+) must be at most (\d+) characters$/, m => t('{field} must be at most {n} characters', { field: field(m[1]), n: m[2] })],
  [/^must be at most (\d+) characters$/, m => t('At most {n} characters', { n: m[1] })],
  [/^(\w+) must be a (finite )?number$/, m => t('{field} must be a number', { field: field(m[1]) })],
  [/^(.+) cannot be negative$/, m => t('{label} cannot be negative.', { label: field(m[1]) })],
  [/^(\w+) must use YYYY-MM-DD$/, m => t('{field} is not a valid date', { field: field(m[1]) })],
  [/^(\w+) cannot be empty$/, m => t('{label} is required.', { label: field(m[1]) })],
  [/^CoreSize must be one of (.+)$/, m => t('Core size must be one of {list}', { list: m[1] })],
  [/^sample type must be one of (.+)$/, m => t('Sample type must be one of {list}', { list: m[1] })],
  [/^(Layers|Core runs) ([\d.]+)-([\d.]+) m and ([\d.]+)-([\d.]+) m overlap$/,
    m => t('{what} {a} m and {b} m overlap', { what: t(m[1] === 'Layers' ? 'Strata' : 'Core runs'), a: `${m[2]}–${m[3]}`, b: `${m[4]}–${m[5]}` })],
  [/^A borehole can have at most (\d+) photos$/, m => t('A borehole can have at most {n} photos', { n: m[1] })],
  [/^(.+) saved this borehole at .+; reload to see their changes before saving$/, m => t('{who} saved this borehole in the meantime; reload to see their changes before saving', { who: m[1] })],
  [/^Role must be one of: (.+)$/, () => t('Choose a valid role')],
  // FastAPI / pydantic wording
  [/^Field required$/, () => t('Required')],
  [/^Input should be greater than or equal to (.+)$/, m => t('Must be {n} or more', { n: m[1] })],
  [/^Input should be greater than (.+)$/, m => t('Must be more than {n}', { n: m[1] })],
  [/^Input should be less than or equal to (.+)$/, m => t('Must be {n} or less', { n: m[1] })],
  [/^String should have at least (\d+) characters?$/, m => t('At least {n} characters', { n: m[1] })],
  [/^String should have at most (\d+) characters?$/, m => t('At most {n} characters', { n: m[1] })],
  [/^List should have at most (\d+) items.*$/, m => t('At most {n} rows', { n: m[1] })],
  [/^Input should be a valid (number|integer).*$/, () => t('Must be a number')],
  [/^Input should be a finite number$/, () => t('Must be a number')],
  [/^value is not a valid email address.*$/, () => t('Enter a valid email address (name@domain)')],
]

function translateOne(text: string): string | null {
  if (ID[text]) return ID[text]
  for (const [re, fn] of PATTERNS) {
    const m = text.match(re)
    if (m) return fn(m)
  }
  return null
}

/** Server messages are in English; shown in the interface language. */
export function translateServer(message: string): string {
  if (current === 'en' || !message) return message
  const whole = translateOne(message)
  if (whole !== null) return whole
  // Validation errors come as "field: message; field: message".
  return message.split('; ').map(part => {
    const fieldPart = /^(\w+): (.+)$/.exec(part)
    const [prefix, text] = fieldPart && FIELD_NAMES[fieldPart[1]] ? [`${field(fieldPart[1])}: `, fieldPart[2]] : ['', part]
    return prefix + (translateOne(text) ?? text)
  }).join('; ')
}
