import { Suspense, lazy, useEffect, useState } from 'react'
import DailyReportForm from './tabs/DailyReportForm'
import QA from './tabs/QA'
import Summary from './tabs/Summary'
import Dashboard from './tabs/Dashboard'
import Boreholes from './tabs/DailyReportData'
import AboutSoilBoring from './tabs/AboutSoilBoring'
import UserAdmin from './tabs/UserAdmin'
import Login from './Login'
import ChangePassword from './ChangePassword'
import Security from './Security'
import Activity from './tabs/Activity'
import { flushOutbox, outboxItems, setOutboxUser, subscribeOutbox, type OutboxItem } from './outbox'
import { confirmLeave } from './unsaved'
import { lang, setLang, t } from './i18n'
import { appTitle, getPublicConfig, login as loginApi, setAuthToken, setUnauthorizedHandler, setupFirstAdmin } from './api'
import type { Role, Session } from './api'
import { BrandMark, Icon, PageHead, ROLE_LABELS } from './ui'
import { NavContext, type Intent, type TabKey } from './nav'
import { SchemaContext, invalidate } from './records'
import { getSchemas, type Schemas } from './api'
import type { Intent as PageIntent } from './nav'

// Business modules load when first opened, so the field log starts fast on a phone.
const business = () => import('./tabs/Business')
type PageProps = { intent?: PageIntent }
const fromBusiness = (name: 'CptPage' | 'ClientsPage' | 'ContractsPage' | 'FieldWorkPage' | 'InvoicesPage' | 'LabPage' | 'ProjectsPage' | 'QuotesPage' | 'RatesPage' | 'ReportsPage' | 'SettingsPage') =>
  lazy(() => business().then(m => ({ default: m[name] as (p: PageProps) => JSX.Element })))
const ProjectsPage = fromBusiness('ProjectsPage')
const ClientsPage = fromBusiness('ClientsPage')
const QuotesPage = fromBusiness('QuotesPage')
const ContractsPage = fromBusiness('ContractsPage')
const CptPage = fromBusiness('CptPage')
const FieldWorkPage = fromBusiness('FieldWorkPage')
const LabPage = fromBusiness('LabPage')
const ReportsPage = fromBusiness('ReportsPage')
const InvoicesPage = fromBusiness('InvoicesPage')
const RatesPage = fromBusiness('RatesPage')
const SettingsPage = fromBusiness('SettingsPage')
const AnalysesPage = lazy(() => import('./tabs/Analyses'))
const worksheetsModule = () => import('./tabs/Worksheets')
const WorksheetCatalogPage = lazy(() => worksheetsModule().then(m => ({ default: m.WorksheetCatalogPage })))
const StandardsPage = lazy(() => worksheetsModule().then(m => ({ default: m.StandardsPage })))
const CoordinatesPage = lazy(() => worksheetsModule().then(m => ({ default: m.CoordinatesPage })))
const SampleRegisterPage = lazy(() => worksheetsModule().then(m => ({ default: m.SampleRegisterPage })))
const LabSummaryPage = lazy(() => worksheetsModule().then(m => ({ default: m.LabSummaryPage })))

type AuthState = { token: string; email: string; role: Role; expiresAt?: number } | null
const ROLES: Role[] = ['admin', 'manager', 'general', 'lab', 'finance']
const AUTH_STORAGE_KEY = 'soilboring-auth'
// AI answers cached in the browser contain data from the logs, so they are cleared when the
// session ends. The unsaved borehole form draft is kept on purpose so field work is never lost.
const USER_DATA_KEYS = ['qa_history']

function clearUserData() {
  if (typeof window === 'undefined') return
  USER_DATA_KEYS.forEach(key => window.localStorage.removeItem(key))
}

type NavItem = { key: TabKey, label: string, icon: string, entity?: string }

