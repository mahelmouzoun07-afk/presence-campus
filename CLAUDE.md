# Projet : Système de présence QR+GPS pour écoles (Bénin)

## Ce que fait ce projet

Modules Odoo 18 pour la gestion de présence des étudiants dans les écoles/universités
du Bénin : check-in/check-out par QR code + GPS, authentification WebAuthn (empreinte/
Face ID), portail étudiant, suivi de scolarité, tableaux de bord enseignant/admin.

Trois modules dans ce dossier :
- `school_base/` — modèles de base (étudiant, enseignant, filière, promotion, cours,
  salle, emploi du temps, paiement) ; groupes Enseignant / Administration / Direction
- `school_attendance_qr/` — présence QR+GPS, WebAuthn, portail étudiant (PWA), hors
  ligne, présence relayée, notifications push, sécurité (audit, détections), surveillance
- `school_academic/` — examens et notes, moyennes, bulletins, calendrier, documents

Version actuelle : **v12** (school_base 18.0.5.0.0, school_attendance_qr 18.0.10.0.0,
school_academic 18.0.1.0.0). Branche Git : `v12/fonctionnalites-0-a-3` (v11 = `main`).

## Architecture d'hébergement retenue

- Serveur sur site ("sur site, connecté"), tunnel Cloudflare nommé pour un sous-domaine
  stable par école (ex. `iut.presence.bj`), un seul serveur Odoo multi-bases.
- `dbfilter` isole chaque école dans sa propre base de données.
- La restriction Wi-Fi campus (`school_attendance_qr.campus_ip_ranges`) ne s'applique
  QU'À l'action de confirmation de présence, jamais au reste du portail.

## WebAuthn — points importants

