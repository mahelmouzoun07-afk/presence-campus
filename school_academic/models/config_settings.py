from odoo import fields, models


class ResConfigSettingsAcademic(models.TransientModel):
    _inherit = 'res.config.settings'

    school_grade_scale = fields.Integer(string="Barème des moyennes", default=20,
                                       config_parameter='school_attendance_qr.grade_scale')
    school_grade_pass_mark = fields.Float(string="Note de passage", default=10,
                                          config_parameter='school_attendance_qr.grade_pass_mark')
    school_grade_absent_policy = fields.Selection([
        ('zero', "Une absence compte 0"),
        ('exclude', "Une absence n'est pas comptée dans la moyenne"),
    ], string="Absence à une évaluation", default='zero', config_parameter='school_attendance_qr.grade_absent_policy')
    school_grade_rounding = fields.Integer(string="Décimales des moyennes", default=2,
                                           config_parameter='school_attendance_qr.grade_rounding')
    school_grade_use_coefficients = fields.Selection([
        ('True', "Pondérée par les coefficients des cours"),
        ('False', "Simple moyenne des cours"),
    ], string="Moyenne générale", default='True', config_parameter='school_attendance_qr.grade_use_coefficients')
    school_bulletin_portal = fields.Boolean(string="Bulletin téléchargeable par l'étudiant",
                                            config_parameter='school_attendance_qr.bulletin_portal')
    school_document_max_mb = fields.Integer(string="Taille maximale d'un document (Mo)", default=20,
                                            config_parameter='school_attendance_qr.document_max_mb')
