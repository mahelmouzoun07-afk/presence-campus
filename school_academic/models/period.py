from odoo import api, fields, models
from odoo.exceptions import ValidationError


class SchoolAcademicPeriod(models.Model):
    """Une période d'évaluation (semestre, trimestre...) : les moyennes et
    les bulletins sont calculés période par période."""
    _name = 'school.academic.period'
    _description = 'Période académique'
    _order = 'date_from desc'

    name = fields.Char(required=True, help="Ex : Semestre 1 — 2026-2027")
    date_from = fields.Date(required=True, string="Du")
    date_to = fields.Date(required=True, string="Au")
    active = fields.Boolean(default=True)

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for rec in self:
            if rec.date_from > rec.date_to:
                raise ValidationError("La date de début de la période doit précéder sa date de fin.")

    @api.model
    def period_for(self, day):
        return self.search([('date_from', '<=', day), ('date_to', '>=', day)], limit=1)

    @api.model
    def current(self):
        return self.period_for(fields.Date.context_today(self)) or self.search([], limit=1)


class SchoolCourseAcademic(models.Model):
    _inherit = 'school.course'

    coefficient = fields.Float(default=1.0, string="Coefficient",
                               help="Poids du cours dans la moyenne générale.")
    evaluation_ids = fields.One2many('school.evaluation', 'course_id', string="Évaluations")
    document_ids = fields.One2many('school.course.document', 'course_id', string="Documents")
