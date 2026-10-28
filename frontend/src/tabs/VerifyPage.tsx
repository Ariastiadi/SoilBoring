/**
 * Public check of a sealed document (/verify/<code>), no sign-in: kind of document, number and
 * title, project, issuing company, date and status. No technical data is shown.
 */
import { FormEvent, useEffect, useState } from 'react'
import { apiGet } from '../api'
import { lang, setLang, t } from '../i18n'
import { formatSealCode } from '../seal'
import { BrandMark, formatDate } from '../ui'
import { SEAL_STATUS } from './ClientReports'
import './ClientReports.css'

type View = {
  document_type: string, number: string, title: string, project: string, issuer: string, date: string, status: string,
  code: string, hash: string, revoked_on: string, superseded_by: string
}

export default function VerifyPage({ token }: { token: string }) {
  const [code, setCode] = useState(token)
  const [view, setView] = useState<View | null>(null)
  const [state, setState] = useState<'idle' | 'loading' | 'missing' | 'error'>(token ? 'loading' : 'idle')
  const check = (value: string) => {
    const clean = value.trim()
    if (!clean) return
    setState('loading')
    setView(null)
    apiGet<View>(`/api/verify/${encodeURIComponent(clean)}`)
      .then(v => { setView(v); setState('idle') })
      .catch((e: Error & { status?: number }) => setState(e.status === 404 ? 'missing' : 'error'))
  }
  useEffect(() => { if (token) check(token) }, [token]) // eslint-disable-line react-hooks/exhaustive-deps
  const submit = (e: FormEvent) => {
    e.preventDefault()
    const formatted = /^[a-f0-9]{64}$/i.test(code.trim()) ? code.trim().toLowerCase() : formatSealCode(code)
    window.history.replaceState(null, '', `/verify/${formatted}`)
    check(formatted)
  }
  const [label, tone] = view ? (SEAL_STATUS[view.status] || [view.status, '']) : ['', '']
  return (
    <main className="verify">
      <div className="verify-card card">
        <div className="verify-top">
          <div className="brand" style={{ padding: 0 }}><BrandMark /><span className="brand-name">{t('Document check')}</span></div>
          <button type="button" className="quiet small" onClick={() => setLang(lang() === 'id' ? 'en' : 'id')}>{lang() === 'id' ? 'English' : 'Bahasa Indonesia'}</button>
        </div>
        <p className="help">{t('Enter the seal code printed on the report or test result, or scan its QR code.')}</p>
        <form className="verify-form" onSubmit={submit}>
          <label className="sr-only" htmlFor="verify-code">{t('Seal code')}</label>
          <input id="verify-code" value={code} onChange={e => setCode(e.target.value)} placeholder="XXXX-XXXX-XXXX" autoComplete="off" spellCheck={false} />
          <button type="submit" className="primary">{t('Check')}</button>
        </form>
        {state === 'loading' && <p className="muted" role="status">{t('Checking…')}</p>}
        {state === 'missing' && <p className="notice error" role="alert">{t('No document with this code. Check the code; a document without a valid seal cannot be confirmed.')}</p>}
        {state === 'error' && <p className="notice error" role="alert">{t('The check is not available right now. Try again later.')}</p>}
        {view && (
          <section className={`verify-result ${tone}`} aria-live="polite">
            <p className={`verify-status status ${tone}`}>{t(label)}</p>
            <dl className="verify-facts">
              <div><dt>{t('Document')}</dt><dd>{t(view.document_type)}</dd></div>
              <div><dt>{t('Number')}</dt><dd>{view.number}</dd></div>
              <div><dt>{t('Title')}</dt><dd>{t(view.title)}</dd></div>
              <div><dt>{t('Project')}</dt><dd>{view.project || '–'}</dd></div>
              <div><dt>{t('Issued by')}</dt><dd>{view.issuer || '–'}</dd></div>
              <div><dt>{t('Date of issue')}</dt><dd>{formatDate(view.date)}</dd></div>
              {view.revoked_on && <div><dt>{t('Revoked on')}</dt><dd>{formatDate(view.revoked_on)}</dd></div>}
              {view.superseded_by && <div><dt>{t('Newer issue')}</dt><dd>{view.superseded_by}</dd></div>}
            </dl>
            <p className="verify-hash"><span className="muted small">SHA-256</span> {view.hash}</p>
            <p className="help">{t('This page confirms that the document was issued as stated. Compare the number, title and date with your copy; it shows no technical data.')}</p>
          </section>
        )}
      </div>
    </main>
  )
}
