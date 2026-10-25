from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    school_logo = fields.Binary(related='company_id.school_logo', readonly=False)
    school_timezone = fields.Char(string="Fuseau horaire de l'établissement", default='Africa/Porto-Novo',
                                  config_parameter='school_attendance_qr.timezone')
    school_campus_ip_ranges = fields.Char(string="Réseaux autorisés (Wi-Fi de l'école)",
                                          config_parameter='school_attendance_qr.campus_ip_ranges')
    school_payment_policy = fields.Selection([
        ('off', "Ne rien faire (par défaut)"),
        ('flag', "Signaler : la présence est enregistrée mais mise « à vérifier »"),
        ('block', "Bloquer : la présence n'est pas enregistrée tant que la scolarité n'est pas à jour"),
    ], string="Étudiants avec scolarité impayée", default='off',
        config_parameter='school_attendance_qr.payment_policy')
    school_payment_include_partial = fields.Boolean(
        string="Inclure aussi les paiements partiels",
        config_parameter='school_attendance_qr.payment_include_partial')
    school_alert_min_sessions = fields.Integer(
        string="Séances minimum avant d'alerter", default=3,
        config_parameter='school_attendance_qr.alert_min_sessions')
    school_alert_rate = fields.Integer(
        string="Alerter sous ce taux de présence (%)", default=70,
        config_parameter='school_attendance_qr.alert_rate')
    school_login_alert_attempts = fields.Integer(
        string="Signaler après (échecs de connexion)", default=5,
        config_parameter='school_attendance_qr.login_alert_attempts')
    school_cluster_seconds = fields.Integer(
        string="Fenêtre des confirmations groupées (s)", default=20,
        config_parameter='school_attendance_qr.cluster_seconds')
    school_cluster_min = fields.Integer(
        string="Nombre de confirmations groupées suspect", default=3,
        config_parameter='school_attendance_qr.cluster_min')
    school_max_speed_kmh = fields.Integer(
        string="Vitesse maximale crédible (km/h)", default=50,
        config_parameter='school_attendance_qr.max_speed_kmh')
    school_require_2fa = fields.Boolean(
        string="Double authentification obligatoire pour le personnel",
        compute='_compute_school_require_2fa', inverse='_inverse_school_require_2fa')
    school_alert_send_email = fields.Boolean(
        string="Envoyer aussi un e-mail à l'étudiant",
        config_parameter='school_attendance_qr.alert_send_email')

    def _compute_school_require_2fa(self):
        policy = self.env['ir.config_parameter'].sudo().get_param('auth_totp.policy')
        for rec in self:
            rec.school_require_2fa = policy in ('employee_required', 'all_required')

    def _inverse_school_require_2fa(self):
        # « employee_required » : tout le personnel (secrétariat, direction,
        # enseignants) doit fournir un second facteur ; les étudiants (portail)
        # ne sont pas concernés, leur preuve forte étant WebAuthn.
        for rec in self:
            self.env['ir.config_parameter'].sudo().set_param(
                'auth_totp.policy', 'employee_required' if rec.school_require_2fa else False)
