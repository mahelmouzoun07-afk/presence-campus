from datetime import date, timedelta
from types import SimpleNamespace

from odoo import fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import HttpCase, tagged
from odoo.tests.common import TransactionCase

from odoo.addons.school_attendance_qr.tests.test_offline_push import HOST, ORIGIN, FakeAuthenticator

CHU = (6.3654, 2.4183)        # CHU — Cardiologie
CLINIQUE = (6.4000, 2.3500)   # autre site de stage, à ~8 km


class InternshipCase(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.sup = cls.env['school.teacher'].create({'name': 'Dr Houngbo', 'email': 'dr.houngbo@chu.bj'})
        cls.sup.action_create_user()
        cls.sup.user_id.groups_id = [(4, cls.env.ref('school_internship.group_internship_supervisor').id)]
        cls.other_sup = cls.env['school.teacher'].create({'name': 'Dr Autre', 'email': 'dr.autre@chu.bj'})
        cls.site = cls.env['school.internship.site'].create({
            'name': 'CHU — Cardiologie test', 'specialty': 'Cardiologie', 'latitude': CHU[0], 'longitude': CHU[1],
            'radius_meters': 80, 'supervisor_ids': [(6, 0, [cls.sup.id])]})
        cls.other_site = cls.env['school.internship.site'].create({
            'name': 'Clinique test', 'latitude': CLINIQUE[0], 'longitude': CLINIQUE[1],
            'supervisor_ids': [(6, 0, [cls.other_sup.id])]})
        cls.student = cls.env['school.student'].create({
            'nom': 'Médecine', 'prenom': 'Yasmine', 'identifiant': 'yasmine.med', 'matricule': '80808080',
            'must_change_password': False})
        cls.period = cls.env['school.internship.period'].create({
            'student_id': cls.student.id, 'site_id': cls.site.id, 'required_hours': 100,
            'date_start': date.today() - timedelta(days=10), 'date_end': date.today() + timedelta(days=20)})
        cls.Shift = cls.env['school.internship.attendance']

    def scan(self, pos=CHU, at=None):
        return self.Shift.register_student_scan(self.student, pos[0], pos[1], f'dev-{self.student.id}', 10, at=at)

    def full_shift(self, hours=12, pos=CHU):
        self.scan(pos, at=fields.Datetime.now() - timedelta(hours=hours))
        self.scan(pos)
        return self.period.attendance_ids.sorted('id')[-1]


class TestShifts(InternshipCase):

    def test_double_validation_counts_hours(self):
        self.assertEqual(self.scan()['phase'], 'checkin')
        res = self.scan()
        self.assertEqual(res['phase'], 'checkout')
        shift = self.period.attendance_ids
        self.assertTrue(shift.student_confirmed)
        self.assertFalse(shift.is_validated)
        self.assertEqual(self.period.validated_hours, 0)

        shift = self.full_shift(hours=12)
        self.assertEqual(self.period.pending_hours, 12)
        shift.validate_by_supervisor(self.sup, rating=4, comment="Très bonne garde")
        self.assertTrue(shift.is_validated)
        self.assertEqual(shift.proof_level, 'D')
        self.assertEqual(self.period.validated_hours, 12)
        self.assertEqual(self.period.progress, 12)
        self.assertEqual(shift.evaluation_ids.rating, '4')
        self.assertEqual(self.student.internship_hours, 12)
        with self.assertRaises(ValidationError):
            shift.validate_by_supervisor(self.sup)  # déjà validée

    def test_only_site_supervisor_can_validate(self):
        shift = self.full_shift()
        with self.assertRaisesRegex(ValidationError, 'superviseur'):
            shift.validate_by_supervisor(self.other_sup)

    def test_scan_at_another_site_is_flagged(self):
        res = self.scan(pos=CLINIQUE)
        self.assertEqual(res['state'], 'flagged')
        self.assertIn('Clinique test', res['flag_reason'])
        self.assertTrue(self.env['school.attendance.task'].search_count([('task_type', '=', 'internship_site')]))

    def test_scan_far_from_any_site_is_rejected(self):
        res = self.scan(pos=(9.34, 2.63))
        self.assertEqual(res['state'], 'rejected')
        self.assertFalse(self.period.open_shift())

    def test_implausible_duration_is_flagged(self):
        shift = self.full_shift(hours=36)
        self.assertIn('Garde de 36', shift.flag_reason)
        self.assertTrue(self.env['school.attendance.task'].search_count([('task_type', '=', 'internship_duration')]))

    def test_no_current_period(self):
        self.period.status = 'validated'
        with self.assertRaisesRegex(ValidationError, 'Aucune période'):
            self.scan()

    def test_forgotten_checkout_and_missing_validation_crons(self):
        self.scan(at=fields.Datetime.now() - timedelta(hours=15))
        self.Shift._cron_internship_checks()
        shift = self.period.attendance_ids
        self.assertTrue(shift.reminder_sent)
        self.assertTrue(self.env['school.notification'].search_count([
            ('user_id', '=', self.student.user_id.id), ('title', 'ilike', 'fin de votre garde')]))
        self.assertTrue(self.env['school.attendance.task'].search_count([('task_type', '=', 'internship_open')]))
        self.scan()
        shift.sudo().checkout_time = fields.Datetime.now() - timedelta(hours=50)
        self.Shift._cron_internship_checks()
        self.assertTrue(self.env['school.attendance.task'].search_count([('task_type', '=', 'internship_unvalidated')]))
        shift.sudo().write({'checkout_time': fields.Datetime.now()})
        shift.validate_by_supervisor(self.sup)
        self.assertFalse(self.env['school.attendance.task'].search_count([
            ('task_type', '=', 'internship_unvalidated'), ('state', '=', 'open')]))

    def test_only_admin_adjusts_hours(self):
        with self.assertRaises(AccessError):
            self.period.with_user(self.sup.user_id).sudo(False).write({'adjusted_hours': 5})
        self.period.write({'adjusted_hours': 5})
        self.assertEqual(self.period.validated_hours, 5)
        self.assertTrue(self.env['school.audit.log'].search_count([
            ('event_type', '=', 'internship'), ('description', 'ilike', 'Ajustement manuel')]))

    def test_supervisor_sees_only_own_sites(self):
        self.full_shift()
        self.env['school.internship.period'].create({
            'student_id': self.student.id, 'site_id': self.other_site.id, 'required_hours': 10,
            'date_start': date.today(), 'date_end': date.today()})
        visible = self.env['school.internship.period'].with_user(self.sup.user_id).search([])
        self.assertEqual(visible.mapped('site_id'), self.site)
        with self.assertRaises(AccessError):
            self.Shift.with_user(self.sup.user_id).search([]).write({'supervisor_confirmed': True})

    def test_hours_statement_pdf(self):
        self.full_shift(hours=10).validate_by_supervisor(self.sup)
        self.period.action_validate()
        cert = self.env['school.attendance.certificate'].search([('internship_period_id', '=', self.period.id)])
        self.assertEqual(cert.certificate_type, 'internship_hours')
        self.assertTrue(cert.pdf_filename.startswith('Releve-stage'))
        self.assertEqual(cert.attended, 10)
        self.assertTrue(cert.pdf_file)


class TestInternshipOffline(InternshipCase):

    def setUp(self):
        super().setUp()
        self.phone = FakeAuthenticator()
        self.phone.register_on(self.student)
        self.sup_phone = FakeAuthenticator()
        self.sup_phone.credential_id = b'cle-superviseur'
        self.sup_phone.register_on(self.sup)
        self.req = SimpleNamespace(host=HOST, host_url=ORIGIN + '/')
        self.Record = self.env['school.attendance.record']
        self.Challenge = self.env['school.offline.challenge']

    def _item(self, holder, phone, extra, captured=None):
        challenge = self.Challenge.top_up(holder)[0]
        if captured:  # défi préchargé AVANT la garde, comme sur un vrai téléphone
            challenge.issued_at = captured - timedelta(minutes=30)
        item = {'key': f'k{challenge.id}', 'challenge_id': challenge.id,
                'captured_at': (captured or fields.Datetime.now()).isoformat() + 'Z',
                'credential': phone.sign(challenge.challenge)}
        item.update(extra)
        return item

    def test_offline_shift_and_offline_supervisor_validation(self):
        gps = {'target': 'internship', 'latitude': CHU[0], 'longitude': CHU[1], 'accuracy': 10,
               'device_fingerprint': f'dev-{self.student.id}'}
        start = fields.Datetime.now() - timedelta(hours=8)
        res = self.Record.sync_offline_item(self.student.user_id, self._item(self.student, self.phone, gps, start),
                                            self.req)
        self.assertEqual(res['phase'], 'checkin')
        res = self.Record.sync_offline_item(self.student.user_id, self._item(self.student, self.phone, gps), self.req)
        self.assertEqual(res['phase'], 'checkout')
        shift = self.period.attendance_ids
        self.assertTrue(shift.offline)
        self.assertEqual(shift.proof_level, 'C')
        self.assertAlmostEqual(shift.duration_hours, 8, delta=0.1)

        self.assertEqual(self.Challenge.holder_for_user(self.sup.user_id), self.sup)
        item = self._item(self.sup, self.sup_phone, {'target': 'internship_validation', 'attendance_id': shift.id,
                                                     'rating': 5, 'comment': 'Bloc opératoire'})
        self.Record.sync_offline_item(self.sup.user_id, item, self.req)
        self.assertTrue(shift.is_validated)
        self.assertEqual(shift.proof_level, 'D')
        self.assertAlmostEqual(self.period.validated_hours, 8, delta=0.1)

    def test_student_key_cannot_validate_as_supervisor(self):
        self.full_shift()
        shift = self.period.attendance_ids
        item = self._item(self.sup, self.phone, {'target': 'internship_validation', 'attendance_id': shift.id})
        with self.assertRaises(ValidationError):
            self.Record.sync_offline_item(self.sup.user_id, item, self.req)
        self.assertFalse(shift.supervisor_confirmed)

    def test_course_offline_flow_still_works(self):
        """Compatibilité : une file hors ligne sans cible reste traitée comme un cours."""
        item = self._item(self.student, self.phone, {'latitude': 1, 'longitude': 1})
        with self.assertRaisesRegex(ValidationError, 'Aucun de vos cours'):
            self.Record.sync_offline_item(self.student.user_id, item, self.req)


@tagged('post_install', '-at_install')
class TestInternshipPortal(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        sup = cls.env['school.teacher'].create({'name': 'Dr Portail', 'email': 'dr.portail@chu.bj'})
        sup.action_create_user()
        sup.user_id.write({'password': 'Dr-Portail-2026',
                           'groups_id': [(4, cls.env.ref('school_internship.group_internship_supervisor').id)]})
        site = cls.env['school.internship.site'].create({
            'name': 'Urgences portail', 'latitude': CHU[0], 'longitude': CHU[1], 'supervisor_ids': [(6, 0, [sup.id])]})
        student = cls.env['school.student'].create({
            'nom': 'Stage', 'prenom': 'Koami', 'identifiant': 'koami.stage', 'matricule': '90909090',
            'must_change_password': False})
        period = cls.env['school.internship.period'].create({
            'student_id': student.id, 'site_id': site.id, 'required_hours': 50,
            'date_start': date.today(), 'date_end': date.today() + timedelta(days=5)})
        shift = cls.env['school.internship.attendance'].register_student_scan(
            student, CHU[0], CHU[1], f'dev-{student.id}', 5, at=fields.Datetime.now() - timedelta(hours=6))
        cls.env['school.internship.attendance'].register_student_scan(student, CHU[0], CHU[1], f'dev-{student.id}', 5)

    def test_student_tab_and_supervisor_screen(self):
        self.authenticate('koami.stage', '90909090')
        page = self.url_open('/presence/stages')
        self.assertEqual(page.status_code, 200)
        self.assertIn('Urgences portail', page.text)
        self.assertIn('Heures cliniques', page.text)
        self.assertIn('/presence/stages', self.url_open('/presence').text)  # onglet visible
        self.assertIn('réservé aux superviseurs', self.url_open('/presence/stages/validation').text)
        self.authenticate('dr.portail@chu.bj', 'Dr-Portail-2026')
        page = self.url_open('/presence/stages/validation')
        self.assertIn('Koami Stage', page.text)
        self.assertIn('Valider avec mon empreinte', page.text)
