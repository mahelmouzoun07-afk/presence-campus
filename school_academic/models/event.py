from datetime import timedelta

from odoo import api, fields, models

EVENT_TYPES = [
    ('devoir', 'Devoir à rendre'), ('echeance', 'Échéance'), ('examen', 'Examen'),
    ('evenement', 'Événement'), ('ferie', 'Jour férié / congé'), ('autre', 'Autre'),
]
IMPORTANCE = [('low', 'Faible'), ('normal', 'Normale'), ('high', 'Haute')]
# Rappels envoyés avant l'événement, selon son importance (en heures)
REMINDER_OFFSETS = {'high': (168, 72, 24, 2), 'normal': (72, 24), 'low': (24,)}


class SchoolAcademicEvent(models.Model):
    """Tout le calendrier académique au même endroit : devoirs, échéances,
    examens, événements. Les examens y sont ajoutés automatiquement depuis
    les évaluations."""
    _name = 'school.academic.event'
    _description = 'Événement académique'
    _order = 'date_start'

    name = fields.Char(required=True, string="Titre")
    event_type = fields.Selection(EVENT_TYPES, required=True, default='devoir', string="Type")
    importance = fields.Selection(IMPORTANCE, required=True, default='normal')
    date_start = fields.Datetime(required=True, string="Date", default=fields.Datetime.now)
    date_end = fields.Datetime(string="Fin")
    all_day = fields.Boolean(string="Toute la journée")
    course_id = fields.Many2one('school.course', string="Cours")
    teacher_id = fields.Many2one('school.teacher', related='course_id.teacher_id', store=True)
    promotion_id = fields.Many2one('school.promotion', string="Promotion")
    filiere_id = fields.Many2one('school.filiere', string="Filière")
    description = fields.Text()
    reminders_sent = fields.Char(readonly=True, copy=False, help="Délais de rappel déjà envoyés (heures).")

    def audience(self):
        """Les étudiants concernés : ceux du cours, sinon de la promotion, sinon
        de la filière, sinon toute l'école."""
        self.ensure_one()
        Student = self.env['school.student'].sudo()
        if self.course_id:
            return self.course_id.sudo().student_ids
        if self.promotion_id:
            return Student.search([('promotion_id', '=', self.promotion_id.id)])
        if self.filiere_id:
            return Student.search([('filiere_id', '=', self.filiere_id.id)])
        return Student.search([])

    @api.model
    def for_student(self, student, date_from, date_to):
        return self.sudo().search([
            ('date_start', '>=', date_from), ('date_start', '<=', date_to),
            '|', '|', '|', ('course_id', 'in', student.sudo().course_ids.ids),
            ('promotion_id', '=', student.promotion_id.id or -1),
            ('filiere_id', '=', student.filiere_id.id or -1),
            '&', '&', ('course_id', '=', False), ('promotion_id', '=', False), ('filiere_id', '=', False),
        ])

    @api.model
    def _cron_event_reminders(self):
        now = fields.Datetime.now()
        Notif = self.env['school.notification']
        for event in self.sudo().search([('date_start', '>', now), ('date_start', '<=', now + timedelta(days=8))]):
            sent = set(filter(None, (event.reminders_sent or '').split(',')))
            hours_left = (event.date_start - now).total_seconds() / 3600
            due = [h for h in REMINDER_OFFSETS[event.importance] if hours_left <= h and str(h) not in sent]
            if not due:
                continue
            when = f"dans {int(round(hours_left))} h" if hours_left < 48 else f"dans {int(hours_left // 24)} jours"
            Notif.notify(event.audience().mapped('user_id'), f"{dict(EVENT_TYPES)[event.event_type]} {when}",
                         event.name, url='/presence/calendrier', category='reminder')
            event.reminders_sent = ','.join(sorted(sent | {str(h) for h in REMINDER_OFFSETS[event.importance]
                                                         if hours_left <= h}))
