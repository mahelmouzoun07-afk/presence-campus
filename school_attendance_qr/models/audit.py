import hashlib
import json

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .helpers import client_ip

AUDIT_EVENTS = [
    ('presence', 'Présence confirmée'),
    ('presence_refused', 'Présence refusée'),
    ('presence_relayed', 'Présence relayée par un responsable'),
    ('presence_offline', 'Présence hors ligne synchronisée'),
    ('headcount', 'Comptage des têtes'),
    ('fraud', 'Anomalie de sécurité détectée'),
    ('device_reset', 'Appareil réinitialisé'),
    ('password_reset', 'Mot de passe réinitialisé par le secrétariat'),
    ('password_changed', "Mot de passe changé par l'étudiant"),
    ('login_failures', 'Échecs de connexion répétés'),
    ('payment', 'Paiement de scolarité'),
    ('grade', 'Note modifiée après publication'),
    ('other', 'Autre'),
]


class SchoolAuditLog(models.Model):
    """Journal d'audit non modifiable : une ligne par action sensible.

    Chaque ligne contient l'empreinte (SHA-256) de la ligne précédente, comme
    les maillons d'une chaîne : modifier ou supprimer une ligne directement
    dans la base casse la chaîne, et le bouton « Vérifier l'intégrité » le
    détecte. Depuis Odoo, personne (même un administrateur) ne peut modifier
    ni supprimer une ligne."""
    _name = 'school.audit.log'
    _description = "Journal d'audit"
    _order = 'id desc'

    event_type = fields.Selection(AUDIT_EVENTS, required=True, readonly=True, string="Événement")
    description = fields.Text(readonly=True)
    user_id = fields.Many2one('res.users', readonly=True, string="Fait par", ondelete='set null')
    student_id = fields.Many2one('school.student', readonly=True, string="Étudiant", ondelete='set null')
    student_label = fields.Char(readonly=True, string="Étudiant (au moment des faits)")
    res_model = fields.Char(readonly=True, string="Objet")
    res_id = fields.Integer(readonly=True, string="N° de l'objet")
    ip_address = fields.Char(readonly=True, string="Adresse IP")
    logged_at = fields.Datetime(readonly=True, string="Date")
    log_hash = fields.Char(readonly=True, string="Empreinte", index=True)
    previous_hash = fields.Char(readonly=True, string="Empreinte précédente")

    @staticmethod
    def _digest(previous_hash, vals, logged_at):
        payload = json.dumps({
            'prev': previous_hash or '', 'date': str(logged_at),
            'event': vals.get('event_type'), 'desc': vals.get('description') or '',
            'user': vals.get('user_id') or 0, 'student': vals.get('student_label') or '',
            'model': vals.get('res_model') or '', 'res_id': vals.get('res_id') or 0,
            'ip': vals.get('ip_address') or '',
        }, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(payload.encode('utf-8')).hexdigest()

    @api.model_create_multi
    def create(self, vals_list):
        # Verrou de transaction : deux écritures simultanées ne doivent pas
        # s'accrocher au même maillon précédent (seule exception à la règle
        # « pas de SQL brut » : l'ORM n'offre pas de verrou consultatif).
        self.env.cr.execute("SELECT pg_advisory_xact_lock(hashtext('school_audit_log'))")
        last = self.sudo().search([], order='id desc', limit=1)
        previous = last.log_hash or ''
        now = fields.Datetime.now()
        for vals in vals_list:
            vals['logged_at'] = now
            vals['previous_hash'] = previous
            vals['log_hash'] = previous = self._digest(previous, vals, now)
        return super().create(vals_list)

    def write(self, vals):
        raise UserError(_("Le journal d'audit ne peut pas être modifié."))

    def unlink(self):
        raise UserError(_("Le journal d'audit ne peut pas être supprimé."))

    @api.model
    def log(self, event_type, description, student=None, record=None):
        """Point d'entrée unique pour écrire dans le journal."""
        student = student or self.env['school.student']
        return self.sudo().create({
            'event_type': event_type, 'description': description,
            'user_id': self.env.uid, 'student_id': student.id or False,
            'student_label': f"{student.name} ({student.matricule})" if student else False,
            'res_model': record._name if record else False, 'res_id': record.id if record else 0,
            'ip_address': client_ip(),
        })

    @api.model
    def check_integrity(self):
        """Recalcule toute la chaîne. Renvoie (True, nb) ou (False, id_cassé)."""
        previous = ''
        count = 0
        for entry in self.sudo().search([], order='id asc'):
            vals = {
                'event_type': entry.event_type, 'description': entry.description,
                'user_id': entry.user_id.id, 'student_label': entry.student_label,
                'res_model': entry.res_model, 'res_id': entry.res_id, 'ip_address': entry.ip_address,
            }
            if entry.previous_hash != previous or entry.log_hash != self._digest(previous, vals, entry.logged_at):
                return False, entry.id
            previous = entry.log_hash
            count += 1
        return True, count

    def action_check_integrity(self):
        ok, info = self.check_integrity()
        if ok:
            params = {'title': "Journal intact", 'type': 'success',
                      'message': f"{info} ligne(s) vérifiée(s) : aucune modification détectée."}
        else:
            params = {'title': "Journal altéré !", 'type': 'danger', 'sticky': True,
                      'message': f"La chaîne est rompue à la ligne n° {info} : le journal a été modifié "
                                 "en dehors d'Odoo (directement dans la base de données)."}
        return {'type': 'ir.actions.client', 'tag': 'display_notification', 'params': params}
