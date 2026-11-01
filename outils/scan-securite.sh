#!/usr/bin/env bash
# Scan de sécurité du portail avec OWASP ZAP (gratuit, sans IA, dans Docker).
# À lancer UNIQUEMENT sur une base de TEST locale (jamais une vraie école),
# et uniquement sur notre propre serveur.
#
#   bash outils/scan-securite.sh [url] [mode]
#
#   url   : adresse à tester   (défaut : http://host.docker.internal:8069/presence)
#   mode  : rapide | complet   (défaut : rapide)
#       rapide  = analyse passive, ne touche à rien (zap-baseline) — toujours sûr.
#       complet = analyse active, ENVOIE DE VRAIES ATTAQUES — base de test seulement.
#
# Exemples :
#   bash outils/scan-securite.sh                                   # scan rapide par défaut
#   bash outils/scan-securite.sh http://host.docker.internal:8069/presence complet
#
# Prérequis : Docker démarré, et (sous WSL) l'intégration Docker Desktop activée
# pour la distribution Ubuntu (Docker Desktop → Settings → Resources → WSL integration).
set -euo pipefail

URL="${1:-http://host.docker.internal:8069/presence}"
MODE="${2:-rapide}"

HERE="$(cd "$(dirname "$0")" && pwd)"
RAPPORTS="$HERE/rapports-securite"
mkdir -p "$RAPPORTS"

HORODATAGE="$(date +%Y-%m-%d_%Hh%M)"
NOM="scan_${MODE}_${HORODATAGE}"

case "$MODE" in
  rapide)  SCRIPT="zap-baseline.py" ;;
  complet) SCRIPT="zap-full-scan.py" ;;
  *) echo "Mode inconnu : '$MODE' (attendu : rapide | complet)"; exit 2 ;;
esac

if ! docker info >/dev/null 2>&1; then
  echo "Docker n'est pas accessible. Démarrez Docker Desktop, et sous WSL activez"
  echo "l'intégration pour Ubuntu (Settings → Resources → WSL integration), puis réessayez."
  exit 1
fi

if [ "$MODE" = "complet" ]; then
  echo "!! Mode COMPLET : ZAP va envoyer de vraies attaques sur $URL"
  echo "!! À faire SEULEMENT sur une base de test locale, jamais une vraie école."
  read -r -p "Taper OUI pour continuer : " reponse
  [ "$reponse" = "OUI" ] || { echo "Annulé."; exit 1; }
fi

echo "Cible   : $URL"
echo "Mode    : $MODE ($SCRIPT)"
echo "Rapport : $RAPPORTS/$NOM.html"
echo "(Le premier lancement télécharge l'image Docker de ZAP, cela peut prendre quelques minutes.)"
echo

# ZAP écrit ses rapports dans /zap/wrk ; on y monte notre dossier de rapports.
# -I : ne renvoie pas un code d'erreur juste parce que des alertes sont trouvées
#      (on veut toujours lire le rapport). Les failles sont dans le HTML.
docker run --rm \
  -v "$RAPPORTS:/zap/wrk:rw" \
  ghcr.io/zaproxy/zaproxy "$SCRIPT" \
  -t "$URL" \
  -I \
  -r "$NOM.html" \
  -w "$NOM.md" \
  -J "$NOM.json" || true

echo
echo "Terminé. Ouvrez le rapport dans le navigateur :"
echo "  $RAPPORTS/$NOM.html"
echo "(Depuis Windows : outils\\rapports-securite\\$NOM.html)"
