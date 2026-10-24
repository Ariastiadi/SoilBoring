// Offline support: the app itself (HTML, scripts, styles) is kept in the browser so it
// opens without a connection. API calls are never cached here (they carry private data);
// new logs made offline wait in the app's outbox instead.
const CACHE = 'soilboring-app-v2'
const NAV_TIMEOUT_MS = 8000
// Server pages that are not the app (API documentation and schema).
const NOT_APP = ['/api/', '/docs', '/redoc', '/openapi.json']
const STATIC = ['/manifest.webmanifest', '/icon.svg', '/apple-touch-icon.png']

self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(['/', ...STATIC])).then(() => self.skipWaiting()))
})

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k.startsWith('soilboring-app-') && k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim()),
  )
})

const assetsIn = html => new Set((html.match(/\/assets\/[^"'\s>)]+/g) || []))

/** Saves a new app page; after a new release, build files of older releases are removed. */
async function keepShell(response) {
  const cache = await caches.open(CACHE)
  const html = await response.clone().text()
  const old = await cache.match('/')
  const oldHtml = old ? await old.text() : ''
  await cache.put('/', response)
  const wanted = assetsIn(html)
  const before = assetsIn(oldHtml)
  if (!wanted.size || (before.size === wanted.size && [...wanted].every(a => before.has(a)))) return
  // Other chunks (map, bore log, AI) are fetched again the next time they are used online.
  for (const request of await cache.keys()) {
    const path = new URL(request.url).pathname
    if (path.startsWith('/assets/') && !wanted.has(path)) await cache.delete(request)
  }
}

function withTimeout(promise, ms) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('timeout')), ms)
    promise.then(v => { clearTimeout(timer); resolve(v) }, e => { clearTimeout(timer); reject(e) })
  })
}

self.addEventListener('fetch', event => {
  const request = event.request
  if (request.method !== 'GET') return
  const url = new URL(request.url)
  if (url.origin !== self.location.origin || NOT_APP.some(p => url.pathname.startsWith(p))) return

  if (request.mode === 'navigate') {
    // Newest page when online; the saved one when offline or when the network hangs.
    event.respondWith(
      withTimeout(fetch(request), NAV_TIMEOUT_MS)
        .then(response => {
          const type = response.headers.get('content-type') || ''
          // Only the app page itself is kept (not a JSON file or image opened directly).
          if (response.ok && type.includes('text/html')) event.waitUntil(keepShell(response.clone()))
          return response
        })
        .catch(() => caches.match('/').then(hit => hit || Response.error())),
    )
    return
  }

  if (STATIC.includes(url.pathname)) {
    event.respondWith(fetch(request).catch(() => caches.match(url.pathname).then(hit => hit || Response.error())))
    return
  }

  if (url.pathname.startsWith('/assets/')) {
    // Build files have a content hash in their name, so a cached copy is always right.
    event.respondWith(
      caches.match(request).then(hit => hit || fetch(request).then(response => {
        if (response.ok) {
          const copy = response.clone()
          caches.open(CACHE).then(cache => cache.put(request, copy))
        }
        return response
      })),
    )
  }
})
