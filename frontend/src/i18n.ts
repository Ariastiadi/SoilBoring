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
  // engineering analysis inputs
  B: 'Footing width B (m)', L: 'Footing length L (m, empty = strip)', Df: 'Founding depth Df (m)', c: 'Cohesion c (kPa)',
  phi_deg: 'Friction angle φ (°)', gamma: 'Unit weight γ (kN/m³)', gamma_sat: 'Saturated unit weight γsat (kN/m³)',
  gw_depth: 'Groundwater depth (m, empty = deep)', fs: 'Factor of safety', diameter: 'Pile diameter D (m)', length: 'Pile length L (m)',
  fs_shaft: 'Factor of safety, shaft', fs_tip: 'Factor of safety, tip', q: 'Net applied pressure q (kPa)',
  amax_g: 'Peak ground acceleration amax (g)', magnitude: 'Earthquake magnitude Mw', energy_ratio: 'SPT hammer energy ratio (%)',
}
const field = (name: string) => (FIELD_NAMES[name] ? t(FIELD_NAMES[name]) : name)
/** Where a record error happened: a field label, or "Items row 2, Unit price". */
const where = (text: string): string => {
  const row = /^(.+) row (\d+)(?:, (.+))?$/.exec(text)
  if (row) return row[3] ? t('{field} row {i}, {sub}', { field: where(row[1]), i: row[2], sub: where(row[3]) }) : `${where(row[1])} #${row[2]}`
  return FIELD_NAMES[text] ? field(text) : t(text)
}
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
  // business records (records.py)
  [/^(.+): choose one of the listed options$/, m => t('{field}: choose one of the listed options', { field: where(m[1]) })],
  [/^(.+): choose from the list$/, m => t('{field}: choose from the list', { field: where(m[1]) })],
  [/^(.+): the chosen record no longer exists$/, m => t('{field}: the chosen record no longer exists', { field: where(m[1]) })],
  [/^(.+): at most (\d+) rows$/, m => t('{field}: at most {n} rows', { field: where(m[1]), n: m[2] })],
  [/^(.+): at most 30 files$/, m => t('{field}: at most 30 files', { field: where(m[1]) })],
  [/^(.+): a file was not found; upload it again$/, m => t('{field}: a file was not found; upload it again', { field: where(m[1]) })],
  [/^(.+): this option does not belong to the chosen (\w+)$/, m => t('{field}: this option does not belong to the chosen {other}', { field: where(m[1]), other: where(m[2]) })],
  [/^(.+): enter a valid email address \(name@domain\)$/, m => t('{field}: enter a valid email address (name@domain)', { field: where(m[1]) })],
  [/^(.+) '(.+)' is already used$/, m => t("{label} '{value}' is already used", { label: where(m[1]), value: m[2] })],
  [/^(.+) changed this record in the meantime; reload before saving$/, m => t('{who} changed this record in the meantime; reload before saving', { who: m[1] === 'Someone' ? t('Someone') : m[1] })],
  [/^Still used by: (.+)$/, m => t('Still used by: {list}', { list: m[1] })],
  [/^(\d+) SPT liquefiable, shallowest at (.+) m$/, m => t('{n} SPT liquefiable, shallowest at {d} m', { n: m[1], d: m[2] })],
  [/^Settlement = (.+) mm$/, m => t('Settlement = {v} mm', { v: m[1] })],
  // engineering notes and checks (engineering.py)
  [/^Layer (\d+): Cr is larger than Cc; check the input\.$/, m => t('Layer {i}: Cr is larger than Cc; check the input.', { i: m[1] })],
  [/^Layer (\d+): sigma_p is below the in-situ effective stress; treated as normally consolidated\.$/, m => t('Layer {i}: sigma_p is below the in-situ effective stress; treated as normally consolidated.', { i: m[1] })],
  [/^No layer defined at (.+) m; treated as clay \(conservative\)\.$/, m => t('No layer defined at {d} m; treated as clay (conservative).', { d: m[1] })],
  [/^USCS '(.*)' not recognised; treated as clay \(conservative\)\.$/, m => t("USCS '{u}' not recognised; treated as clay (conservative).", { u: m[1] })],
  [/^USCS '(.*)' not recognised; evaluated as clean sand \(FC = 5%, conservative\)\.$/, m => t("USCS '{u}' not recognised; evaluated as clean sand (FC = 5%, conservative).", { u: m[1] })],
  [/^no layer defined at (.+) m$/, m => t('no layer defined at {d} m', { d: m[1] })],
  [/^effective stress is not positive at (.+) m; check unit weights$/, m => t('effective stress is not positive at {d} m; check unit weights', { d: m[1] })],
  [/^effective stress is not positive at (.+) m$/, m => t('effective stress is not positive at {d} m', { d: m[1] })],
  [/^duplicate SPT depth (.+) m$/, m => t('duplicate SPT depth {d} m', { d: m[1] })],
  [/^depth (.+) m is below the deepest layer$/, m => t('depth {d} m is below the deepest layer', { d: m[1] })],
  [/^(\w+) must be greater than (.+)$/, m => `${field(m[1])}: ${t('Must be more than {n}', { n: m[2] })}`],
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
  // general forms, after the specific ones above
  [/^(.+) must be a number$/, m => t('{field} must be a number', { field: where(m[1]) })],
  [/^(.+) must be at least (.+)$/, m => t('{field} must be at least {n}', { field: where(m[1]), n: m[2] })],
  [/^(.+) must be at most (\d+) characters$/, m => t('{field} must be at most {n} characters', { field: where(m[1]), n: m[2] })],
  [/^(.+) must be at most (.+)$/, m => t('{field} must be at most {n}', { field: where(m[1]), n: m[2] })],
  [/^(.+) is not a valid date$/, m => t('{field} is not a valid date', { field: where(m[1]) })],
  [/^(.+) is required$/, m => t('{field} is required', { field: where(m[1]) })],
  [/^(.+) is not valid$/, m => t('{field} is not valid', { field: where(m[1]) })],
  [/^(.+) is too large$/, m => t('{field} is too large', { field: where(m[1]) })],
  [/^(.+) must be a list$/, m => t('{field} must be a list', { field: where(m[1]) })],
  [/^(.+) must be text$/, m => t('{field} must be text', { field: where(m[1]) })],
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
