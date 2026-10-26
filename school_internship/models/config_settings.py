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
    school_internship_ping_minutes = fields.Integer(
        string="Suivi GPS : une position toutes les (min)", default=5,
        config_parameter='school_attendance_qr.internship_ping_minutes')
    school_internship_gap_minutes = fields.Integer(
        string="Suivi interrompu au-delà de (min)", default=30,
        config_parameter='school_attendance_qr.internship_gap_minutes')
    school_internship_outside_points = fields.Integer(
        string="Signaler après N positions hors du site", default=3,
        config_parameter='school_attendance_qr.internship_outside_points')
    school_internship_validation_delay_hours = fields.Integer(
        string="Alerter si le superviseur n'a pas validé après (h)", default=48,
        config_parameter='school_attendance_qr.internship_validation_delay_hours')
