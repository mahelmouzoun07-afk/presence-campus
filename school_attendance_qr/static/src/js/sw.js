/* Service worker du portail étudiant (portée : /presence).
 *
 * - Pages du portail : réseau d'abord (toujours la version à jour), et la
 *   dernière version vue si le réseau ne répond pas en quelques secondes.
 * - Fichiers statiques (scripts, polices, styles) : servis depuis le cache et
 *   rafraîchis en arrière-plan.
 * - Les envois (confirmation de présence, synchronisation) ne passent JAMAIS
 *   par le cache : ils vont au serveur ou échouent, la page gère alors la file
 *   d'attente hors ligne.
 * - Notifications push : affichées même application fermée. */
'use strict';

var VERSION = 'presence-v12-1';
var PAGES = VERSION + '-pages';
var ASSETS = VERSION + '-assets';
var DOCS = 'presence-documents';  // documents gardés hors ligne à la demande (indépendant des versions)
var OFFLINE_URL = '/presence/hors-ligne';
var PRECACHE = [OFFLINE_URL, '/school_attendance_qr/static/src/js/confirm.js',
                '/school_attendance_qr/static/src/js/pwa.js'];

self.addEventListener('install', function (event) {
  event.waitUntil(caches.open(PAGES).then(function (cache) {
    return cache.addAll(PRECACHE).catch(function () { /* première visite sans réseau complet */ });
  }).then(function () { return self.skipWaiting(); }));
});

self.addEventListener('activate', function (event) {
  event.waitUntil(caches.keys().then(function (keys) {
    return Promise.all(keys.filter(function (k) {
      return k.indexOf(VERSION) !== 0 && k !== DOCS;
    }).map(function (k) { return caches.delete(k); }));
  }).then(function () { return self.clients.claim(); }));
});

function timeout(ms) {
  return new Promise(function (_resolve, reject) { setTimeout(function () { reject(new Error('timeout')); }, ms); });
}

function networkFirst(request) {
  return Promise.race([fetch(request), timeout(6000)]).then(function (response) {
    if (response && response.ok && response.type === 'basic' && !response.redirected) {
      var copy = response.clone();
      caches.open(PAGES).then(function (cache) { cache.put(request, copy); });
    }
    return response;
  }).catch(function () {
    return caches.match(request, { ignoreSearch: true }).then(function (cached) {
      return cached || caches.match(OFFLINE_URL);
    });
  });
}

function staleWhileRevalidate(request) {
  return caches.open(ASSETS).then(function (cache) {
    return cache.match(request).then(function (cached) {
      var refresh = fetch(request).then(function (response) {
        if (response && response.ok) cache.put(request, response.clone());
        return response;
      }).catch(function () { return cached; });
      return cached || refresh;
    });
  });
}

self.addEventListener('fetch', function (event) {
  var request = event.request;
  if (request.method !== 'GET') return;  // les envois ne sont jamais mis en cache
  var url = new URL(request.url);
  if (url.origin !== self.location.origin) {
    if (url.hostname.indexOf('fonts.') === 0) event.respondWith(staleWhileRevalidate(request));
    return;
  }
  if (url.pathname === '/presence/ping' || url.pathname.indexOf('/presence/push') === 0) return;
  if (url.pathname.indexOf('/presence/documents/') === 0) {
    event.respondWith(caches.open(DOCS).then(function (cache) {
      return cache.match(request).then(function (cached) { return cached || fetch(request); });
    }));
    return;
  }
  if (request.mode === 'navigate' && url.pathname.indexOf('/presence') === 0) {
    event.respondWith(networkFirst(request));
    return;
  }
  if (url.pathname.indexOf('/web/assets/') === 0 || url.pathname.indexOf('/static/') !== -1 ||
      url.pathname.indexOf('/presence/icone/') === 0 || url.pathname === '/presence/manifest.webmanifest') {
    event.respondWith(staleWhileRevalidate(request));
  }
});

self.addEventListener('push', function (event) {
  var data = {};
  try { data = event.data ? event.data.json() : {}; } catch (e) { data = { title: 'Présence', body: event.data.text() }; }
  event.waitUntil(self.registration.showNotification(data.title || 'Présence', {
    body: data.body || '', icon: '/presence/icone/192.png', badge: '/presence/icone/192.png',
    data: { url: data.url || '/presence' }, lang: 'fr',
  }));
});

self.addEventListener('notificationclick', function (event) {
  event.notification.close();
  var target = (event.notification.data && event.notification.data.url) || '/presence';
  event.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function (list) {
    for (var i = 0; i < list.length; i++) {
      if ('focus' in list[i]) { list[i].navigate(target); return list[i].focus(); }
    }
    return self.clients.openWindow(target);
  }));
});

/* La page demande de garder un document disponible hors ligne. */
self.addEventListener('message', function (event) {
  var msg = event.data || {};
  if (msg.type === 'cache-document' && msg.url) {
    event.waitUntil(caches.open(DOCS).then(function (cache) {
      return cache.add(msg.url);
    }).then(function () {
      if (event.source) event.source.postMessage({ type: 'document-cached', url: msg.url });
    }).catch(function () {
      if (event.source) event.source.postMessage({ type: 'document-cache-failed', url: msg.url });
    }));
  }
});
