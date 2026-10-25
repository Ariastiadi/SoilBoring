/** Soil groups shared by the bore log sheet, the profile view and the strata strips. */

// Graphic log patterns per USCS group (first symbol of dual symbols such as SP-SM).
export type Pattern = 'clay' | 'silt' | 'sand' | 'gravel' | 'organic' | 'peat' | 'unknown'

export function patternOf(uscs: string): Pattern {
  const first = (uscs || '').toUpperCase().split(/[-/ ]/)[0]
  if (first === 'PT') return 'peat'
  if (first === 'OL' || first === 'OH') return 'organic'
  if (first.startsWith('C')) return 'clay'
  if (first.startsWith('M')) return 'silt'
  if (first.startsWith('S')) return 'sand'
  if (first.startsWith('G')) return 'gravel'
  return 'unknown'
}

// Shown when a layer has no written description.
export const USCS_NAMES: Record<Pattern, string> = {
  clay: 'Clay', silt: 'Silt', sand: 'Sand', gravel: 'Gravel', organic: 'Organic soil', peat: 'Peat', unknown: '',
}

export const FILL: Record<Pattern, string> = {
  clay: '#d9c7a7', silt: '#e6d9b8', sand: '#f3e3a1', gravel: '#e8c98f', organic: '#b9b39a', peat: '#8d7b62', unknown: '#dddddd',
}

/**
 * Column width by grain size, as on a sedimentary graphic log: fine soils draw narrow,
 * coarse soils wide, so a coarsening or fining sequence is visible at a glance.
 */
export const GRAIN_WIDTH: Record<Pattern, number> = {
  peat: 0.38, organic: 0.45, clay: 0.5, silt: 0.62, sand: 0.8, gravel: 1, unknown: 0.62,
}

export const PATTERN_ORDER: Pattern[] = ['clay', 'silt', 'sand', 'gravel', 'organic', 'peat']

/** SVG <pattern> fills. `prefix` keeps ids unique when several drawings share a page. */
export function PatternDefs({ prefix = 'p' }: { prefix?: string }) {
  return (
    <defs>
      <pattern id={`${prefix}-clay`} width="12" height="6" patternUnits="userSpaceOnUse">
        <rect width="12" height="6" fill={FILL.clay} /><line x1="0" y1="3" x2="12" y2="3" stroke="#6b5a3c" strokeWidth="0.8" />
      </pattern>
      <pattern id={`${prefix}-silt`} width="12" height="6" patternUnits="userSpaceOnUse">
        <rect width="12" height="6" fill={FILL.silt} /><line x1="1" y1="3" x2="6" y2="3" stroke="#6b5a3c" strokeWidth="0.8" />
        <circle cx="9" cy="3" r="0.7" fill="#6b5a3c" />
      </pattern>
      <pattern id={`${prefix}-sand`} width="8" height="8" patternUnits="userSpaceOnUse">
        <rect width="8" height="8" fill={FILL.sand} /><circle cx="2" cy="2" r="0.8" fill="#7a6430" /><circle cx="6" cy="6" r="0.8" fill="#7a6430" />
      </pattern>
      <pattern id={`${prefix}-gravel`} width="14" height="12" patternUnits="userSpaceOnUse">
        <rect width="14" height="12" fill={FILL.gravel} /><circle cx="4" cy="4" r="2.4" fill="none" stroke="#6b4f20" strokeWidth="0.8" />
        <circle cx="11" cy="9" r="2" fill="none" stroke="#6b4f20" strokeWidth="0.8" />
      </pattern>
      <pattern id={`${prefix}-organic`} width="12" height="8" patternUnits="userSpaceOnUse">
        <rect width="12" height="8" fill={FILL.organic} /><path d="M1 4 q2 -2 4 0 t4 0" fill="none" stroke="#3f3a2a" strokeWidth="0.8" />
      </pattern>
      <pattern id={`${prefix}-peat`} width="8" height="8" patternUnits="userSpaceOnUse">
        <rect width="8" height="8" fill={FILL.peat} /><line x1="0" y1="8" x2="8" y2="0" stroke="#3b2f20" strokeWidth="0.9" />
      </pattern>
      <pattern id={`${prefix}-unknown`} width="8" height="8" patternUnits="userSpaceOnUse">
        <rect width="8" height="8" fill={FILL.unknown} /><path d="M0 0 L8 8 M8 0 L0 8" stroke="#777" strokeWidth="0.5" />
      </pattern>
    </defs>
  )
}
