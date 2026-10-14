from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .helpers import icp_bool

TASK_TYPES = [
    ('absence_alert', 'Absences répétées'),
    ('flagged_entry', 'Entrée à vérifier'),
    ('flagged_exit', 'Sortie à vérifier'),
    ('missing_checkout', 'Sortie non scannée'),
    ('device_shared', 'Appareil partagé entre étudiants'),
    ('device_attempt', 'Tentative depuis un autre appareil'),
    ('payment', 'Scolarité impayée'),
]


class SchoolAttendanceTask(models.Model):
    """Boîte unique « À traiter » du secrétariat : tout ce qui demande un œil
    humain arrive ici, au lieu d'être à chercher dans plusieurs écrans."""
    _name = 'school.attendance.task'
    _description = 'À traiter (secrétariat)'
    _order = 'state desc, create_date desc, id desc'

    name = fields.Char(required=True)
    task_type = fields.Selection(TASK_TYPES, required=True, string="Type")
    student_id = fields.Many2one('school.student', string="Étudiant", ondelete='cascade')
    session_id = fields.Many2one('school.attendance.session', string="Séance", ondelete='set null')
    record_id = fields.Many2one('school.attendance.record', string="Présence", ondelete='cascade')
    course_id = fields.Many2one('school.course', related='session_id.course_id', store=True, string="Cours")
    description = fields.Text()
    state = fields.Selection([('open', 'À traiter'), ('done', 'Traité')], default='open', required=True, index=True)
    done_by = fields.Many2one('res.users', string="Traité par", readonly=True)
    done_date = fields.Datetime(string="Traité le", readonly=True)
    resolution_note = fields.Char(string="Note")

    # ----------------------------------------------------------- création
    @api.model
    def create_unique(self, task_type, student, name, description='', record=None, session=None):
        """Crée la tâche sauf si la même est déjà ouverte (pas de doublons)."""
        domain = [('task_type', '=', task_type), ('student_id', '=', student.id), ('state', '=', 'open')]
        if record:
            domain.append(('record_id', '=', record.id))
        existing = self.sudo().search(domain, limit=1)
        if existing:
            return existing
        return self.sudo().create({
            'task_type': task_type, 'student_id': student.id, 'name': name, 'description': description,
            'record_id': record.id if record else False,
            'session_id': (session or (record.session_id if record else self.env['school.attendance.session'])).id,
        })

    # ------------------------------------------------------------ actions
    def action_done(self):
        self.filtered(lambda t: t.state == 'open').write({
            'state': 'done', 'done_by': self.env.user.id, 'done_date': fields.Datetime.now()})

    def action_reopen(self):
        self.write({'state': 'open', 'done_by': False, 'done_date': False})

    def action_authorize_new_device(self):
        """Pour « Tentative depuis un autre appareil » : l'étudiant a changé de téléphone."""
        for task in self:
            if task.task_type != 'device_attempt' or not task.student_id:
                raise UserError(_("Cette action ne concerne que les tentatives depuis un autre appareil."))
            task.student_id.action_reset_device()
        self.action_done()

    def action_open_student(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'res_model': 'school.student', 'res_id': self.student_id.id,
                'view_mode': 'form', 'target': 'current'}

    # --------------------------------------------- alertes d'absences (cron)
    @api.model
    def _cron_absence_alerts(self):
        """Crée une alerte pour chaque étudiant qui franchit le seuil d'absences,
        et la clôt toute seule quand son taux repasse au-dessus."""
        students = self.env['school.student'].sudo().search([('course_ids', '!=', False)])
        send_mail = icp_bool(self.env, 'alert_send_email')
        created = 0
        for student in students:
            open_alerts = self.sudo().search([('task_type', '=', 'absence_alert'),
                                              ('student_id', '=', student.id), ('state', '=', 'open')])
            if student.at_risk:
                if not open_alerts:
                    self.sudo().create({
                        'task_type': 'absence_alert', 'student_id': student.id,
                        'name': f"Absences répétées : {student.name}",
                        'description': (f"{student.sessions_missed} séance(s) manquée(s) sur {student.sessions_expected} "
                                        f"(présence {student.attendance_rate:.0f} %)."),
                    })
                    created += 1
                    if send_mail:
                        self._send_absence_email(student)
            elif open_alerts:
                open_alerts.write({
                    'state': 'done', 'done_date': fields.Datetime.now(),
                    'resolution_note': "Clôturée automatiquement : le taux de présence est repassé au-dessus du seuil."})
        return created

    @api.model
    def _send_absence_email(self, student):
        if not student.email:
            return False
        body = (f"<p>Bonjour {student.prenom},</p>"
                f"<p>Nous constatons que vous avez manqué <b>{student.sessions_missed}</b> séance(s) sur "
                f"<b>{student.sessions_expected}</b> ({student.attendance_rate:.0f} % de présence).</p>"
                "<p>Merci de vous rapprocher de la scolarité si vous rencontrez une difficulté.</p>")
        try:
            mail = self.env['mail.mail'].sudo().create({
                'subject': "Vos absences", 'body_html': body, 'email_to': student.email, 'auto_delete': True})
            mail.send(raise_exception=False)
            return True
        except Exception:
            return False
