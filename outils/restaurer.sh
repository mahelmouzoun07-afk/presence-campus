#!/usr/bin/env bash
# Restaure une sauvegarde dans une NOUVELLE base (jamais par-dessus une base existante).
#
#   bash ~/odoo-custom-addons/outils/restaurer.sh ~/sauvegardes/quotidiennes/mon_ecole_2026-10-25_0230.tar.gpg ecole_restauree
#
# À faire une fois par trimestre pour vérifier que les sauvegardes sont vraiment
# utilisables (« une sauvegarde jamais restaurée n'est pas une sauvegarde »).
set -euo pipefail
ARCHIVE="$1"
NOUVELLE="${2:?Indiquez le nom de la nouvelle base, ex. ecole_restauree}"
PASSFILE="${PASSFILE:-$HOME/.config/presence/sauvegarde.pass}"
FILESTORE="${FILESTORE:-$HOME/.local/share/Odoo/filestore}"

if psql -lqt | cut -d'|' -f1 | grep -qw "$NOUVELLE"; then
  echo "La base $NOUVELLE existe déjà : choisissez un autre nom (rien n'a été modifié)."; exit 1
fi
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
gpg --batch --quiet --decrypt --passphrase-file "$PASSFILE" "$ARCHIVE" | tar -C "$TMP" -xf -
createdb "$NOUVELLE"
pg_restore --no-owner -d "$NOUVELLE" "$TMP/base.dump"
mkdir -p "$FILESTORE/$NOUVELLE"
ANCIENNE=$(tar -tzf "$TMP/filestore.tar.gz" | head -1 | cut -d/ -f1)
if [ -n "$ANCIENNE" ]; then
  tar -C "$TMP" -xzf "$TMP/filestore.tar.gz"
  cp -r "$TMP/$ANCIENNE"/. "$FILESTORE/$NOUVELLE"/
fi
echo "Restauré dans la base « $NOUVELLE ». Pour la tester :"
echo "  cd ~/odoo && ./odoo-bin --addons-path=addons,\$HOME/odoo-custom-addons -d $NOUVELLE --http-port=8070"
