import React, { Suspense, lazy } from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
// Fonts are bundled with the app (no external requests; they also work offline).
import '@fontsource/barlow/400.css'
import '@fontsource/barlow/500.css'
import '@fontsource/barlow/600.css'
import '@fontsource/barlow/400-italic.css'
import '@fontsource/barlow-semi-condensed/500.css'
import '@fontsource/barlow-semi-condensed/600.css'
import '@fontsource/barlow-semi-condensed/700.css'
import './styles.css'

// Public check of a sealed document (no sign-in): /verify/<code>
const verify = /^\/verify\/?([^/]*)$/.exec(window.location.pathname)
const VerifyPage = lazy(() => import('./tabs/VerifyPage'))

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    {verify ? <Suspense fallback={null}><VerifyPage token={(() => { try { return decodeURIComponent(verify[1] || '') } catch { return '' } })()} /></Suspense> : <App />}
  </React.StrictMode>,
)

// Offline support (see public/sw.js). Not in development, where files change all the time.
if ('serviceWorker' in navigator && import.meta.env.PROD) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => {})
  })
}
