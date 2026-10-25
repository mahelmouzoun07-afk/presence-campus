"""Branchement des notifications sur les événements de l'école (liste établie
avec l'école : rappels de cours, absences constatées, emploi du temps modifié,
sécurité du compte, tâches « À traiter », synthèses)."""
from datetime import timedelta
from zoneinfo import ZoneInfo

from odoo import api, fields, models

from .helpers import icp, icp_bool, icp_int
from .task import DIRECTION_TASK_TYPES

FRAUD_TASK_TYPES = ('gps_identical', 'scan_cluster', 'impossible_speed', 'device_shared', 'login_failures',
                    'relay_pattern', 'headcount', 'offline_check')


def _local_hhmm(env, dt):
    try:
        tz = ZoneInfo(icp(env, 'timezone', 'Africa/Porto-Novo'))
    except Exception:
        tz = ZoneInfo('Africa/Porto-Novo')
    return dt.replace(tzinfo=ZoneInfo('UTC')).astimezone(tz).strftime('%Hh%M')


class SchoolSessionNotify(models.Model):
    _inherit = 'school.attendance.session'

    reminder_sent = fields.Boolean(readonly=True, copy=False)
    closing_reminder_sent = fields.Boolean(readonly=True, copy=False)
    end_notified = fields.Boolean(readonly=True, copy=False)

    def _student_users(self, students):
        return students.sudo().mapped('user_id')

    @api.model
    def _cron_session_notifications(self):
        Notif = self.env['school.notification']
        now = fields.Datetime.now()
        lead = icp_int(self.env, 'reminder_minutes', 10)
        # 1. Rappel avant le cours (étudiants et enseignant)
        for session in self.sudo().search([('reminder_sent', '=', False), ('time_start', '>', now),
                                           ('time_start', '<=', now + timedelta(minutes=lead + 5))]):
            hhmm = _local_hhmm(self.env, session.time_start)
            Notif.notify(self._student_users(session.course_id.student_ids),
                         f"Cours à {hhmm} : {session.course_id.name}",
                         f"Salle {session.room_id.name}. Pensez à confirmer votre présence en arrivant.",
                         category='reminder')
            Notif.notify(session.teacher_id.user_id, f"Votre cours commence à {hhmm}",
                         f"{session.course_id.name}, salle {session.room_id.name}.", category='reminder')
            session.reminder_sent = True
        # 2. La fenêtre d'entrée va se fermer et l'étudiant n'a pas confirmé
        for session in self.sudo().search([('closing_reminder_sent', '=', False), ('time_start', '<=', now),
                                           ('time_start', '>=', now - timedelta(hours=3))]):
            closes = session.time_start + timedelta(minutes=session.checkin_window_minutes)
            if now <= closes <= now + timedelta(minutes=5):
                done = session.record_ids.filtered(lambda r: r.state != 'rejected').mapped('student_id')
                pending = session.course_id.student_ids.filtered(lambda s: not s.no_phone) - done
                Notif.notify(self._student_users(pending), "Plus que quelques minutes pour confirmer",
                             f"La confirmation d'entrée pour « {session.course_id.name} » se ferme à "
                             f"{_local_hhmm(self.env, closes)}.", category='reminder')
                session.closing_reminder_sent = True
        # 3. Après la séance : absences constatées + résumé pour l'enseignant
        for session in self.sudo().search([('end_notified', '=', False),
                                           ('time_start', '>=', now - timedelta(days=1)),
                                           ('time_start', '<=', now)]):
            if now <= session.time_end + timedelta(minutes=session.checkout_window_minutes):
                continue
            absents = session.absent_student_ids
            date_label = session.date.strftime('%d/%m')
            Notif.notify(self._student_users(absents), f"Absence constatée : {session.course_id.name}",
                         f"Vous avez été marqué(e) absent(e) au cours du {date_label}. En cas d'erreur, "
                         "rapprochez-vous du secrétariat.", url='/presence/mes-absences', category='result')
            Notif.notify(session.teacher_id.user_id, f"Résumé : {session.course_id.name} ({date_label})",
                         f"{session.present_count} présent(s), {session.absent_count} absent(s) sur "
                         f"{session.enrolled_count} inscrit(s).", url='/odoo', category='summary')
            session.end_notified = True

    def write(self, vals):
        moved = {'room_id', 'time_start'} & set(vals) and not self.env.context.get('no_schedule_notify')
        old = {s.id: (s.room_id.name, s.time_start) for s in self} if moved else {}
        res = super().write(vals)
        if moved:
            for session in self.filtered(lambda s: s.time_start and s.time_start > fields.Datetime.now()):
                if old.get(session.id) != (session.room_id.name, session.time_start):
                    self.env['school.notification'].notify(
                        self._student_users(session.course_id.student_ids),
                        f"Changement : {session.course_id.name}",
                        f"Le {session.date.strftime('%d/%m')} à {_local_hhmm(self.env, session.time_start)}, "
                        f"salle {session.room_id.name}.", url='/presence/emploi-du-temps', category='result')
        return res

    def unlink(self):
        now = fields.Datetime.now()
        for session in self.filtered(lambda s: s.time_start and s.time_start > now):
            self.env['school.notification'].notify(
                self._student_users(session.course_id.student_ids), f"Séance annulée : {session.course_id.name}",
                f"La séance du {session.date.strftime('%d/%m')} à {_local_hhmm(self.env, session.time_start)} "
                "est annulée.", url='/presence/emploi-du-temps', category='result')
        return super().unlink()


