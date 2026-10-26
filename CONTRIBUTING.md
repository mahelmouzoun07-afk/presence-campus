# Contribuer à Présence Campus

Merci de l'intérêt ! Le projet est en français ; les messages, commentaires et documents le sont aussi.

## Signaler un problème

Ouvrez une *issue* en indiquant : la version (tag), ce que vous avez fait, ce que vous attendiez, ce qui s'est passé, et le type de téléphone/navigateur si c'est côté étudiant. **Ne collez jamais** de mots de passe, matricules réels ou données d'étudiants. Pour une faille de sécurité, suivez plutôt [SECURITY.md](SECURITY.md).

## Proposer une modification

1. Forkez le dépôt et créez une branche (`correctif/…` ou `fonction/…`).
2. Installez l'environnement : voir [docs/INSTALLATION.md](docs/INSTALLATION.md).
3. Respectez les conventions du projet :
   - ORM Odoo uniquement, pas de SQL brut (seule exception : le verrou du journal d'audit) ;
   - filtrage par groupe avec des `ir.rule`, jamais de `if user.role == …` ;
   - heures affichées dans le portail via `fmt_local` / `local_time` (Odoo stocke en UTC) ;
   - pas de `default_order` sur un champ calculé non stocké (plante Odoo 18) ;
   - textes visibles en français.
4. Ajoutez ou adaptez des tests, puis lancez-les sur une base **à part** :
   ```bash
   ./odoo-bin --addons-path=addons,$HOME/presence-campus -d presence_test \
     -i school_base,school_attendance_qr,school_academic,school_internship \
     --test-enable --stop-after-init
   ```
   Les tests ne doivent pas dépendre de données déjà présentes (utilisez des noms uniques).
5. Ouvrez une *pull request* qui explique le problème résolu.

## Données personnelles

N'ajoutez jamais de vraies données d'étudiants (noms, matricules, e-mails, positions) dans le code, les tests ou les captures d'écran.
