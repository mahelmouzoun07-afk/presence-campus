# Projet : Système de présence QR+GPS pour écoles (Bénin)

## Ce que fait ce projet

Modules Odoo 18 pour la gestion de présence des étudiants dans les écoles/universités
du Bénin : check-in/check-out par QR code + GPS, authentification WebAuthn (empreinte/
Face ID), portail étudiant, suivi de scolarité, tableaux de bord enseignant/admin.

Deux modules dans ce dossier :
- `school_base/` — modèles de base (école, étudiant, enseignant, promotion, paiement)
- `school_attendance_qr/` — présence QR+GPS, WebAuthn, portail étudiant, QR stylés,
  attestations PDF, alertes d'absence, tâches "À traiter"

Version actuelle : **v11** (manifest 18.0.9.0.0).

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
- Après toute modif de code, relancer avec `-u school_base,school_attendance_qr`
  pour forcer la relecture des fichiers.
- Tunnel de test rapide : `cloudflared tunnel --url http://localhost:8069`, puis mettre
  à jour `web.base.url` dans Paramètres → Technique → Paramètres système.

## Fonctionnalités déjà codées (v11)

QR stylés + affiches PDF, dashboard enseignant temps réel, attestations PDF, boîte
"À traiter" (alertes absence, appareils suspects, impayés), scolarité (`school.payment`,
politique off/flag/block), WebAuthn sur la confirmation, portail étudiant complet
(`/presence`, `/presence/emploi-du-temps`, `/presence/profil`, `/presence/mes-absences`).

## Pas encore codé (réflexion faite, rien implémenté)

- Étudiants sans téléphone : circuit "présence relayée" (responsable + son WebAuthn,
  conservation des têtes, quota, audit aléatoire, niveaux de preuve A/B/C).
- Filières.
- PWA (manifest dynamique par école, service worker, mode hors ligne avec préchargement
  de défis WebAuthn, distinction panne réelle vs hors réseau campus).
- Notifications push (Firebase).
- Examens et notes (règles de calcul de moyenne configurables par école).
- Calendrier des événements académiques.
- Documents d'études (upload/organisation par matière).
- Interface du responsable (relais).
- Renforts sécurité : 5 tentatives puis signalement, journal d'audit non modifiable,
  détection vitesse impossible / GPS identique / scans en grappe, 2FA admin.

## Problème ouvert au moment du transfert (25/10/2026)

Après déploiement de la v11, le rendu (téléphone via tunnel) affichait toujours
l'ancienne version. Pistes non encore vérifiées : ancien processus `odoo-bin` encore
actif, mauvaise base, `__pycache__` périmé, cache navigateur.

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
