/* Bouton rond de la barre de navigation : ouvre le panneau sombre des actions
 * rapides (page d'accueil). Sur les autres pages, il ramène à l'accueil, panneau ouvert. */
(function (global) {
  'use strict';
  var fab = document.getElementById('tab_confirm');
  if (!fab) return;
  var sheet = document.getElementById('sheet');
  var backdrop = document.getElementById('sheet_backdrop');

  function isOpen() { return document.body.classList.contains('sheet-open'); }
  function open() {
    document.body.classList.add('sheet-open');
    fab.setAttribute('aria-expanded', 'true');
    var first = sheet.querySelector('button:not([disabled]), a');
    if (first) first.focus({ preventScroll: true });
  }
  function close() {
    document.body.classList.remove('sheet-open');
    fab.setAttribute('aria-expanded', 'false');
    fab.focus({ preventScroll: true });
  }

  fab.addEventListener('click', function () {
    if (!sheet) { global.location.href = '/presence#actions'; return; }
    if (isOpen()) close(); else open();
  });
  if (backdrop) backdrop.addEventListener('click', close);
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && isOpen()) close(); });

  if (sheet && global.location.hash === '#actions') {
    open();
    if (global.history && global.history.replaceState) global.history.replaceState(null, '', global.location.pathname);
  }
  global.SchoolSheet = { open: open, close: close };
})(window);
