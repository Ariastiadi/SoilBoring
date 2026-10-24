import { useEffect, useState } from 'react'
import { getPublicConfig, getSetupStatus, requestResetEmail, resetWithCode, resetWithToken } from './api'
import { lang, setLang, t } from './i18n'

type Props = {
  onLogin: (email: string, password: string, otp?: string) => Promise<void>
  onSetup: (email: string, password: string) => Promise<void>
  title: string
}

type Mode = 'login' | 'otp' | 'setup' | 'forgot' | 'reset-link'
const MIN_PASSWORD_LENGTH = 8

function resetTokenFromUrl(): string {
  const hash = window.location.hash || ''
  return hash.startsWith('#reset=') ? decodeURIComponent(hash.slice(7)) : ''
}

const fieldStyle = { display: 'flex', flexDirection: 'column' as const, gap: '.25rem' }

export default function Login({ onLogin, onSetup, title }: Props) {
  const [mode, setMode] = useState<Mode>(() => (resetTokenFromUrl() ? 'reset-link' : 'login'))
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [otp, setOtp] = useState('')
  const [recovery, setRecovery] = useState('')
  const [status, setStatus] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [emailReset, setEmailReset] = useState(false)

  useEffect(() => {
    let active = true
    getSetupStatus().then(needed => { if (active && needed && mode === 'login') setMode('setup') })
    getPublicConfig().then(cfg => { if (active) setEmailReset(cfg.email_reset) })
    return () => { active = false }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const switchMode = (next: Mode) => {
    setMode(next)
    setError('')
    setStatus('')
  }

  const run = async (fn: () => Promise<void>) => {
    if (busy) return
    setError('')
    setBusy(true)
    try {
      await fn()
    } catch (err: any) {
      setStatus('')
      const message = String(err?.message || '')
      if (message.includes('otp_required')) {
        setMode('otp')
        setStatus(t('Enter the 6-digit code from your authenticator app.'))
      } else {
        setError(message || t('Something went wrong'))
        // Someone finished setup in the meantime: fall back to the normal sign-in form.
        if (mode === 'setup' && err?.status === 409) setMode('login')
      }
    } finally {
      setBusy(false)
    }
  }

  const checkNew = () => {
    if (password.length < MIN_PASSWORD_LENGTH) throw new Error(t('Password must be at least {n} characters', { n: MIN_PASSWORD_LENGTH }))
    if (password !== confirm) throw new Error(t('The two passwords do not match'))
  }

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    void run(async () => {
      if (mode === 'login') {
        if (!email.trim() || !password) throw new Error(t('Email and password are required'))
        setStatus(t('Signing in...'))
        await onLogin(email.trim(), password)
      } else if (mode === 'otp') {
        setStatus(t('Signing in...'))
        await onLogin(email.trim(), password, otp.trim())
      } else if (mode === 'setup') {
        checkNew()
        setStatus(t('Creating admin account...'))
        await onSetup(email.trim(), password)
      } else if (mode === 'forgot') {
        checkNew()
        await resetWithCode(email.trim(), recovery.trim(), password)
        setPassword('')
        setConfirm('')
        setRecovery('')
        setMode('login')
        setStatus(t('Password changed. Sign in with the new password.'))
      } else if (mode === 'reset-link') {
        checkNew()
        await resetWithToken(resetTokenFromUrl(), password)
        history.replaceState(null, '', window.location.pathname)
        setPassword('')
        setConfirm('')
        setMode('login')
        setStatus(t('Password changed. Sign in with the new password.'))
      }
    })
  }

  const sendLink = () => run(async () => {
    if (!email.trim()) throw new Error(t('Enter your email first'))
    await requestResetEmail(email.trim())
    setStatus(t('If this email has an account, a reset link is on its way. Check your inbox (and spam).'))
  })

  const intro: Record<Mode, string> = {
    login: t('Sign in with your assigned operator email and password to log boreholes.'),
    otp: t('Two-step verification is on for this account.'),
    setup: t('Welcome! No accounts exist yet. Create the first administrator account; you can add operators afterwards under Users.'),
    forgot: t('Forgot your password? Use one of your recovery codes to set a new one. No codes? Ask an admin to reset your password.'),
    'reset-link': t('Choose a new password for your account.'),
  }
  const button: Record<Mode, string> = {
    login: t('Sign In'), otp: t('Verify'), setup: t('Create admin account'), forgot: t('Set new password'), 'reset-link': t('Set new password'),
  }
  const needsEmail = mode === 'login' || mode === 'setup' || mode === 'forgot'
  const needsNewPassword = mode === 'setup' || mode === 'forgot' || mode === 'reset-link'

  return (
    <div className="card" style={{ maxWidth: '480px', margin: '3rem auto', padding: '2rem' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '.5rem' }}>
        <h2 style={{ marginTop: 0 }}>{title}</h2>
        <button type="button" className="button-secondary" style={{ padding: '.2rem .5rem' }}
          onClick={() => setLang(lang() === 'id' ? 'en' : 'id')}>{lang() === 'id' ? 'EN' : 'ID'}</button>
      </div>
      <p style={{ color: 'var(--muted)', marginBottom: '1.5rem' }}>{intro[mode]}</p>
      <form onSubmit={submit} style={{ display: 'flex', flexDirection: 'column', gap: '.75rem' }}>
        {needsEmail && (
          <label style={fieldStyle}>
            {t('Email')}
            <input type="email" value={email} onChange={e => setEmail(e.target.value)}
              placeholder={mode === 'setup' ? 'admin@example.com' : 'operator@example.com'} autoComplete="username" required />
          </label>
        )}
        {mode === 'login' && (
          <label style={fieldStyle}>
            {t('Password')}
            <input type="password" value={password} onChange={e => setPassword(e.target.value)} placeholder={t('Password')} autoComplete="current-password" required />
          </label>
        )}
        {mode === 'otp' && (
          <label style={fieldStyle}>
            {t('Authentication code')}
            <input value={otp} onChange={e => setOtp(e.target.value)} inputMode="numeric" autoComplete="one-time-code" autoFocus
              placeholder={t('6 digits, or a recovery code')} maxLength={16} required />
          </label>
        )}
        {mode === 'forgot' && (
          <label style={fieldStyle}>
            {t('Recovery code')}
            <input value={recovery} onChange={e => setRecovery(e.target.value)} placeholder="ABCD-EFGH" autoComplete="off" maxLength={16} required />
          </label>
        )}
        {needsNewPassword && (
          <>
            <label style={fieldStyle}>
              {mode === 'setup' ? t('Password') : t('New password')}
              <input type="password" value={password} onChange={e => setPassword(e.target.value)} minLength={MIN_PASSWORD_LENGTH}
                placeholder={t('At least {n} characters', { n: MIN_PASSWORD_LENGTH })} autoComplete="new-password" required />
            </label>
            <label style={fieldStyle}>
              {t('Repeat password')}
              <input type="password" value={confirm} onChange={e => setConfirm(e.target.value)} autoComplete="new-password" required />
            </label>
          </>
        )}
        <button type="submit" disabled={busy}>{button[mode]}</button>
        {status && <span style={{ color: 'var(--muted)' }}>{status}</span>}
        {error && <span style={{ color: 'var(--danger)' }}>{error}</span>}
      </form>
      <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap', marginTop: '1rem', fontSize: '.9rem' }}>
        {mode === 'login' && <a href="#" onClick={e => { e.preventDefault(); switchMode('forgot') }}>{t('Forgot password?')}</a>}
        {mode === 'forgot' && emailReset && <a href="#" onClick={e => { e.preventDefault(); void sendLink() }}>{t('Email me a reset link instead')}</a>}
        {(mode === 'forgot' || mode === 'otp' || mode === 'reset-link') && (
          <a href="#" onClick={e => { e.preventDefault(); if (mode === 'reset-link') history.replaceState(null, '', window.location.pathname); switchMode('login') }}>{t('Back to sign in')}</a>
        )}
      </div>
    </div>
  )
}
