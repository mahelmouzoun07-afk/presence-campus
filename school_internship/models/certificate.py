"""Relevé d'heures de stage : une variante de l'attestation de présence
existante (même modèle school.attendance.certificate, même moteur render.py)."""
from reportlab.lib.units import cm as CM

from odoo import fields, models


class SchoolAttendanceCertificateInternship(models.Model):
    _inherit = 'school.attendance.certificate'

    certificate_type = fields.Selection(selection_add=[('internship_hours', "Relevé d'heures de stage")],
                                        ondelete={'internship_hours': 'cascade'})
    internship_period_id = fields.Many2one('school.internship.period', readonly=True, string="Période de stage")

    def _pdf_extra(self):
        if self.certificate_type != 'internship_hours':
            return super()._pdf_extra()
        period = self.internship_period_id.sudo()
        shifts = period.attendance_ids.filtered('is_validated').sorted('checkin_time')
        fmt = lambda dt: self.env['school.attendance.session'].fmt_local(dt, '%d/%m/%Y %Hh%M')  # noqa: E731
        table = [["Garde (entrée)", "Sortie", "Durée", "Validée par"]]
        table += [[fmt(s.checkin_time), fmt(s.checkout_time), f"{s.duration_hours:g} h",
                   s.supervisor_id.name or ''] for s in shifts]
        if period.adjusted_hours:
            table.append(["Ajustement administratif", "", f"{period.adjusted_hours:g} h", ""])
        table.append(["Total validé", "", f"{period.validated_hours:g} h",
                      f"sur {period.required_hours:g} h requises"])
        rate = period.progress
        extra = {
            'title': "Relevé d'heures de stage",
            'file_prefix': 'Releve-stage',
            'intro': (f"Nous soussignés, <b>{self.env.company.name}</b>, attestons que l'étudiant(e) "
                      f"<b>{period.student_id.name}</b>, matricule <b>{period.student_id.matricule}</b>, a effectué "
                      f"<b>{period.validated_hours:g} heure(s)</b> de stage clinique validée(s) au sein de "
                      f"<b>{period.site_id.name}</b>"
                      + (f" ({period.site_id.specialty})" if period.site_id.specialty else '')
                      + f", du <b>{self._fmt(period.date_start)}</b> au <b>{self._fmt(period.date_end)}</b>, "
                        f"soit <b>{rate:.0f} %</b> des {period.required_hours:g} heures requises."),
            'table': table,
            'col_widths': [5.2 * CM, 4.4 * CM, 2.4 * CM, 4.6 * CM],
            'footnote': ("Seules les gardes doublement validées sont comptées : confirmées par l'étudiant (position "
                         "et empreinte vérifiées) puis par un superviseur du site avec sa propre empreinte."),
        }
        stats = {'rows': [], 'expected': int(round(period.required_hours)),
                 'attended': int(round(period.validated_hours)), 'rate': round(rate, 1)}
        return extra, stats
