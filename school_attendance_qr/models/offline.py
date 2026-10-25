"""Confirmation hors ligne (panne du Wi-Fi de l'école).

Principe : pendant qu'il est en ligne, le téléphone précharge quelques
« défis » à usage unique. En cas de vraie panne, l'empreinte signe l'un de ces
défis SUR le téléphone (aucun réseau n'est nécessaire pour ça), la confirmation
est mise en file d'attente, puis envoyée dès que n'importe quelle connexion
revient. Le serveur vérifie alors la signature, l'heure et la position, et la
présence apparaît avec le badge « Validée hors ligne » (niveau de preuve C)."""
import base64
import json
import secrets
from datetime import datetime, timedelta, timezone

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from . import webauthn_helper as wa
from .helpers import icp_int


def _b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()


class SchoolOfflineChallenge(models.Model):
    _name = 'school.offline.challenge'
    _description = 'Défi préchargé pour confirmation hors ligne'
    _order = 'issued_at'

    student_id = fields.Many2one('school.student', required=True, ondelete='cascade', index=True)
    challenge = fields.Char(required=True, index=True)
    issued_at = fields.Datetime(required=True, default=fields.Datetime.now)
    expires_at = fields.Datetime(required=True)
    used_at = fields.Datetime()

    @api.model
    def top_up(self, student):
        """Complète la réserve du téléphone : au plus N défis valides (3 par
        défaut), chacun utilisable une seule fois et pendant 24 h."""
        now = fields.Datetime.now()
        self.sudo().search([('student_id', '=', student.id), ('expires_at', '<', now - timedelta(days=7))]).unlink()
        valid = self.sudo().search([('student_id', '=', student.id), ('used_at', '=', False),
                                    ('expires_at', '>', now)])
        wanted = icp_int(self.env, 'offline_max', 3) - len(valid)
        hours = icp_int(self.env, 'offline_validity_hours', 24)
        if wanted > 0:
            valid |= self.sudo().create([{
                'student_id': student.id, 'challenge': _b64url(secrets.token_bytes(32)),
                'issued_at': now, 'expires_at': now + timedelta(hours=hours)} for _i in range(wanted)])
        return valid