export default function App() {
  const [tab, setTab] = useState<TabKey>('boreholes')
  const [auth, setAuth] = useState<AuthState>(() => {
    if (typeof window === 'undefined') return null
    // A password-reset link opened in a browser where someone is signed in: show the reset form.
    if (window.location.hash.startsWith('#reset=')) {
      window.localStorage.removeItem(AUTH_STORAGE_KEY)
      clearUserData()
      return null
    }
    const raw = window.localStorage.getItem(AUTH_STORAGE_KEY)
    if (!raw) return null
    try {
      const parsed = JSON.parse(raw)
      if (parsed?.token && parsed?.email) {
        if (typeof parsed.expiresAt === 'number' && parsed.expiresAt <= Date.now()) {
          window.localStorage.removeItem(AUTH_STORAGE_KEY)
          return null
        }
        const role: Role = ROLES.includes(parsed?.role) ? parsed.role : 'general'
        // Set now, not in an effect: the first page fetches data while mounting.
        setAuthToken(parsed.token)
        return { token: parsed.token, email: parsed.email, role, expiresAt: parsed.expiresAt }
      }
    } catch {
      return null
    }
    return null
  })
  const [authNotice, setAuthNotice] = useState('')
  const [notice, setNotice] = useState('')
  const [moreOpen, setMoreOpen] = useState(false)
  const [intent, setIntent] = useState<Intent | undefined>(undefined)
  const [navCount, setNavCount] = useState(0)
  const [schemas, setSchemas] = useState<Schemas | null>(null)

  useEffect(() => {
    setAuthToken(auth?.token ?? null)
    if (typeof window === 'undefined') return
    if (auth) {
      window.localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(auth))
    } else {
      window.localStorage.removeItem(AUTH_STORAGE_KEY)
    }
  }, [auth])

  useEffect(() => {
    const handler = () => {
      setNotice('')
      setAuth(null)
      clearUserData()
      setAuthNotice(t('Your session has expired. Please sign in again.'))
    }
    setUnauthorizedHandler(handler)
    return () => setUnauthorizedHandler(null)
  }, [])

  const startSession = (session: Session) => {
    setAuthToken(session.token)
    setAuth({
      token: session.token,
      email: session.email,
      role: session.role,
      expiresAt: Date.now() + session.expires_in * 1000,
    })
    setAuthNotice('')
    setNotice('')
    setTab('boreholes')
  }

  const handleLogin = async (email: string, password: string, otp?: string) => {
    startSession(await loginApi(email, password, otp))
  }

  const handleSetup = async (email: string, password: string) => {
    startSession(await setupFirstAdmin(email, password))
  }

  const handleLogout = () => {
    if (!confirmLeave()) return
    const waiting = outboxItems().length
    if (waiting && !window.confirm((waiting === 1 ? t('1 log on this device has not been sent yet. It stays here and is sent the next time you sign in. Sign out anyway?') : t('{n} log(s) on this device have not been sent yet. They stay here and are sent the next time you sign in. Sign out anyway?', { n: waiting })))) return
    setMoreOpen(false)
    setNotice('')
    clearUserData()
    setAuth(null)
    setAuthNotice('')
    setAuthToken(null)
  }

  const [orgName, setOrgName] = useState('')
  useEffect(() => {
    let active = true
    getPublicConfig().then(cfg => {
      if (!active) return
      setOrgName(cfg.org_name)
      document.title = appTitle(cfg.org_name)
    })
    return () => { active = false }
  }, [])

  const isAdmin = auth?.role === 'admin'
  useEffect(() => {
    if (!auth) { setSchemas(null); invalidate(); return }
    let active = true
    getSchemas().then(sc => { if (active) setSchemas(sc) }).catch(() => {})
    return () => { active = false }
  }, [auth?.token, auth?.role]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if ((tab === 'users' || tab === 'activity') && !isAdmin) {
      setTab('boreholes')
    }
  }, [tab, isAdmin])

  // Offline: logs saved without a connection wait here and are sent when back online.
  const [online, setOnline] = useState(() => navigator.onLine)
  const [outbox, setOutbox] = useState<OutboxItem[]>(outboxItems)
  const userEmail = auth?.email ?? ''
  useEffect(() => {
    setOutboxUser(userEmail)
    setOutbox(outboxItems())
    const off = subscribeOutbox(setOutbox)
    const tryNow = () => { if (userEmail && navigator.onLine && outboxItems().some(i => !i.error)) void flushOutbox() }
    const up = () => { setOnline(true); tryNow() }
    const down = () => setOnline(false)
    const visible = () => { if (document.visibilityState === 'visible') tryNow() }
    window.addEventListener('online', up)
    window.addEventListener('offline', down)
    document.addEventListener('visibilitychange', visible)
    // Weak or captive connections do not always fire "online": try again every minute.
    const timer = window.setInterval(tryNow, 60000)
    tryNow()
    return () => {
      off()
      window.removeEventListener('online', up)
      window.removeEventListener('offline', down)
      document.removeEventListener('visibilitychange', visible)
      window.clearInterval(timer)
    }
  }, [userEmail])

  if (!auth) {
    return <Login onLogin={handleLogin} onSetup={handleSetup} title={appTitle(orgName)} orgName={orgName} notice={authNotice} />
  }

  const go = (key: TabKey, next?: Intent) => {
    setMoreOpen(false)
    if (confirmLeave()) {
      setTab(key)
      setIntent(next)
      setNavCount(n => n + 1)
      setNotice('')
      window.scrollTo(0, 0)
    }
  }
  const can = (entity?: string) => !entity || !schemas || !!schemas[entity]?.can_read
  const switchLanguage = () => { if (confirmLeave()) setLang(lang() === 'id' ? 'en' : 'id') }

  const comop: NavItem[] = [
    { key: 'projects', label: t('Projects'), icon: 'folder', entity: 'projects' },
    { key: 'clients', label: t('Clients'), icon: 'building', entity: 'clients' },
    { key: 'quotes', label: t('Quotations'), icon: 'tag', entity: 'quotes' },
    { key: 'contracts', label: t('Contracts'), icon: 'contract', entity: 'contracts' },
  ]
  const field: NavItem[] = [
    { key: 'boreholes', label: t('Boreholes'), icon: 'boreholes' },
    { key: 'new', label: t('New log'), icon: 'plus' },
    { key: 'cpt', label: t('CPT / sondir'), icon: 'cone', entity: 'cpt' },
    { key: 'fieldwork', label: t('Field worksheets'), icon: 'sheet', entity: 'field_activities' },
    { key: 'coordinates', label: t('Coordinates & maps'), icon: 'pin' },
  ]
  const lab: NavItem[] = [
    { key: 'lab', label: t('Laboratory tests'), icon: 'flask', entity: 'lab_tests' },
    { key: 'samples', label: t('Sample register'), icon: 'sample', entity: 'lab_tests' },
    { key: 'labsummary', label: t('Results summary'), icon: 'list', entity: 'lab_tests' },
  ]
  const engineering: NavItem[] = [
    { key: 'analyses', label: t('Engineering analyses'), icon: 'calc', entity: 'analyses' },
    { key: 'reports', label: t('Client reports'), icon: 'summary', entity: 'project_reports' },
  ]
  const finance: NavItem[] = [
    { key: 'invoices', label: t('Invoices'), icon: 'invoice', entity: 'invoices' },
    { key: 'rates', label: t('Price list'), icon: 'tag', entity: 'rates' },
  ]
  const analysis: NavItem[] = [
    { key: 'qa', label: 'Geo AI', icon: 'ai' },
    { key: 'summary', label: t('Summaries'), icon: 'summary' },
    { key: 'dashboard', label: t('Dashboard'), icon: 'chart' },
    { key: 'worksheets', label: t('Worksheet list'), icon: 'book' },
    { key: 'standards', label: t('Standards'), icon: 'book' },
  ]
  const admin: NavItem[] = isAdmin ? [
    { key: 'users', label: t('Users'), icon: 'users' },
    { key: 'activity', label: t('Activity'), icon: 'activity' },
    { key: 'settings', label: t('Company settings'), icon: 'settings' },
  ] : []
  const groups: Array<[string, NavItem[]]> = [
    ['Commercial operations', comop], ['Field work', field], ['Laboratory', lab], ['Engineering', engineering],
    ['Finance', finance], ['Data & references', analysis], ['Administration', admin],
  ]
  const about: NavItem = { key: 'about', label: t('About'), icon: 'info' }
  const PAGES: Partial<Record<TabKey, (i?: Intent) => JSX.Element>> = {
    projects: i => <ProjectsPage intent={i} />, clients: i => <ClientsPage intent={i} />, quotes: i => <QuotesPage intent={i} />,
    contracts: i => <ContractsPage intent={i} />, cpt: i => <CptPage intent={i} />, fieldwork: i => <FieldWorkPage intent={i} />,
    lab: i => <LabPage intent={i} />, analyses: i => <AnalysesPage intent={i} />, reports: i => <ReportsPage intent={i} />,
    invoices: i => <InvoicesPage intent={i} />, rates: i => <RatesPage intent={i} />, settings: () => <SettingsPage />,
    worksheets: () => <WorksheetCatalogPage />, standards: () => <StandardsPage />, coordinates: () => <CoordinatesPage />,
    samples: () => <SampleRegisterPage />, labsummary: () => <LabSummaryPage />,
  }
  const loading = <p className="muted">{t('Loading…')}</p>
  const page = schemas && PAGES[tab] ? <Suspense fallback={loading}>{PAGES[tab]!(intent)}</Suspense> : (PAGES[tab] ? loading : null)
  const waiting = outbox.filter(i => !i.error).length

  const navButton = (item: NavItem) => (
    <button key={item.key} type="button" className={`nav-item${tab === item.key ? ' active' : ''}`}
      aria-current={tab === item.key ? 'page' : undefined} onClick={() => go(item.key, undefined)}>
      <Icon name={item.icon} />{item.label}
      {item.key === 'boreholes' && outbox.length > 0 && <span className="count">{t('{n} waiting', { n: outbox.length })}</span>}
    </button>
  )
  const accountButtons = (
    <>
      {navButton({ key: 'account', label: t('Account & security'), icon: 'account' })}
      <button type="button" className="nav-item" onClick={switchLanguage} title={t('Language')}>
        <Icon name="language" />{lang() === 'id' ? 'English' : 'Bahasa Indonesia'}
      </button>
      <button type="button" className="nav-item" onClick={handleLogout}><Icon name="logout" />{t('Sign Out')}</button>
    </>
  )
  const brand = (
    <div className="brand">
      <BrandMark />
      <span className="brand-name">SoilBoring{orgName && <span className="brand-org">{orgName}</span>}</span>
    </div>
  )
  const who = <div className="who"><strong>{auth.email}</strong>{t(ROLE_LABELS[auth.role] || auth.role)}</div>

  return (
    <NavContext.Provider value={{ go, role: auth.role, email: auth.email }}>
    <SchemaContext.Provider value={schemas}>
    <div className="shell">
      <aside className="sidebar" aria-label={t('Main menu')}>
        {brand}
        <nav>
          {groups.map(([title, items]) => {
            const shown = items.filter(i => can(i.entity))
            return shown.length > 0 && (
              <div className="nav-group" key={title}>
                <div className="nav-group-title">{t(title)}</div>
                {shown.map(navButton)}
              </div>
            )
          })}
          <div className="nav-group">{navButton(about)}</div>
        </nav>
        <div className="sidebar-foot">
          {who}
          {accountButtons}
        </div>
      </aside>

      <header className="mobile-top">
        {brand}
        <button type="button" className="quiet" onClick={() => go('account')} aria-label={t('Account & security')}><Icon name="account" size={22} /></button>
      </header>

      <main className="main" id="main">
        <div className="page">
          {(!online || waiting > 0) && (
            <div className="offline-banner" role="status">
              <span>
                {!online && <strong>{t('Offline.')} </strong>}
                {waiting > 0
                  ? (waiting === 1 ? t('1 log saved on this device, waiting to be sent.') : t('{n} log(s) saved on this device, waiting to be sent.', { n: waiting }))
                  : t('New logs are kept on this device and sent when the connection is back.')}
              </span>
              {online && waiting > 0 && <button type="button" className="small" onClick={() => void flushOutbox()}>{t('Send now')}</button>}
            </div>
          )}
          {notice && <p className="notice ok" role="status">{notice}</p>}

          {tab === 'boreholes' && <Boreholes key={`b-${navCount}`} user={{ email: auth.email, role: auth.role }} outbox={outbox} onNew={() => go('new')} openBorehole={intent?.borehole} />}
          {tab === 'new' && <DailyReportForm key={`n-${navCount}`} onDone={() => go('boreholes')} defaults={intent?.newWith as Record<string, string> | undefined} />}
          {page && <div key={`${tab}-${navCount}`}>{page}</div>}
          {tab === 'qa' && <QA />}
          {tab === 'summary' && <Summary />}
          {tab === 'dashboard' && <Dashboard />}
          {tab === 'about' && <AboutSoilBoring />}
          {tab === 'users' && isAdmin && <UserAdmin currentUserEmail={auth.email} />}
          {tab === 'activity' && isAdmin && <Activity />}
          {tab === 'account' && (
            <>
              <PageHead title={t('Account & security')} description={t('Signed in as {email}.', { email: auth.email })} />
              <div className="account-grid">
                <ChangePassword
                  onChanged={session => {
                    setAuthToken(session.token)
                    setAuth({
                      token: session.token,
                      email: session.email,
                      role: session.role,
                      expiresAt: Date.now() + session.expires_in * 1000,
                    })
                    setNotice(t('Password changed.'))
                  }}
                />
                <Security />
              </div>
            </>
          )}
        </div>
      </main>

      <nav className="bottom-nav" aria-label={t('Main menu')}>
        {[field[0], field[1], ...(can('projects') ? [comop[0]] : [analysis[2]]), analysis[0]].map(item => (
          <button key={item.key} type="button" className={tab === item.key ? 'active' : ''} aria-current={tab === item.key ? 'page' : undefined} onClick={() => go(item.key)}>
            <Icon name={item.icon} />{item.label}
          </button>
        ))}
        <button type="button" className={moreOpen || !BOTTOM.includes(tab) ? 'active' : ''}
          aria-expanded={moreOpen} onClick={() => setMoreOpen(v => !v)}>
          <Icon name="more" />{t('More')}
        </button>
      </nav>
      {moreOpen && (
        <>
          <div className="sheet-backdrop" onClick={() => setMoreOpen(false)} />
          <div className="sheet" role="dialog" aria-label={t('More')}>
            {who}
            {groups.map(([title, items]) => {
              const shown = items.filter(i => can(i.entity) && !BOTTOM.includes(i.key))
              return shown.length > 0 && (
                <div key={title}>
                  <div className="nav-group-title" style={{ marginTop: '.5rem' }}>{t(title)}</div>
                  {shown.map(navButton)}
                </div>
              )
            })}
            {navButton(about)}
            {accountButtons}
          </div>
        </>
      )}
    </div>
    </SchemaContext.Provider>
    </NavContext.Provider>
  )
}

const BOTTOM: TabKey[] = ['boreholes', 'new', 'projects', 'qa']
