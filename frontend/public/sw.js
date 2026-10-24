// Offline support: the app itself (HTML, scripts, styles) is kept in the browser so it
// opens without a connection. API calls are never cached here (they carry private data);
// new logs made offline wait in the app's outbox instead.
const CACHE = 'soilboring-app-v1'

self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(['/', '/manifest.webmanifest', '/icon.svg'])).then(() => self.skipWaiting()))
})

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k.startsWith('soilboring-app-') && k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim()),
  )
})

self.addEventListener('fetch', event => {
  const request = event.request
  if (request.method !== 'GET') return
  const url = new URL(request.url)
  if (url.origin !== self.location.origin || url.pathname.startsWith('/api/') || url.pathname.startsWith('/docs')) return

  if (request.mode === 'navigate') {
    // Newest page when online; the saved one when offline.
    event.respondWith(
      fetch(request)
        .then(response => {
          if (response.ok) {
            const copy = response.clone()
            caches.open(CACHE).then(cache => cache.put('/', copy))
          }
          return response
        })
        .catch(() => caches.match('/')),
    )
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
