from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class SchoolInternshipEvaluation(models.Model):
    """Mini-évaluation facultative, remplie par le superviseur sur le MÊME
    écran que la validation de la garde."""
    _name = 'school.internship.evaluation'
    _description = 'Évaluation de garde'
    _order = 'id desc'

    attendance_id = fields.Many2one('school.internship.attendance', required=True, ondelete='cascade', index=True)
    student_id = fields.Many2one(related='attendance_id.student_id', store=True, string="Étudiant")
    site_id = fields.Many2one(related='attendance_id.site_id', store=True, string="Site")
    supervisor_id = fields.Many2one('school.teacher', readonly=True, string="Superviseur")
    rating = fields.Selection([(str(i), str(i)) for i in range(1, 6)], string="Note (1 à 5)")
    comment = fields.Text(string="Commentaire")

    @api.constrains('rating', 'comment')
    def _check_not_empty(self):
        for rec in self:
            if not rec.rating and not (rec.comment or '').strip():
                raise ValidationError(_("Une évaluation doit contenir une note ou un commentaire."))
