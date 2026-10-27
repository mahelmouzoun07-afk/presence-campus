# Faire une démonstration devant un client

## 1. Préparer la base de démo (une fois, ~3 minutes)

Dans WSL (ou n'importe quel Linux avec Odoo 18), en indiquant la **position de la salle où se fera la démo** (clic droit sur Google Maps → coordonnées) :

```bash
bash ~/presence-campus/outils/demo.sh 6.3703 2.3912
```

Cela recrée **uniquement** la base `demo_clients` avec : une filière, une promotion, une salle, une enseignante, 5 étudiants (dont Awa et Koffi), une séance qui démarre « maintenant », des notes, un calendrier, un site de stage avec son superviseur et deux gardes passées (une validée, une en attente). Relancez la commande pour tout remettre à zéro avant chaque démonstration.

Puis lancez le serveur et le tunnel :

```bash
bash ~/presence-campus/outils/demo.sh lancer          # Odoo sur le port 8069
cloudflared tunnel --url http://localhost:8069         # dans un autre terminal
```

Mettez l'adresse du tunnel dans Paramètres → Technique → Paramètres système → `web.base.url`.

## 2. Comptes de démonstration

| Rôle | Identifiant | Mot de passe |
|---|---|---|
| Étudiante honnête (Awa) | `demo.awa` | `Demo-Awa-2026` |
| Étudiant « tricheur » (Koffi) | `demo.koffi` | `Demo-Koffi-2026` |
| Étudiante sans téléphone (Fatou) | `demo.fatou` | `90000003` |
| Enseignante | `prof.demo@demo.bj` | `Demo-Prof-2026` |
| Superviseur de stage | `gbaguidi@demo.bj` | `Demo-Superviseur-2026` |
| Administrateur | `admin` | `admin` |

Ce sont des mots de passe de démonstration : n'utilisez jamais cette base pour de vraies données.

## 3. Avant l'arrivée du client

- Awa se connecte sur le téléphone A, installe l'application et ouvre l'accueil. Koffi fait de même sur le téléphone B. Ils enregistrent leur empreinte au premier « Confirmer ».
- Sur l'ordinateur, ouvrez les écrans Tableau de bord, À traiter et Journal d'audit.
- Laissez le champ « Réseau Wi-Fi autorisé » **vide** : vous le renseignerez pendant la démo.
- Les téléphones sont en charge, la localisation est autorisée, les bulles flottantes Android sont fermées.

## 4. Déroulé (15 minutes)

| Min | Acte | Qui fait quoi | Résultat attendu |
|---|---|---|---|
| 0–1 | Annonce des trois preuves : où, sur quel réseau, qui | Vous | Tableau de bord vide |
| 1–2 | **Cas normal** | Awa confirme son entrée avec l'empreinte | Awa « présente » en direct |
| 2–3 | **Hors de la salle** | Awa sort au parking et réessaie | Refus avec la distance affichée |
| 3–4 | **Triche par appareil** | Koffi essaie de confirmer avec le compte d'Awa | Refus, alerte dans « À traiter » |
| 4–5 | **Contrôle du Wi-Fi** | Vous renseignez le réseau, Koffi essaie en 4G puis sur le Wi-Fi avec son compte | Refus en 4G, accepté sur le Wi-Fi |
| 5–7 | **Hors ligne** | Awa passe en mode avion, confirme sa sortie, rétablit le réseau | « Validée hors ligne » |
| 7–9 | **Sans téléphone** | Le client joue Fatou ; l'enseignante relaie avec son empreinte, puis comptage des têtes | Preuve de niveau B/C |
| 9–12 | **Pilotage** | Statistiques, « À traiter », attestation PDF | Pourcentages et PDF numéroté |
| 12–13 | **Audit** | Journal d'audit → « Vérifier l'intégrité » | Chaîne vérifiée |
| 13–15 | **Stages cliniques** | Awa confirme sa garde, le superviseur la valide avec son empreinte, relevé d'heures PDF | Garde doublement validée |

## 5. Plan B

- **Pas de réseau** : montrez le mode hors ligne, puis les captures du README.
- **Localisation refusée sur Android** : fermez les bulles flottantes d'autres applications ou passez sur l'iPhone.
- **Une triche qui n'est pas refusée comme prévu** : expliquez qu'une application de fausse position peut tromper le GPS ; le système rend la fraude visible (détections), pas impossible.
- **En retard** : sautez les stages ou le mode sans téléphone, jamais le cas normal ni la triche.

## 6. À dire honnêtement

Le projet n'est pas encore audité ni en production ; la localisation est une donnée sensible (conformité APDP) ; proposez un **pilote d'un mois** sur une promotion.
