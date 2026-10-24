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
import Security from './Security'
import Activity from './tabs/Activity'
import { discardOutboxItem, flushOutbox, outboxItems, retryOutboxItem, setOutboxUser, subscribeOutbox, type OutboxItem } from './outbox'
import { confirmLeave } from './unsaved'
import { lang, setLang, t } from './i18n'
import { appTitle, getPublicConfig, login as loginApi, setAuthToken, setUnauthorizedHandler, setupFirstAdmin } from './api'
import type { Session } from './api'

type TabKey = 'report' | 'qa' | 'summary' | 'dashboard' | 'reportData' | 'about' | 'users' | 'activity'
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
      setAuthNotice(t('Your session has expired. Please sign in again.'))
    }
    setUnauthorizedHandler(handler)
    return () => setUnauthorizedHandler(null)
  }, [])

  const startSession = (session: Session) => {
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

  const handleLogin = async (email: string, password: string, otp?: string) => {
    startSession(await loginApi(email, password, otp))
  }

  const handleSetup = async (email: string, password: string) => {
    startSession(await setupFirstAdmin(email, password))
  }

  const handleLogout = () => {
    if (!confirmLeave()) return
    const waiting = outboxItems().length
    if (waiting && !window.confirm(t('{n} log(s) on this device have not been sent yet. They stay here and are sent the next time you sign in. Sign out anyway?', { n: waiting }))) return
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
    if ((tab === 'users' || tab === 'activity') && !isAdmin) {
      setTab('report')
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

  const tabs: { key: TabKey, label: string }[] = [
    { key: 'report', label: t('Borehole Log') },
    { key: 'qa', label: 'Geo AI' },
    { key: 'summary', label: t('Summaries') },
    { key: 'dashboard', label: t('Dashboard') },
    { key: 'reportData', label: t('Borehole Data') },
    { key: 'about', label: t('About') },
    ...(isAdmin ? [{ key: 'users' as const, label: t('Users') }, { key: 'activity' as const, label: t('Activity') }] : []),
  ]

  if (!auth) {
    return (
      <div>
        {authNotice && (
          <div className="card" style={{ maxWidth: '480px', margin: '2rem auto', padding: '1rem', color: 'var(--danger)' }}>
            {authNotice}
          </div>
        )}
        <Login onLogin={handleLogin} onSetup={handleSetup} title={appTitle(orgName)} />
      </div>
    )
  }

  return (
    <div>
      <div className="actions topbar">
        <span>
          {orgName && <strong style={{ marginRight: '.75rem' }}>{orgName}</strong>}
          {t('Signed in as')} <strong>{auth.email}</strong> ({auth.role})
        </span>
        <div style={{ display: 'flex', gap: '.5rem', flexWrap: 'wrap' }}>
          <button onClick={() => { setShowPasswordForm(v => !v); setNotice('') }}>{t('Account & security')}</button>
          <button className="button-secondary" onClick={() => { if (confirmLeave()) setLang(lang() === 'id' ? 'en' : 'id') }} title={t('Language')}>
            {lang() === 'id' ? 'EN' : 'ID'}
          </button>
          <button onClick={handleLogout}>{t('Sign Out')}</button>
        </div>
      </div>
      {(!online || outbox.length > 0) && (
        <div className="offline-banner" role="status">
          {!online && <strong>{t('Offline.')} </strong>}
          {outbox.length > 0
            ? t('{n} log(s) saved on this device, waiting to be sent.', { n: outbox.length })
            : t('New logs are kept on this device and sent when the connection is back.')}
          {outbox.filter(i => i.error).map(i => (
            <div key={i.id} style={{ marginTop: '.35rem' }}>
              {String(i.data.BoreholeID)}: {i.error}{' '}
              <button onClick={() => retryOutboxItem(i.id)}>{t('Retry')}</button>{' '}
              <button className="button-danger" onClick={() => { if (window.confirm(t('Discard this unsent log?'))) discardOutboxItem(i.id) }}>{t('Discard')}</button>
            </div>
          ))}
          {online && outbox.some(i => !i.error) && <> <button onClick={() => void flushOutbox()}>{t('Send now')}</button></>}
        </div>
      )}
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
            setNotice(t('Password changed.'))
          }}
        />
      )}
      {showPasswordForm && <Security />}
      {notice && <p role="status" style={{ textAlign: 'center', margin: '.5rem' }}>{notice}</p>}
      <nav>
        {tabs.map(t => (
          <button
            key={t.key}
            className={tab === t.key ? 'active' : ''}
            onClick={() => { if (t.key !== tab && confirmLeave()) setTab(t.key) }}
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
        {tab === 'reportData' && <DailyReportData user={{ email: auth.email, role: auth.role }} />}
        {tab === 'about' && <AboutSoilBoring />}
        {tab === 'users' && isAdmin && <UserAdmin currentUserEmail={auth.email} />}
        {tab === 'activity' && isAdmin && <Activity />}
      </div>
    </div>
  )
}
