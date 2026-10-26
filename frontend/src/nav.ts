import { createContext, useContext } from 'react'

export type TabKey =
  | 'boreholes' | 'new' | 'cpt' | 'fieldwork' | 'lab'
  | 'projects' | 'clients' | 'quotes' | 'contracts'
  | 'analyses' | 'reports' | 'invoices' | 'rates'
  | 'qa' | 'summary' | 'dashboard' | 'about' | 'users' | 'activity' | 'settings' | 'account'
  | 'worksheets' | 'standards' | 'coordinates' | 'samples' | 'labsummary'
  | 'approvals' | 'overview'
  | 'equipment' | 'mobilisations' | 'work_orders' | 'vendors' | 'procurements' | 'purchase_orders' | 'fixed_assets' | 'performance' | 'ops_settings'
  | 'pbd' | 'client_decisions' | 'work_plans' | 'guarantees' | 'receivables' | 'client_cards' | 'pricing_settings'
  | 'sample_receipts' | 'nonconformities' | 'vendor_evaluations'

/** Where to go, and what to open there: a record, or a new one with values filled in. */
export type Intent = { open?: string, newWith?: Record<string, unknown>, borehole?: string }

export type Nav = { go: (tab: TabKey, intent?: Intent) => void, role: string, email: string }

export const NavContext = createContext<Nav>({ go: () => {}, role: 'general', email: '' })
export const useNav = () => useContext(NavContext)

/** The page that opens a record of each entity (approvals inbox, dashboard links). */
export const ENTITY_TAB: Record<string, TabKey> = {
  clients: 'clients', projects: 'projects', quotes: 'quotes', contracts: 'contracts', invoices: 'invoices', rates: 'rates',
  cpt: 'cpt', field_activities: 'fieldwork', lab_tests: 'lab', analyses: 'analyses', project_reports: 'reports',
  equipment: 'equipment', mobilisations: 'mobilisations', work_orders: 'work_orders', vendors: 'vendors',
  procurements: 'procurements', purchase_orders: 'purchase_orders', fixed_assets: 'fixed_assets',
  performance_cards: 'performance', ops_settings: 'ops_settings',
  pbd: 'pbd', client_decisions: 'client_decisions', work_plans: 'work_plans', guarantees: 'guarantees',
  sample_receipts: 'sample_receipts', nonconformities: 'nonconformities', vendor_evaluations: 'vendor_evaluations',
}
