from odoo import fields, models


class ResConfigSettingsInternship(models.TransientModel):
    _inherit = 'res.config.settings'

    school_internship_open_reminder_hours = fields.Integer(
        string="Rappel si la sortie n'est pas confirmée après (h)", default=14,
        config_parameter='school_attendance_qr.internship_open_reminder_hours')
    school_internship_min_hours = fields.Integer(
        string="Durée de garde minimale crédible (h)", default=1,
        config_parameter='school_attendance_qr.internship_min_hours')
    school_internship_max_hours = fields.Integer(
        string="Durée de garde maximale crédible (h)", default=30,
        config_parameter='school_attendance_qr.internship_max_hours')
    school_internship_validation_delay_hours = fields.Integer(
        string="Alerter si le superviseur n'a pas validé après (h)", default=48,
        config_parameter='school_attendance_qr.internship_validation_delay_hours')
