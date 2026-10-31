/* Interface du responsable : confirmer la présence d'un étudiant sans
 * téléphone. L'étudiant tape LUI-MÊME son matricule et son identifiant,
 * puis le responsable valide avec sa propre empreinte (WebAuthn). */
(function () {
  'use strict';
  var SA;  // confirm.js est chargé en fin de page : lu au démarrage

  function setMsg(el, cls, text) {
    el.className = 'ac-result ' + cls;
    el.textContent = text;
    el.style.display = 'block';
  }

  function getPosition() {
    return new Promise(function (resolve, reject) {
      if (!navigator.geolocation) { reject(new Error("Localisation indisponible sur cet appareil.")); return; }
      navigator.geolocation.getCurrentPosition(resolve, function () {
        reject(new Error("Autorisez la localisation pour relayer une présence."));
      }, { enableHighAccuracy: true, timeout: 15000 });
    });
  }

  function initRow(row) {
    var openBtn = row.querySelector('.rl-open');
    var form = row.querySelector('.rl-form');
    var submit = row.querySelector('.rl-submit');
    var msg = row.querySelector('.rl-msg');
    openBtn.addEventListener('click', function () {
      form.style.display = form.style.display === 'none' ? 'flex' : 'none';
    });
    submit.addEventListener('click', function () {
      var matricule = row.querySelector('input[name=matricule]').value.trim();
      var identifiant = row.querySelector('input[name=identifiant]').value.trim();
      if (!matricule || !identifiant) { setMsg(msg, 'ac-err', "L'étudiant doit saisir son matricule et son identifiant."); return; }
      submit.disabled = true;
      setMsg(msg, '', 'Vérification en cours…');
      getPosition().then(function (pos) {
        // position du responsable : transmise seulement s'il est dans la salle
        var z = (row.dataset.zone || '').split(',').map(Number);
        var zoneCheck = SA.minimizePosition(pos.coords, z.length === 3 ? [{ lat: z[0], lng: z[1], radius: z[2] }] : []);
        return SA.runWebAuthnCeremony('/presence/relais/options').then(function (wa) {
          return SA.rpcCall('/presence/relais/confirmer', Object.assign({
            session_id: row.dataset.session, student_id: row.dataset.student,
            matricule: matricule, identifiant: identifiant,
            webauthn_mode: wa.mode, webauthn_credential: wa.credential,
          }, zoneCheck.send));
        });
      }).then(function (res) {
        res = res || {};
        if (res.error) { submit.disabled = false; setMsg(msg, 'ac-err', res.error); return; }
        var label = res.phase === 'checkout' ? 'Sortie' : 'Entrée';
        if (res.state === 'valid') setMsg(msg, 'ac-ok', label + ' confirmée pour ' + res.student + '.');
        else if (res.state === 'rejected') setMsg(msg, 'ac-err', label + ' refusée : vous êtes hors de la salle.');
        else setMsg(msg, 'ac-warn', label + ' enregistrée, à vérifier.');
        form.style.display = 'none';
        openBtn.style.display = 'none';
        var counter = document.querySelector('.rl-used[data-session="' + row.dataset.session + '"]');
        if (counter && res.phase !== 'checkout') counter.textContent = String(parseInt(counter.textContent, 10) + 1);
      }).catch(function (err) {
        submit.disabled = false;
        setMsg(msg, 'ac-err', err && err.message ? err.message : String(err));
      });
    });
  }

  function initHeadcount(box) {
    var btn = box.querySelector('.rl-count-submit');
    var msg = box.querySelector('.rl-count-msg');
    btn.addEventListener('click', function () {
      var value = box.querySelector('input[name=headcount]').value;
      if (value === '') { setMsg(msg, 'ac-err', 'Indiquez le nombre de personnes comptées dans la salle.'); return; }
      btn.disabled = true;
      SA.rpcCall('/presence/relais/comptage', { session_id: box.dataset.session, headcount: value }).then(function (res) {
        res = res || {};
        btn.disabled = false;
        if (res.error) { setMsg(msg, 'ac-err', res.error); return; }
        if (res.mismatch) {
          setMsg(msg, 'ac-err', 'Incohérence : ' + res.present + ' présents enregistrés pour ' + res.headcount +
            ' têtes comptées. Les relais sont bloqués et la direction est prévenue.');
        } else {
          setMsg(msg, 'ac-ok', 'Comptage enregistré (' + res.headcount + ' têtes, ' + res.present + ' présents).');
        }
      });
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    SA = window.SchoolAttendance;
    document.querySelectorAll('.rl-row').forEach(initRow);
    document.querySelectorAll('.rl-count').forEach(initHeadcount);
  });
})();
