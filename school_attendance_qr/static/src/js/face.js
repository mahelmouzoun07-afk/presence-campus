/* Vérification du visage (caméra avant). Le téléphone ne fait que filmer et guider :
 * toute la décision est prise par le serveur de l'école. Les images ne sont gardées
 * nulle part (ni sur le téléphone ni sur le serveur) après l'analyse.
 *
 * SchoolFace.prepare({course, place}) → Promise<{ skip } | { frames, noCamera } | { enrolledNow }>
 *   - { skip: true }  : la vérification du visage n'est pas demandée par l'école ;
 *   - { frames: [...] }: 3 images prises sous 3 couleurs d'écran, à joindre à la confirmation ;
 *   - { noCamera: true }: pas de caméra utilisable (le serveur le traitera comme « à vérifier »).
 * Au premier usage, lance l'inscription guidée avant la vérification.
 * Si l'étudiant annule, la promesse est rejetée avec une erreur portant cancelled = true. */
(function (global) {
  'use strict';

  var POSES = [
    'Regardez droit devant vous',
    'Tournez doucement la tête vers la gauche',
    'Tournez doucement la tête vers la droite',
    'Levez un peu le menton',
    'Baissez un peu le menton',
  ];
  var COLORS = { red: '#ff1a1a', green: '#14d62b', blue: '#1f3dff' };
  var MAX_WIDTH = 480, JPEG_QUALITY = 0.7;
  var NS = 'http://www.w3.org/2000/svg';
  var ICON_FACE = ['M4 8V6a2 2 0 0 1 2-2h2M16 4h2a2 2 0 0 1 2 2v2M20 16v2a2 2 0 0 1-2 2h-2M8 20H6a2 2 0 0 1-2-2v-2',
                   'M9 9.5v1.2M15 9.5v1.2', 'M9 14.2c1.4 1.3 4.6 1.3 6 0'];
  var ICON_SHIELD = ['M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6l8-3z'];
  var ICON_CLOSE = ['M6 6l12 12M18 6L6 18'];
  var ICON_CHECK = ['M5 12l5 5L20 7'];

  var run = { cancelled: false, abort: null };  // annulation en cours de route

  function rpc(url, params) { return global.SchoolAttendance.rpcCall(url, params); }
  function cancelError() { var e = new Error('Vérification annulée.'); e.cancelled = true; return e; }
  function wait(ms) {
    return new Promise(function (resolve, reject) {
      if (run.cancelled) { reject(cancelError()); return; }
      var t = setTimeout(function () { run.abort = null; run.cancelled ? reject(cancelError()) : resolve(); }, ms);
      run.abort = function () { clearTimeout(t); reject(cancelError()); };
    });
  }

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined && text !== null) e.textContent = text;
    return e;
  }
  function icon(paths, size, width) {
    var svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('width', size); svg.setAttribute('height', size); svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('fill', 'none'); svg.setAttribute('stroke', 'currentColor'); svg.setAttribute('stroke-width', width || 2.2);
    svg.setAttribute('stroke-linecap', 'round'); svg.setAttribute('stroke-linejoin', 'round'); svg.setAttribute('aria-hidden', 'true');
    paths.forEach(function (d) { var p = document.createElementNS(NS, 'path'); p.setAttribute('d', d); svg.appendChild(p); });
    return svg;
  }

  function openCamera() {
    var md = navigator.mediaDevices;
    if (!md || !md.getUserMedia) return Promise.reject({ name: 'NotFoundError' });
    return md.getUserMedia({ video: { facingMode: 'user', width: { ideal: 640 }, height: { ideal: 480 } }, audio: false })
      .catch(function (err) {
        if (err && err.name === 'OverconstrainedError') return md.getUserMedia({ video: true, audio: false });
        throw err;
      });
  }

  /* Mesures sur une petite copie : luminosité moyenne et netteté (variance du Laplacien). */
  function measure(canvas) {
    var w = 120, h = Math.max(1, Math.round(canvas.height * w / canvas.width));
    var c = document.createElement('canvas'); c.width = w; c.height = h;
    var ctx = c.getContext('2d'); ctx.drawImage(canvas, 0, 0, w, h);
    var d = ctx.getImageData(0, 0, w, h).data, g = new Float32Array(w * h), sum = 0, i, x, y;
    for (i = 0; i < w * h; i++) { g[i] = 0.299 * d[i * 4] + 0.587 * d[i * 4 + 1] + 0.114 * d[i * 4 + 2]; sum += g[i]; }
    var lap = 0, lapSq = 0, n = 0;
    for (y = 1; y < h - 1; y++) {
      for (x = 1; x < w - 1; x++) {
        var v = 4 * g[y * w + x] - g[y * w + x - 1] - g[y * w + x + 1] - g[(y - 1) * w + x] - g[(y + 1) * w + x];
        lap += v; lapSq += v * v; n++;
      }
    }
    return { light: sum / (w * h), sharp: lapSq / n - (lap / n) * (lap / n) };
  }

  function grab(video) {
    var scale = Math.min(1, MAX_WIDTH / (video.videoWidth || MAX_WIDTH));
    var c = document.createElement('canvas');
    c.width = Math.round((video.videoWidth || MAX_WIDTH) * scale);
    c.height = Math.round((video.videoHeight || 360) * scale);
    c.getContext('2d').drawImage(video, 0, 0, c.width, c.height);
    var m = measure(c);
    return { data: c.toDataURL('image/jpeg', JPEG_QUALITY), light: m.light, sharp: m.sharp };
  }

  /* Plusieurs images rapprochées : on garde la plus nette. */
  function grabBest(video, count) {
    var best = null, i = 0;
    function next() {
      var f = grab(video);
      if (!best || f.sharp > best.sharp) best = f;
      i++;
      return i < count ? wait(120).then(next) : best;
    }
    return Promise.resolve().then(next);
  }

  /* ------------------------------------------------------------ interface */
  function buildOverlay(opts) {
    var root = el('div', 'sf'), inner = el('div', 'sf-inner');
    root.setAttribute('role', 'dialog'); root.setAttribute('aria-label', 'Vérification du visage');

    var head = el('div', 'sf-head');
    var x = el('button', 'sf-x'); x.type = 'button'; x.setAttribute('aria-label', 'Annuler'); x.appendChild(icon(ICON_CLOSE, 20, 2.6));
    head.appendChild(x);
    head.appendChild(el('h1', 'sf-title', 'Confirmer ma présence'));
    var where = [opts.course, opts.place].filter(Boolean).join(' · ');
    if (where) head.appendChild(el('div', 'sf-sub', where));
    var steps = el('div', 'sf-steps');
    var s1 = el('div', 'sf-step done'), b1 = el('b'); b1.appendChild(icon(ICON_CHECK, 16, 3)); s1.appendChild(b1); s1.appendChild(el('span', '', 'Position'));
    var s2 = el('div', 'sf-step now'), b2 = el('b', '', '2'); s2.appendChild(b2); s2.appendChild(el('span', '', 'Selfie'));
    var s3 = el('div', 'sf-step'), b3 = el('b', '', '3'); s3.appendChild(b3); s3.appendChild(el('span', '', 'Envoi'));
    steps.appendChild(s1); steps.appendChild(el('div', 'sf-line')); steps.appendChild(s2); steps.appendChild(el('div', 'sf-line')); steps.appendChild(s3);
    head.appendChild(steps);
    inner.appendChild(head);

    var card = el('section', 'sf-card');
    var h = el('div', 'sf-h'); h.appendChild(icon(ICON_FACE, 22)); var title = el('span', '', 'Regardez la caméra'); h.appendChild(title);
    var p = el('div', 'sf-p', 'Tenez le téléphone près du visage : la photo se prend toute seule.');
    var cam = el('div', 'sf-cam'), camIn = el('div', 'sf-cam-in');
    var video = document.createElement('video');
    video.setAttribute('playsinline', ''); video.setAttribute('webkit-playsinline', ''); video.muted = true; video.autoplay = true;
    camIn.appendChild(video); cam.appendChild(camIn);
    var status = el('div', 'sf-status'); status.appendChild(el('i')); var statusText = el('span', '', 'Recherche de votre visage…'); status.appendChild(statusText);
    var hint = el('div', 'sf-hint');
    var bars = el('div', 'sf-bars'), cap = el('div', 'sf-cap');
    [h, p, cam, status, hint, bars, cap].forEach(function (n) { card.appendChild(n); });
    inner.appendChild(card);

    var foot = el('div', 'sf-foot');
    var note = el('div', 'sf-note'); note.appendChild(icon(ICON_SHIELD, 22, 2));
    note.appendChild(el('span', '', "Votre photo n'est jamais conservée : seule une empreinte numérique de votre visage est gardée."));
    var go = el('button', 'sf-go', 'Commencer'); go.type = 'button'; go.style.display = 'none';
    var cancel = el('button', 'sf-cancel', 'Annuler'); cancel.type = 'button';
    foot.appendChild(note); foot.appendChild(go); foot.appendChild(cancel);
    inner.appendChild(foot);
    root.appendChild(inner);
    document.body.appendChild(root);

    function stop() { run.cancelled = true; if (run.abort) run.abort(); }
    x.addEventListener('click', stop); cancel.addEventListener('click', stop);
    return { root: root, title: title, p: p, status: statusText, video: video, hint: hint, bars: bars, cap: cap, go: go,
             cancel: cancel, step2: s2, step3: s3, b3: b3 };
  }

  function setBars(ui, total, done) {
    while (ui.bars.firstChild) ui.bars.removeChild(ui.bars.firstChild);
    for (var i = 0; i < total; i++) ui.bars.appendChild(el('span', i < done ? 'on' : ''));
  }

  function guidance(ui, stop) {
    var timer = setInterval(function () {
      if (!ui.video.videoWidth) return;
      var m = measure(grab_canvas(ui.video));
      ui.hint.textContent = m.light < 70 ? 'Trop sombre : tournez-vous vers une fenêtre ou une lampe.' : '';
    }, 500);
    stop.push(function () { clearInterval(timer); });
  }
  function grab_canvas(video) {
    var c = document.createElement('canvas'); c.width = 160; c.height = Math.round(160 * (video.videoHeight / video.videoWidth) || 120);
    c.getContext('2d').drawImage(video, 0, 0, c.width, c.height); return c;
  }

  /* Test de vie : l'écran prend tour à tour trois couleurs, le serveur vérifie leur reflet sur le visage. */
  function flashPhase(ui, colors) {
    var frames = [];
    ui.root.classList.add('flash');
    ui.status.textContent = "Regardez l'écran sans bouger";
    return colors.reduce(function (p, color, i) {
      return p.then(function () {
        ui.root.style.background = COLORS[color];
        return wait(450).then(function () { return grabBest(ui.video, 2); }).then(function (f) { frames.push(f.data); });
      });
    }, Promise.resolve()).then(function () {
      ui.root.classList.remove('flash'); ui.root.style.background = '';
      return frames;
    }, function (err) { ui.root.classList.remove('flash'); ui.root.style.background = ''; throw err; });
  }

  function posesPhase(ui) {
    var frames = [];
    setBars(ui, POSES.length, 0);
    ui.p.textContent = "Suivez les consignes : la photo se prend toute seule.";
    ui.cap.textContent = 'Inscription : ' + POSES.length + ' positions à prendre';
    return POSES.reduce(function (p, text, i) {
      return p.then(function () {
        ui.title.textContent = text;
        ui.status.textContent = 'Restez immobile…';
        return wait(1800).then(function () { return grabBest(ui.video, 3); }).then(function (f) {
          frames.push(f.data); setBars(ui, POSES.length, i + 1);
        });
      });
    }, Promise.resolve()).then(function () { return frames; });
  }

  function intro(ui) {
    ui.title.textContent = 'Enregistrez votre visage (une seule fois)';
    ui.p.textContent = 'Retirez lunettes, casquette et masque. Placez-vous face à la lumière, seul(e), le téléphone à hauteur du visage.';
    ui.status.textContent = 'Prêt quand vous l\'êtes';
    ui.go.style.display = 'block';
    return new Promise(function (resolve, reject) {
      run.abort = function () { reject(cancelError()); };
      ui.go.addEventListener('click', function () { run.abort = null; ui.go.style.display = 'none'; resolve(); });
    });
  }

  function prepare(opts) {
    opts = opts || {};
    run = { cancelled: false, abort: null };
    return rpc('/school/attendance/face/status').then(function (status) {
      if (!status || !status.active) return { skip: true };
      var stops = [], ui, stream;
      function cleanup() {
        stops.forEach(function (f) { f(); });
        if (stream) stream.getTracks().forEach(function (t) { t.stop(); });
        if (ui) ui.root.remove();
      }
      return openCamera().then(function (s) {
        stream = s;
        ui = buildOverlay(opts);
        ui.video.srcObject = stream;
        return ui.video.play().catch(function () { /* lecture automatique refusée : l'image arrivera quand même */ });
      }, function () { return 'nocamera'; }).then(function (noCam) {
        if (noCam === 'nocamera') return { noCamera: true };
        guidance(ui, stops);
        return rpc('/school/attendance/face/challenge').then(function (ch) {
          var colors = ch.colors;
          setBars(ui, colors.length, 0);
          ui.cap.textContent = "Test de vie : l'écran change de couleur " + colors.length + ' fois';
          if (status.enrolled) return flashPhase(ui, colors).then(function (frames) { return { frames: frames }; });
          var poses;
          return intro(ui).then(function () { return posesPhase(ui); }).then(function (p) {
            poses = p; setBars(ui, colors.length, 0); ui.cap.textContent = 'Dernier contrôle : test de vie';
            return flashPhase(ui, colors);
          }).then(function (flash) {
            ui.step2.className = 'sf-step done'; ui.step3.className = 'sf-step now';
            ui.title.textContent = 'Enregistrement…'; ui.status.textContent = 'Envoi sécurisé';
            ui.cancel.style.display = 'none';
            return rpc('/school/attendance/face/enroll', { poses: poses, flash: flash });
          }).then(function (res) {
            if (!res || res.error) throw new Error((res && res.error) || "L'enregistrement du visage a échoué.");
            return { enrolledNow: true };
          });
        });
      }).then(function (out) { cleanup(); return out; }, function (err) { cleanup(); throw err; });
    });
  }

  global.SchoolFace = { prepare: prepare };
})(window);
