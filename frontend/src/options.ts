// Shared by the new-log form and the edit form so both offer the same choices.
export const METHOD_OPTIONS = [
  'Wash Boring + SPT',
  'Rotary Wash + SPT',
  'Hollow Stem Auger',
  'Coring + SPT',
  'CPT / CPTu (Sondir)',
  'Hand Auger',
]

// All USCS group symbols (ASTM D2487); the first entry is the form default.
export const USCS_OPTIONS = [
  'CL', 'ML', 'SM', 'SC', 'GC', 'SP', 'SW',
  'CH', 'MH', 'OL', 'OH', 'GW', 'GP', 'GM', 'PT',
]

// Keeps a stored value that is not in the list selectable (older or imported logs).
export function withCurrent(options: string[], current: string | undefined | null): string[] {
  return current && !options.includes(current) ? [current, ...options] : options
}

// Wireline (Q-series) core sizes: nominal hole and core diameters in mm.
export const CORE_SIZES: Array<{ code: string; hole: number; core: number }> = [
  { code: 'AQ', hole: 48, core: 27 },
  { code: 'BQ', hole: 60, core: 36.5 },
  { code: 'NQ', hole: 75.7, core: 47.6 },
  { code: 'HQ', hole: 96, core: 63.5 },
  { code: 'PQ', hole: 122.6, core: 85 },
]

export const coreSizeLabel = (code: string) => {
  const size = CORE_SIZES.find(s => s.code === code)
  return size ? `${size.code} (hole ${size.hole} mm, core ${size.core} mm)` : code
}
