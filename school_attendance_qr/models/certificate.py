import base64
from datetime import date

from odoo import api, fields, models
from odoo.exceptions import UserError

from . import render


class SchoolAttendanceCertificate(models.Model):
    """Une attestation de présence émise : conservée avec sa référence, pour
    pouvoir la retrouver et la re-télécharger."""
    _name = 'school.attendance.certificate'
    _description = 'Attestation de présence'
    _order = 'issue_date desc, id desc'

    name = fields.Char(string="Référence", readonly=True, default='Nouveau', copy=False)
    student_id = fields.Many2one('school.student', required=True, string="Étudiant", ondelete='cascade')
    date_from = fields.Date(string="Du", required=True)
    date_to = fields.Date(string="Au", required=True)
    issue_date = fields.Date(string="Émise le", default=fields.Date.context_today, readonly=True)
    expected = fields.Integer(string="Séances programmées", readonly=True)
    attended = fields.Integer(string="Séances présentes", readonly=True)
    rate = fields.Float(string="Taux de présence (%)", readonly=True)
    issued_by = fields.Many2one('res.users', string="Émise par", default=lambda self: self.env.user, readonly=True)
    pdf_file = fields.Binary(attachment=True, readonly=True)
    pdf_filename = fields.Char(readonly=True)

    @api.model
    def compute_period_stats(self, student, date_from, date_to):
        """Séances programmées / présentes d'un étudiant sur une période, par cours."""
        Session = self.env['school.attendance.session'].sudo()
        rows, expected, attended = [], 0, 0
        for course in student.sudo().course_ids:
            sessions = Session.search([('course_id', '=', course.id), ('date', '>=', date_from), ('date', '<=', date_to)])
            if not sessions:
                continue
            present = len(sessions.filtered(lambda s: s.record_ids.filtered(
                lambda r: r.student_id == student and r.state != 'rejected')))
            rows.append((course.name, len(sessions), present, present / len(sessions) * 100))
            expected += len(sessions)
            attended += present
        return {'rows': rows, 'expected': expected, 'attended': attended,
                'rate': round(attended / expected * 100, 1) if expected else 0.0}

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'Nouveau') == 'Nouveau':
                vals['name'] = self.env['ir.sequence'].next_by_code('school.attendance.certificate') or 'Nouveau'
        return super().create(vals_list)

    def _fmt(self, d):
        return d.strftime('%d/%m/%Y')

    def _build_pdf(self):
        self.ensure_one()
        company = self.env.company
        style = self.env['school.qr.style'].search([], limit=1)
        logo = style._effective_logo_bytes() if style else (
            base64.b64decode(company.school_logo) if company.school_logo else None)
        student = self.student_id.sudo()
        stats = self.compute_period_stats(student, self.date_from, self.date_to)
        pdf = render.build_certificate_pdf({
            'school_name': company.name, 'logo_bytes': logo, 'reference': self.name,
            'student_name': student.name, 'matricule': student.matricule,
            'promotion': student.promotion_id.name or '',
            'date_from': self._fmt(self.date_from), 'date_to': self._fmt(self.date_to),
            'issue_date': self._fmt(self.issue_date or date.today()), 'city': company.city or '',
            'expected': stats['expected'], 'attended': stats['attended'], 'rate': stats['rate'], 'rows': stats['rows'],
            'color_1': style.color_1 if style else render.DEFAULT_COLOR_1,
            'color_2': style.color_2 if style else render.DEFAULT_COLOR_2,
        })
        self.write({
            'expected': stats['expected'], 'attended': stats['attended'], 'rate': stats['rate'],
            'pdf_file': base64.b64encode(pdf),
            'pdf_filename': f"Attestation-{self.name.replace('/', '-')}-{student.matricule}.pdf",
        })

    def action_download(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_url', 'target': 'self',
                'url': f'/web/content/school.attendance.certificate/{self.id}/pdf_file/{self.pdf_filename}?download=true'}


class SchoolCertificateWizard(models.TransientModel):
    _name = 'school.certificate.wizard'
    _description = "Assistant d'attestation de présence"

    student_id = fields.Many2one('school.student', required=True, string="Étudiant")
    date_from = fields.Date(string="Du", required=True,
                            default=lambda self: date(fields.Date.context_today(self).year, 1, 1))
    date_to = fields.Date(string="Au", required=True, default=fields.Date.context_today)

    def action_generate(self):
        self.ensure_one()
        if self.date_from > self.date_to:
            raise UserError("La date de début doit précéder la date de fin.")
        stats = self.env['school.attendance.certificate'].compute_period_stats(
            self.student_id, self.date_from, self.date_to)
        if not stats['expected']:
            raise UserError("Aucune séance n'était programmée pour cet étudiant sur cette période : "
                            "il n'y a rien à attester.")
        cert = self.env['school.attendance.certificate'].create({
            'student_id': self.student_id.id, 'date_from': self.date_from, 'date_to': self.date_to})
        cert._build_pdf()
        return cert.action_download()
