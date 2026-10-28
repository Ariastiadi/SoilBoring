/**
 * Integrity seal on printed documents: the short code and a QR code that opens the public
 * verify page (/verify/<code>), where anyone can check the document without signing in.
 */
import { useEffect, useState } from 'react'
import { t } from './i18n'
import './tabs/ClientReports.css'

export const formatSealCode = (code: string) => (code || '').replace(/[^A-Fa-f0-9]/g, '').toUpperCase().replace(/(.{4})(?=.)/g, '$1-')

export const verifyUrl = (code: string) => `${window.location.origin}/verify/${formatSealCode(code)}`

export function SealMark({ code, hash, compact = false }: { code?: string, hash?: string, compact?: boolean }) {
  const [qr, setQr] = useState('')
  useEffect(() => {
    if (!code) return
    let live = true
    import('qrcode').then(mod => mod.toDataURL(verifyUrl(code), { margin: 0, width: 220, errorCorrectionLevel: 'M' }))
      .then(url => { if (live) setQr(url) }).catch(() => {})
    return () => { live = false }
  }, [code])
  if (!code) return null
  return (
    <div className={`seal-mark${compact ? ' compact' : ''}`}>
      {qr ? <img src={qr} alt={t('QR code to check this document')} /> : <div className="qr-wait" />}
      <div>
        <div className="doc-small">{t('Integrity seal (SHA-256)')}</div>
        <div className="seal-code">{formatSealCode(code)}</div>
        <div className="doc-small">{t('Check at {url}', { url: verifyUrl(code) })}</div>
        {hash && !compact && <div className="seal-hash">{hash}</div>}
      </div>
    </div>
  )
}
