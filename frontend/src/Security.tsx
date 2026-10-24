import { FormEvent, useEffect, useState } from 'react'
import { disableTwoFactor, enableTwoFactor, getMe, newRecoveryCodes, startTwoFactor, type Me } from './api'
import { t } from './i18n'

function CodesBox({ codes, onDone }: { codes: string[], onDone: () => void }) {
  const text = codes.join('\n')
  const download = () => {
    const url = URL.createObjectURL(new Blob([text + '\n'], { type: 'text/plain' }))
    const a = document.createElement('a')
    a.href = url
    a.download = 'soilboring-recovery-codes.txt'
    a.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
  return (
    <div className="notice warn">
      <p style={{ marginTop: 0 }}><strong>{t('Save these recovery codes now.')}</strong> {t('Each code works once: to sign in without your phone, or to set a new password when you forget it. They are shown only this time.')}</p>
      <div className="codes">{codes.map(c => <span key={c}>{c}</span>)}</div>
      <div className="actions" style={{ marginTop: '.75rem', flexWrap: 'wrap' }}>
        <button type="button" onClick={() => navigator.clipboard?.writeText(text)}>{t('Copy')}</button>
        <button type="button" onClick={download}>{t('Download .txt')}</button>
        <button type="button" className="button-secondary" onClick={onDone}>{t('I saved them')}</button>
      </div>
    </div>
  )
}

/** Two-step verification and recovery codes for the signed-in user. */
export default function Security() {
  const [me, setMe] = useState<Me | null>(null)
  const [setup, setSetup] = useState<{ secret: string, qr: string } | null>(null)
  const [code, setCode] = useState('')
  const [password, setPassword] = useState('')
  const [offCode, setOffCode] = useState('')
  const [codes, setCodes] = useState<string[] | null>(null)
  const [status, setStatus] = useState('')
  const [busy, setBusy] = useState(false)

  const refresh = () => getMe().then(setMe).catch(e => setStatus(e.message))
  useEffect(() => { void refresh() }, [])

  const run = async (fn: () => Promise<void>) => {
    if (busy) return
    setBusy(true)
    setStatus('')
    try { await fn() } catch (e: any) { setStatus(e.message) } finally { setBusy(false) }
  }

  const begin = () => run(async () => {
    const res = await startTwoFactor()
    const QRCode = (await import('qrcode')).default
    setSetup({ secret: res.secret, qr: await QRCode.toDataURL(res.otpauth_uri, { margin: 1, width: 200 }) })
  })

  const confirm = (e: FormEvent) => {
    e.preventDefault()
    void run(async () => {
      const res = await enableTwoFactor(code)
      setCodes(res.recovery_codes)
      setSetup(null)
      setCode('')
      await refresh()
    })
  }

  const turnOff = (e: FormEvent) => {
    e.preventDefault()
    void run(async () => {
      await disableTwoFactor(password, offCode.trim())
      setPassword('')
      setOffCode('')
      setStatus(t('Two-step verification is off.'))
      await refresh()
    })
  }

  const [codesPassword, setCodesPassword] = useState('')
  const regenerate = (e: FormEvent) => {
    e.preventDefault()
    void run(async () => {
      const res = await newRecoveryCodes(codesPassword)
      setCodesPassword('')
      setCodes(res.recovery_codes)
      await refresh()
    })
  }

  if (!me) return <p>{status || t('Loading…')}</p>
  return (
    <div className="card" style={{ maxWidth: 560, margin: '1rem auto', display: 'grid', gap: '.75rem' }}>
      <h3 style={{ margin: 0 }}>{t('Two-step verification')}</h3>
      {codes && <CodesBox codes={codes} onDone={() => setCodes(null)} />}
      {me.totp_enabled ? (
        <>
          <p style={{ margin: 0 }}>✅ {t('On. Signing in needs your password and a 6-digit code from your authenticator app.')}</p>
          <form onSubmit={turnOff} className="actions" style={{ flexWrap: 'wrap', alignItems: 'flex-end' }}>
            <label style={{ display: 'grid', gap: '.25rem' }}>{t('Password')}
              <input type="password" value={password} onChange={e => setPassword(e.target.value)} autoComplete="current-password" required />
            </label>
            <label style={{ display: 'grid', gap: '.25rem' }}>{t('6-digit code from the app')}
              <input value={offCode} onChange={e => setOffCode(e.target.value)} inputMode="numeric" autoComplete="one-time-code" maxLength={8} required />
            </label>
            <button type="submit" className="button-danger" disabled={busy}>{t('Turn off')}</button>
          </form>
        </>
      ) : setup ? (
        <form onSubmit={confirm} style={{ display: 'grid', gap: '.5rem' }}>
          <p style={{ margin: 0 }}>{t('1. Scan this code with Google Authenticator, Microsoft Authenticator, Aegis or a similar app.')}</p>
          <span className="qr"><img src={setup.qr} alt="QR" width={200} height={200} /></span>
          <p style={{ margin: 0, fontSize: '.85rem', color: 'var(--muted)' }}>{t('Cannot scan? Enter this key in the app:')} <code style={{ wordBreak: 'break-all' }}>{setup.secret}</code></p>
          <label style={{ display: 'grid', gap: '.25rem' }}>{t('2. Type the 6-digit code the app shows')}
            <input value={code} onChange={e => setCode(e.target.value)} inputMode="numeric" autoComplete="one-time-code" maxLength={8} required />
          </label>
          <div className="actions"><button type="submit" disabled={busy}>{t('Turn on')}</button><button type="button" className="button-secondary" onClick={() => setSetup(null)}>{t('Cancel')}</button></div>
        </form>
      ) : (
        <>
          <p style={{ margin: 0 }}>{t('Off. Turn it on so a stolen password alone cannot open your account.')}</p>
          <div className="actions"><button type="button" onClick={begin} disabled={busy}>{t('Set up two-step verification')}</button></div>
        </>
      )}
      <hr style={{ border: 0, borderTop: '1px solid var(--border)', width: '100%' }} />
      <h3 style={{ margin: 0 }}>{t('Recovery codes')}</h3>
      <p style={{ margin: 0 }}>
        {t('Recovery codes let you set a new password yourself when you forget it.')} {t('Codes left: {n}', { n: me.recovery_codes_left })}
      </p>
      <form onSubmit={regenerate} className="actions" style={{ flexWrap: 'wrap', alignItems: 'flex-end' }}>
        <label style={{ display: 'grid', gap: '.25rem' }}>{t('Password')}
          <input type="password" value={codesPassword} onChange={e => setCodesPassword(e.target.value)} autoComplete="current-password" required />
        </label>
        <button type="submit" disabled={busy}>{me.recovery_codes_left ? t('Create new codes (old ones stop working)') : t('Create recovery codes')}</button>
      </form>
      {status && <p role="status" style={{ margin: 0 }}>{status}</p>}
    </div>
  )
}
