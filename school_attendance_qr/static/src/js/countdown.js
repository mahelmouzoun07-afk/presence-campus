/* Compte à rebours de la fenêtre de confirmation d'un cours : met à jour tous
 * les éléments avec data-close-at (heure UTC ISO) toutes les secondes.
 * S'arrête à 0, et affiche « fermée » quand c'est passé. */
(function () {
  'use strict';
  function fmt(ms) {
    if (ms <= 0) return 'fenêtre fermée';
    var m = Math.floor(ms / 60000), s = Math.floor((ms % 60000) / 1000);
    return 'ferme dans ' + m + ':' + (s < 10 ? '0' + s : s);
  }
  function tick() {
    document.querySelectorAll('[data-close-at]').forEach(function (el) {
      var ts = Date.parse(el.getAttribute('data-close-at'));
      if (!ts) return;
      el.textContent = fmt(ts - Date.now());
    });
  }
  document.addEventListener('DOMContentLoaded', function () { tick(); setInterval(tick, 1000); });
})();
