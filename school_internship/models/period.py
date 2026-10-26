from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError


class SchoolInternshipPeriod(models.Model):
    """Une période de stage d'un étudiant sur un site. Contrairement aux
    séances de cours (générées depuis un emploi du temps fixe), elle est
    flexible : l'étudiant enchaîne des gardes d'horaires variables, et ce qui
    compte est le total d'heures validées."""
    _name = 'school.internship.period'
    _description = 'Période de stage'
    _order = 'date_start desc, id desc'

    name = fields.Char(compute='_compute_name', store=True)
    student_id = fields.Many2one('school.student', required=True, index=True, string="Étudiant")
    site_id = fields.Many2one('school.internship.site', required=True, index=True, string="Site")
    date_start = fields.Date(required=True, string="Du")
    date_end = fields.Date(required=True, string="Au")
    required_hours = fields.Float(default=0.0, string="Heures à valider")
    status = fields.Selection([
        ('in_progress', 'En cours'), ('done', 'Terminé'), ('validated', 'Validé'),
    ], default='in_progress', required=True, string="Statut")
    attendance_ids = fields.One2many('school.internship.attendance', 'period_id', string="Gardes")
    adjusted_hours = fields.Float(
        string="Ajustement manuel (h)", groups='school_base.group_school_admin',
        help="Réservé à l'administration (ex. garde validée sur papier pendant une panne). "
             "Chaque modification est enregistrée dans le journal d'audit.")
    # Compteur NON stocké : jamais de default_order dessus (bug Odoo 18 documenté dans CLAUDE.md).
    validated_hours = fields.Float(compute='_compute_hours', string="Heures validées")
    pending_hours = fields.Float(compute='_compute_hours', string="Heures en attente de validation")
    progress = fields.Float(compute='_compute_hours', string="Avancement (%)")

    @api.depends('student_id', 'site_id', 'date_start')
    def _compute_name(self):
        for rec in self:
            rec.name = f"{rec.student_id.name or ''} — {rec.site_id.name or ''} ({rec.date_start or ''})"

    @api.depends('attendance_ids.duration_hours', 'attendance_ids.is_validated', 'attendance_ids.checkout_time',
                 'attendance_ids.checkout_state', 'required_hours', 'adjusted_hours')
    def _compute_hours(self):
        for rec in self:
            done = rec.attendance_ids.filtered('is_validated')
            pending = rec.attendance_ids.filtered(lambda a: a.checkout_time and not a.is_validated
                                                  and a.checkout_state != 'rejected')
            total = sum(done.mapped('duration_hours')) + (rec.sudo().adjusted_hours or 0.0)
            rec.validated_hours = round(total, 2)
            rec.pending_hours = round(sum(pending.mapped('duration_hours')), 2)
            rec.progress = min(total / rec.required_hours * 100, 100.0) if rec.required_hours else 0.0

    @api.constrains('date_start', 'date_end')
    def _check_dates(self):
        for rec in self:
            if rec.date_start > rec.date_end:
                raise ValidationError(_("La période de stage doit commencer avant de finir."))

    def write(self, vals):
        if 'adjusted_hours' in vals:
            if not (self.env.su or self.env.user.has_group('school_base.group_school_admin')):
                raise AccessError(_("Seule l'administration peut ajuster les heures de stage."))
            for rec in self:
                self.env['school.audit.log'].log(
                    'internship', f"Ajustement manuel des heures de stage ({rec.site_id.name}) : "
                                  f"{rec.sudo().adjusted_hours or 0:g} h → {vals['adjusted_hours'] or 0:g} h.",
                    student=rec.student_id, record=rec)
        return super().write(vals)

    def action_mark_done(self):
        self.write({'status': 'done'})

    def action_validate(self):
        """Validation finale par l'administration : génère le relevé d'heures."""
        for rec in self:
            rec.status = 'validated'
            rec.action_generate_statement()

    def action_generate_statement(self):
        """Relevé d'heures PDF : même modèle et même moteur que les attestations
        de présence (school.attendance.certificate + render.py)."""
        self.ensure_one()
        cert = self.env['school.attendance.certificate'].sudo().create({
            'student_id': self.student_id.id, 'date_from': self.date_start, 'date_to': self.date_end,
            'certificate_type': 'internship_hours', 'internship_period_id': self.id,
        })
        cert._build_pdf()
        return cert.action_download()

    def open_shift(self):
        """La garde commencée et pas encore terminée, s'il y en a une."""
        self.ensure_one()
        return self.attendance_ids.filtered(lambda a: a.checkin_time and not a.checkout_time
                                            and a.checkin_state != 'rejected')[:1]


class SchoolStudentInternship(models.Model):
    _inherit = 'school.student'

    internship_period_ids = fields.One2many('school.internship.period', 'student_id', string="Stages")
    # Non stocké : jamais de default_order dessus.
    internship_hours = fields.Float(compute='_compute_internship_hours', string="Heures cliniques validées")

    @api.depends('internship_period_ids.validated_hours')
    def _compute_internship_hours(self):
        for rec in self:
            rec.internship_hours = sum(rec.sudo().internship_period_ids.mapped('validated_hours'))

    def current_internship_period(self):
        self.ensure_one()
        today = fields.Date.context_today(self)
        return self.env['school.internship.period'].sudo().search([
            ('student_id', '=', self.id), ('status', '=', 'in_progress'),
            ('date_start', '<=', today), ('date_end', '>=', today)], limit=1)
