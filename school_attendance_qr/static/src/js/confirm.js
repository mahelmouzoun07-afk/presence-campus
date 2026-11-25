/* Logique partagée du bouton de confirmation : géolocalisation, puis selfie
 * (cours) ou WebAuthn (relais, stages), puis appel au serveur.
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

  /* Même formule que le serveur (_haversine_meters) : distance en mètres. */
  function haversine(lat1, lon1, lat2, lon2) {
    var R = 6371000, rad = Math.PI / 180;
    var dLat = (lat2 - lat1) * rad, dLon = (lon2 - lon1) * rad;
    var a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
      Math.cos(lat1 * rad) * Math.cos(lat2 * rad) * Math.sin(dLon / 2) * Math.sin(dLon / 2);
    return 2 * R * Math.asin(Math.sqrt(a));
  }

  /* Minimisation des données : la position ne quitte le téléphone que si
   * elle tombe dans une des zones prévues (salle, site de stage), avec la
   * même tolérance que le serveur (rayon + précision du GPS). Sinon on
   * n'envoie que « hors zone » (latitude/longitude nulles) : le serveur ne
   * saura jamais où était l'étudiant. Une position transmise est toujours
   * revérifiée par le serveur : modifier ce calcul ne permet pas de tricher.
   * Renvoie {send: champs à transmettre, outside: bool, distance: m (local)}. */
  function minimizePosition(coords, zones) {
    var acc = Math.max(coords.accuracy || 0, 0), nearest = null, inside = false;
    (zones || []).forEach(function (z) {
      var d = haversine(z.lat, z.lng, coords.latitude, coords.longitude);
      if (nearest === null || d < nearest) nearest = d;
      if (d <= z.radius + acc) inside = true;
    });
    if (inside) {
      return { outside: false, distance: nearest,
               send: { latitude: coords.latitude, longitude: coords.longitude, accuracy: coords.accuracy } };
    }
    return { outside: true, distance: nearest, send: { latitude: null, longitude: null, accuracy: coords.accuracy } };
  }

  function distanceLabel(m) {
    if (m === null || m === undefined) return '';
    return m >= 1000 ? (m / 1000).toFixed(1).replace('.', ',') + ' km' : Math.round(m) + ' m';
  }

  function outsideMessage(zoneCheck, place) {
    var where = zoneCheck.distance !== null ? 'Vous êtes à ' + distanceLabel(zoneCheck.distance) + ' ' + (place || 'de la salle') + '. ' : '';
    return where + 'Votre position, vérifiée sur votre téléphone, n\'a pas été transmise.';
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

  /* ------------------------------------------------ écran de résultat plein écran */
  var ICONS = {
    ok: 'M5 12l5 5L20 7',
    warn: 'M12 8v5M12 16.5h.01M10.3 3.9L2.6 17a2 2 0 0 0 1.7 3h15.4a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z',
    bad: 'M6 6l12 12M18 6L6 18',
  };
  function svgIcon(d, size) {
    var ns = 'http://www.w3.org/2000/svg', svg = document.createElementNS(ns, 'svg'), path = document.createElementNS(ns, 'path');
    svg.setAttribute('width', size); svg.setAttribute('height', size); svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('fill', 'none'); svg.setAttribute('stroke', 'currentColor'); svg.setAttribute('stroke-width', '3');
    svg.setAttribute('stroke-linecap', 'round'); svg.setAttribute('stroke-linejoin', 'round'); svg.setAttribute('aria-hidden', 'true');
    path.setAttribute('d', d); svg.appendChild(path);
    return svg;
  }
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined && text !== null) e.textContent = text;
    return e;
  }
  /* spec : kind (ok|warn|bad), title, sub, message, student {name, initials}, rows [[libellé, texte, chip?]],
   * button {label, onClick}. Tout le texte passe par textContent : rien n'est interprété comme du HTML. */
  function showOutcome(spec) {
    var root = el('div', 'oc ' + (spec.kind === 'ok' ? '' : spec.kind));
    root.setAttribute('role', 'alertdialog');
    root.setAttribute('aria-live', 'assertive');
    var inner = el('div', 'oc-inner');
    var head = el('div', 'oc-head');
    var icon = el('div', 'oc-icon');
    icon.appendChild(svgIcon(ICONS[spec.kind], 46));
    head.appendChild(icon);
    head.appendChild(el('h1', 'oc-title', spec.title));
    if (spec.sub) head.appendChild(el('div', 'oc-sub', spec.sub));
    inner.appendChild(head);

    if (spec.rows && spec.rows.length) {
      var card = el('div', 'oc-card');
      var av = el('div', 'oc-avatar');
      av.appendChild(el('span', '', (spec.student && spec.student.initials) || ''));
      card.appendChild(av);
      var rows = el('div', 'oc-rows');
      spec.rows.forEach(function (r) {
        var row = el('div', 'oc-row');
        row.appendChild(el('span', 'k', r[0]));
        if (r[2]) {
          var chip = el('span', 'oc-chip ' + r[2]); chip.appendChild(el('i')); chip.appendChild(document.createTextNode(r[1]));
          row.appendChild(chip);
        } else {
          row.appendChild(el('span', 'v', r[1]));
        }
        rows.appendChild(row);
      });
      card.appendChild(rows);
      inner.appendChild(card);
    }
    if (spec.message) inner.appendChild(el('p', 'oc-msg', spec.message));

    var foot = el('div', 'oc-foot');
    var btn = el('button', 'btn-primary', spec.button.label); btn.type = 'button';
    btn.addEventListener('click', function () { root.remove(); spec.button.onClick(); });
    foot.appendChild(btn);
    inner.appendChild(foot);
    root.appendChild(inner);
    document.body.appendChild(root);
    btn.focus({ preventScroll: true });
    return root;
  }

  function nowLabel() {
    var d = new Date();
    return ('0' + d.getHours()).slice(-2) + 'h' + ('0' + d.getMinutes()).slice(-2);
  }

  /* options (facultatif) : confirmUrl (adresse d'envoi, par défaut celle des
   * cours), params (champs ajoutés à l'envoi), offline (champs ajoutés à une
   * confirmation hors ligne, ex. {target: 'internship'}), zones (salles ou
   * sites où la position peut être transmise), place (« de la salle »…),
   * webauthn (false : pas de clé d'appareil, c'est le visage qui prouve),
   * student / course : si présents, le résultat s'affiche en plein écran. */
  function initConfirmWidget(token, phaseHint, options) {
    options = options || {};
    var seal = document.getElementById('ac_seal');
    var result = document.getElementById('ac_result');
    var resultSub = document.getElementById('ac_result_sub');
    if (!seal) return;
    var fullScreen = !!options.student;

    function showResult(cls, text, sub) {
      if (!result) return;
      result.className = 'ac-result ' + cls;
      result.textContent = text;
      result.style.display = 'block';
      if (sub && resultSub) { resultSub.textContent = sub; resultSub.style.display = 'block'; }
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
    function release() { seal.classList.remove('ac-busy'); resetLabel(); }

    /* Affiche un échec : plein écran si la page le prévoit, sinon dans le texte sous le bouton. */
    function fail(message, title) {
      release();
      if (!fullScreen) { showResult('ac-err', message); return; }
      showOutcome({ kind: 'bad', title: title || 'Confirmation impossible', message: message,
                    button: { label: 'Fermer', onClick: function () {} } });
    }

    seal.addEventListener('click', function () {
      if (seal.classList.contains('ac-busy') || seal.classList.contains('ac-stamped')) return;
      seal.classList.add('ac-busy');
      var label = seal.querySelector('.ac-seal-label'); if (label) label.textContent = '...';

      var probe = global.SchoolPwa ? global.SchoolPwa.probe() : Promise.resolve('online');
      probe.then(function (state) {
        if (state === 'offline') {
          global.SchoolPwa.confirmOffline(options.offline, { zones: options.zones }).then(function () {
            seal.classList.remove('ac-busy');
            var text = "Le réseau de l'école ne répond pas. Votre confirmation sera envoyée et vérifiée dès le retour " +
              "de la connexion (badge « Validée hors ligne »).";
            if (fullScreen) {
              seal.classList.add('ac-stamped');
              showOutcome({ kind: 'warn', title: 'Enregistrée hors ligne', sub: 'En attente de synchronisation', message: text,
                            button: { label: 'Terminer', onClick: function () { global.location.reload(); } } });
            } else {
              stamp('var(--muted)', ICON_CHECK);
              showResult('ac-warn', 'Enregistrée hors ligne', text);
            }
            global.SchoolPwa.updateBanner();
          }).catch(function (err) { fail(err && err.message ? err.message : String(err)); });
          return;
        }
        confirmOnline();
      });
    });

    /* Vérification du visage (seulement sur la page des cours, si l'école l'a activée). */
    function faceStep() {
      if (!options.face || !global.SchoolFace) return Promise.resolve({});
      return global.SchoolFace.prepare({ place: options.course && options.course.room, course: options.course && options.course.name })
        .then(function (out) { return out && !out.skip ? out : {}; });
    }

    function present(res, faceChecked, zoneCheck, outsideNote) {
      var isCheckout = res.phase === 'checkout';
      var okLabel = isCheckout ? 'Sortie confirmée' : 'Entrée confirmée';
      var warnLabel = isCheckout ? 'Sortie enregistrée, à vérifier' : 'Entrée enregistrée, à vérifier';
      var errLabel = isCheckout ? 'Sortie refusée' : 'Entrée refusée';
      if (!fullScreen) {
        if (res.error) { stamp('var(--brick)', ICON_CROSS); showResult('ac-err', res.error); }
        else if (res.state === 'valid') { stamp('var(--green)', ICON_CHECK); showResult('ac-ok', okLabel); }
        else if (res.state === 'rejected') { stamp('var(--brick)', ICON_CROSS); showResult('ac-err', errLabel, res.flag_reason); }
        else { stamp('var(--amber)', ICON_WARN); showResult('ac-warn', warnLabel, res.flag_reason); }
        return;
      }
      if (res.error) { fail(res.error); return; }
      if (res.state === 'rejected') { fail(res.flag_reason || 'La confirmation a été refusée.', errLabel); return; }
      seal.classList.add('ac-stamped');
      var course = res.course_name || (options.course && options.course.name) || '';
      var room = res.room_name || (options.course && options.course.room) || '';
      var rows = [
        ['Nom', options.student.name], ['Matricule', options.student.matricule],
        ['Cours', course], ['Salle · heure', room + ' · ' + (res.time_label || nowLabel())],
      ];
      var done = { label: 'Terminer', onClick: function () { global.location.reload(); } };
      if (res.state === 'valid') {
        rows.push(['Preuve', faceChecked ? 'Visage + position vérifiés' : 'Position vérifiée', 'ok']);
        showOutcome({ kind: 'ok', title: isCheckout ? 'Sortie enregistrée !' : 'Présence enregistrée !',
          sub: isCheckout ? 'Votre sortie a bien été prise en compte.' : 'Votre entrée a bien été prise en compte.',
          student: options.student, rows: rows, button: done });
      } else {
        rows.push(['À vérifier', res.flag_reason || 'Un responsable va contrôler votre présence.', 'warn']);
        showOutcome({ kind: 'warn', title: 'Enregistrée, à vérifier',
          sub: 'Un responsable va contrôler votre présence.', student: options.student, rows: rows, button: done });
      }
    }

    function confirmOnline() {
      if (!navigator.geolocation) { fail("Localisation indisponible sur cet appareil."); return; }
      navigator.geolocation.getCurrentPosition(function (pos) {
        var zoneCheck = minimizePosition(pos.coords, options.zones);
        // Cours : le visage (selfie + test de vie) remplace WebAuthn. Relais et stages gardent WebAuthn.
        var device = options.webauthn === false ? Promise.resolve(null) : runWebAuthnCeremony(options.optionsUrl);
        var faceChecked = false;
        device.then(function (wa) {
          return faceStep().then(function (face) {
            faceChecked = !!(face.frames || face.enrolledNow);
            var params = { token: token, device_fingerprint: deviceFingerprint(),
                           face_frames: face.frames || null, face_no_camera: !!face.noCamera };
            if (wa) { params.webauthn_mode = wa.mode; params.webauthn_credential = wa.credential; }
            return rpcCall(options.confirmUrl || '/school/attendance/confirm',
              Object.assign(params, zoneCheck.send, options.params || {}));
          });
        }).then(function (res) {
          if (res && zoneCheck.outside && res.state === 'rejected') res.flag_reason = outsideMessage(zoneCheck, options.place);
          res = res || {};
          seal.classList.remove('ac-busy');
          present(res, faceChecked);
        }).catch(function (err) {
          if (err && err.cancelled) { release(); return; }
          fail(err && err.message ? err.message : "Vérification annulée ou refusée par votre téléphone.");
        });
      }, function () {
        fail("Autorise la localisation pour confirmer ta présence.", 'Position nécessaire');
      }, { enableHighAccuracy: true, timeout: 15000 });
    }
  }

  global.SchoolAttendance = {
    initConfirmWidget: initConfirmWidget, runWebAuthnCeremony: runWebAuthnCeremony, rpcCall: rpcCall,
    b64urlToBuffer: b64urlToBuffer, bufferToB64url: bufferToB64url, deviceFingerprint: deviceFingerprint,
    explainWebAuthnError: explainWebAuthnError, minimizePosition: minimizePosition, outsideMessage: outsideMessage,
  };
})(window);
