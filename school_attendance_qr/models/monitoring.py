"""Surveillance du serveur, en deux niveaux :
1. « Est-il vivant ? » : un service externe (UptimeRobot, gratuit) appelle
   /presence/sante toutes les 5 minutes et prévient si rien ne répond.
2. « Va-t-il bien ? » : cette tâche planifiée vérifie toutes les heures l'espace
   disque, la fraîcheur de la dernière sauvegarde et les erreurs du journal
   Odoo, et crée une alerte « À traiter » + notification aux administrateurs."""
import os
import shutil
from datetime import datetime, timedelta, timezone

from odoo import api, fields, models
from odoo.tools import config

from .helpers import icp, icp_int


class SchoolServerHealth(models.AbstractModel):
    _name = 'school.server.health'
    _description = 'Surveillance du serveur'

    @api.model
    def check(self):
        """Renvoie la liste des problèmes détectés (texte), sans rien créer."""
        problems = []
        threshold = icp_int(self.env, 'monitoring_disk_min_free_pct', 15)
        for label, path in (("données Odoo", config['data_dir']), ("système", '/')):
            try:
                usage = shutil.disk_usage(path)
            except OSError:
                continue
            free_pct = usage.free / usage.total * 100
            if free_pct < threshold:
                problems.append(f"Disque {label} presque plein : {free_pct:.0f} % libre "
                                f"({usage.free // 1024 ** 3} Go).")
        status_file = icp(self.env, 'backup_status_file', os.path.expanduser('~/sauvegardes/derniere_reussite'))
        max_age = icp_int(self.env, 'backup_max_age_hours', 26)
        if status_file and icp(self.env, 'monitoring_backups', 'True') == 'True':
            try:
                with open(status_file, encoding='utf-8') as f:
                    last = datetime.strptime(f.read().strip(), '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
                age = datetime.now(timezone.utc) - last
                if age > timedelta(hours=max_age):
                    problems.append(f"Aucune sauvegarde réussie depuis {int(age.total_seconds() // 3600)} h.")
            except (OSError, ValueError):
                problems.append("Aucune sauvegarde réussie n'a jamais été enregistrée sur ce serveur "
                                "(voir outils/installer-sauvegarde.sh).")
        logfile = config.get('logfile')
        if logfile and os.path.exists(logfile):
            errors = self._recent_log_errors(logfile)
            if errors >= icp_int(self.env, 'monitoring_max_errors', 20):
                problems.append(f"{errors} erreurs dans le journal Odoo au cours de la dernière heure.")
        return problems

    @staticmethod
    def _recent_log_errors(logfile):
        since = (datetime.now() - timedelta(hours=1)).strftime('%Y-%m-%d %H:%M')
        count = 0
        try:
            with open(logfile, 'rb') as f:
                f.seek(max(os.path.getsize(logfile) - 2_000_000, 0))  # seulement la fin du fichier
                for raw in f:
                    line = raw.decode('utf-8', 'replace')
                    if line[:16] >= since and (' ERROR ' in line or ' CRITICAL ' in line):
                        count += 1
        except OSError:
            return 0
        return count

    @api.model
    def _cron_health(self):
        problems = self.check()
        Task = self.env['school.attendance.task'].sudo()
        for problem in problems:
            title = f"Serveur : {problem.split(':')[0]}"
            if not Task.search_count([('task_type', '=', 'server'), ('name', '=', title), ('state', '=', 'open')]):
                Task.create({'task_type': 'server', 'name': title, 'description': problem})
        return problems
