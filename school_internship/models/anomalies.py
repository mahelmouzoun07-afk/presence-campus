"""Anomalies des gardes, envoyées dans la boîte « À traiter » existante, et
rappel de fin de garde (même mécanisme que _cron_absence_alerts)."""
from datetime import timedelta

from odoo import api, fields, models

from odoo.addons.school_attendance_qr.models.helpers import icp_int, local_time


class SchoolAttendanceTaskInternship(models.Model):
    _inherit = 'school.attendance.task'

    task_type = fields.Selection(selection_add=[
        ('internship_site', 'Stage : garde confirmée sur un autre site'),
        ('internship_duration', 'Stage : durée de garde invraisemblable'),
        ('internship_open', 'Stage : sortie de garde non confirmée'),
        ('internship_unvalidated', 'Stage : validation du superviseur manquante'),
    ], ondelete={'internship_site': 'cascade', 'internship_duration': 'cascade',
                 'internship_open': 'cascade', 'internship_unvalidated': 'cascade'})
    internship_attendance_id = fields.Many2one('school.internship.attendance', string="Garde",
                                               ondelete='cascade')

    @api.model
    def create_internship(self, task_type, shift, name, description):
        """Une seule tâche ouverte par garde et par type."""
        existing = self.sudo().search([('task_type', '=', task_type), ('internship_attendance_id', '=', shift.id),
                                       ('state', '=', 'open')], limit=1)
        if existing:
            return existing
        return self.sudo().create({'task_type': task_type, 'internship_attendance_id': shift.id,
                                   'student_id': shift.student_id.id, 'name': name, 'description': description})


class SchoolAuditLogInternship(models.Model):
    _inherit = 'school.audit.log'

    event_type = fields.Selection(selection_add=[('internship', 'Stage clinique')],
                                  ondelete={'internship': 'cascade'})


class SchoolInternshipAttendanceAnomalies(models.Model):
    _inherit = 'school.internship.attendance'

    def _after_scan(self, phase):
        res = super()._after_scan(phase)
        Task = self.env['school.attendance.task']
        for shift in self:
            student = shift.student_id
            label = 'Entrée' if phase == 'checkin' else 'Sortie'
            state = shift.checkin_state if phase == 'checkin' else shift.checkout_state
            if state == 'flagged' and 'au lieu de' in (shift.flag_reason or ''):
                Task.create_internship('internship_site', shift, f"Garde sur un autre site : {student.name}",
                                       shift.flag_reason)
            if phase == 'checkout' and state != 'rejected':
                low = icp_int(self.env, 'internship_min_hours', 1)
                high = icp_int(self.env, 'internship_max_hours', 30)
                if not low <= shift.duration_hours <= high:
                    reason = f"Garde de {shift.duration_hours:g} h (attendu entre {low} et {high} h)"
                    shift.write({'flag_reason': self.env['school.attendance.record']._join_reasons(
                        shift.flag_reason, reason)})
                    Task.create_internship('internship_duration', shift,
                                           f"Durée de garde invraisemblable : {student.name}", reason)
                # Les superviseurs du site sont prévenus qu'une garde attend leur validation
                self.env['school.notification'].notify(
                    shift.site_id.supervisor_ids.mapped('user_id'), f"Garde à valider : {student.name}",
                    f"{shift.site_id.name}, {shift.duration_hours:g} h.", url='/presence/stages/validation',
                    category='admin')
            self.env['school.audit.log'].log(
                'internship', f"{label} de garde « {shift.site_id.name} » : "
                              f"{dict(self._fields['checkin_state'].selection).get(state, '')}"
                              f"{' (hors ligne)' if shift.offline else ''}"
                              f"{' — ' + shift.flag_reason if shift.flag_reason else ''}",
                student=student, record=shift)
        return res

    @api.model
    def _cron_internship_checks(self):
        """Toutes les heures :
        - sortie oubliée : garde ouverte depuis plus de 14 h (réglable) → rappel
          à l'étudiant + tâche (oubli fréquent après une garde de 24 h) ;
        - validation manquante : garde confirmée par l'étudiant mais pas par le
          superviseur après 48 h (réglable) → tâche + rappel aux superviseurs."""
        now = fields.Datetime.now()
        Task = self.env['school.attendance.task']
        Notif = self.env['school.notification']
        open_hours = icp_int(self.env, 'internship_open_reminder_hours', 14)
        for shift in self.sudo().search([('checkout_time', '=', False), ('checkin_time', '!=', False),
                                         ('checkin_state', '!=', 'rejected'), ('reminder_sent', '=', False),
                                         ('checkin_time', '<=', now - timedelta(hours=open_hours))]):
            Notif.notify(shift.student_id.user_id, "Pensez à confirmer la fin de votre garde",
                         f"Garde commencée à {local_time(self.env, shift.checkin_time, '%d/%m %Hh%M')} "
                         f"({shift.site_id.name}) : confirmez votre sortie.", url='/presence/stages',
                         category='reminder')
            Task.create_internship('internship_open', shift, f"Sortie de garde non confirmée : {shift.student_id.name}",
                                   f"Garde ouverte depuis plus de {open_hours} h sur « {shift.site_id.name} ».")
            shift.reminder_sent = True
        delay = icp_int(self.env, 'internship_validation_delay_hours', 48)
        for shift in self.sudo().search([('student_confirmed', '=', True), ('supervisor_confirmed', '=', False),
                                         ('checkout_state', '!=', 'rejected'), ('unvalidated_alert_sent', '=', False),
                                         ('checkout_time', '<=', now - timedelta(hours=delay))]):
            Task.create_internship('internship_unvalidated', shift,
                                   f"Validation superviseur manquante : {shift.student_id.name}",
                                   f"Garde du {local_time(self.env, shift.checkin_time, '%d/%m')} sur "
                                   f"« {shift.site_id.name} » non validée après {delay} h.")
            Notif.notify(shift.site_id.supervisor_ids.mapped('user_id'), "Gardes en attente de validation",
                         f"{shift.student_id.name} attend votre validation depuis plus de {delay} h.",
                         url='/presence/stages/validation', category='admin')
            shift.unvalidated_alert_sent = True
