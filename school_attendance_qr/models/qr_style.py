import base64

from odoo import api, fields, models
from odoo.exceptions import ValidationError

from . import render


class SchoolQrStyle(models.Model):
    """Apparence des QR codes et des affiches : couleurs, forme, logo au centre."""
    _name = 'school.qr.style'
    _description = 'Style de QR code'
    _order = 'sequence, id'

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10, help="Le premier style de la liste est celui utilisé par défaut.")
    active = fields.Boolean(default=True)

    shape = fields.Selection(render.SHAPES, default='rounded', required=True, string="Forme des points")
    color_mode = fields.Selection(render.COLOR_MODES, default='radial', required=True, string="Mode de couleur")
    color_1 = fields.Char(string="Couleur principale", default=render.DEFAULT_COLOR_1, required=True)
    color_2 = fields.Char(string="Couleur secondaire", default=render.DEFAULT_COLOR_2, required=True,
                          help="Seconde couleur du dégradé, et couleur d'accent de l'affiche.")
    background_color = fields.Char(string="Fond", default=render.DEFAULT_BG, required=True)

    logo = fields.Binary(string="Logo au centre", attachment=True,
                         help="Image placée au milieu du QR. Laissez vide pour utiliser le logo de l'établissement.")
    use_school_logo = fields.Boolean(string="Utiliser le logo de l'établissement si aucun logo n'est choisi",
                                     default=True)
    logo_scale = fields.Integer(string="Taille du logo (%)", default=22,
                                help="Entre 12 et 28 % de la largeur du QR. Plus grand, il risque de le rendre illisible.")

    poster_title = fields.Char(string="Titre de l'affiche", default="Scannez pour confirmer votre présence")
    poster_subtitle = fields.Char(string="Sous-titre de l'affiche",
                                  default="Ouvrez l'appareil photo de votre téléphone, scannez le code, puis confirmez.")

    preview_image = fields.Binary(compute='_compute_preview', string="Aperçu")

    @api.constrains('color_1', 'color_2', 'background_color')
    def _check_colors(self):
        """Un QR doit rester lisible : on refuse les couleurs trop proches du fond."""
        for rec in self:
            for field in ('color_1', 'color_2'):
                if rec.color_mode == 'solid' and field == 'color_2':
                    continue
                if render.contrast_ratio(rec[field], rec.background_color) < 3.0:
                    raise ValidationError(
                        "Contraste insuffisant : la couleur choisie est trop proche du fond, le QR code risquerait "
                        "de ne plus être lisible par les téléphones. Choisissez une couleur plus foncée "
                        "(ou un fond plus clair).")

    @api.constrains('logo_scale')
    def _check_logo_scale(self):
        for rec in self:
            if not 12 <= rec.logo_scale <= 28:
                raise ValidationError("La taille du logo doit être comprise entre 12 % et 28 % : au-delà, le QR n'est plus fiable.")

    def _effective_logo_bytes(self):
        self.ensure_one()
        data = self.logo or (self.env.company.school_logo if self.use_school_logo else False)
        return base64.b64decode(data) if data else None

    def render_png(self, url, box_size=12):
        """Octets PNG du QR de cette adresse, dans ce style."""
        self.ensure_one()
        img = render.render_qr_image(
            url, shape=self.shape, color_mode=self.color_mode, color_1=self.color_1, color_2=self.color_2,
            background=self.background_color, logo_bytes=self._effective_logo_bytes(),
            logo_scale=self.logo_scale, box_size=box_size)
        return render.image_to_png_bytes(img)

    @api.depends('shape', 'color_mode', 'color_1', 'color_2', 'background_color', 'logo', 'use_school_logo', 'logo_scale')
    def _compute_preview(self):
        for rec in self:
            try:
                png = rec.render_png("https://exemple.org/school/attendance/scan/APERCU", box_size=8)
                rec.preview_image = base64.b64encode(png)
            except Exception:
                rec.preview_image = False

    @api.model
    def default_render_png(self, url, box_size=12):
        """QR au style par défaut quand aucun style n'a été défini."""
        logo = self.env.company.school_logo
        img = render.render_qr_image(url, logo_bytes=base64.b64decode(logo) if logo else None, box_size=box_size)
        return render.image_to_png_bytes(img)
