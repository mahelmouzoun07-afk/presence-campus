# Installation

Ce guide installe la **dernière version (v12)**. Pour une version plus ancienne, voir [VERSIONS.md](VERSIONS.md).

## 1. Prérequis

| Élément | Version | Remarque |
|---|---|---|
| Odoo | **18.0 Community** | Les modules ne sont pas prévus pour une autre version d'Odoo. |
| Python | 3.12 | Celui d'Odoo 18. |
| PostgreSQL | 14 ou plus | |
| Système | Linux (Ubuntu 22.04+ conseillé) | Sous Windows, passer par **WSL 2** avec Ubuntu. |
| HTTPS | obligatoire pour les téléphones | L'empreinte (WebAuthn) et l'installation de l'application n'existent que sur une adresse `https://` (ou `localhost`). |

## 2. Installer Odoo 18 (si ce n'est pas fait)

```bash
sudo apt update && sudo apt install -y git python3.12 python3.12-venv postgresql libpq-dev build-essential \
  libxml2-dev libxslt1-dev libldap2-dev libsasl2-dev libjpeg-dev
sudo service postgresql start
sudo -u postgres createuser -s $USER

git clone --depth 1 --branch 18.0 https://github.com/odoo/odoo.git ~/odoo
cd ~/odoo && python3.12 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

## 3. Récupérer Présence Campus

```bash
git clone https://github.com/mahelmouzoun07-afk/presence-campus.git ~/presence-campus
```

## 4. Dépendances Python supplémentaires

À installer **dans l'environnement d'Odoo** (`source ~/odoo/venv/bin/activate`) :

```bash
python -m pip install webauthn qrcode pillow reportlab
python -m pip install pywebpush      # facultatif : notifications push sur les téléphones
```

> Utilisez toujours `python -m pip`, pas `pip` seul : sur certaines machines, `pip` pointe vers un autre Python que celui d'Odoo.

## 5. Installer les modules

Créez une base et installez ce dont vous avez besoin :

```bash
cd ~/odoo && source venv/bin/activate

# Présence seule
./odoo-bin --addons-path=addons,$HOME/presence-campus -d mon_ecole \
  -i school_base,school_attendance_qr --stop-after-init

# Présence + notes + stages cliniques
./odoo-bin --addons-path=addons,$HOME/presence-campus -d mon_ecole \
  -i school_base,school_attendance_qr,school_academic,school_internship --stop-after-init
```

Puis lancez le serveur :

```bash
./odoo-bin --addons-path=addons,$HOME/presence-campus -d mon_ecole --proxy-mode
```

Ouvrez `http://localhost:8069`. Le mot de passe de l'administrateur est celui défini à la création de la base (`admin` / `admin` en test local : **à changer**).

### Mettre à jour après un changement du code

```bash
./odoo-bin --addons-path=addons,$HOME/presence-campus -d mon_ecole \
  -u school_base,school_attendance_qr,school_academic,school_internship --stop-after-init
```

## 6. Premiers réglages (administrateur)

1. **Paramètres → École** : fuseau horaire (par défaut `Africa/Porto-Novo`), réseau Wi-Fi autorisé (adresse IP publique de l'école, ex. `41.138.1.0/24`, ou vide pour ne rien restreindre), logo de l'établissement.
2. **École → Filières, Promotions, Enseignants, Salles** : pour chaque salle, renseigner la **latitude et la longitude** (clic droit sur Google Maps) et le rayon toléré.
3. **École → Cours** puis **Emploi du temps** : les séances du jour sont créées automatiquement.
4. **École → Élèves** : créer ou importer les étudiants. Leur compte est créé tout seul : **identifiant** de l'école, et **matricule** comme premier mot de passe (à changer à la première connexion).
5. Imprimer les affiches QR (facultatif) depuis **École → Salles**.

## 7. Tester sur un téléphone

L'empreinte et l'application installable exigent HTTPS. Pour un essai rapide, un tunnel Cloudflare gratuit suffit :

```bash
# installation de cloudflared : voir https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/
cloudflared tunnel --url http://localhost:8069
```

Ouvrez l'adresse `https://….trycloudflare.com` affichée, sur le téléphone, et connectez-vous avec un compte étudiant. L'adresse change à chaque lancement : pour la production, utilisez un tunnel nommé ou un vrai nom de domaine (voir [`outils/INFRA.md`](../outils/INFRA.md)).

> Android : si Chrome affiche « Ce site ne peut pas demander votre autorisation », fermez les bulles flottantes d'autres applications (filtre de lumière bleue, verrou d'applications, bulles de discussion), puis réessayez.

## 8. Sauvegardes et production

Voir [`outils/INFRA.md`](../outils/INFRA.md) : sauvegardes chiffrées automatiques, restauration, surveillance du serveur, un nom de domaine par école, fonctionnement sans Internet.

Fichiers prêts à copier : [`outils/odoo.conf.exemple`](../outils/odoo.conf.exemple), [`outils/cloudflared-config.yml.exemple`](../outils/cloudflared-config.yml.exemple).

## 9. Lancer les tests

```bash
cd ~/odoo && source venv/bin/activate
python -m pip install cbor2       # uniquement pour les tests hors ligne
createdb presence_test
./odoo-bin --addons-path=addons,$HOME/presence-campus -d presence_test \
  -i school_base,school_attendance_qr,school_academic,school_internship \
  --test-enable --stop-after-init --http-port=8079
```

Résultat attendu : `0 failed, 0 error(s) of 68 tests`. Les tests tournent sur une base à part (`presence_test`) : ne les lancez jamais sur la base réelle d'une école. Le script [`outils/lancer-tests.sh`](../outils/lancer-tests.sh) automatise cela pour l'organisation de dossiers utilisée par l'auteur (WSL).

## Problèmes fréquents

| Symptôme | Cause et solution |
|---|---|
| Le téléphone affiche encore l'ancienne version | Odoo n'a pas relu les fichiers : relancer avec `-u …`, tuer les anciens processus (`pkill -f odoo-bin`), vider le cache du navigateur. |
| `ModuleNotFoundError: webauthn` | Dépendance installée dans le mauvais Python : `python -m pip install webauthn` après `source venv/bin/activate`. |
| L'empreinte n'est jamais proposée | L'adresse n'est pas en HTTPS, ou le téléphone n'a ni code, ni schéma, ni empreinte configuré. |
| Erreur 500 au changement de mot de passe | Double envoi du formulaire sur un réseau lent : corrigé depuis la v12, mettre à jour. |
