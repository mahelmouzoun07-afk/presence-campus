from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import HttpCase, tagged

from .common import SchoolCase


class TestAuditLog(SchoolCase):

    def test_log_is_chained_and_immutable(self):
        Audit = self.env['school.audit.log']
        first = Audit.log('other', "Premier événement", student=self.student)
        second = Audit.log('other', "Deuxième événement")
        self.assertEqual(second.previous_hash, first.log_hash)
        self.assertTrue(Audit.check_integrity()[0])
        with self.assertRaises(UserError):
            first.write({'description': 'falsifié'})
        with self.assertRaises(UserError):
            second.unlink()

    def test_tampering_in_database_is_detected(self):
        Audit = self.env['school.audit.log']
        entry = Audit.log('other', "Original")
        Audit.log('other', "Suivant")
        # Simule quelqu'un qui modifie la base directement, sans passer par Odoo
        self.env.cr.execute("UPDATE school_audit_log SET description = 'Modifié' WHERE id = %s", [entry.id])
        self.env.invalidate_all()
        ok, broken_id = Audit.check_integrity()
        self.assertFalse(ok)
        self.assertEqual(broken_id, entry.id)


class TestFraudDetections(SchoolCase):

    def test_identical_gps_flags_both_students(self):
        self.scan(self.student, lat=6.3703101, lon=2.3912202)
        res = self.scan(self.student2, lat=6.3703101, lon=2.3912202)
        self.assertEqual(res['state'], 'flagged')
        records = self.session.record_ids
        self.assertTrue(all(r.state == 'flagged' for r in records))
        self.assertIn('identique', records[0].flag_reason)
        self.assertTrue(self.env['school.attendance.task'].search_count([('task_type', '=', 'gps_identical')]))

    def test_clustered_confirmations_are_flagged(self):
        third = self.env['school.student'].create({
            'nom': 'Hounsou', 'prenom': 'Paul', 'identifiant': 'paul.hounsou', 'matricule': '10000003',
            'course_ids': [(6, 0, [self.course.id])]})
        self.scan(self.student, lat=6.37030, lon=2.39120)
        self.scan(self.student2, lat=6.37031, lon=2.39121)
        res = self.scan(third, lat=6.37030, lon=2.39121)
        self.assertEqual(res['state'], 'flagged')
        self.assertTrue(self.env['school.attendance.task'].search_count([('task_type', '=', 'scan_cluster')]))

    def test_normal_confirmations_are_not_flagged(self):
        self.assertEqual(self.scan(self.student, lat=6.37030, lon=2.39120)['state'], 'valid')
        self.assertEqual(self.scan(self.student2, lat=6.37045, lon=2.39105)['state'], 'valid')

    def test_impossible_speed_is_flagged(self):
        far_room = self.env['school.room'].create({'name': 'Campus Parakou', 'latitude': 9.3400, 'longitude': 2.6300})
        other_course = self.env['school.course'].create({'name': 'Histoire', 'teacher_id': self.teacher.id})
        earlier = self.env['school.attendance.session'].create({
            'course_id': other_course.id, 'teacher_id': self.teacher.id, 'room_id': far_room.id,
            'time_start': fields.Datetime.now() - timedelta(hours=3), 'duration_minutes': 60})
        self.env['school.attendance.record'].create({
            'session_id': earlier.id, 'student_id': self.student.id, 'device_fingerprint': f'dev-{self.student.id}',
            'latitude': 9.3400, 'longitude': 2.6300, 'scan_datetime': fields.Datetime.now() - timedelta(minutes=10)})
        res = self.scan(self.student)
        self.assertEqual(res['state'], 'flagged')
        self.assertIn('Déplacement impossible', res['flag_reason'])


@tagged('post_install', '-at_install')
class TestAccountSecurity(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        teacher = cls.env['school.teacher'].create({'name': 'Prof', 'email': 'prof.secu@ecole.bj'})
        course = cls.env['school.course'].create({'name': 'Cours', 'teacher_id': teacher.id})
        cls.student = cls.env['school.student'].create({
            'nom': 'Secu', 'prenom': 'Ama', 'identifiant': 'ama.secu', 'matricule': '20202020',
            'course_ids': [(6, 0, [course.id])]})

    def _try_login(self, password):
        credential = {'login': 'ama.secu', 'password': password, 'type': 'password'}
        return self.env['res.users'].authenticate(self.env.cr.dbname, credential, {'interactive': False})

    def test_five_failures_flag_the_student(self):
        # Le branchement sur la vraie connexion (_login) est vérifié en conditions
        # réelles (odoo-bin shell) : en test, Odoo annule la transaction séparée
        # qu'il utilise. On vérifie donc ici le compteur lui-même.
        Users = self.env.registry['res.users']
        for _i in range(5):
            Users._school_register_failed_login('ama.secu')
        self.env.invalidate_all()
        self.assertEqual(self.student.user_id.school_failed_logins, 5)
        self.assertTrue(self.student.account_flagged)
        self.assertTrue(self.env['school.attendance.task'].search_count(
            [('task_type', '=', 'login_failures'), ('student_id', '=', self.student.id)]))
        # Une connexion réussie remet le compteur à zéro
        self._try_login('20202020')
        self.env.invalidate_all()
        self.assertEqual(self.student.user_id.school_failed_logins, 0)
        # La réinitialisation par le secrétariat lève le signalement
        self.student.action_reset_password()
        self.assertFalse(self.student.account_flagged)
        self.assertTrue(self.student.must_change_password)

    def test_new_student_must_choose_password_first(self):
        self.assertTrue(self.student.must_change_password)
        self.authenticate('ama.secu', '20202020')
        res = self.url_open('/presence', allow_redirects=False)
        self.assertTrue(res.headers['Location'].endswith('/presence/mot-de-passe'))
        page = self.url_open('/presence/mot-de-passe')
        self.assertIn('matricule', page.text)

    def test_password_change_rejects_matricule_and_unlocks_portal(self):
        self.authenticate('ama.secu', '20202020')
        csrf = self.url_open('/presence/mot-de-passe').text.split('name="csrf_token" value="')[1].split('"')[0]
        res = self.url_open('/presence/mot-de-passe', data={
            'csrf_token': csrf, 'old': '20202020', 'new1': '20202020', 'new2': '20202020'})
        self.assertIn('ne doit pas être votre matricule', res.text)
        res = self.url_open('/presence/mot-de-passe', data={
            'csrf_token': csrf, 'old': '20202020', 'new1': 'Mon-Secret-2026', 'new2': 'Mon-Secret-2026'},
            allow_redirects=False)
        self.assertTrue(res.headers['Location'].endswith('/presence'))
        self.student.invalidate_recordset()
        self.assertFalse(self.student.must_change_password)
        self.assertEqual(self.url_open('/presence').status_code, 200)
