import base64
import mimetypes

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from odoo.addons.school_attendance_qr.models.helpers import icp_int

DOCUMENT_TYPES = [
    ('cours', 'Support de cours'), ('td', 'Travaux dirigés'), ('tp', 'Travaux pratiques'),
    ('sujet', "Sujet d'examen (ancien)"), ('autre', 'Autre'),
]
# Seuls des PDF et des images : lisibles sur tous les téléphones, sans risque d'exécution
ALLOWED = {
    'application/pdf': b'%PDF',
    'image/jpeg': b'\xff\xd8\xff',
    'image/png': b'\x89PNG',
    'image/webp': b'RIFF',
}


class SchoolCourseDocument(models.Model):
    _name = 'school.course.document'
    _description = 'Document de cours'
    _order = 'course_id, create_date desc'

    name = fields.Char(required=True, string="Titre")
    course_id = fields.Many2one('school.course', required=True, string="Cours", index=True)
    teacher_id = fields.Many2one('school.teacher', related='course_id.teacher_id', store=True)
    document_type = fields.Selection(DOCUMENT_TYPES, default='cours', required=True, string="Type")
    file = fields.Binary(required=True, attachment=True, string="Fichier")
    filename = fields.Char(string="Nom du fichier")
    mimetype = fields.Char(readonly=True)
    file_size = fields.Integer(readonly=True, string="Taille (octets)")
    description = fields.Text()
    uploaded_by = fields.Many2one('res.users', default=lambda self: self.env.user, readonly=True, string="Déposé par")

    def _check_file(self, vals):
        if not vals.get('file'):
            return vals
        raw = base64.b64decode(vals['file'])
        limit = icp_int(self.env, 'document_max_mb', 20)
        if len(raw) > limit * 1024 * 1024:
            raise ValidationError(_("Fichier trop lourd : %s Mo maximum.", limit))
        mimetype = next((m for m, magic in ALLOWED.items() if raw.startswith(magic)), None)
        if not mimetype:
            raise ValidationError(_("Seuls les fichiers PDF et les images (JPEG, PNG, WebP) sont acceptés."))
        ext = mimetypes.guess_extension(mimetype) or ''
        filename = vals.get('filename') or f"{vals.get('name') or 'document'}{ext}"
        return dict(vals, mimetype=mimetype, file_size=len(raw), filename=filename)

    @api.model_create_multi
    def create(self, vals_list):
        docs = super().create([self._check_file(v) for v in vals_list])
        for doc in docs:
            self.env['school.notification'].notify(
                doc.course_id.sudo().student_ids.mapped('user_id'), f"Nouveau document : {doc.course_id.name}",
                doc.name, url='/presence/documents', category='result')
        return docs

    def write(self, vals):
        return super().write(self._check_file(vals))

    def download_url(self):
        self.ensure_one()
        return f"/presence/documents/{self.id}/{self.filename or 'document'}"
