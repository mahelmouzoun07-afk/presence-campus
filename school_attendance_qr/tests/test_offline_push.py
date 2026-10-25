import base64
import hashlib
import json
from datetime import timedelta
from types import SimpleNamespace

import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

from odoo import fields
from odoo.tests import HttpCase, tagged

from .common import SchoolCase

HOST = 'presence.test'
ORIGIN = f'https://{HOST}'


def b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()


class FakeAuthenticator:
    """Simule l'empreinte d'un téléphone : une vraie clé EC qui signe les
    défis WebAuthn, comme le ferait le capteur du téléphone."""

    def __init__(self):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = b'cle-test-0001'
        self.count = 0

    def cose_public_key(self):
        numbers = self.key.public_key().public_numbers()
        return cbor2.dumps({1: 2, 3: -7, -1: 1, -2: numbers.x.to_bytes(32, 'big'), -3: numbers.y.to_bytes(32, 'big')})

    def register_on(self, student):
        student.write({'webauthn_credential_id': b64url(self.credential_id),
                       'webauthn_public_key': base64.b64encode(self.cose_public_key()).decode(),
                       'webauthn_sign_count': 0})

    def sign(self, challenge_b64url):
        self.count += 1
        client_data = json.dumps({'type': 'webauthn.get', 'challenge': challenge_b64url,
                                  'origin': ORIGIN, 'crossOrigin': False}).encode()
        auth_data = hashlib.sha256(HOST.encode()).digest() + bytes([0x05]) + self.count.to_bytes(4, 'big')
        signature = self.key.sign(auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256()))
        return {'id': b64url(self.credential_id), 'rawId': b64url(self.credential_id), 'type': 'public-key',
                'response': {'clientDataJSON': b64url(client_data), 'authenticatorData': b64url(auth_data),
                             'signature': b64url(signature)}}


class TestOfflineConfirmation(SchoolCase):

    def setUp(self):
        super().setUp()
        self.phone = FakeAuthenticator()
        self.phone.register_on(self.student)
        self.httprequest = SimpleNamespace(host=HOST, host_url=ORIGIN + '/')
        self.Record = self.env['school.attendance.record']

    def _item(self, challenge, captured=None, lat=6.3703, lon=2.3912):
        captured = captured or fields.Datetime.now()
        return {'key': 'k1', 'challenge_id': challenge.id, 'captured_at': captured.isoformat() + 'Z',
                'latitude': lat, 'longitude': lon, 'accuracy': 8, 'device_fingerprint': f'dev-{self.student.id}',
                'credential': self.phone.sign(challenge.challenge)}

    def test_challenges_are_topped_up_and_limited(self):
        first = self.env['school.offline.challenge'].top_up(self.student)
        self.assertEqual(len(first), 3)
        self.assertEqual(self.env['school.offline.challenge'].top_up(self.student), first)

    def test_offline_confirmation_is_verified_and_marked(self):
        challenge = self.env['school.offline.challenge'].top_up(self.student)[0]
        res = self.Record.register_offline(self.student, self._item(challenge), self.httprequest)
        self.assertEqual(res['phase'], 'checkin')
        self.assertEqual(res['state'], 'valid')
        record = self.session.record_ids
        self.assertEqual(record.proof_level, 'C')
        self.assertTrue(record.offline_synced_at)
        self.assertTrue(challenge.used_at)
        self.assertTrue(self.env['school.audit.log'].search_count([('event_type', '=', 'presence_offline')]))

    def test_challenge_cannot_be_replayed(self):
        challenge = self.env['school.offline.challenge'].top_up(self.student)[0]
        item = self._item(challenge)
        self.Record.register_offline(self.student, item, self.httprequest)
        with self.assertRaisesRegex(Exception, 'déjà été envoyée'):
            self.Record.register_offline(self.student, item, self.httprequest)

    def test_forged_signature_is_refused(self):
        challenge = self.env['school.offline.challenge'].top_up(self.student)[0]
        item = self._item(challenge)
        item['credential'] = FakeAuthenticator().sign(challenge.challenge)  # autre téléphone
        with self.assertRaises(Exception):
            self.Record.register_offline(self.student, item, self.httprequest)
        self.assertFalse(self.session.record_ids)

    def test_time_outside_challenge_validity_is_refused(self):
        challenge = self.env['school.offline.challenge'].top_up(self.student)[0]
        item = self._item(challenge, captured=fields.Datetime.now() - timedelta(days=2))
        with self.assertRaisesRegex(Exception, 'incohérente'):
            self.Record.register_offline(self.student, item, self.httprequest)

    def test_offline_while_campus_wifi_worked_is_flagged(self):
        third = self.env['school.student'].create({
            'nom': 'Zinsou', 'prenom': 'Eric', 'identifiant': 'eric.zinsou', 'matricule': '10000004',
            'course_ids': [(6, 0, [self.course.id])]})
        self.scan(self.student2, lat=6.37035, lon=2.39125)
        self.scan(third, lat=6.37025, lon=2.39115)
        challenge = self.env['school.offline.challenge'].top_up(self.student)[0]
        res = self.Record.register_offline(self.student, self._item(challenge), self.httprequest)
        self.assertEqual(res['state'], 'flagged')
        self.assertTrue(self.env['school.attendance.task'].search_count([('task_type', '=', 'offline_check')]))


