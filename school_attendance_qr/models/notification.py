"""Notifications : une liste consultable dans le portail (« Mes notifications »)
et, si l'utilisateur l'a activé, une notification push sur son téléphone,
même application fermée (norme Web Push, sans compte Firebase ni frais).

Les notifications de sécurité ne peuvent pas être désactivées ; les rappels et
les résultats, si."""
import base64
import json
import logging

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

try:
    from py_vapid import Vapid02
    from pywebpush import WebPushException, webpush
except ImportError:  # paquet optionnel : sans lui, seule la liste dans le portail fonctionne
    webpush = None

CATEGORIES = [
    ('reminder', 'Rappels (cours, échéances)'),
    ('result', 'Résultats (absences, notes, emploi du temps)'),
    ('summary', 'Synthèses périodiques'),
    ('admin', 'À traiter (personnel)'),
    ('security', 'Sécurité'),
]
# Préférence correspondante sur res.users ; « security » est toujours envoyée.
PREF_FIELD = {'reminder': 'school_notify_reminders', 'result': 'school_notify_results',
              'summary': 'school_notify_summaries', 'admin': 'school_notify_admin'}


def _b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()


class ResUsersNotifyPrefs(models.Model):
    _inherit = 'res.users'

    school_notify_reminders = fields.Boolean(default=True, string="Recevoir les rappels")
    school_notify_results = fields.Boolean(default=True, string="Recevoir les résultats")
    school_notify_summaries = fields.Boolean(default=True, string="Recevoir les synthèses")
    school_notify_admin = fields.Boolean(default=True, string="Recevoir les nouvelles tâches « À traiter »")

    @property
    def SELF_WRITEABLE_FIELDS(self):
        return super().SELF_WRITEABLE_FIELDS + list(PREF_FIELD.values())


class SchoolPushSubscription(models.Model):
    """Un téléphone (ou navigateur) abonné aux notifications push."""
    _name = 'school.push.subscription'
    _description = 'Abonnement aux notifications push'

    user_id = fields.Many2one('res.users', required=True, ondelete='cascade', index=True)
    endpoint = fields.Char(required=True)
    p256dh = fields.Char(required=True)
    auth = fields.Char(required=True)
    user_agent = fields.Char()
    failures = fields.Integer(default=0)

    _sql_constraints = [('endpoint_uniq', 'unique(endpoint)', "Cet appareil est déjà abonné.")]

    @api.model
    def subscribe(self, user, subscription, user_agent=''):
        keys = subscription.get('keys') or {}
        vals = {'user_id': user.id, 'endpoint': subscription['endpoint'], 'p256dh': keys.get('p256dh'),
                'auth': keys.get('auth'), 'user_agent': (user_agent or '')[:250], 'failures': 0}
        existing = self.sudo().search([('endpoint', '=', vals['endpoint'])], limit=1)
        if existing:
            existing.write(vals)
            return existing
        return self.sudo().create(vals)

    # ----------------------------------------------------------- clés VAPID
    @api.model
    def _vapid_keys(self):
        """Paire de clés du serveur pour signer les envois push, créée une
        fois pour toutes et propre à chaque école (base de données)."""
        ICP = self.env['ir.config_parameter'].sudo()
        pem = ICP.get_param('school_attendance_qr.vapid_private_pem')
        if not pem:
            key = ec.generate_private_key(ec.SECP256R1())
            pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                    serialization.NoEncryption()).decode()
            ICP.set_param('school_attendance_qr.vapid_private_pem', pem)
        key = serialization.load_pem_private_key(pem.encode(), password=None)
        public = key.public_key().public_bytes(serialization.Encoding.X962,
                                               serialization.PublicFormat.UncompressedPoint)
        return pem, _b64url(public)

    @api.model
    def vapid_public_key(self):
        return self._vapid_keys()[1]


class SchoolNotification(models.Model):
    _name = 'school.notification'
    _description = 'Notification'
    _order = 'id desc'

    user_id = fields.Many2one('res.users', required=True, ondelete='cascade', index=True)
    title = fields.Char(required=True)
    body = fields.Text()
    url = fields.Char(default='/presence')
    category = fields.Selection(CATEGORIES, default='result', required=True)
    is_read = fields.Boolean(default=False)

    @api.model
    def notify(self, users, title, body='', url='/presence', category='result'):
        """Point d'entrée unique : enregistre la notification pour chaque
        utilisateur qui l'accepte, et l'envoie en push APRÈS l'enregistrement
        définitif en base (jamais pour une action finalement annulée)."""
        users = users.sudo().filtered('active')
        pref = PREF_FIELD.get(category)
        if pref:
            users = users.filtered(pref)
        if not users:
            return self.browse()
        notes = self.sudo().create([{'user_id': u.id, 'title': title, 'body': body, 'url': url,
                                     'category': category} for u in users])
        if webpush:
            subs = self.env['school.push.subscription'].sudo().search([('user_id', 'in', users.ids)])
            if subs:
                pem, _pub = self.env['school.push.subscription']._vapid_keys()
                payload = json.dumps({'title': title, 'body': body, 'url': url})
                targets = [(s.id, {'endpoint': s.endpoint, 'keys': {'p256dh': s.p256dh, 'auth': s.auth}})
                           for s in subs]
                contact = self.env.company.email or 'contact@presence.bj'
                dbname = self.env.cr.dbname
                self.env.cr.postcommit.add(lambda: self._send_push(dbname, pem, contact, payload, targets))
        return notes

    @api.model
    def _send_push(self, dbname, pem, contact, payload, targets):
        vapid = Vapid02.from_pem(pem.encode())
        dead = []
        for sub_id, info in targets:
            try:
                webpush(info, data=payload, vapid_private_key=vapid,
                        vapid_claims={'sub': f'mailto:{contact}'}, timeout=10, ttl=86400)
            except WebPushException as e:
                status = getattr(e.response, 'status_code', None)
                if status in (404, 410):  # abonnement expiré (application désinstallée, etc.)
                    dead.append(sub_id)
                _logger.info("Push refusé (%s) pour l'abonnement %s", status, sub_id)
            except Exception:
                _logger.exception("Échec d'envoi push")
        if dead:
            from odoo.modules.registry import Registry
            with Registry(dbname).cursor() as cr:
                api.Environment(cr, 1, {})['school.push.subscription'].browse(dead).unlink()

    # ------------------------------------------------- groupes de destinataires
    @api.model
    def users_of_group(self, xmlid):
        # Odoo ajoute automatiquement les membres d'un groupe aux groupes qu'il implique
        group = self.env.ref(xmlid, raise_if_not_found=False)
        return group.sudo().users if group else self.env['res.users']
