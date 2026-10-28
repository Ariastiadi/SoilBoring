import { useEffect, useState } from 'react'
import { type Department, getPublicConfig, getSetupStatus, requestAccount, requestResetEmail, resetWithCode, resetWithToken } from './api'
import { lang, setLang, t } from './i18n'
import { BrandMark } from './ui'
import { FILL, GRAIN_WIDTH, type Pattern } from './soil'

type Props = {
  onLogin: (email: string, password: string, otp?: string) => Promise<void>
  onSetup: (email: string, password: string) => Promise<void>
  title: string
  orgName?: string
  notice?: string
}

type Mode = 'login' | 'otp' | 'setup' | 'forgot' | 'reset-link' | 'signup' | 'signup-done'
const MIN_PASSWORD_LENGTH = 8

function resetTokenFromUrl(): string {
  const hash = window.location.hash || ''
  return hash.startsWith('#reset=') ? decodeURIComponent(hash.slice(7)) : ''
}

const fieldStyle = { display: 'flex', flexDirection: 'column' as const, gap: '.3rem' }

const DEPARTMENTS: [Department, string][] = [
  ['field', 'Field work (drilling, CPT, survey)'],
  ['lab', 'Laboratory'],
  ['engineering', 'Engineering / project leader'],
  ['finance', 'Finance'],
  ['management', 'Management'],
  ['other', 'Other'],
]

// A cross-section of five boreholes: each column's width follows grain size.
const SECTION: Pattern[][] = [
  ['silt', 'clay', 'clay', 'sand', 'sand', 'gravel'],
  ['silt', 'clay', 'sand', 'sand', 'gravel', 'gravel'],
  ['clay', 'clay', 'clay', 'silt', 'sand', 'gravel'],
  ['silt', 'clay', 'sand', 'silt', 'sand', 'gravel'],
  ['clay', 'silt', 'sand', 'sand', 'sand', 'gravel'],
]

function CrossSection() {
  const colW = 70, gap = 30, layerH = 34, top = 30
  return (
    <svg className="strata-art" viewBox="0 0 520 260" aria-hidden="true" focusable="false">
      <path d="M0 34 Q 130 18 260 30 T 520 26" fill="none" stroke="#23282d" strokeWidth="1.5" />
      <path d="M0 112 L520 104" stroke="#1f5f8b" strokeWidth="1.2" strokeDasharray="6 4" />
      {SECTION.map((col, i) => {
        const x = 20 + i * (colW + gap)
        return (
          <g key={i}>
            <line x1={x + colW / 2} x2={x + colW / 2} y1={top - 22} y2={top} stroke="#23282d" strokeWidth="2" />
            {col.map((p, j) => (
              <rect key={j} x={x} y={top + j * layerH} width={colW * GRAIN_WIDTH[p]} height={layerH}
                fill={FILL[p]} stroke="#23282d" strokeWidth="1" />
            ))}
          </g>
        )
      })}
    </svg>
  )
}