class TestNotifications(SchoolCase):

    def test_preferences_are_respected_but_security_always_sent(self):
        Notif = self.env['school.notification']
        user = self.student.user_id
        user.school_notify_reminders = False
        self.assertFalse(Notif.notify(user, 'Rappel', category='reminder'))
        self.assertTrue(Notif.notify(user, 'Sécurité', category='security'))

    def test_course_reminder_and_absence_notifications(self):
        upcoming = self.env['school.attendance.session'].create({
            'course_id': self.course.id, 'teacher_id': self.teacher.id,
            'room_id': self.env['school.room'].create({'name': 'Salle B'}).id,
            'time_start': fields.Datetime.now() + timedelta(minutes=8), 'duration_minutes': 60})
        self.env['school.attendance.session']._cron_session_notifications()
        self.assertTrue(upcoming.reminder_sent)
        notes = self.env['school.notification'].search([('user_id', '=', self.student.user_id.id)])
        self.assertTrue(any('Algèbre' in n.title for n in notes))

        self.session.write({'time_start': fields.Datetime.now() - timedelta(hours=3)})
        self.env['school.attendance.session']._cron_session_notifications()
        self.assertTrue(self.session.end_notified)
        self.assertTrue(self.env['school.notification'].search_count([
            ('user_id', '=', self.student.user_id.id), ('title', 'ilike', 'Absence constatée')]))

    def test_new_task_notifies_admins(self):
        admin = self.env.ref('base.user_admin')
        self.env['school.attendance.task'].create_unique('gps_identical', self.student, 'Test GPS')
        self.assertTrue(self.env['school.notification'].search_count([
            ('user_id', '=', admin.id), ('category', '=', 'security')]))


@tagged('post_install', '-at_install')
class TestPwaRoutes(HttpCase):

    def test_manifest_icon_worker_and_ping(self):
        manifest = self.url_open('/presence/manifest.webmanifest')
        self.assertEqual(manifest.status_code, 200)
        data = manifest.json()
        self.assertEqual(data['start_url'], '/presence')
        self.assertEqual(data['display'], 'standalone')
        icon = self.url_open('/presence/icone/192.png')
        self.assertEqual(icon.headers['Content-Type'], 'image/png')
        worker = self.url_open('/presence/sw.js')
        self.assertEqual(worker.headers.get('Service-Worker-Allowed'), '/presence')
        self.assertIn('notificationclick', worker.text)
        self.assertTrue(self.url_open('/presence/ping').json()['ok'])
        self.assertEqual(self.url_open('/presence/hors-ligne').status_code, 200)
