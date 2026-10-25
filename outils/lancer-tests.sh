#!/usr/bin/env bash
# Lance les tests automatiques des modules sur une base de TEST séparée
# (presence_test), jamais sur la base réelle de l'école.
# Usage : bash ~/odoo-custom-addons/outils/lancer-tests.sh [modules]
set -euo pipefail
MODULES="${1:-school_base,school_attendance_qr,school_academic}"
DB=presence_test
cd ~/odoo
if ! psql -lqt | cut -d'|' -f1 | grep -qw "$DB"; then createdb "$DB"; fi
# Modules déjà installés : mise à jour (-u) ; les autres : installation (-i)
INSTALL=(); UPDATE=()
for m in ${MODULES//,/ }; do
  state=$(psql -d "$DB" -Atc "select state from ir_module_module where name='$m'" 2>/dev/null || true)
  if [ "$state" = "installed" ]; then UPDATE+=("$m"); else INSTALL+=("$m"); fi
done
ARGS=()
[ ${#INSTALL[@]} -gt 0 ] && ARGS+=(-i "$(IFS=,; echo "${INSTALL[*]}")")
[ ${#UPDATE[@]} -gt 0 ] && ARGS+=(-u "$(IFS=,; echo "${UPDATE[*]}")")
rm -f /tmp/presence_tests.log
TAGS=$(echo "$MODULES" | sed 's/\([^,]*\)/\/\1/g')
venv/bin/python odoo-bin --addons-path=addons,$HOME/odoo-custom-addons -d "$DB" "${ARGS[@]}" \
  --test-enable --test-tags "$TAGS" --stop-after-init --http-port=8079 --log-level=test \
  --logfile=/tmp/presence_tests.log || true
grep -E "ERROR|FAIL|Traceback|tests when" /tmp/presence_tests.log | grep -v "Login failed" | tail -40
echo "--- Journal complet : /tmp/presence_tests.log"
