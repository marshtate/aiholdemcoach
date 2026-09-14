const CACHE = 'aihc-v1';
const CORE = ['/', '/index.html', '/app.js', '/manifest.webmanifest', '/logo-512.png', '/logo.png', '/apple-touch-icon.png'];

self.addEventListener('install', e => {
e.waitUntil(caches.open(CACHE).then(c => c.addAll(CORE)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});

self.addEventListener('fetch', e => {
const url = new URL(e.request.url);
if (e.request.method !== 'GET') return;
if (url.origin !== self.location.origin) return;
e.respondWith((async () => {
const cache = await caches.open(CACHE);
try {
if (e.request.mode === 'navigate') {
const fresh = await fetch(e.request);
cache.put(e.request, fresh.clone());
return fresh;
}
const cached = await cache.match(e.request);
if (cached) return cached;
const res = await fetch(e.request);
if (res && res.ok) cache.put(e.request, res.clone());
return res;
} catch (err) {
const fallback = await cache.match(e.request) || await cache.match('/');
if (fallback) return fallback;
return new Response('Offline', { status: 503, statusText: 'Offline' });
}
})());
});