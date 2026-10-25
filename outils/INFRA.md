# Infrastructure : sauvegardes, surveillance, tunnel, hébergement local

Tout ce qui se fait **en dehors d'Odoo** pour qu'une école tourne sans souci.
Les commandes `bash` se tapent dans le terminal Ubuntu (WSL sur ton PC, ou le serveur de l'école).

---

## 1. Sauvegardes chiffrées

**Ce qui est sauvegardé** : la base PostgreSQL ET les fichiers joints (logos, PDF, documents de cours).
**Chiffrement** : AES-256 avant tout envoi. **Rétention** : 7 jours, 4 semaines, 12 mois.
**Trois copies** : `~/sauvegardes` (sur place), `D:\Sauvegardes-Presence` (2ᵉ disque), cloud (optionnel).

### Mise en place (une fois)

```bash
bash ~/odoo-custom-addons/outils/installer-sauvegarde.sh mon_ecole
```

Ça crée la **phrase secrète** (`~/.config/presence/sauvegarde.pass`), programme la sauvegarde
chaque nuit à 2 h 30 et en fait une tout de suite.

> ⚠️ **Copie la phrase secrète hors du serveur** (gestionnaire de mots de passe, papier au coffre).
> Sans elle, aucune sauvegarde ne peut être restaurée. Pour l'afficher :
> `cat ~/.config/presence/sauvegarde.pass`

**Sur ton PC Windows (WSL)**, le service `cron` de Linux ne démarre pas tout seul. Programme plutôt
la sauvegarde dans Windows (une fois, dans PowerShell) :

```powershell
powershell -ExecutionPolicy Bypass -File "$HOME\Desktop\Presence-Ecole\outils\planifier-sauvegarde-windows.ps1"
```

**Sur le serveur de l'école (Ubuntu)** : `sudo systemctl enable --now cron` suffit.

### Copie dans le cloud (optionnel, recommandé)

Avec [rclone](https://rclone.org) et un stockage bon marché (Backblaze B2 : ~0,006 $/Go/mois) :
`rclone config` (créer un « remote » nommé `b2`), puis ajouter devant la commande programmée :
`RCLONE_DISTANT=b2:presence-sauvegardes`. Les fichiers envoyés sont déjà chiffrés.

### Tester une restauration (une fois par trimestre)

```bash
bash ~/odoo-custom-addons/outils/restaurer.sh ~/sauvegardes/quotidiennes/<fichier>.tar.gpg ecole_test
```

Restaure dans une **nouvelle** base (jamais par-dessus la vraie). Ouvre-la pour vérifier, puis supprime-la.

---

## 2. Surveillance du serveur

**Niveau 1 : « est-il vivant ? »** (externe, gratuit)
1. Crée un compte sur [uptimerobot.com](https://uptimerobot.com) (offre gratuite : 50 sondes, toutes les 5 min).
2. Nouvelle sonde **HTTP(s)** → adresse : `https://<école>.presence.bj/presence/sante`.
3. Alerte par e-mail (et l'application mobile UptimeRobot pour les notifications).

`/presence/sante` répond `ok` si Odoo et la base répondent, sans rien divulguer d'autre.

**Niveau 2 : « va-t-il bien ? »** (intégré à Odoo, toutes les heures)
Alerte dans « À traiter » + notification aux administrateurs si :
- le disque passe sous 15 % d'espace libre (réglable) ;
- aucune sauvegarde n'a réussi depuis 26 h ;
- plus de 20 erreurs dans le journal Odoo en une heure (nécessite `logfile` dans `odoo.conf`).

Réglages : **Paramètres → École → Surveillance du serveur**.

---

## 3. Tunnel nommé : une adresse fixe par école

Le tunnel rapide (`trycloudflare.com`) change d'adresse à chaque redémarrage : parfait pour tester,
impossible en production (les clés d'empreinte WebAuthn sont liées à l'adresse exacte).

**Prérequis** : un nom de domaine (ex. `presence.bj` chez un registraire béninois, ou un `.com`
à ~10 $/an) et un compte Cloudflare **gratuit** qui gère ce domaine.

```bash
cloudflared tunnel login                       # ouvre le navigateur, choisir le domaine
cloudflared tunnel create presence             # crée le tunnel et son fichier d'identifiants
cloudflared tunnel route dns presence iut.presence.bj
cp ~/odoo-custom-addons/outils/cloudflared-config.yml.exemple ~/.cloudflared/config.yml
nano ~/.cloudflared/config.yml                 # remplacer l'ID du tunnel et les sous-domaines
cloudflared tunnel run presence                # test ; ensuite : sudo cloudflared service install
```

**Une base par école** : copier `outils/odoo.conf.exemple` en `~/odoo/odoo.conf`.
Avec `dbfilter = ^%d$`, l'adresse `iut.presence.bj` ouvre la base **`iut`** : chaque école a ses
données séparées. ⚠️ Un nom de base ne peut pas contenir `_` s'il doit servir de sous-domaine :
renommer `mon_ecole` (ex. en `demo`) avant de passer en production.

---

## 4. Hébergement local qui continue sans Internet (mode hybride)

Pour une école qui veut que tout marche **même quand Internet est coupé** (le serveur est dans l'école) :

**Idée clé : garder le MÊME nom de domaine en ligne et en local.** Les clés d'empreinte (WebAuthn)
sont liées au nom de domaine : si `iut.presence.bj` désigne le serveur de l'école des deux côtés,
les étudiants n'ont rien à refaire.

1. **Serveur** dans l'école (mini-PC), adresse IP fixe sur le réseau (ex. `192.168.1.10`), branché
   sur onduleur.
2. **DNS local** : dans le routeur Wi-Fi (ou avec `dnsmasq` sur le serveur), faire pointer
   `iut.presence.bj` vers `192.168.1.10`. Sur le réseau de l'école, les téléphones vont alors
   directement au serveur, sans passer par Internet.
3. **Certificat HTTPS valide en local** : obligatoire pour WebAuthn et l'application. Avec
   [Caddy](https://caddyserver.com) et le module DNS Cloudflare, le certificat Let's Encrypt est
   obtenu par **défi DNS** : aucune ouverture de port, et il reste valide 90 jours même sans
   Internet (renouvellement automatique dès qu'Internet revient). Aucune installation de
   certificat sur les téléphones.
   ```
   iut.presence.bj {
       tls { dns cloudflare {env.CF_API_TOKEN} }
       reverse_proxy localhost:8069
   }
   ```
4. **Depuis l'extérieur** (parents, administration à distance) : le tunnel nommé (section 3)
   continue de fonctionner quand Internet est là.
5. **Wi-Fi « présence uniquement »** possible : un routeur dont le câble Internet est débranché
   suffit, aucun abonnement. Le contrôle « Wi-Fi de l'école » (Paramètres → École → Réseaux
   autorisés) se règle alors sur la plage locale, ex. `192.168.1.0/24`.

Coût indicatif au Bénin : mini-PC reconditionné 120 000–200 000 FCFA, onduleur 40 000–70 000 FCFA,
routeur TP-Link 15 000–35 000 FCFA (couverture : un point d'accès par bâtiment).

---

## 5. Notifications push

Fonctionnent sans compte Firebase (norme Web Push). Le paquet Python `pywebpush` doit être installé
dans l'environnement d'Odoo (déjà fait sur ton PC) :

```bash
cd ~/odoo && venv/bin/python -m pip install pywebpush
```

Sur iPhone, les notifications n'arrivent que si l'étudiant a **installé l'application sur l'écran
d'accueil** (iOS 16.4 ou plus récent) — le guide est dans l'application (`/presence/installer`).