- Package Python `webauthn` v3.0.1. Utiliser `parse_registration_credential_json` /
  `parse_authentication_credential_json`, PAS `.parse_raw()` (n'existe pas en v3.0.1).
- `rp_id_from_request` dérive le domaine depuis `httprequest.host` (sans le port).
- Le challenge est stocké dans la session Odoo (`school_webauthn_challenge`).
- Le contrôle d'empreinte navigateur (localStorage) reste une couche additionnelle,
  pas un remplacement de WebAuthn.

## Emplacement du projet

- Dossier réel : `C:\Users\HP\Desktop\Presence-Ecole` (Bureau Windows).
- Dans WSL, `~/odoo-custom-addons` est un lien symbolique vers
  `/mnt/c/Users/HP/Desktop/Presence-Ecole` : les commandes Odoo ci-dessous restent valides.
- `outils/` : `commandes.txt` (commandes de lancement Odoo + tunnel) et l'ancien raccourci
  `Odoo.lnk` (URL de tunnel périmée).
- Ancienne copie conservée dans WSL : `~/odoo-custom-addons.sauvegarde-2026-10-25`.
- Outils Claude du projet : skills Odoo dans `.claude/skills/`, plugins `superpowers` et
  `odoo-lens` (déclarés dans `.claude/settings.json`). odoo-lens lit une copie des sources
  Odoo 18 (code uniquement) dans `D:\odoo-sources\odoo-18.0` (voir `.odoo-lens.json`) —
  à recopier depuis `~/odoo` si Odoo est mis à jour.

## Environnement de test (WSL Ubuntu)

```bash
cd ~/odoo && source venv/bin/activate
./odoo-bin --addons-path=addons,$HOME/odoo-custom-addons -d mon_ecole \
  -u school_base,school_attendance_qr --stop-after-init   # test d'install
./odoo-bin --addons-path=addons,$HOME/odoo-custom-addons -d mon_ecole \
  --proxy-mode   # lancement réel, derrière le tunnel Cloudflare
```

- PostgreSQL : `sudo service postgresql start`
- Installer un paquet Python dans le venv : toujours `python -m pip install <paquet>`,
  jamais `pip install` seul (peut pointer vers le mauvais interpréteur sur cette machine).
- Après toute modif de code, relancer avec `-u school_base,school_attendance_qr,school_academic`
  pour forcer la relecture des fichiers.
- Tests automatiques (base séparée `presence_test`, jamais la vraie) :
  `bash ~/odoo-custom-addons/outils/lancer-tests.sh` — 78 tests. Les tests ne doivent
  pas dépendre des données déjà présentes dans `presence_test` (noms uniques).
- Paquet Python supplémentaire : `pywebpush` (notifications push), installé dans le venv.
- Infra (sauvegardes, surveillance, tunnel nommé, mode hybride) : `outils/INFRA.md`.
- Adresse de test fixe : Tailscale Funnel (dans WSL) `https://mahel.tail88ed56.ts.net` → port 8069
  (`tailscale funnel status`). Funnel envoie X-Forwarded-For : l'IP réelle arrive via `--proxy-mode`.
- Ancien tunnel de test rapide : `cloudflared tunnel --url http://localhost:8069` (adresse qui change),
  puis mettre à jour `web.base.url` dans Paramètres → Technique → Paramètres système.

## Fonctionnalités codées (v12)

- v11 : QR stylés + affiches PDF, dashboard enseignant, attestations PDF, « À traiter »,
  scolarité (politique off/flag/block), WebAuthn sur la confirmation, portail étudiant.
- Correctif : après connexion, les étudiants arrivaient sur `/my` (portail Odoo
  générique = « l'ancienne version ») → redirection vers `/presence` (`controllers/portal.py`).
- Filières (étudiant ← promotion, cours, emploi du temps, statistiques).
- Sécurité : mot de passe de départ (matricule) à changer obligatoirement ; 5 échecs de
  connexion → compte signalé (compteur écrit APRÈS l'annulation de la transaction de
  connexion, dans `_login`) ; journal d'audit `school.audit.log` chaîné SHA-256 (seule
  exception « SQL brut » : verrou `pg_advisory_xact_lock`) ; détections GPS identique,
  confirmations groupées, déplacement impossible ; 2FA personnel via `auth_totp.policy`.
- Présence relayée (`/presence/relais`) : liste fermée « sans téléphone », saisie de
  l'identité par l'étudiant, WebAuthn du responsable (clé sur `school.teacher` ou sur le
  délégué), quota, comptage des têtes, contrôles aléatoires, niveaux de preuve A/B/C.
- PWA : manifest/icône par école, service worker `/presence/sw.js` (portée `/presence`),
  guide iPhone. Hors ligne : défis préchargés (`school.offline.challenge`), signature sur
  le téléphone, synchronisation vérifiée côté serveur, preuve C « Validée hors ligne ».
- Notifications : `school.notification.notify(users, titre, texte, url, catégorie)` +
  Web Push (VAPID, sans Firebase) ; préférences par utilisateur ; sécurité toujours envoyée.
- Études : évaluations/notes (`is_graded` distingue 0 et « non saisi »), moyennes selon
  règles de l'école, rang, bulletins PDF, calendrier avec rappels, documents de cours.
- Infra : `outils/sauvegarde.sh` (testé : sauvegarde + restauration), `/presence/sante`,
  surveillance horaire (disque, sauvegardes, erreurs).
- Heures du portail : toujours via `fmt_local` / `local_time` (Odoo stocke en UTC).
- Vie privée GPS : le téléphone vérifie lui-même la zone (`minimizePosition` dans confirm.js, zones
  de la page ou reçues avec les défis hors ligne via `offline_zones`) ; hors zone il envoie
  latitude/longitude nulles (`gps_float` → None → refus « position non transmise »). Une position
  transmise est TOUJOURS revérifiée par le serveur. Effacement après `gps_retention_days` (30 j).
- IP client : `helpers.client_ip()` = `remote_addr` (corrigé par `--proxy-mode`), jamais le
  premier maillon de X-Forwarded-For (falsifiable).
- Changer un script du portail → monter `VERSION` dans `sw.js` (cache des téléphones).

## Reste à faire (hors code ou à décider)

- Tester la PWA, le hors ligne et les push sur de vrais téléphones (Android + iPhone) via
  le tunnel : le navigateur intégré de Claude Code n'accepte pas les service workers.
- Acheter le domaine, créer le tunnel nommé, compte UptimeRobot, programmer la sauvegarde.
- Décider qui relaie (enseignant, délégué ou les deux : réglage, « les deux » par défaut).
- Conformité APDP (loi béninoise sur les données personnelles) : juridique.
- Écrans admin/enseignant dédiés (au-delà des vues Odoo), piste Bluetooth, Odoo 20.

## Conventions de code

- Pas de SQL brut, toujours l'ORM Odoo.
- `ir.rule` pour le filtrage par groupe (`group_school_admin`, `group_school_teacher`),
  jamais de `if user.role ==` dans le code métier.
- Rendu PDF/QR dans `models/render.py` (qrcode + Pillow + reportlab).
- Logo de l'école centralisé sur `company.school_logo`, réutilisé partout
  (QR, affiches, attestations).

## Bug Odoo 18 connu à éviter

`default_order` sur un champ non stocké (`computed`, non-`store=True`) fait planter
le serveur. Ne jamais l'utiliser sur les stats de présence non stockées.
