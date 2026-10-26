from odoo import fields, models


class SchoolInternshipSite(models.Model):
    """Un lieu de stage (service hospitalier). Ses champs GPS portent les
    MÊMES noms que ceux d'une salle (latitude, longitude, radius_meters) : la
    vérification de distance existante (_evaluate_distance) s'y applique telle
    quelle, sans copie de code."""
    _name = 'school.internship.site'
    _description = 'Site de stage'
    _order = 'name'

    name = fields.Char(required=True, help="Ex : CHU — Cardiologie")
    location = fields.Char(string="Établissement / adresse")
    specialty = fields.Char(string="Spécialité", help="Ex : Cardiologie, Urgences, Pédiatrie")
    latitude = fields.Float(digits=(10, 7), help="Coordonnées du service (clic droit sur Google Maps).")
    longitude = fields.Float(digits=(10, 7))
    radius_meters = fields.Integer(default=80, string="Rayon toléré (m)",
                                   help="Plus large qu'une salle : un service hospitalier s'étend souvent sur "
                                        "plusieurs étages, où le GPS est moins précis.")
    supervisor_ids = fields.Many2many('school.teacher', string="Superviseurs",
                                      help="Les enseignants / praticiens qui valident les gardes sur ce site.")
    period_ids = fields.One2many('school.internship.period', 'site_id', string="Périodes de stage")
    active = fields.Boolean(default=True)
