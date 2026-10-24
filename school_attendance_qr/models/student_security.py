from odoo import fields, models


class SchoolStudentWebAuthn(models.Model):
    """Clé d'appareil (passkey) de l'étudiant : remplace, pour l'action de
    confirmation, le simple identifiant stocké dans le navigateur par une
    preuve cryptographique liée au déverrouillage du téléphone."""
    _inherit = 'school.student'

    webauthn_credential_id = fields.Char(readonly=True, copy=False)
    webauthn_public_key = fields.Char(readonly=True, copy=False)
    webauthn_sign_count = fields.Integer(readonly=True, default=0, copy=False)
    webauthn_registered_at = fields.Datetime(readonly=True, copy=False)

    def action_reset_device(self):
        """Réinitialise aussi la clé d'appareil (changement de téléphone)."""
        res = super().action_reset_device()
        self.write({
            'webauthn_credential_id': False, 'webauthn_public_key': False,
            'webauthn_sign_count': 0, 'webauthn_registered_at': False,
        })
        return res
