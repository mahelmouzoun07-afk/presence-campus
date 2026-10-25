/* Côté page : installation de l'application, mode hors ligne (défis
 * préchargés + file d'attente), notifications push. Dépend de confirm.js. */
(function (global) {
  'use strict';
  var SA = global.SchoolAttendance;

  /* ---------------------------------------------------- petite base locale */
  var DB_NAME = 'presence-hors-ligne';
  function db() {
    return new Promise(function (resolve, reject) {
      var req = indexedDB.open(DB_NAME, 1);
      req.onupgradeneeded = function () {
        req.result.createObjectStore('challenges', { keyPath: 'id' });
        req.result.createObjectStore('queue', { keyPath: 'key' });
        req.result.createObjectStore('meta', { keyPath: 'k' });
      };
      req.onsuccess = function () { resolve(req.result); };
      req.onerror = function () { reject(req.error); };
    });
  }
  function tx(store, mode, fn) {
    return db().then(function (d) {
      return new Promise(function (resolve, reject) {
        var t = d.transaction(store, mode);
        var result = fn(t.objectStore(store));
        t.oncomplete = function () { resolve(result && result.result !== undefined ? result.result : result); };
        t.onerror = function () { reject(t.error); };
      });
    });
  }
  function all(store) { return tx(store, 'readonly', function (s) { return s.getAll(); }); }
  function put(store, value) { return tx(store, 'readwrite', function (s) { s.put(value); }); }
  function del(store, key) { return tx(store, 'readwrite', function (s) { s['delete'](key); }); }
  function clear(store) { return tx(store, 'readwrite', function (s) { s.clear(); }); }

  /* ------------------------------------------------------ test de connexion */
  /* 'offline' : le serveur ne répond pas du tout (vraie panne) ;
   * 'online'  : il répond (même s'il dit « pas sur le Wi-Fi de l'école » :
   *             ce n'est pas une panne, le hors ligne n'est PAS autorisé). */
  function probe() {
    if (!navigator.onLine) return Promise.resolve('offline');
    var ctrl = global.AbortController ? new AbortController() : null;
    var timer = setTimeout(function () { if (ctrl) ctrl.abort(); }, 5000);
    return fetch('/presence/ping?t=' + Date.now(), { cache: 'no-store', signal: ctrl && ctrl.signal })
      .then(function (r) { clearTimeout(timer); return r.ok ? 'online' : 'offline'; })
      .catch(function () { clearTimeout(timer); return 'offline'; });
  }

  /* ------------------------------------------------ défis et synchronisation */
  function refreshChallenges() {
    return SA.rpcCall('/presence/hors-ligne/defis', {}).then(function (res) {
      if (!res || !res.challenges) return;
      return clear('challenges').then(function () {
        return Promise.all(res.challenges.map(function (c) {
          return put('challenges', { id: c.id, challenge: c.challenge, expires_at: c.expires_at,
                                     rp_id: res.rp_id, credential_id: res.credential_id });
        }));
      });
    }).catch(function () { /* pas grave : on réessaiera */ });
  }

  var syncing = false;
  function syncQueue() {
    if (syncing) return Promise.resolve();
    return all('queue').then(function (items) {
      if (!items.length) return;
      syncing = true;
      return SA.rpcCall('/presence/hors-ligne/synchroniser', { items: items }).then(function (res) {
        var results = (res && res.results) || [];
        return Promise.all(results.map(function (r) {
          notifyResult(r);
          return del('queue', r.key);
        }));
      }).then(function () { updateBanner(); }, function () { /* toujours hors ligne */ });
    }).then(function () { syncing = false; }, function () { syncing = false; });
  }

  function notifyResult(r) {
    var box = document.getElementById('pw_sync_result');
    if (!box) return;
    box.style.display = 'block';
    var line = document.createElement('div');
    line.className = 'ac-result ' + (r.ok ? (r.state === 'valid' ? 'ac-ok' : 'ac-warn') : 'ac-err');
    line.textContent = r.ok ? ('Synchronisé : ' + (r.phase === 'checkout' ? 'sortie' : 'entrée') + ' « ' +
      r.course_name + ' » — validée hors ligne') : ('Confirmation hors ligne refusée : ' + r.error);
    box.appendChild(line);
  }

  /* ------------------------------------------------ confirmation hors ligne */
  function getPosition() {
    return new Promise(function (resolve, reject) {
      if (!navigator.geolocation) { reject(new Error("Localisation indisponible sur cet appareil.")); return; }
      navigator.geolocation.getCurrentPosition(resolve, function () {
        reject(new Error("Autorisez la localisation pour confirmer votre présence."));
      }, { enableHighAccuracy: true, timeout: 20000 });
    });
  }

  function confirmOffline() {
    var now = new Date();
    return all('challenges').then(function (list) {
      var usable = list.filter(function (c) { return new Date(c.expires_at) > now; });
      if (!usable.length) {
        throw new Error("Impossible de confirmer hors ligne : ouvrez l'application au moins une fois avec une " +
          "connexion (et confirmez une première présence en ligne) pour l'activer.");
      }
      var c = usable[0];
      return getPosition().then(function (pos) {
        return navigator.credentials.get({ publicKey: {
          challenge: SA.b64urlToBuffer(c.challenge), rpId: c.rp_id, userVerification: 'required', timeout: 60000,
          allowCredentials: [{ type: 'public-key', id: SA.b64urlToBuffer(c.credential_id) }],
        } }).then(function (cred) {
          var item = {
            key: 'k' + Date.now(), challenge_id: c.id, captured_at: new Date().toISOString(),
            latitude: pos.coords.latitude, longitude: pos.coords.longitude, accuracy: pos.coords.accuracy,
            device_fingerprint: SA.deviceFingerprint(),
            credential: { id: cred.id, rawId: SA.bufferToB64url(cred.rawId), type: cred.type, response: {
              clientDataJSON: SA.bufferToB64url(cred.response.clientDataJSON),
              authenticatorData: SA.bufferToB64url(cred.response.authenticatorData),
              signature: SA.bufferToB64url(cred.response.signature),
            } },
          };
          return del('challenges', c.id).then(function () { return put('queue', item); });
        }, function (err) { throw SA.explainWebAuthnError(err); });
      });
    });
  }

  /* --------------------------------------------------------- bandeau état */
  function updateBanner() {
    var banner = document.getElementById('pw_banner');
    if (!banner) return Promise.resolve();
    return all('queue').then(function (queue) {
      var offline = !navigator.onLine || banner.dataset.offline === '1';
      var text = '';
      if (offline) text = 'Hors connexion';
      if (queue.length) text += (text ? ' — ' : '') + queue.length + ' confirmation(s) en attente de synchronisation';
      banner.querySelector('.pw-text').textContent = text;
      banner.style.display = text ? 'flex' : 'none';
      var btn = document.getElementById('pw_offline_confirm');
      if (btn) btn.style.display = offline ? 'block' : 'none';
    });
  }

  function initOfflineButton() {
    var btn = document.getElementById('pw_offline_confirm');
    var msg = document.getElementById('pw_offline_msg');
    if (!btn) return;
    btn.addEventListener('click', function () {
      btn.disabled = true;
      confirmOffline().then(function () {
        msg.className = 'ac-result'; msg.style.color = 'var(--muted)';
        msg.textContent = 'Confirmation enregistrée hors ligne. Elle sera envoyée et vérifiée dès le retour ' +
          'de la connexion (badge « Validée hors ligne »).';
        msg.style.display = 'block';
        updateBanner();
      }).catch(function (err) {
        btn.disabled = false;
        msg.className = 'ac-result ac-err'; msg.textContent = err.message || String(err); msg.style.display = 'block';
      });
    });
  }

  /* ------------------------------------------------------- installation */
  var deferredPrompt = null;
  global.addEventListener('beforeinstallprompt', function (e) {
    e.preventDefault();
    deferredPrompt = e;
    var btn = document.getElementById('pw_install');
    if (btn) btn.style.display = 'flex';
  });
  function isStandalone() {
    return global.matchMedia('(display-mode: standalone)').matches || navigator.standalone === true;
  }
  function initInstall() {
    var btn = document.getElementById('pw_install');
    if (!btn || isStandalone()) return;
    var ios = /iphone|ipad|ipod/i.test(navigator.userAgent);
    if (ios) btn.style.display = 'flex';
    btn.addEventListener('click', function (e) {
      if (deferredPrompt) {
        e.preventDefault();
        deferredPrompt.prompt();
        deferredPrompt.userChoice.then(function () { deferredPrompt = null; btn.style.display = 'none'; });
      }  // sinon (iPhone) : le lien mène au guide d'installation
    });
  }

  /* ------------------------------------------------- notifications push */
  function enablePush() {
    if (!('serviceWorker' in navigator) || !('PushManager' in global)) {
      return Promise.reject(new Error("Ce navigateur ne gère pas les notifications. Sur iPhone, installez d'abord " +
        "l'application sur l'écran d'accueil (iOS 16.4 ou plus récent)."));
    }
    return Notification.requestPermission().then(function (perm) {
      if (perm !== 'granted') throw new Error("Notifications refusées dans les réglages du téléphone.");
      return Promise.all([navigator.serviceWorker.ready, SA.rpcCall('/presence/push/cle', {})]);
    }).then(function (res) {
      return res[0].pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: SA.b64urlToBuffer(res[1].key) });
    }).then(function (sub) {
      return SA.rpcCall('/presence/push/abonner', { subscription: sub.toJSON() });
    });
  }
  function disablePush() {
    return navigator.serviceWorker.ready.then(function (reg) { return reg.pushManager.getSubscription(); })
      .then(function (sub) {
        if (!sub) return;
        return SA.rpcCall('/presence/push/desabonner', { endpoint: sub.endpoint }).then(function () { return sub.unsubscribe(); });
      });
  }
  function pushState() {
    if (!('serviceWorker' in navigator) || !('PushManager' in global)) return Promise.resolve('unsupported');
    // Si le navigateur refuse le service worker, « ready » n'arrive jamais : on n'attend pas plus de 5 s
    var timeout = new Promise(function (resolve) { setTimeout(function () { resolve('unsupported'); }, 5000); });
    var state = navigator.serviceWorker.ready.then(function (reg) { return reg.pushManager.getSubscription(); })
      .then(function (sub) { return sub ? 'on' : 'off'; });
    return Promise.race([state, timeout]);
  }

  function cacheDocument(url) {
    return navigator.serviceWorker.ready.then(function (reg) {
      reg.active.postMessage({ type: 'cache-document', url: url });
    });
  }

  /* ------------------------------------------------------------- démarrage */
  function start() {
    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.register('/presence/sw.js', { scope: '/presence' }).catch(function () {});
    }
    initInstall();
    initOfflineButton();
    probe().then(function (state) {
      var banner = document.getElementById('pw_banner');
      if (banner) banner.dataset.offline = state === 'offline' ? '1' : '0';
      var ctx = document.getElementById('pw_ctx');
      if (state === 'online' && ctx && ctx.dataset.student === '1') {
        refreshChallenges();
        syncQueue();
      }
      updateBanner();
    });
    global.addEventListener('online', function () {
      var banner = document.getElementById('pw_banner');
      if (banner) banner.dataset.offline = '0';
      syncQueue().then(refreshChallenges);
    });
    global.addEventListener('offline', function () {
      var banner = document.getElementById('pw_banner');
      if (banner) banner.dataset.offline = '1';
      updateBanner();
    });
    setInterval(function () { if (navigator.onLine) syncQueue(); }, 60000);
  }
  if (global.indexedDB) document.addEventListener('DOMContentLoaded', start);

  global.SchoolPwa = {
    probe: probe, confirmOffline: confirmOffline, syncQueue: syncQueue, enablePush: enablePush,
    disablePush: disablePush, pushState: pushState, cacheDocument: cacheDocument, updateBanner: updateBanner,
  };
})(window);
