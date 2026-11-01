/* Vérification du visage (caméra avant). Le téléphone ne fait que filmer et guider :
 * toute la décision est prise par le serveur de l'école. Les images ne sont gardées
 * nulle part (ni sur le téléphone ni sur le serveur) après l'analyse.
 *
 * SchoolFace.prepare() → Promise<{ skip } | { frames, noCamera }>
 *   - { skip: true }  : la vérification du visage n'est pas demandée par l'école ;
 *   - { frames: [...] }: 3 images prises sous 3 couleurs d'écran, à joindre à la confirmation ;
 *   - { noCamera: true }: pas de caméra utilisable (le serveur le traitera comme « à vérifier »).
 * Au premier usage, lance l'inscription guidée avant la vérification. */
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

  function rpc(url, params) { return global.SchoolAttendance.rpcCall(url, params); }
  function wait(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

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

  function buildOverlay() {
    var root = document.createElement('div');
    root.style.cssText = 'position:fixed;inset:0;z-index:99999;background:#111;color:#fff;display:flex;flex-direction:column;' +
      'align-items:center;justify-content:center;gap:16px;padding:20px;text-align:center;font-family:system-ui,sans-serif;' +
      'transition:background .15s;';
    var title = document.createElement('div'); title.style.cssText = 'font-size:20px;font-weight:700;max-width:320px;';
    var video = document.createElement('video');
    video.setAttribute('playsinline', ''); video.muted = true; video.autoplay = true;
    video.style.cssText = 'width:min(62vmin,260px);height:min(78vmin,320px);object-fit:cover;border-radius:50%;' +
      'border:4px solid #fff;transform:scaleX(-1);background:#000;';
    var hint = document.createElement('div'); hint.style.cssText = 'min-height:22px;font-size:15px;color:#ffd166;max-width:320px;';
    var button = document.createElement('button'); button.type = 'button';
    button.style.cssText = 'display:none;height:48px;padding:0 28px;border:0;border-radius:24px;font-size:16px;font-weight:700;' +
      'background:#fff;color:#111;';
    root.appendChild(title); root.appendChild(video); root.appendChild(hint); root.appendChild(button);
    document.body.appendChild(root);
    return { root: root, title: title, video: video, hint: hint, button: button };
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

  function flashPhase(ui, colors) {
    var frames = [];
    ui.title.textContent = "Regardez l'écran sans bouger";
    ui.hint.textContent = '';
    return colors.reduce(function (p, color) {
      return p.then(function () {
        ui.root.style.background = COLORS[color];
        return wait(450).then(function () { return grabBest(ui.video, 2); }).then(function (f) { frames.push(f.data); });
      });
    }, Promise.resolve()).then(function () { ui.root.style.background = '#111'; return frames; });
  }

  function posesPhase(ui) {
    var frames = [];
    return POSES.reduce(function (p, text) {
      return p.then(function () {
        ui.title.textContent = text;
        return wait(1800).then(function () { return grabBest(ui.video, 3); }).then(function (f) { frames.push(f.data); });
      });
    }, Promise.resolve()).then(function () { return frames; });
  }

  function intro(ui) {
    ui.title.textContent = 'Enregistrez votre visage (une seule fois)';
    ui.hint.style.color = '#fff';
    ui.hint.textContent = 'Retirez lunettes, casquette et masque. Placez-vous face à la lumière, seul(e), le téléphone à hauteur du visage.';
    ui.button.textContent = 'Commencer'; ui.button.style.display = 'inline-block';
    return new Promise(function (resolve) {
      ui.button.addEventListener('click', function () {
        ui.button.style.display = 'none'; ui.hint.style.color = '#ffd166'; ui.hint.textContent = ''; resolve();
      });
    });
  }

  function prepare() {
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
        ui = buildOverlay();
        ui.video.srcObject = stream;
        return ui.video.play().catch(function () { /* lecture automatique refusée : l'image arrivera quand même */ });
      }, function () { return 'nocamera'; }).then(function (noCam) {
        if (noCam === 'nocamera') return { noCamera: true };
        guidance(ui, stops);
        return rpc('/school/attendance/face/challenge').then(function (ch) {
          var colors = ch.colors;
          if (status.enrolled) return flashPhase(ui, colors).then(function (frames) { return { frames: frames }; });
          var poses;
          return intro(ui).then(function () { return posesPhase(ui); }).then(function (p) {
            poses = p; return flashPhase(ui, colors);
          }).then(function (flash) {
            ui.title.textContent = 'Enregistrement…';
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
