"""Bulletin de notes en PDF, fabriqué par reportlab comme les attestations
(fonctionne aussi sur un serveur sans Internet)."""
import base64
import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm as CM
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from odoo import _, fields, models
from odoo.exceptions import UserError

from odoo.addons.school_attendance_qr.models import render


def _fmt(value, scale=None):
    if value is None:
        return '—'
    text = f"{value:.2f}".rstrip('0').rstrip('.').replace('.', ',')
    return f"{text} / {scale:g}" if scale else text


def build_bulletin_pdf(school, pages):
    """pages : une entrée par étudiant {student, period, results, rank, rank_total, attendance_rate}."""
    buf = io.BytesIO()
    navy = render._rl_color(school.get('color_1'), (20, 33, 61))
    gold = render._rl_color(school.get('color_2'), (140, 90, 11))
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=1.8 * CM, rightMargin=1.8 * CM,
                            topMargin=4.6 * CM, bottomMargin=2.2 * CM, title="Bulletin de notes",
                            author=school.get('name') or '')
    title = ParagraphStyle('t', fontName='Helvetica-Bold', fontSize=17, textColor=navy, alignment=1, spaceAfter=10)
    body = ParagraphStyle('b', fontName='Helvetica', fontSize=10.5, leading=15)
    small = ParagraphStyle('s', fontName='Helvetica', fontSize=8.5, leading=11, textColor=colors.Color(0.4, 0.42, 0.48))

    def header_footer(pdf, _doc):
        w, h = A4
        pdf.saveState()
        render._gradient_rect(pdf, 0, h - 3.2 * CM, w, 3.2 * CM, navy, render._darker(navy))
        pdf.setFillColor(gold)
        pdf.rect(0, h - 3.2 * CM - 4, w, 4, stroke=0, fill=1)
        pdf.setFillColor(colors.white)
        pdf.setFont('Helvetica-Bold', 16)
        pdf.drawString(1.8 * CM, h - 1.8 * CM, (school.get('name') or '')[:60])
        pdf.setFont('Helvetica', 8.5)
        pdf.setFillColor(colors.Color(0.4, 0.42, 0.48))
        pdf.drawRightString(w - 1.8 * CM, 1.2 * CM, "Document généré par le système de l'établissement")
        pdf.restoreState()

    story = []
    for i, page in enumerate(pages):
        student, results = page['student'], page['results']
        scale = results['scale']
        if i:
            story.append(PageBreak())
        story.append(Paragraph("BULLETIN DE NOTES", title))
        story.append(Paragraph(
            f"<b>{student.name}</b> — matricule <b>{student.matricule}</b>"
            + (f" — {student.promotion_id.name}" if student.promotion_id else '')
            + (f" ({student.filiere_id.name})" if student.filiere_id else '')
            + f"<br/>Période : <b>{page['period'].name if page['period'] else 'toute l’année'}</b>", body))
        story.append(Spacer(1, 12))
        rows = [["Cours", "Coef.", "Évaluations", "Moyenne"]]
        for c in results['courses']:
            detail = ", ".join(
                f"{line['evaluation'].name} : {'abs.' if line['grade'].is_absent else _fmt(line['normalized'])}"
                for line in c['lines'])
            rows.append([Paragraph(c['course'].name, body), f"{c['coefficient']:g}", Paragraph(detail, small),
                         _fmt(c['average'], scale)])
        rows.append(["Moyenne générale", "", "", _fmt(results['general'], scale)])
        table = Table(rows, colWidths=[5.0 * CM, 1.4 * CM, 8.0 * CM, 3.0 * CM], repeatRows=1)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), navy), ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'), ('FONTSIZE', (0, 0), (-1, -1), 9.5),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'), ('LINEABOVE', (0, -1), (-1, -1), 1.2, gold),
            ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.white, colors.Color(0.96, 0.96, 0.94)]),
            ('ALIGN', (1, 0), (1, -1), 'CENTER'), ('ALIGN', (3, 0), (3, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('GRID', (0, 0), (-1, -1), 0.4, colors.Color(0.82, 0.83, 0.8)),
            ('TOPPADDING', (0, 0), (-1, -1), 6), ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ]))
        story += [table, Spacer(1, 14)]
        decision = ("Admis(e)" if results['passed'] else "Non admis(e)") if results['general'] is not None else "—"
        rank = f"{page['rank']} / {page['rank_total']}" if page.get('rank') else "—"
        story.append(Paragraph(
            f"Note de passage : {_fmt(results['pass_mark'], scale)} — Décision : <b>{decision}</b> — "
            f"Rang dans la promotion : <b>{rank}</b> — Taux de présence : <b>{page['attendance_rate']:.0f} %</b>",
            body))
        story.append(Spacer(1, 36))
        sign = Table([["", "Le responsable de la scolarité\n\n\n______________________________"]],
                     colWidths=[9.0 * CM, 8.4 * CM])
        sign.setStyle(TableStyle([('FONTNAME', (0, 0), (-1, -1), 'Helvetica'), ('FONTSIZE', (0, 0), (-1, -1), 10),
                                  ('ALIGN', (1, 0), (1, 0), 'CENTER')]))
        story.append(sign)
    doc.build(story, onFirstPage=header_footer, onLaterPages=header_footer)
    return buf.getvalue()


class SchoolStudentBulletin(models.Model):
    _inherit = 'school.student'

    def bulletin_pdf(self, period=None):
        style = self.env['school.qr.style'].sudo().search([], limit=1)
        company = self.env.company
        pages = []
        for student in self.sudo():
            rank, total = self.promotion_rank(student, period)
            pages.append({'student': student, 'period': period, 'results': student.compute_results(period),
                          'rank': rank, 'rank_total': total, 'attendance_rate': student.attendance_rate})
        return build_bulletin_pdf({'name': company.name, 'color_1': style.color_1 if style else None,
                                   'color_2': style.color_2 if style else None}, pages)


class SchoolBulletinWizard(models.TransientModel):
    _name = 'school.bulletin.wizard'
    _description = 'Génération des bulletins de notes'

    period_id = fields.Many2one('school.academic.period', string="Période",
                                default=lambda self: self.env['school.academic.period'].current())
    promotion_id = fields.Many2one('school.promotion', string="Promotion entière")
    student_ids = fields.Many2many('school.student', string="Ou étudiants choisis")
    pdf_file = fields.Binary(readonly=True)
    pdf_filename = fields.Char(readonly=True)

    def action_generate(self):
        self.ensure_one()
        students = self.student_ids or self.env['school.student'].search(
            [('promotion_id', '=', self.promotion_id.id)] if self.promotion_id else [('id', '=', 0)])
        if not students:
            raise UserError(_("Choisissez une promotion ou au moins un étudiant."))
        self.write({'pdf_file': base64.b64encode(students.bulletin_pdf(self.period_id)),
                    'pdf_filename': f"Bulletins-{(self.period_id.name or 'annee').replace(' ', '-')}.pdf"})
        return {'type': 'ir.actions.act_url', 'target': 'self',
                'url': f'/web/content/school.bulletin.wizard/{self.id}/pdf_file/{self.pdf_filename}?download=true'}
