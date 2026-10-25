#!/usr/bin/env bash
# Sauvegarde chiffrée d'une école : base PostgreSQL + fichiers joints (filestore).
#
#   bash ~/odoo-custom-addons/outils/sauvegarde.sh [base1 base2 ...]   (par défaut : mon_ecole)
#
# - Chiffrement AES-256 (gpg) AVANT tout envoi : la phrase secrète est dans
#   ~/.config/presence/sauvegarde.pass (créée par installer-sauvegarde.sh).
#   SANS ELLE, AUCUNE RESTAURATION N'EST POSSIBLE : gardez-en une copie hors du serveur.
# - Trois copies : ~/sauvegardes (sur place), COPIE_LOCALE (2e disque), et
#   RCLONE_DISTANT (cloud, optionnel : ex. "b2:presence-sauvegardes").
# - Rétention : 7 quotidiennes, 4 hebdomadaires (dimanche), 12 mensuelles (le 1er).
# - En fin de réussite, écrit ~/sauvegardes/derniere_reussite : Odoo surveille
#   ce fichier et alerte si aucune sauvegarde n'a réussi depuis plus de 26 h.
set -euo pipefail

BASES=("${@:-mon_ecole}")
RACINE="${RACINE:-$HOME/sauvegardes}"
COPIE_LOCALE="${COPIE_LOCALE:-/mnt/d/Sauvegardes-Presence}"
RCLONE_DISTANT="${RCLONE_DISTANT:-}"
PASSFILE="${PASSFILE:-$HOME/.config/presence/sauvegarde.pass}"
FILESTORE="${FILESTORE:-$HOME/.local/share/Odoo/filestore}"
JOURNAL="$RACINE/sauvegarde.log"

mkdir -p "$RACINE"/{quotidiennes,hebdomadaires,mensuelles}
log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" | tee -a "$JOURNAL"; }

if [ ! -s "$PASSFILE" ]; then
  log "ERREUR : phrase secrète absente ($PASSFILE). Lancez d'abord installer-sauvegarde.sh."
  exit 1
fi

STAMP=$(date +%Y-%m-%d_%H%M)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

for BASE in "${BASES[@]}"; do
  log "Sauvegarde de $BASE…"
  pg_dump -Fc "$BASE" -f "$TMP/base.dump"
  if [ -d "$FILESTORE/$BASE" ]; then
    tar -C "$FILESTORE" -czf "$TMP/filestore.tar.gz" "$BASE"
  else
    tar -czf "$TMP/filestore.tar.gz" --files-from /dev/null
  fi
  ARCHIVE="$RACINE/quotidiennes/${BASE}_${STAMP}.tar.gpg"
  tar -C "$TMP" -cf - base.dump filestore.tar.gz \
    | gpg --batch --yes --symmetric --cipher-algo AES256 --passphrase-file "$PASSFILE" -o "$ARCHIVE"
  # Vérification immédiate : l'archive se déchiffre et contient bien la base
  gpg --batch --quiet --decrypt --passphrase-file "$PASSFILE" "$ARCHIVE" | tar -tf - > "$TMP/contenu"
  grep -q base.dump "$TMP/contenu"
  log "  OK : $(basename "$ARCHIVE") ($(du -h "$ARCHIVE" | cut -f1))"

  if [ "$(date +%u)" = "7" ]; then cp "$ARCHIVE" "$RACINE/hebdomadaires/"; fi
  if [ "$(date +%d)" = "01" ]; then cp "$ARCHIVE" "$RACINE/mensuelles/"; fi
  rm -f "$TMP/base.dump" "$TMP/filestore.tar.gz" "$TMP/contenu"
done

# Rétention : on garde les N plus récentes de chaque base dans chaque dossier
garder() {  # dossier nombre
  for BASE in "${BASES[@]}"; do
    { ls -1t "$1"/"${BASE}"_*.tar.gpg 2>/dev/null || true; } | tail -n +"$(($2 + 1))" | xargs -r rm -f
  done
}
garder "$RACINE/quotidiennes" 7
garder "$RACINE/hebdomadaires" 4
garder "$RACINE/mensuelles" 12

# 2e copie (autre disque) et copie distante, chiffrées elles aussi
if [ -n "$COPIE_LOCALE" ] && mkdir -p "$COPIE_LOCALE" 2>/dev/null; then
  cp -r "$RACINE"/quotidiennes "$RACINE"/hebdomadaires "$RACINE"/mensuelles "$COPIE_LOCALE"/ \
    && log "Copie sur $COPIE_LOCALE : OK"
  for d in quotidiennes hebdomadaires mensuelles; do
    for f in "$COPIE_LOCALE/$d"/*.tar.gpg; do
      if [ -e "$f" ] && [ ! -e "$RACINE/$d/$(basename "$f")" ]; then rm -f "$f"; fi
    done
  done
fi
if [ -n "$RCLONE_DISTANT" ] && command -v rclone >/dev/null; then
  rclone sync "$RACINE" "$RCLONE_DISTANT" --exclude sauvegarde.log && log "Copie distante ($RCLONE_DISTANT) : OK"
fi

date -u +%Y-%m-%dT%H:%M:%SZ > "$RACINE/derniere_reussite"
log "Sauvegarde terminée."
