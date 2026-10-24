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
