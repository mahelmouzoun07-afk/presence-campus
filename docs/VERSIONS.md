# Versions

Chaque version est un **tag Git**. Les versions v9 à v11 ont été retrouvées parmi les archives du projet (`odoo_ecole_modules_v9.zip`, `v9b`, `v10`, `v11`) et importées telles quelles, avec la date de l'archive. **Les versions v1 à v8 n'ont pas été conservées** : elles n'existent pas sur le disque de l'auteur et ne peuvent pas être publiées.

| Tag | Date | school_base | school_attendance_qr | Autres modules |
|---|---|---|---|---|
| [`v9`](#v9--présence-par-qr-permanent) | 06/10/2026 | 18.0.3.0.0 | 18.0.7.0.0 | — |
| [`v9b`](#v9b--correctif-de-la-v9) | 06/10/2026 | 18.0.3.0.0 | 18.0.7.1.0 | — |
| [`v10`](#v10--tableau-de-bord-alertes-attestations-scolarité) | 14/10/2026 | 18.0.4.0.0 | 18.0.8.0.0 | — |
| [`v11`](#v11--portail-étudiant-et-empreinte) | 24/10/2026 | 18.0.4.0.0 | 18.0.9.0.0 | — |
| [`v12`](#v12--application-complète) | 26/10/2026 | 18.0.5.0.0 | 18.0.11.0.0 | school_academic 18.0.1.0.0, school_internship 18.0.1.0.0 |

## Installer une version précise

Valable pour toutes les versions. Remplacez `v10` par le tag voulu.

```bash
git clone https://github.com/mahelmouzoun07-afk/presence-campus.git ~/presence-campus
cd ~/presence-campus && git checkout v10        # revenir à cette version

cd ~/odoo && source venv/bin/activate            # Odoo 18 Community
./odoo-bin --addons-path=addons,$HOME/presence-campus -d test_v10 \
  -i school_base,school_attendance_qr --stop-after-init
./odoo-bin --addons-path=addons,$HOME/presence-campus -d test_v10 --proxy-mode
```

- **Utilisez une base neuve par version** (`test_v9`, `test_v10`…). Une mise à jour en place de **v11 vers v12** a été éprouvée ; les autres passages ne l'ont pas été.
- Pour revenir à la dernière version : `git checkout main`.
- Dépendances Python supplémentaires par version : voir chaque section. `qrcode`, `Pillow` et `reportlab` sont déjà fournis par `requirements.txt` d'Odoo.
- Une version ancienne n'a que les modules `school_base` et `school_attendance_qr` ; les dossiers `school_academic` et `school_internship` n'existent qu'à partir de v12.

---

## v9 : présence par QR permanent

**Ce que c'est.** La première version complète du système : un QR code collé dans chaque salle, que l'étudiant scanne pour confirmer son entrée, puis sa sortie.

**Fonctions**
- Étudiants, enseignants, promotions, cours, salles (avec coordonnées GPS et rayon), emploi du temps hebdomadaire.
- Compte de connexion créé automatiquement pour chaque étudiant : identifiant de l'école, matricule comme mot de passe.
- Séances du jour **générées automatiquement** depuis l'emploi du temps (tâche planifiée toutes les 15 minutes) ; deux salles ne peuvent pas être réservées au même moment.
- Scan d'**entrée** (15 min après le début) et de **sortie** (autour de la fin) ; sortie non scannée signalée.
- Contrôle GPS (distance à la salle + précision), un seul appareil par compte (identifiant d'appareil du navigateur), détection d'un même appareil pour plusieurs étudiants.
- Restriction facultative au Wi-Fi de l'école.
- Statistiques : vue d'ensemble du jour, absences par étudiant, par cours, par promotion, par enseignant.

**Installer** : voir ci-dessus, avec `git checkout v9`. Aucune dépendance Python en plus d'Odoo.

**Utiliser**
1. Menu **École** : créer promotions, enseignants, cours, salles (latitude, longitude, rayon), emploi du temps, élèves.
2. Dans **Salles**, ouvrir une salle : son QR s'affiche. L'imprimer et le coller dans la salle.
3. L'étudiant se connecte au site avec son identifiant et son matricule, scanne le QR avec l'appareil photo du téléphone, autorise la localisation et touche le bouton de confirmation.
4. Menu **Présences** : séances, statistiques, absences.
5. Réseau Wi-Fi de l'école (facultatif) : paramètre système `school_attendance_qr.campus_ip_ranges` (menu Paramètres → Technique → Paramètres système, mode développeur), par exemple `41.138.1.0/24`.

**Limites** : le QR doit être scanné avec une adresse **HTTPS** pour que la localisation fonctionne sur les téléphones ; la v9 ne gère qu'une seule base de données par adresse.

## v9b : correctif de la v9

Deux petites corrections de la v9 (school_attendance_qr 18.0.7.1.0) :
- l'adresse encodée dans le QR contient désormais le nom de la base (`?db=…`), nécessaire quand plusieurs bases tournent sur le même serveur ;
- suppression d'un tri (`default_order`) sur un champ calculé non stocké, qui faisait planter la page « Absences par étudiant » d'Odoo 18.

Installation et utilisation : identiques à la v9 (`git checkout v9b`).

## v10 : tableau de bord, alertes, attestations, scolarité

**Ce que ça ajoute à la v9** (school_base 18.0.4.0.0, school_attendance_qr 18.0.8.0.0)
- **Tableau de bord du jour** pour l'enseignant : une carte par séance, présents et absents en direct.
- Boîte **« À traiter »** pour le secrétariat : absences répétées, entrées à vérifier, appareil partagé, tentative depuis un autre appareil, scolarité impayée.
- **Alertes d'absences répétées** automatiques (seuil réglable) et e-mail facultatif à l'étudiant.
- **Attestations de présence en PDF**, avec référence numérotée.
- **QR stylés** (formes, couleurs, dégradés, logo de l'école au centre) et **affiches PDF** prêtes à imprimer.
- **Scolarité** : frais par promotion, paiements, état par étudiant, et réglage « ne rien faire / signaler / bloquer » pour les impayés.
- Un enseignant ne voit que ses cours, ses séances et ses étudiants ; les statistiques par promotion et par enseignant sont réservées à l'administration.
- Écran **Réglages** (Paramètres → École) : fuseau horaire, logo, réseau autorisé, seuils d'alerte.

**Installer** : `git checkout v10`. Dépendances Python : `qrcode`, `Pillow`, `reportlab` (fournies par Odoo).

**Utiliser**
1. **Paramètres → École** : logo, fuseau horaire, réseau Wi-Fi autorisé, seuils d'alerte, politique de scolarité.
2. **École → Configuration → Styles de QR** : choisir les couleurs et le logo, puis, dans **Salles**, imprimer l'affiche PDF.
3. **Tableau de bord** : suivre les séances en direct. **À traiter** : traiter les alertes chaque jour.
4. **Attestations** : choisir un étudiant et une période, télécharger le PDF.
5. **Scolarité** : saisir les paiements reçus.

## v11 : portail étudiant et empreinte

**Ce que ça ajoute à la v10** (school_attendance_qr 18.0.9.0.0)
- **Empreinte digitale / Face ID / code du téléphone (WebAuthn)** à chaque confirmation. Aucune donnée biométrique n'est envoyée : seule une preuve chiffrée.
- **Portail étudiant** : l'étudiant n'a plus besoin de scanner un QR. Après connexion, `/presence` affiche son cours en cours et le bouton de confirmation ; pages Emploi du temps, Profil, Mes absences.
- Statistiques de présence calculées pour chaque étudiant, accessibles depuis son profil.
- Les étudiants arrivent sur `/presence` et se connectent avec leur identifiant (étiquette adaptée sur la page de connexion).

**Installer** : `git checkout v11`. Dépendance Python supplémentaire : `webauthn` (`python -m pip install webauthn`).

**Utiliser**
1. L'étudiant ouvre l'adresse du serveur **en HTTPS**, se connecte (identifiant + matricule) et va sur `/presence`.
2. Il touche « Confirmer mon entrée » : le téléphone demande l'empreinte, la première fois pour enregistrer la clé, ensuite pour s'authentifier.
3. Même fonctionnement pour la sortie. Si un étudiant change de téléphone, le secrétariat clique sur « Réinitialiser l'appareil » sur sa fiche.
4. Le reste est identique à la v10.

**Notes**
- Le tag `v11` est la copie **complète et testée** du dossier de travail. L'archive d'origine `odoo_ecole_modules_v11.zip` est le commit précédent (`v11 : portail étudiant, empreinte (WebAuthn)`) : il lui manquait le fichier `views/attendance_views.xml`.
- La clé d'appareil est liée au **nom de domaine** : une clé créée via un tunnel de test ne marche plus si l'adresse change.

## v12 : application complète

**Ce que ça ajoute à la v11** (school_base 18.0.5.0.0, school_attendance_qr 18.0.11.0.0, plus deux modules)

*Correctif* : après connexion, Odoo envoyait les étudiants sur son portail générique (`/my`) au lieu de `/presence`.

*Nouveautés*
- **Application installable (PWA)** : plus aucune trace d'Odoo, nom et icône de l'école, 4 onglets (Accueil, Planning, Études, Moi) et bouton central de confirmation, mode clair/sombre.
- **Mode hors ligne** : confirmation signée sur le téléphone en cas de panne du Wi-Fi, envoyée et vérifiée au retour du réseau (badge « Validée hors ligne »).
- **Notifications push** (Web Push, sans Firebase) : rappels de cours, absences, notes, échéances, alertes de sécurité.
- **Étudiants sans téléphone** : présence relayée par l'enseignant ou le délégué (quota, comptage des têtes, contrôles aléatoires).
- **Sécurité** : mot de passe personnel obligatoire, 5 échecs = compte signalé, **journal d'audit infalsifiable**, détection de fraude (GPS identique, confirmations groupées, déplacement impossible), double authentification du personnel, groupe Direction.
- **Filières**.
- **Surveillance du serveur**, sauvegardes chiffrées, modèles de tunnel et de configuration (dossier `outils/`).
- **`school_academic`** : évaluations, notes, moyennes selon les règles de l'école, rang, bulletins PDF, calendrier avec rappels, documents de cours consultables hors ligne.
- **`school_internship`** : stages cliniques, gardes à double validation (étudiant puis superviseur), suivi GPS continu et contrôles d'empreinte aux pauses, compteur d'heures, relevé PDF.
- 68 tests automatiques.

**Installer** : voir [INSTALLATION.md](INSTALLATION.md). Dépendances : `webauthn`, `qrcode`, `pillow`, `reportlab`, et `pywebpush` pour les notifications.

**Utiliser** : voir [UTILISATION.md](UTILISATION.md) et le [guide complet](guide-projet.html).

---

## Retrouver le code d'origine de chaque version

```bash
git show v10 --stat                  # ce que contient la version
git diff v10 v11 --stat              # ce qui a changé entre deux versions
git log --oneline --decorate         # toute l'histoire
```