class SchoolSlotNotify(models.Model):
    _inherit = 'school.timetable.slot'

    def write(self, vals):
        res = super().write(vals)
        if {'room_id', 'weekday', 'start_time', 'duration_minutes', 'active'} & set(vals):
            for slot in self:
                users = slot.course_id.sudo().student_ids.mapped('user_id')
                status = "supprimé" if not slot.active else "modifié"
                self.env['school.notification'].notify(
                    users, f"Emploi du temps {status} : {slot.course_id.name}",
                    f"Nouveau créneau : {slot.name}, salle {slot.room_id.name}." if slot.active else
                    "Ce créneau hebdomadaire n'a plus lieu.", url='/presence/emploi-du-temps', category='result')
        return res


class SchoolTaskNotify(models.Model):
    _inherit = 'school.attendance.task'

    assigned_user_id = fields.Many2one('res.users', string="Assignée à",
                                       help="La personne prévenue en priorité (ex. l'enseignant pour un contrôle).")

    @api.model_create_multi
    def create(self, vals_list):
        tasks = super().create(vals_list)
        Notif = self.env['school.notification']
        admins = Notif.users_of_group('school_base.group_school_admin')
        direction = Notif.users_of_group('school_base.group_school_direction')
        for task in tasks:
            if task.task_type in FRAUD_TASK_TYPES:
                Notif.notify(admins, f"Sécurité : {task.name}", task.description or '', url='/odoo',
                             category='security')
            else:
                Notif.notify(admins, f"À traiter : {task.name}", task.description or '', url='/odoo',
                             category='admin')
            if task.task_type in DIRECTION_TASK_TYPES and direction:
                Notif.notify(direction - admins, f"Direction : {task.name}", task.description or '',
                             url='/odoo', category='security')
            if task.assigned_user_id:
                task._notify_assignee()
        return tasks

    def write(self, vals):
        res = super().write(vals)
        if vals.get('assigned_user_id'):
            self._notify_assignee()
        return res

    def _notify_assignee(self):
        for task in self.filtered('assigned_user_id'):
            self.env['school.notification'].notify(task.assigned_user_id, f"Tâche pour vous : {task.name}",
                                                   task.description or '', url='/odoo', category='admin')

    @api.model
    def _cron_absence_alerts(self):
        before = set(self.sudo().search([('task_type', '=', 'absence_alert'), ('state', '=', 'open')]).ids)
        created = super()._cron_absence_alerts()
        Notif = self.env['school.notification']
        for task in self.sudo().search([('task_type', '=', 'absence_alert'), ('state', '=', 'open'),
                                        ('id', 'not in', list(before))]):
            student = task.student_id
            Notif.notify(student.user_id, "Attention à vos absences",
                         f"Votre taux de présence est de {student.attendance_rate:.0f} %. Rapprochez-vous de la "
                         "scolarité si vous rencontrez une difficulté.", url='/presence/mes-absences',
                         category='result')
            teachers = student.course_ids.mapped('teacher_id.user_id')
            Notif.notify(teachers, f"Absences répétées : {student.name}",
                         f"Taux de présence : {student.attendance_rate:.0f} %.", url='/odoo', category='result')
        return created


