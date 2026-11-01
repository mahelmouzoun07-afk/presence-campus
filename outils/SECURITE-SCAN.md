# Scan de sécurité — OWASP ZAP (gratuit)

Audit automatique du portail, **sans aucun coût** : pas de clé d'IA à payer.
ZAP est l'outil de référence de la fondation OWASP. Il joue l'attaquant sur
l'application en marche et produit un rapport des failles.

> Alternative payante : Strix (agents IA, ~10 $/analyse). Plus malin sur la
> logique propre au projet, mais pas gratuit. Voir plus bas « Quand ZAP ne
> suffit pas ».

## Règles d'or

- **Jamais sur une vraie école.** Uniquement une base de test locale.
- **Jamais sur le lien Tailscale public.** Uniquement en local.
- Sur la base de test, couper les e-mails et les notifications push.
- Ne scanner que **notre propre serveur**. Scanner le serveur d'autrui sans
  autorisation écrite est illégal.

## Une seule fois : préparer Docker

1. Démarrer **Docker Desktop**.
2. Docker Desktop → Settings → Resources → **WSL integration** → activer **Ubuntu**.
3. Vérifier dans Ubuntu : `docker --version` doit répondre.

## Lancer un scan

Dans Ubuntu (WSL), avec Odoo démarré sur le port 8069 :

```bash
# Scan rapide (passif, ne touche à rien) — à faire en premier, toujours sûr
bash outils/scan-securite.sh

# Scan complet (actif, envoie de vraies attaques) — base de test seulement
bash outils/scan-securite.sh http://host.docker.internal:8069/presence complet
```

Le premier lancement télécharge l'image de ZAP (quelques minutes).
Les rapports arrivent dans `outils/rapports-securite/` (exclu de Git) :
un `.html` à ouvrir dans le navigateur, plus `.md` et `.json`.

- `host.docker.internal` = la machine hôte, vue depuis le conteneur Docker.
  C'est ainsi que ZAP joint Odoo qui tourne dans WSL.

## Les deux modes

| Mode | Ce qu'il fait | Risque | Quand |
|---|---|---|---|
| `rapide` | observe les pages, repère les défauts visibles (en-têtes manquants, cookies, formulaires) | aucun | à chaque fois, pour commencer |
| `complet` | envoie de vraies charges d'attaque (XSS, injections…) | peut créer/modifier des données | base de test seulement, avant une version |

## Limite importante : la connexion

Le portail est derrière une connexion. Sans identifiants, ZAP ne voit que la
page de login. Pour un vrai scan, il faut lui donner une session authentifiée
(contexte ZAP + un compte de test). C'est l'étape suivante à configurer ;
le scan `rapide` par défaut donne déjà un premier aperçu utile sur les pages
publiques et les en-têtes de sécurité.

## Après chaque faille trouvée

Toujours la même méthode (comme pour le reste du projet) :

1. vérifier qu'elle est réelle (ZAP donne des « peut-être ») ;
2. écrire un test automatique qui la reproduit (il rejoint les 78 existants) ;
3. corriger ;
4. relancer le scan pour confirmer.

## Quand ZAP ne suffit pas

ZAP suit des règles génériques. Il ne « raisonne » pas sur notre logique métier.
Pour ces questions-là, l'IA de Strix est meilleure :

- Awa peut-elle voir ou modifier les présences / notes de Koffi (IDOR) ?
- Peut-on rejouer un QR code ou réutiliser un défi hors ligne ?
- Peut-on contourner WebAuthn, la présence relayée, la restriction Wi-Fi ?
- Peut-on contourner les `ir.rule` via l'API Odoo (`/web/dataset/call_kw`) ?

Stratégie : **ZAP d'abord (gratuit)** pour le technique, **Strix de temps en
temps (budget plafonné)** pour ces attaques « intelligentes ».

## Autres outils gratuits, complémentaires

- **Nuclei** — vérifie une grande liste de failles connues, très rapide.
- **Trivy** — analyse notre code et nos dépendances Python (bibliothèques
  vulnérables), pas l'application en marche.
