/* Mode sombre persistant (par téléphone) : lu depuis localStorage avant que la
 * page ne finisse de peindre, pour éviter le « flash » clair. */
(function () {
  'use strict';
  try {
    var saved = localStorage.getItem('presence-theme');
    if (saved === 'dark' || saved === 'light') document.documentElement.setAttribute('data-theme', saved);
  } catch (e) { /* stockage refusé en navigation privée : on garde la préférence système */ }

  window.SchoolTheme = {
    get: function () {
      return document.documentElement.getAttribute('data-theme') || 'auto';
    },
    set: function (value) {
      try {
        if (value === 'dark' || value === 'light') {
          localStorage.setItem('presence-theme', value);
          document.documentElement.setAttribute('data-theme', value);
        } else {
          localStorage.removeItem('presence-theme');
          document.documentElement.removeAttribute('data-theme');
        }
      } catch (e) { /* stockage refusé : la préférence ne tiendra pas, mais pas d'erreur */ }
    },
  };
})();
