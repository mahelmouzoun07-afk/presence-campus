/* Logique partagée du bouton de confirmation : géolocalisation, WebAuthn
 * (empreinte / Face ID / code PIN du téléphone), puis appel au serveur.
 * Utilisée à la fois par la page de scan (QR) et le tableau de bord
 * personnel (lien direct, sans QR). */
(function (global) {
  'use strict';

  function b64urlToBuffer(s) {
    var pad = s + '='.repeat((4 - s.length % 4) % 4);
    var bin = atob(pad.replace(/-/g, '+').replace(/_/g, '/'));
    var buf = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
    return buf.buffer;
  }
  function bufferToB64url(buf) {
    var bytes = new Uint8Array(buf), bin = '';
    for (var i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
    return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  }

  function deviceFingerprint() {
    var key = 'school_device_fingerprint';
    var fp = localStorage.getItem(key);
    if (!fp) { fp = 'dev-' + crypto.randomUUID(); localStorage.setItem(key, fp); }
    return fp;
  }

  function rpcCall(url, params) {
    return fetch(url, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ jsonrpc: '2.0', method: 'call', params: params || {} }),
    }).then(function (r) { return r.json(); }).then(function (d) { return d.result; });
  }

  /* Déroule la cérémonie WebAuthn : enregistre une nouvelle clé si
   * l'étudiant n'en a pas encore, sinon redemande son empreinte/PIN pour
   * la clé déjà enregistrée. Renvoie {mode, credential} prêt à transmettre
   * au serveur, ou lève une erreur si l'étudiant annule / le téléphone ne
   * supporte pas WebAuthn. */
  var NO_LOCK_MESSAGE = "Votre téléphone n'a pas encore de code, de schéma ou d'empreinte configuré. " +
    "Pour confirmer votre présence en toute sécurité, activez un verrouillage de l'écran, puis réessayez : " +
    "Android : Paramètres > Sécurité > Verrouillage de l'écran. iPhone : Réglages > Face ID et code. " +
    "Si votre téléphone est trop ancien pour cela, signalez-le au secrétariat.";
  var UNSUPPORTED_MESSAGE = "Ce téléphone ne prend pas en charge la vérification sécurisée (trop ancien ou navigateur " +
    "non compatible). Essayez avec Chrome ou Safari à jour ; sinon, signalez-le au secrétariat : votre présence " +
    "sera confirmée par le responsable.";

  /* Traduit les erreurs techniques du navigateur en consignes claires. */
  function explainWebAuthnError(err) {
    var name = err && err.name;
    if (name === 'NotAllowedError') {
      return new Error("Vérification annulée ou refusée par votre téléphone. Si aucun code ni empreinte n'est " +
        "configuré sur ce téléphone : " + NO_LOCK_MESSAGE);
    }
    if (name === 'NotSupportedError' || name === 'SecurityError') return new Error(UNSUPPORTED_MESSAGE);
    if (name === 'InvalidStateError') return new Error("Ce téléphone est déjà enregistré. Réessayez.");
    return err instanceof Error ? err : new Error(String(err));
  }

  /* Vérifie AVANT la cérémonie que le téléphone sait demander un code ou une
   * empreinte : sinon on explique tout de suite quoi faire. */
  function checkDeviceLock() {
    if (!window.PublicKeyCredential) return Promise.reject(new Error(UNSUPPORTED_MESSAGE));
    if (!PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable) return Promise.resolve();
    return PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable().then(function (ok) {
      if (!ok) throw new Error(NO_LOCK_MESSAGE);
    }, function () { /* information indisponible : on tente quand même */ });
  }

  function runWebAuthnCeremony(optionsUrl) {
    return checkDeviceLock().then(function () {
      return rpcCall(optionsUrl || '/school/attendance/webauthn/options', {});
    }).then(function (res) {
      if (!res || res.error) throw new Error((res && res.error) || "Impossible de préparer la vérification.");
      var o = res.options;
      if (res.mode === 'register') {
        var publicKey = Object.assign({}, o, {
          challenge: b64urlToBuffer(o.challenge),
          user: Object.assign({}, o.user, { id: b64urlToBuffer(o.user.id) }),
          excludeCredentials: (o.excludeCredentials || []).map(function (c) {
            return Object.assign({}, c, { id: b64urlToBuffer(c.id) });
          }),
        });
        return navigator.credentials.create({ publicKey: publicKey }).then(function (cred) {
          return { mode: 'register', credential: {
            id: cred.id, rawId: bufferToB64url(cred.rawId), type: cred.type,
            response: {
              clientDataJSON: bufferToB64url(cred.response.clientDataJSON),
              attestationObject: bufferToB64url(cred.response.attestationObject),
            },
          } };
        }, function (err) { throw explainWebAuthnError(err); });
      }
      var publicKeyReq = Object.assign({}, o, {
        challenge: b64urlToBuffer(o.challenge),
        allowCredentials: (o.allowCredentials || []).map(function (c) {
          return Object.assign({}, c, { id: b64urlToBuffer(c.id) });
        }),
      });
      return navigator.credentials.get({ publicKey: publicKeyReq }).then(function (cred) {
        return { mode: 'authenticate', credential: {
          id: cred.id, rawId: bufferToB64url(cred.rawId), type: cred.type,
          response: {
            clientDataJSON: bufferToB64url(cred.response.clientDataJSON),
            authenticatorData: bufferToB64url(cred.response.authenticatorData),
            signature: bufferToB64url(cred.response.signature),
          },
        } };
      }, function (err) { throw explainWebAuthnError(err); });
    });
  }

  /* options (facultatif) : confirmUrl (adresse d'envoi, par défaut celle des
   * cours), params (champs ajoutés à l'envoi), offline (champs ajoutés à une
   * confirmation hors ligne, ex. {target: 'internship'}). */
  function initConfirmWidget(token, phaseHint, options) {
    options = options || {};
    var seal = document.getElementById('ac_seal');
    var result = document.getElementById('ac_result');
    var resultSub = document.getElementById('ac_result_sub');
    if (!seal) return;

    function showResult(cls, text, sub) {
      result.className = 'ac-result ' + cls;
      result.textContent = text;
      result.style.display = 'block';
      if (sub) { resultSub.textContent = sub; resultSub.style.display = 'block'; }
    }
    function stamp(color, iconPath) {
      seal.style.setProperty('--state-color', color);
      seal.innerHTML = '<svg class="ac-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="' + iconPath + '"/></svg>';
      seal.classList.add('ac-stamped');
    }
    var ICON_CHECK = 'M4 12l5 5L20 6';
    var ICON_WARN = 'M12 8v5M12 16.5h.01M10.3 3.9L2.6 17a2 2 0 0 0 1.7 3h15.4a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z';
    var ICON_CROSS = 'M6 6l12 12M18 6L6 18';
    var defaultLabel = phaseHint === 'checkout' ? 'Confirmer ma sortie' : 'Confirmer mon entrée';

    function resetLabel() { var l = seal.querySelector('.ac-seal-label'); if (l) l.textContent = defaultLabel; }

    seal.addEventListener('click', function () {
      if (seal.classList.contains('ac-busy') || seal.classList.contains('ac-stamped')) return;
      seal.classList.add('ac-busy');
      var label = seal.querySelector('.ac-seal-label'); if (label) label.textContent = '...';

      var probe = global.SchoolPwa ? global.SchoolPwa.probe() : Promise.resolve('online');
      probe.then(function (state) {
        if (state === 'offline') {
          global.SchoolPwa.confirmOffline(options.offline).then(function () {
            seal.classList.remove('ac-busy');
            stamp('var(--muted)', ICON_CHECK);
            showResult('ac-warn', 'Enregistrée hors ligne', "Le réseau de l'école ne répond pas. Votre confirmation " +
              "sera envoyée et vérifiée dès le retour de la connexion (badge « Validée hors ligne »).");
            global.SchoolPwa.updateBanner();
          }).catch(function (err) {
            seal.classList.remove('ac-busy'); resetLabel();
            showResult('ac-err', err && err.message ? err.message : String(err));
          });
          return;
        }
        confirmOnline();
      });
    });

    function confirmOnline() {
      if (!navigator.geolocation) {
        seal.classList.remove('ac-busy'); resetLabel();
        showResult('ac-err', "Localisation indisponible sur cet appareil.");
        return;
      }
      navigator.geolocation.getCurrentPosition(function (pos) {
        runWebAuthnCeremony(options.optionsUrl).then(function (wa) {
          return rpcCall(options.confirmUrl || '/school/attendance/confirm', Object.assign({
            token: token, latitude: pos.coords.latitude, longitude: pos.coords.longitude,
            accuracy: pos.coords.accuracy, device_fingerprint: deviceFingerprint(),
            webauthn_mode: wa.mode, webauthn_credential: wa.credential,
          }, options.params || {}));
        }).then(function (res) {
          res = res || {};
          seal.classList.remove('ac-busy');
          var isCheckout = res.phase === 'checkout';
          var okLabel = isCheckout ? 'Sortie confirmée' : 'Entrée confirmée';
          var warnLabel = isCheckout ? 'Sortie enregistrée, à vérifier' : 'Entrée enregistrée, à vérifier';
          var errLabel = isCheckout ? 'Sortie refusée' : 'Entrée refusée';
          if (res.error) { stamp('var(--brick)', ICON_CROSS); showResult('ac-err', res.error); }
          else if (res.state === 'valid') { stamp('var(--green)', ICON_CHECK); showResult('ac-ok', okLabel); }
          else if (res.state === 'rejected') { stamp('var(--brick)', ICON_CROSS); showResult('ac-err', errLabel, res.flag_reason); }
          else { stamp('var(--amber)', ICON_WARN); showResult('ac-warn', warnLabel, res.flag_reason); }
        }).catch(function (err) {
          seal.classList.remove('ac-busy'); resetLabel();
          showResult('ac-err', err && err.message ? err.message : "Vérification annulée ou refusée par votre téléphone.");
        });
      }, function () {
        seal.classList.remove('ac-busy'); resetLabel();
        showResult('ac-err', "Autorise la localisation pour confirmer ta présence.");
      }, { enableHighAccuracy: true, timeout: 15000 });
    }
  }

  global.SchoolAttendance = {
    initConfirmWidget: initConfirmWidget, runWebAuthnCeremony: runWebAuthnCeremony, rpcCall: rpcCall,
    b64urlToBuffer: b64urlToBuffer, bufferToB64url: bufferToB64url, deviceFingerprint: deviceFingerprint,
    explainWebAuthnError: explainWebAuthnError,
  };
})(window);
