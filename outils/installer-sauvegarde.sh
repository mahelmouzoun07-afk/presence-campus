#!/usr/bin/env bash
# Prépare les sauvegardes automatiques (à lancer UNE fois sur le serveur de l'école).
#   bash ~/odoo-custom-addons/outils/installer-sauvegarde.sh [base]
set -euo pipefail
BASE="${1:-mon_ecole}"
PASSFILE="$HOME/.config/presence/sauvegarde.pass"
SCRIPT="$HOME/odoo-custom-addons/outils/sauvegarde.sh"

mkdir -p "$(dirname "$PASSFILE")"
if [ ! -s "$PASSFILE" ]; then
  umask 077
  head -c 48 /dev/urandom | base64 > "$PASSFILE"
  echo "Phrase secrète créée dans $PASSFILE."
  echo ">>> COPIEZ-LA MAINTENANT dans un endroit sûr HORS du serveur (gestionnaire de mots de passe,"
  echo ">>> papier dans un coffre) : sans elle, les sauvegardes ne pourront jamais être restaurées."
fi
chmod 600 "$PASSFILE"

LIGNE="30 2 * * * bash $SCRIPT $BASE >/dev/null 2>&1"
if crontab -l 2>/dev/null | grep -qF "$SCRIPT"; then
  echo "La sauvegarde quotidienne est déjà programmée."
else
  (crontab -l 2>/dev/null; echo "$LIGNE") | crontab -
  echo "Sauvegarde programmée chaque nuit à 2h30."
fi
if ! (pgrep -x cron >/dev/null || systemctl is-active --quiet cron 2>/dev/null); then
  echo "ATTENTION : le service cron n'est pas démarré. Sur un serveur Ubuntu : sudo systemctl enable --now cron"
  echo "Sous WSL (PC Windows) : sudo service cron start (à refaire à chaque redémarrage),"
  echo "ou programmez plutôt la sauvegarde dans le Planificateur de tâches Windows (voir outils/INFRA.md)."
fi
echo "Test immédiat :"
bash "$SCRIPT" "$BASE"
