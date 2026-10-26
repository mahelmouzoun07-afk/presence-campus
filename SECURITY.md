# Politique de sécurité

Le projet traite des données sensibles (présence, position GPS, notes d'étudiants). Merci de signaler toute faille **en privé**.

## Signaler une vulnérabilité

Utilisez l'onglet **Security → Report a vulnerability** du dépôt GitHub (signalement privé). Décrivez le problème, les étapes pour le reproduire et la version concernée. Ne publiez pas la faille dans une issue publique avant correction.

## Versions concernées

Seule la dernière version (`main`, tag `v12`) reçoit des correctifs. Les tags v9 à v11 sont conservés pour mémoire.

## Ce que le projet fait déjà

Mot de passe personnel obligatoire, verrouillage après 5 échecs, WebAuthn (aucune donnée biométrique côté serveur), appareil lié au compte, journal d'audit chaîné SHA-256, détections de fraude, règles d'accès par groupe.

## Limites connues

- Une application de fausse position GPS peut tromper le contrôle de lieu ; le système le rend visible (détections) sans le rendre impossible.
- Le projet n'a **pas encore été audité** par un tiers.
- Avant un usage réel, faites valider le traitement des données personnelles (au Bénin : loi sur les données personnelles, APDP).
