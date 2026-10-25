import { createContext, useContext } from 'react'

export type TabKey =
  | 'boreholes' | 'new' | 'cpt' | 'fieldwork' | 'lab'
  | 'projects' | 'clients' | 'quotes' | 'contracts'
  | 'analyses' | 'reports' | 'invoices' | 'rates'
  | 'qa' | 'summary' | 'dashboard' | 'about' | 'users' | 'activity' | 'settings' | 'account'
  | 'worksheets' | 'standards' | 'coordinates' | 'samples' | 'labsummary'

/** Where to go, and what to open there: a record, or a new one with values filled in. */
export type Intent = { open?: string, newWith?: Record<string, unknown>, borehole?: string }

export type Nav = { go: (tab: TabKey, intent?: Intent) => void, role: string, email: string }

export const NavContext = createContext<Nav>({ go: () => {}, role: 'general', email: '' })
export const useNav = () => useContext(NavContext)
