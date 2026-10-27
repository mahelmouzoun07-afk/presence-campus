#!/usr/bin/env bash
# Prépare une base de DÉMONSTRATION neuve (demo_clients) avec Awa, Koffi, une salle,
# un cours en cours et un stage. Détruit et recrée uniquement la base « demo_clients ».
#
#   bash outils/demo.sh <latitude> <longitude>     # position de la salle de démo
#   ex : bash outils/demo.sh 6.3703 2.3912
#
# Puis lancer le serveur : bash outils/demo.sh lancer   (port 8069, derrière le tunnel)
set -euo pipefail
ODOO="${ODOO_DIR:-$HOME/odoo}"
HERE="$(cd "$(dirname "$0")" && pwd)"
ADDONS="addons,$(dirname "$HERE")"
DB=demo_clients
cd "$ODOO"
PY="venv/bin/python"

if [ "${1:-}" = "lancer" ]; then
  exec "$PY" odoo-bin --addons-path="$ADDONS" -d "$DB" --db-filter="^$DB\$" --proxy-mode --no-database-list --http-port=8069
fi

LAT="${1:?latitude manquante (ex : 6.3703)}"; LNG="${2:?longitude manquante (ex : 2.3912)}"
dropdb --if-exists "$DB" && createdb "$DB"
"$PY" odoo-bin --addons-path="$ADDONS" -d "$DB" -i school_base,school_attendance_qr,school_academic,school_internship \
  --stop-after-init --log-level=warn
DEMO_LAT="$LAT" DEMO_LNG="$LNG" "$PY" odoo-bin shell --addons-path="$ADDONS" -d "$DB" --log-level=warn \
  < "$HERE/donnees_demo.py"
cat <<'E'

Comptes de démonstration (mots de passe de démo, base locale uniquement) :
  Étudiante honnête   demo.awa      / Demo-Awa-2026
  Étudiant « tricheur » demo.koffi  / Demo-Koffi-2026
  Étudiante sans téléphone demo.fatou / 90000003
  Enseignante         prof.demo@demo.bj    / Demo-Prof-2026
  Superviseur         gbaguidi@demo.bj     / Demo-Superviseur-2026
  Administrateur      admin / admin (à utiliser en local seulement)
Lancer : bash outils/demo.sh lancer
E
