#!/usr/bin/env bash
# Lance les tests automatiques des modules sur une base de TEST séparée
# (presence_test), jamais sur la base réelle de l'école.
# Usage : bash ~/odoo-custom-addons/outils/lancer-tests.sh [modules]
set -euo pipefail
MODULES="${1:-school_base,school_attendance_qr,school_academic}"
DB=presence_test
cd ~/odoo
if ! psql -lqt | cut -d'|' -f1 | grep -qw "$DB"; then createdb "$DB"; fi
INSTALLED=$(psql -d "$DB" -Atc "select count(*) from ir_module_module where name='school_base' and state='installed'" 2>/dev/null || echo 0)
if [ "$INSTALLED" = "1" ]; then MODE=-u; else MODE=-i; fi
rm -f /tmp/presence_tests.log
TAGS=$(echo "$MODULES" | sed 's/\([^,]*\)/\/\1/g')
venv/bin/python odoo-bin --addons-path=addons,$HOME/odoo-custom-addons -d "$DB" $MODE "$MODULES" \
  --test-enable --test-tags "$TAGS" --stop-after-init --http-port=8079 --log-level=test \
  --logfile=/tmp/presence_tests.log || true
grep -E "ERROR|FAIL|Traceback|tests? .*(failed|error)|Ran [0-9]+ test|0 failed" /tmp/presence_tests.log | tail -40
echo "--- Journal complet : /tmp/presence_tests.log"
