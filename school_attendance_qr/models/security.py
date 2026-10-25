import logging

from odoo import SUPERUSER_ID, api, fields, models
from odoo.exceptions import AccessDenied

from .helpers import icp_int

_logger = logging.getLogger(__name__)


class ResUsersSchoolSecurity(models.Model):
    """Compte les échecs de connexion successifs : au-delà du seuil (5 par
    défaut), l'étudiant est signalé à la direction dans « À traiter ».
    Odoo bloque déjà en plus les tentatives pendant un court délai."""
    _inherit = 'res.users'

    school_failed_logins = fields.Integer(readonly=True, copy=False, string="Échecs de connexion successifs")

    @classmethod
    def _login(cls, db, credential, user_agent_env):
        try:
            return super()._login(db, credential, user_agent_env)
        except AccessDenied:
            if credential.get('type') == 'password' and credential.get('login'):
                cls._school_register_failed_login(credential['login'])
            raise

    def _check_credentials(self, credential, env):
        auth_info = super()._check_credentials(credential, env)
        if self.school_failed_logins and credential.get('type') == 'password':
            self.sudo().school_failed_logins = 0
        return auth_info

    @classmethod
    def _school_register_failed_login(cls, login):
        """Appelé une fois la transaction de connexion annulée (l'échec
        l'annule) : le compteur est écrit dans une nouvelle transaction,
        sinon il ne serait jamais conservé."""
        try:
            with cls.pool.cursor() as cr:
                env = api.Environment(cr, SUPERUSER_ID, {})
                user = env['res.users'].search(env['res.users']._get_login_domain(login), limit=1)
                if not user:
                    return
                count = user.school_failed_logins + 1
                user.write({'school_failed_logins': count})
                limit = icp_int(env, 'login_alert_attempts', 5)
                student = env['school.student'].search([('user_id', '=', user.id)], limit=1)
                if student and count == limit:
                    student.write({'account_flagged': True})
                    env['school.attendance.task'].create_unique(
                        'login_failures', student, f"Compte signalé (connexions échouées) : {student.name}",
                        f"{count} tentatives de connexion échouées d'affilée sur ce compte. Vérifiez auprès de "
                        "l'étudiant ; s'il a oublié son mot de passe, réinitialisez-le.")
                    env['school.audit.log'].log('login_failures', f"{count} échecs de connexion successifs.",
                                                student=student)
        except Exception:
            _logger.exception("Impossible d'enregistrer l'échec de connexion")


class SchoolStudentAccountSecurity(models.Model):
    _inherit = 'school.student'

    must_change_password = fields.Boolean(
        default=True, copy=False, string="Doit changer son mot de passe",
        help="Le mot de passe de départ est le matricule, que d'autres peuvent connaître : "
             "l'étudiant doit en choisir un nouveau à sa première connexion.")
    account_flagged = fields.Boolean(readonly=True, copy=False, string="Compte signalé",
                                     help="Trop de tentatives de connexion échouées d'affilée.")
    failed_logins = fields.Integer(related='user_id.school_failed_logins', string="Échecs de connexion")

    def action_reset_password(self):
        res = super().action_reset_password()
        for student in self:
            student.user_id.sudo().school_failed_logins = 0
            self.env['school.audit.log'].log('password_reset', "Mot de passe remis au matricule.", student=student)
        self.write({'must_change_password': True, 'account_flagged': False})
        return res

    def action_reset_device(self):
        res = super().action_reset_device()
        for student in self:
            self.env['school.audit.log'].log('device_reset', "Appareil et clé d'appareil réinitialisés.",
                                             student=student)
        return res
