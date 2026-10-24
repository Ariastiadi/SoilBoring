import { useEffect, useState } from 'react'
import DailyReportForm from './tabs/DailyReportForm'
import QA from './tabs/QA'
import Summary from './tabs/Summary'
import Dashboard from './tabs/Dashboard'
import DailyReportData from './tabs/DailyReportData'
import AboutSoilBoring from './tabs/AboutSoilBoring'
import UserAdmin from './tabs/UserAdmin'
import Login from './Login'
import ChangePassword from './ChangePassword'
import { appTitle, getPublicConfig, login as loginApi, setAuthToken, setUnauthorizedHandler } from './api'

type TabKey = 'report' | 'qa' | 'summary' | 'dashboard' | 'reportData' | 'about' | 'users'
type AuthState = { token: string; email: string; role: 'admin' | 'general'; expiresAt?: number } | null
const AUTH_STORAGE_KEY = 'soilboring-auth'
// AI answers cached in the browser contain data from the logs, so they are cleared when the
// session ends. The unsaved borehole form draft is kept on purpose so field work is never lost.
const USER_DATA_KEYS = ['qa_history']

function clearUserData() {
  if (typeof window === 'undefined') return
  USER_DATA_KEYS.forEach(key => window.localStorage.removeItem(key))
}

export default function App() {
  const [tab, setTab] = useState<TabKey>('report')
  const [auth, setAuth] = useState<AuthState>(() => {
    if (typeof window === 'undefined') return null
    const raw = window.localStorage.getItem(AUTH_STORAGE_KEY)
    if (!raw) return null
    try {
      const parsed = JSON.parse(raw)
      if (parsed?.token && parsed?.email) {
        if (typeof parsed.expiresAt === 'number' && parsed.expiresAt <= Date.now()) {
          window.localStorage.removeItem(AUTH_STORAGE_KEY)
          return null
        }
        const role = parsed?.role === 'admin' ? 'admin' : 'general'
        return { token: parsed.token, email: parsed.email, role, expiresAt: parsed.expiresAt }
      }
    } catch {
      return null
    }
    return null
  })
  const [authNotice, setAuthNotice] = useState('')
  const [showPasswordForm, setShowPasswordForm] = useState(false)
  const [notice, setNotice] = useState('')

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
      setShowPasswordForm(false)
      setNotice('')
      setAuth(null)
      clearUserData()
      setAuthNotice('Your session has expired. Please sign in again.')
    }
    setUnauthorizedHandler(handler)
    return () => setUnauthorizedHandler(null)
  }, [])

  const handleLogin = async (email: string, password: string) => {
    const session = await loginApi(email, password)
    setAuth({
      token: session.token,
      email: session.email,
      role: session.role,
      expiresAt: Date.now() + session.expires_in * 1000,
    })
    setAuthNotice('')
    setShowPasswordForm(false)
    setNotice('')
    setTab('report')
  }

  const handleLogout = () => {
    setShowPasswordForm(false)
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
    if (tab === 'users' && !isAdmin) {
      setTab('report')
    }
  }, [tab, isAdmin])

  const tabs: { key: TabKey, label: string }[] = [
    { key: 'report', label: 'Borehole Log' },
    { key: 'qa', label: 'Geo AI' },
    { key: 'summary', label: 'Summaries' },
    { key: 'dashboard', label: 'Dashboard' },
    { key: 'reportData', label: 'Borehole Data' },
    { key: 'about', label: 'About' },
    ...(isAdmin ? [{ key: 'users' as const, label: 'Users' }] : []),
  ]

  if (!auth) {
    return (
      <div>
        {authNotice && (
          <div className="card" style={{ maxWidth: '480px', margin: '2rem auto', padding: '1rem', color: 'var(--danger)' }}>
            {authNotice}
          </div>
        )}
        <Login onLogin={handleLogin} title={appTitle(orgName)} />
      </div>
    )
  }

  return (
    <div>
      <div className="actions topbar">
        <span>
          {orgName && <strong style={{ marginRight: '.75rem' }}>{orgName}</strong>}
          Signed in as <strong>{auth.email}</strong> ({auth.role})
        </span>
        <div style={{ display: 'flex', gap: '.5rem', flexWrap: 'wrap' }}>
          <button onClick={() => { setShowPasswordForm(v => !v); setNotice('') }}>Change Password</button>
          <button onClick={handleLogout}>Sign Out</button>
        </div>
      </div>
      {showPasswordForm && (
        <ChangePassword
          onClose={() => setShowPasswordForm(false)}
          onChanged={session => {
            setAuth({
              token: session.token,
              email: session.email,
              role: session.role,
              expiresAt: Date.now() + session.expires_in * 1000,
            })
            setShowPasswordForm(false)
            setNotice('Password changed.')
          }}
        />
      )}
      {notice && <p role="status" style={{ textAlign: 'center', margin: '.5rem' }}>{notice}</p>}
      <nav>
        {tabs.map(t => (
          <button
            key={t.key}
            className={tab === t.key ? 'active' : ''}
            onClick={() => setTab(t.key)}
          >
            {t.label}
          </button>
        ))}
      </nav>
      <div className="container">
        {tab === 'report' && <DailyReportForm />}
        {tab === 'qa' && <QA />}
        {tab === 'summary' && <Summary />}
        {tab === 'dashboard' && <Dashboard />}
        {tab === 'reportData' && <DailyReportData />}
        {tab === 'about' && <AboutSoilBoring />}
        {tab === 'users' && isAdmin && <UserAdmin currentUserEmail={auth.email} />}
      </div>
    </div>
  )
}
