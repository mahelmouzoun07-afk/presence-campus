import base64
import secrets

from odoo import api, fields, models

from . import render
from .helpers import get_base_url


class SchoolRoomQr(models.Model):
    """Ajoute à la salle son QR permanent (jamais modifié), stylé et imprimable."""
    _inherit = 'school.room'

    qr_token = fields.Char(default=lambda self: secrets.token_urlsafe(16), readonly=True, copy=False)
    qr_style_id = fields.Many2one('school.qr.style', string="Style du QR",
                                  help="Laissez vide pour utiliser le style par défaut.")
    scan_url = fields.Char(compute='_compute_scan_url',
                           help="Adresse encodée dans le QR. Elle ne change jamais pour cette salle.")
    qr_image = fields.Binary(compute='_compute_qr_image', attachment=False, string="Aperçu du QR")

    @api.depends('qr_token')
    def _compute_scan_url(self):
        base = get_base_url(self.env)
        for rec in self:
            rec.scan_url = f"{base}/school/attendance/scan/{rec.qr_token}" if rec.qr_token else False

    def _get_qr_style(self):
        self.ensure_one()
        return self.qr_style_id or self.env['school.qr.style'].search([], limit=1)

    def _render_qr_png(self, box_size=12):
        self.ensure_one()
        style = self._get_qr_style()
        if style:
            return style.render_png(self.scan_url, box_size=box_size)
        return self.env['school.qr.style'].default_render_png(self.scan_url, box_size=box_size)

    @api.depends('scan_url', 'qr_style_id', 'qr_style_id.shape', 'qr_style_id.color_mode', 'qr_style_id.color_1',
                 'qr_style_id.color_2', 'qr_style_id.background_color', 'qr_style_id.logo', 'qr_style_id.logo_scale')
    def _compute_qr_image(self):
        for rec in self:
            rec.qr_image = base64.b64encode(rec._render_qr_png(box_size=8)) if rec.scan_url else False

    def _render_posters_pdf(self):
        """Une page A4 par salle, prête à imprimer et à coller au mur."""
        posters = []
        company = self.env.company
        for room in self:
            style = room._get_qr_style()
            logo = style._effective_logo_bytes() if style else (
                base64.b64decode(company.school_logo) if company.school_logo else None)
            posters.append({
                'room_name': room.name, 'building': room.building or '',
                'qr_png': room._render_qr_png(box_size=14),
                'title': (style.poster_title if style else "Scannez pour confirmer votre présence"),
                'subtitle': (style.poster_subtitle if style else
                             "Ouvrez l'appareil photo de votre téléphone, scannez le code, puis confirmez."),
                'school_name': company.name, 'logo_bytes': logo,
                'color_1': style.color_1 if style else render.DEFAULT_COLOR_1,
                'color_2': style.color_2 if style else render.DEFAULT_COLOR_2,
            })
        return render.build_poster_pdf(posters)

    def action_download_qr_png(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_url', 'url': f'/school/qr/png/{self.id}', 'target': 'self'}

    def action_print_posters(self):
        ids = ','.join(str(i) for i in self.ids)
        return {'type': 'ir.actions.act_url', 'url': f'/school/qr/poster?ids={ids}', 'target': 'self'}