export default function Login({ onLogin, onSetup, title, orgName, notice }: Props) {
  const [mode, setMode] = useState<Mode>(() => (resetTokenFromUrl() ? 'reset-link' : 'login'))
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [otp, setOtp] = useState('')
  const [recovery, setRecovery] = useState('')
  const [resetOtp, setResetOtp] = useState('')
  const [status, setStatus] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [emailReset, setEmailReset] = useState(false)
  const [signupOn, setSignupOn] = useState(false)
  const [name, setName] = useState('')
  const [department, setDepartment] = useState<Department>('field')
  const [note, setNote] = useState('')

  useEffect(() => {
    let active = true
    getSetupStatus().then(needed => { if (active && needed && mode === 'login') setMode('setup') })
    getPublicConfig().then(cfg => { if (active) { setEmailReset(cfg.email_reset); setSignupOn(cfg.signup) } })
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
        await resetWithCode(email.trim(), recovery.trim(), password, resetOtp.trim() || undefined)
        setPassword('')
        setConfirm('')
        setRecovery('')
        setResetOtp('')
        setMode('login')
        setStatus(t('Password changed. Sign in with the new password.'))
      } else if (mode === 'signup') {
        if (name.trim().length < 2) throw new Error(t('Enter your full name'))
        checkNew()
        setStatus(t('Sending the request...'))
        await requestAccount({ email: email.trim(), password, name: name.trim(), department, note: note.trim() })
        setPassword('')
        setConfirm('')
        setNote('')
        setStatus('')
        setMode('signup-done')
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
    signup: t('Ask for an account. An administrator checks the request and chooses your access; until then you cannot sign in.'),
    'signup-done': t('Request sent. Once an administrator approves it, sign in with this email and the password you just chose. Ask your administrator if it takes long.'),
  }
  const button: Record<Mode, string> = {
    login: t('Sign In'), otp: t('Verify'), setup: t('Create admin account'), forgot: t('Set new password'), 'reset-link': t('Set new password'),
    signup: t('Request an account'), 'signup-done': t('Request sent'),
  }
  const needsEmail = mode === 'login' || mode === 'setup' || mode === 'forgot' || mode === 'signup'
  const needsNewPassword = mode === 'setup' || mode === 'forgot' || mode === 'reset-link' || mode === 'signup'

  return (
    <div className="auth">
      <div className="auth-art">
        <div>
          <div className="brand" style={{ padding: 0, marginBottom: '2rem' }}>
            <BrandMark />
            <span className="brand-name">SoilBoring{orgName && <span className="brand-org">{orgName}</span>}</span>
          </div>
          <h1>{t('Daily borehole logs, from the rig to the report.')}</h1>
          <p>{t('Record boreholes, strata, SPT, samples and core photos. Works without signal, exports AGS4 and prints the bore log sheet.')}</p>
          <CrossSection />
        </div>
      </div>
      <div className="auth-form">
        <div style={{ maxWidth: 380, width: '100%', margin: '0 auto' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: '.5rem' }}>
            <h2 style={{ margin: 0 }}>{button[mode]}</h2>
            <button type="button" className="quiet small" onClick={() => setLang(lang() === 'id' ? 'en' : 'id')}>
              {lang() === 'id' ? 'English' : 'Bahasa Indonesia'}
            </button>
          </div>
          <p className="muted" style={{ margin: '.4rem 0 1.25rem' }}>{intro[mode]}</p>
          {notice && <p className="notice warn" role="alert">{notice}</p>}
      {mode !== 'signup-done' && <form onSubmit={submit} style={{ display: 'flex', flexDirection: 'column', gap: '.75rem' }}>
        {mode === 'signup' && (
          <label style={fieldStyle}>
            {t('Full name')}
            <input value={name} onChange={e => setName(e.target.value)} autoComplete="name" maxLength={120} required />
          </label>
        )}
        {needsEmail && (
          <label style={fieldStyle}>
            {t('Email')}
            <input type="email" value={email} onChange={e => setEmail(e.target.value)}
              placeholder={t('name@company.com')} autoComplete="username" required />
          </label>
        )}
        {mode === 'login' && (
          <label style={fieldStyle}>
            {t('Password')}
            <input type="password" value={password} onChange={e => setPassword(e.target.value)} autoComplete="current-password" required />
          </label>
        )}
        {mode === 'otp' && (
          <label style={fieldStyle}>
            {t('Authentication code')}
            <input value={otp} onChange={e => setOtp(e.target.value)} autoComplete="one-time-code" autoCapitalize="characters" autoFocus
              placeholder={t('6 digits, or a recovery code')} maxLength={16} required />
          </label>
        )}
        {mode === 'forgot' && (
          <label style={fieldStyle}>
            {t('Recovery code')}
            <input value={recovery} onChange={e => setRecovery(e.target.value)} placeholder="XXXX-XXXX-XXXX" autoComplete="off" autoCapitalize="characters" maxLength={20} required />
          </label>
        )}
        {mode === 'forgot' && (
          <label style={fieldStyle}>
            {t('Authenticator code (only if two-step verification is on)')}
            <input value={resetOtp} onChange={e => setResetOtp(e.target.value)} inputMode="numeric" autoComplete="one-time-code" maxLength={8} />
          </label>
        )}
        {mode === 'signup' && (
          <label style={fieldStyle}>
            {t('Your work')}
            <select value={department} onChange={e => setDepartment(e.target.value as Department)}>
              {DEPARTMENTS.map(([key, label]) => <option key={key} value={key}>{t(label)}</option>)}
            </select>
          </label>
        )}
        {needsNewPassword && (
          <>
            <label style={fieldStyle}>
              {mode === 'setup' || mode === 'signup' ? t('Password') : t('New password')}
              <input type="password" value={password} onChange={e => setPassword(e.target.value)} minLength={MIN_PASSWORD_LENGTH}
                placeholder={t('At least {n} characters', { n: MIN_PASSWORD_LENGTH })} autoComplete="new-password" required />
            </label>
            <label style={fieldStyle}>
              {t('Repeat password')}
              <input type="password" value={confirm} onChange={e => setConfirm(e.target.value)} autoComplete="new-password" required />
            </label>
          </>
        )}
        {mode === 'signup' && (
          <label style={fieldStyle}>
            {t('Note for the administrator (optional)')}
            <input value={note} onChange={e => setNote(e.target.value)} maxLength={300}
              placeholder={t('e.g. project, site or supervisor')} />
          </label>
        )}
        <button type="submit" className="primary" disabled={busy}>{button[mode]}</button>
        {status && <p className="muted small" role="status" style={{ margin: 0 }}>{status}</p>}
        {error && <p className="notice error" role="alert" style={{ margin: 0 }}>{error}</p>}
      </form>}
      {mode === 'signup-done' && (
        <button type="button" className="primary" style={{ width: '100%' }} onClick={() => switchMode('login')}>{t('Back to sign in')}</button>
      )}
      <div style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap', marginTop: '1rem', fontSize: '.92rem' }}>
        {mode === 'login' && <a href="#" onClick={e => { e.preventDefault(); switchMode('forgot') }}>{t('Forgot password?')}</a>}
        {mode === 'login' && signupOn && <a href="#" onClick={e => { e.preventDefault(); switchMode('signup') }}>{t('No account yet? Request one')}</a>}
        {mode === 'forgot' && emailReset && <a href="#" onClick={e => { e.preventDefault(); void sendLink() }}>{t('Email me a reset link instead')}</a>}
        {(mode === 'forgot' || mode === 'otp' || mode === 'reset-link' || mode === 'signup') && (
          <a href="#" onClick={e => { e.preventDefault(); if (mode === 'reset-link') history.replaceState(null, '', window.location.pathname); switchMode('login') }}>{t('Back to sign in')}</a>
        )}
      </div>
        </div>
      </div>
    </div>
  )
}