class SchoolAttendanceRecordOffline(models.Model):
    _inherit = 'school.attendance.record'

    offline_captured_at = fields.Datetime(readonly=True, string="Confirmée hors ligne à")
    offline_synced_at = fields.Datetime(readonly=True, string="Synchronisée le")

    @api.model
    def _find_session_at(self, student, at):
        """La séance de l'étudiant dont une fenêtre (entrée ou sortie) était
        ouverte à l'instant `at`."""
        sessions = self.env['school.attendance.session'].sudo().search([
            ('course_id', 'in', student.sudo().course_ids.ids),
            ('time_start', '<=', at), ('time_start', '>=', at - timedelta(hours=8))], order='time_start desc')
        for session in sessions:
            if session.is_within_checkin_window(at):
                return session, 'checkin'
            if session.is_within_checkout_window(at):
                return session, 'checkout'
        return sessions.browse(), False

    @api.model
    def register_offline(self, student, item, httprequest):
        """Vérifie et enregistre UNE confirmation faite hors ligne."""
        Challenge = self.env['school.offline.challenge'].sudo()
        challenge = Challenge.search([('id', '=', int(item.get('challenge_id') or 0)),
                                      ('student_id', '=', student.id)], limit=1)
        if not challenge:
            raise ValidationError(_("Défi hors ligne inconnu."))
        if challenge.used_at:
            raise ValidationError(_("Cette confirmation hors ligne a déjà été envoyée."))
        try:
            captured = datetime.fromisoformat(str(item['captured_at']).replace('Z', '+00:00'))
            captured = captured.astimezone(timezone.utc).replace(tzinfo=None, microsecond=0)
        except (KeyError, ValueError):
            raise ValidationError(_("Heure de confirmation illisible."))
        now = fields.Datetime.now()
        # L'horloge du téléphone n'est pas fiable : l'heure annoncée doit tomber
        # entre la création du défi et sa date d'expiration, et pas dans le futur.
        if not (challenge.issued_at - timedelta(minutes=2) <= captured <= min(challenge.expires_at, now)
                + timedelta(minutes=2)):
            raise ValidationError(_("Heure de confirmation incohérente avec la validité du défi."))

        raw_challenge = base64.urlsafe_b64decode(challenge.challenge + '=' * (-len(challenge.challenge) % 4))
        ok, error = wa.verify_assertion(httprequest, student, json.dumps(item.get('credential') or {}), raw_challenge)
        if not ok:
            raise ValidationError(error)
        challenge.used_at = now

        session, phase = self._find_session_at(student, captured)
        if not session:
            raise ValidationError(_("Aucun de vos cours n'était ouvert à la confirmation à cette heure-là."))
        if student not in session.course_id.student_ids:
            raise ValidationError(_("Vous n'êtes pas inscrit à ce cours."))
        payment_reason = self._payment_policy_check(student)
        lat, lon = float(item.get('latitude') or 0), float(item.get('longitude') or 0)
        accuracy = max(float(item.get('accuracy') or 0), 0.0)
        fingerprint = item.get('device_fingerprint') or 'hors-ligne'
        self._check_device_binding(student, fingerprint)
        distance, state, reason = self._evaluate_distance(session.room_id, lat, lon, accuracy)
        if state != 'rejected' and fingerprint != student.device_fingerprint:
            self._log_device_attempt(student)
            raise ValidationError(_("Ce compte est associé à un autre appareil."))
        if payment_reason and state != 'rejected':
            state, reason = 'flagged', self._join_reasons(reason, payment_reason)

        record = self.sudo().search([('session_id', '=', session.id), ('student_id', '=', student.id)], limit=1)
        if phase == 'checkin':
            if record and record.state != 'rejected':
                raise ValidationError(_("Entrée déjà enregistrée pour ce cours."))
            conflict = self._find_conflicting_session(session, student, at=captured)
            if conflict:
                raise ValidationError(_("Vous étiez programmé(e) ailleurs à cette heure-là (« %s »).",
                                        conflict.course_id.name))
            vals = {'session_id': session.id, 'student_id': student.id, 'scan_datetime': captured,
                    'device_fingerprint': fingerprint, 'latitude': lat, 'longitude': lon, 'accuracy': accuracy,
                    'distance_meters': distance, 'state': state, 'flag_reason': reason, 'proof_level': 'C',
                    'offline_captured_at': captured, 'offline_synced_at': now}
            if record:
                record.write(vals)
            else:
                record = self.sudo().create(vals)
        else:
            if not record or record.state == 'rejected':
                raise ValidationError(_("Aucune entrée valide pour ce cours : la sortie ne peut pas être enregistrée."))
            if record.checkout_state != 'not_done':
                raise ValidationError(_("Sortie déjà confirmée pour ce cours."))
            record.write({'checkout_scan_datetime': captured, 'checkout_latitude': lat, 'checkout_longitude': lon,
                          'checkout_distance_meters': distance, 'checkout_accuracy': accuracy,
                          'checkout_state': state, 'checkout_flag_reason': reason, 'proof_level': 'C',
                          'offline_captured_at': captured, 'offline_synced_at': now})
        record._check_cross_student_device_conflict(phase)
        record._run_fraud_detections(phase)
        record._check_campus_wifi_was_down(phase, captured)
        self.env['school.audit.log'].log(
            'presence_offline', f"{'Entrée' if phase == 'checkin' else 'Sortie'} « {session.course_id.name} » "
                                f"confirmée hors ligne à {captured} (UTC), synchronisée à {now}.",
            student=student, record=record)
        return {'phase': phase, 'state': record.state if phase == 'checkin' else record.checkout_state,
                'course_name': session.course_id.name}

    def _check_campus_wifi_was_down(self, phase, captured):
        """Si d'autres étudiants confirmaient EN LIGNE dans la même séance au
        même moment, le Wi-Fi de l'école fonctionnait : la confirmation hors
        ligne est alors suspecte (contournement du contrôle Wi-Fi)."""
        window = timedelta(minutes=5)
        for rec in self:
            online = self.sudo().search_count([
                ('session_id', '=', rec.session_id.id), ('id', '!=', rec.id), ('proof_level', '=', 'A'),
                ('scan_datetime', '>=', captured - window), ('scan_datetime', '<=', captured + window)])
            if online >= 2:
                reason = "Hors ligne alors que le Wi-Fi de l'école fonctionnait pour d'autres"
                rec._flag(phase, reason)
                self.env['school.attendance.task'].create_unique(
                    'offline_check', rec.student_id, f"Hors ligne suspect : {rec.student_id.name}",
                    f"{online} autres étudiants ont confirmé en ligne au même moment.", record=rec)
