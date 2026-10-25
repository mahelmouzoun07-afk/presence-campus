from odoo.exceptions import ValidationError

from .common import SchoolCase


class TestRelay(SchoolCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.teacher.action_create_user()
        cls.teacher_user = cls.teacher.user_id
        cls.student.no_phone = True
        cls.env['ir.config_parameter'].sudo().set_param('school_attendance_qr.relay_audit_rate', 0)
        cls.Record = cls.env['school.attendance.record']

    def _relay(self, student=None, matricule=None, identifiant=None, lat=6.3703, lon=2.3912):
        student = student or self.student
        return self.Record.register_relay(
            self.session, student, matricule or student.matricule, identifiant or student.identifiant,
            lat, lon, 5.0, self.teacher_user)

    def test_teacher_relays_student_without_phone(self):
        self.assertIn(self.session, self.Record.relay_actor_sessions(self.teacher_user))
        phase, eligible = self.Record.relay_eligible_students(self.session)
        self.assertEqual((phase, eligible), ('checkin', self.student))
        res = self._relay()
        self.assertEqual(res['state'], 'valid')
        record = self.session.record_ids
        self.assertEqual(record.proof_level, 'B')
        self.assertEqual(record.relayed_by_user_id, self.teacher_user)
        self.assertTrue(self.env['school.audit.log'].search_count([('event_type', '=', 'presence_relayed')]))

    def test_student_with_phone_cannot_be_relayed(self):
        with self.assertRaises(ValidationError):
            self._relay(student=self.student2)

    def test_identity_must_be_typed_by_the_student(self):
        with self.assertRaises(ValidationError):
            self._relay(matricule='00000000')

    def test_quota_per_session(self):
        self.env['ir.config_parameter'].sudo().set_param('school_attendance_qr.relay_max_per_session', 1)
        self.student2.no_phone = True
        self._relay()
        with self.assertRaises(ValidationError):
            self._relay(student=self.student2)

    def test_delegate_can_relay_when_allowed(self):
        self.student2.write({'is_delegate': True, 'must_change_password': False})
        delegate_user = self.student2.user_id
        self.assertIn(self.session, self.Record.relay_actor_sessions(delegate_user))
        self.env['ir.config_parameter'].sudo().set_param('school_attendance_qr.relay_actor', 'teacher')
        self.assertFalse(self.Record.relay_actor_sessions(delegate_user))

    def test_headcount_mismatch_blocks_relays(self):
        self.scan(self.student2)
        self._relay()
        res = self.session.submit_headcount(1, self.teacher_user)
        self.assertTrue(res['mismatch'])
        self.assertTrue(self.session.relay_blocked)
        relayed = self.session.record_ids.filtered(lambda r: r.proof_level == 'B')
        self.assertEqual(relayed.state, 'flagged')
        self.assertTrue(self.env['school.attendance.task'].search_count([('task_type', '=', 'headcount')]))

    def test_headcount_consistent(self):
        self._relay()
        res = self.session.submit_headcount(5, self.teacher_user)
        self.assertFalse(res['mismatch'])
        self.assertFalse(self.session.relay_blocked)