class SchoolStudentNotify(models.Model):
    _inherit = 'school.student'

    def action_reset_device(self):
        res = super().action_reset_device()
        for student in self:
            self.env['school.notification'].notify(
                student.user_id, "Appareil réinitialisé",
                "Le secrétariat a réinitialisé l'appareil lié à votre compte. Si vous n'êtes pas à l'origine de "
                "cette demande, signalez-le immédiatement.", category='security')
        return res

    def write(self, vals):
        res = super().write(vals)
        if vals.get('account_flagged'):
            for student in self:
                self.env['school.notification'].notify(
                    student.user_id, "Votre compte a été signalé",
                    "Plusieurs tentatives de connexion ont échoué sur votre compte. Si ce n'était pas vous, "
                    "prévenez le secrétariat.", category='security')
        return res

    @api.model
    def _cron_fees_reminders(self):
        """Rappels avant la date limite de paiement de la scolarité (14, 7, 3
        et 1 jours avant), puis alerte le lendemain si la politique « bloquer »
        est active."""
        deadline = icp(self.env, 'fees_deadline', '')
        if not deadline:
            return
        deadline = fields.Date.to_date(deadline)
        today = fields.Date.context_today(self)
        days_left = (deadline - today).days
        debtors = self.sudo().search([('fees_balance', '>', 0), ('fees_exempt', '=', False)])
        Notif = self.env['school.notification']
        if days_left in (14, 7, 3, 1):
            for student in debtors:
                Notif.notify(student.user_id, "Rappel : scolarité",
                             f"Il vous reste {student.fees_balance:,.0f} {student.currency_id.symbol or ''} à "
                             f"régler avant le {deadline.strftime('%d/%m/%Y')}.".replace(',', ' '),
                             category='reminder')
        elif days_left == -1 and icp(self.env, 'payment_policy', 'off') == 'block':
            for student in debtors:
                Notif.notify(student.user_id, "Scolarité impayée",
                             "La date limite est passée : tant que votre scolarité n'est pas à jour, vos "
                             "confirmations de présence ne seront pas enregistrées.", category='security')

    @api.model
    def _cron_summaries(self):
        """Synthèse quotidienne (secrétariat, si activée) et hebdomadaire le
        lundi (direction) : présences, absences, impayés, tâches en attente."""
        Notif = self.env['school.notification']
        Record = self.env['school.attendance.record'].sudo()
        Session = self.env['school.attendance.session'].sudo()
        today = fields.Date.context_today(self)
        open_tasks = self.env['school.attendance.task'].sudo().search_count([('state', '=', 'open')])
        if icp_bool(self.env, 'daily_summary'):
            sessions = Session.search([('date', '=', today)])
            present = Record.search_count([('session_date', '=', today), ('state', '!=', 'rejected')])
            expected = sum(sessions.mapped('enrolled_count'))
            Notif.notify(Notif.users_of_group('school_base.group_school_admin'), "Synthèse du jour",
                         f"{len(sessions)} séance(s), {present} présence(s) sur {expected} attendue(s). "
                         f"{open_tasks} tâche(s) à traiter.", url='/odoo', category='summary')
        if today.weekday() == 0:
            week_ago = today - timedelta(days=7)
            sessions = Session.search([('date', '>=', week_ago), ('date', '<', today)])
            expected = sum(sessions.mapped('enrolled_count'))
            present = Record.search_count([('session_date', '>=', week_ago), ('session_date', '<', today),
                                           ('state', '!=', 'rejected')])
            rate = present / expected * 100 if expected else 100
            unpaid = self.sudo().search_count([('payment_status', 'in', ('unpaid', 'partial'))])
            Notif.notify(Notif.users_of_group('school_base.group_school_direction'), "Synthèse de la semaine",
                         f"Taux de présence : {rate:.0f} %. Étudiants avec impayés : {unpaid}. "
                         f"Tâches à traiter : {open_tasks}.", url='/odoo', category='summary')
