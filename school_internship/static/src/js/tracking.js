/* Suivi GPS continu pendant une garde, et réponse aux contrôles de présence.
 *
 * Dès que la garde est ouverte (entrée confirmée), et tant que la page est
 * ouverte, le téléphone suit sa position (watchPosition) et en envoie une
 * toutes les N minutes. Sans réseau (sous-sol, bloc), les positions sont
 * gardées sur le téléphone et envoyées en bloc au retour du réseau.
 * Limite : une application web ne peut pas suivre le GPS écran verrouillé ;
 * on demande donc de garder l'écran allumé (Wake Lock) quand c'est possible. */
(function () {
  'use strict';
  var KEY = 'presence-stage-positions';
  var SA, P, box, last = null, wakeLock = null;

  function load() { try { return JSON.parse(localStorage.getItem(KEY) || '[]'); } catch (e) { return []; } }
  function save(list) { try { localStorage.setItem(KEY, JSON.stringify(list.slice(-500))); } catch (e) { /* plein */ } }
  function status(text, cls) {
    var el = document.getElementById('tr_status');
    if (el) { el.textContent = text; el.style.color = cls || 'var(--muted)'; }
  }

  function flush() {
    var pending = load();
    if (!pending.length) return Promise.resolve();
    return SA.rpcCall('/presence/stages/positions', { points: pending }).then(function (res) {
      res = res || {};
      if (res.error && !res.stop) return;
      save([]);
      if (res.stop) { status('Garde terminée : suivi arrêté.'); return; }
      status('Suivi GPS actif — dernière position envoyée à ' + new Date().toLocaleTimeString().slice(0, 5),
             res.outside ? 'var(--brick)' : 'var(--green)');
      if (res.check && !document.getElementById('tr_check')) location.reload();
    }, function () {
      status('Suivi GPS actif — ' + pending.length + ' position(s) gardée(s) hors ligne', 'var(--amber)');
    });
  }

  function keepAwake() {
    if (!('wakeLock' in navigator)) return;
    navigator.wakeLock.request('screen').then(function (lock) { wakeLock = lock; }, function () {});
  }

  function startTracking(minutes) {
    if (!navigator.geolocation) { status("Localisation indisponible sur ce téléphone.", 'var(--brick)'); return; }
    navigator.geolocation.watchPosition(function (pos) {
      last = { at: new Date().toISOString(), latitude: pos.coords.latitude, longitude: pos.coords.longitude,
               accuracy: pos.coords.accuracy };
    }, function () {
      status("Autorisez la localisation : elle est vérifiée pendant toute la garde.", 'var(--brick)');
    }, { enableHighAccuracy: true, maximumAge: 60000 });
    function tick() {
      if (last) { var list = load(); list.push(last); save(list); last = null; }
      flush();
    }
    setTimeout(tick, 15000);
    setInterval(tick, Math.max(minutes, 1) * 60000);
    keepAwake();
    document.addEventListener('visibilitychange', function () {
      if (document.visibilityState === 'visible') { keepAwake(); tick(); }
    });
  }

  function initCheck() {
    var btn = document.getElementById('tr_check');
    if (!btn) return;
    var msg = document.getElementById('tr_check_msg');
    function show(cls, text) { msg.className = 'ac-result ' + cls; msg.textContent = text; msg.style.display = 'block'; }
    btn.addEventListener('click', function () {
      btn.disabled = true; show('', 'Vérification…');
      P.probe().then(function (state) {
        if (state === 'offline') {
          return P.confirmOffline({ target: 'internship_check' }).then(function () {
            show('ac-warn', 'Contrôle enregistré hors ligne : envoyé et vérifié au retour du réseau.');
            btn.style.display = 'none';
          });
        }
        return new Promise(function (resolve, reject) {
          navigator.geolocation.getCurrentPosition(resolve, function () {
            reject(new Error('Autorisez la localisation pour répondre au contrôle.'));
          }, { enableHighAccuracy: true, timeout: 20000 });
        }).then(function (pos) {
          return SA.runWebAuthnCeremony().then(function (wa) {
            return SA.rpcCall('/presence/stages/controle', {
              latitude: pos.coords.latitude, longitude: pos.coords.longitude, accuracy: pos.coords.accuracy,
              webauthn_mode: wa.mode, webauthn_credential: wa.credential });
          });
        }).then(function (res) {
          res = res || {};
          if (res.error) { btn.disabled = false; show('ac-err', res.error); return; }
          if (res.state === 'done') show('ac-ok', 'Présence confirmée.');
          else show('ac-err', 'Contrôle enregistré, mais vous êtes hors du site : signalé.');
          btn.style.display = 'none';
        });
      }).catch(function (err) { btn.disabled = false; show('ac-err', err.message || String(err)); });
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    SA = window.SchoolAttendance; P = window.SchoolPwa;
    box = document.getElementById('tr_box');
    if (!box) return;
    startTracking(parseInt(box.dataset.minutes || '5', 10));
    initCheck();
  });
})();
