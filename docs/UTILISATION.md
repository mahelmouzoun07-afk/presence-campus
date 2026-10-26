# Utilisation (version 12)

Ce guide dit **quoi faire selon votre rôle**. Le fonctionnement détaillé du système est dans le [guide complet](guide-projet.html). Pour une version plus ancienne, voir [VERSIONS.md](VERSIONS.md).

## Étudiant

1. **Première connexion** : ouvrez l'adresse de l'école sur votre téléphone (en `https://`). Identifiant = celui de l'école, mot de passe = votre **matricule**. L'application vous demande aussitôt de choisir un **mot de passe personnel** (8 caractères minimum).
2. **Installer l'application** : sur Android, bouton « Installer l'application » ; sur iPhone, Safari → Partager → « Sur l'écran d'accueil ». Ouvrez-la une première fois **avec du réseau**.
3. **Confirmer sa présence** : à l'accueil, quand un cours est ouvert, touchez « Confirmer mon entrée ». Autorisez la localisation, puis déverrouillez le téléphone (empreinte, visage ou code). Refaites « Confirmer ma sortie » en fin de cours.
4. **Wi-Fi coupé ?** Un bouton « Confirmer ma présence (hors ligne) » apparaît : la confirmation part toute seule au retour du réseau.
5. **Consulter** : Planning (cours de la semaine), Études (notes, calendrier, documents, stages), Moi (absences, attestations, scolarité, thème, notifications).
6. **Notifications** : onglet Moi → Notifications → Activer.
7. **Changement de téléphone** : demandez au secrétariat de réinitialiser votre appareil.

> Android : si Chrome ne peut pas demander l'autorisation de localisation, fermez les bulles flottantes d'autres applications (filtre de lumière bleue, verrou d'applications) puis réessayez.

## Secrétariat / administration

| Tâche | Où |
|---|---|
| Structure : filières, promotions, enseignants, cours, salles, emploi du temps | Menu **École** |
| Étudiants (leur compte est créé automatiquement) | École → Élèves |
| Étudiant sans téléphone utilisable | Fiche étudiant → case « Sans téléphone utilisable » |
| Changement de téléphone | Fiche étudiant → « Réinitialiser l'appareil » |
| Mot de passe oublié | Fiche étudiant → « Réinitialiser le mot de passe » (redevient le matricule) |
| Traiter les alertes chaque jour | **À traiter** |
| Attestations de présence | **Attestations** |
| Paiements de scolarité | **Scolarité** |
| Statistiques | **Statistiques** (par étudiant, cours, filière, promotion, enseignant) |
| Réglages (réseau, seuils, notifications, notes) | **Paramètres → École** |
| Vérifier le journal d'audit | École → Configuration → Journal d'audit → « Vérifier l'intégrité » |

## Enseignant

- **Tableau de bord** : séances du jour avec présents et absents en direct ; « Démarrer maintenant » si le cours commence plus tôt.
- **Relayer** : menu « Relayer des présences » pour les étudiants sans téléphone (l'étudiant saisit son matricule et son identifiant, vous validez avec votre empreinte), puis comptage des têtes en fin de séance.
- **Notes** : Études → Évaluations et notes. Créez l'évaluation, « Préparer la liste des étudiants », saisissez les notes, « Publier ».
- **Documents de cours** (PDF ou images) et **échéances** au calendrier.
- Vous ne voyez que vos propres cours, séances et étudiants.

## Superviseur de stage

1. L'administration vous rattache à un ou plusieurs **sites de stage** (fiche du site → Superviseurs) et vous donne le groupe « Superviseur de stage ».
2. Menu **Stages cliniques → Gardes à valider** (ou `/presence/stages/validation`).
3. Pour chaque garde : note facultative de 1 à 5, commentaire, puis « Valider avec mon empreinte ». Hors réseau, la validation est gardée sur le téléphone.
4. Seules les gardes doublement validées comptent dans les heures de l'étudiant.

## Étudiant en stage

Onglet **Études → Stages** : « Confirmer mon entrée » au début de la garde, laissez la page ouverte (le GPS est suivi régulièrement), répondez aux **contrôles d'empreinte** envoyés aux heures de pause, puis « Terminer ma garde ». Les heures validées et en attente sont affichées.

## Direction

Reçoit les signalements graves (comptes signalés, comptages incohérents, relais suspects) et une synthèse chaque lundi ; consulte les statistiques et le journal d'audit.

## Réglages importants (Paramètres → École)

| Réglage | Par défaut |
|---|---|
| Réseau Wi-Fi autorisé | vide (aucune restriction) |
| Alerte d'absences | sous 70 % à partir de 3 séances |
| Scolarité impayée | ne rien faire (ou signaler, ou bloquer) |
| Échecs de connexion avant signalement | 5 |
| Qui relaie les étudiants sans téléphone | enseignant ou délégué |
| Rappel avant le cours | 10 minutes |
| Barème et note de passage | 20 et 10 |
| Suivi GPS en stage | une position toutes les 5 minutes |
