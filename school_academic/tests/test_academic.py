import base64
from datetime import date, timedelta

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import HttpCase, tagged
from odoo.tests.common import TransactionCase

PDF = b'%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF'


class AcademicCase(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['school.academic.period'].search([]).write({'active': False})  # isole les tests des données existantes
        cls.period = cls.env['school.academic.period'].create({
            'name': 'Semestre test', 'date_from': date.today() - timedelta(days=60),
            'date_to': date.today() + timedelta(days=60)})
        cls.teacher = cls.env['school.teacher'].create({'name': 'Prof Notes', 'email': 'prof.notes@ecole.bj'})
        cls.maths = cls.env['school.course'].create({'name': 'Maths', 'teacher_id': cls.teacher.id, 'coefficient': 3})
        cls.info = cls.env['school.course'].create({'name': 'Info', 'teacher_id': cls.teacher.id, 'coefficient': 1})
        cls.promo = cls.env['school.promotion'].create({'name': 'L1 Test'})
        cls.ama = cls.env['school.student'].create({
            'nom': 'Kiki', 'prenom': 'Ama', 'identifiant': 'ama.kiki', 'matricule': '50505050',
            'promotion_id': cls.promo.id, 'course_ids': [(6, 0, [cls.maths.id, cls.info.id])]})
        cls.yao = cls.env['school.student'].create({
            'nom': 'Yao', 'prenom': 'Koffi', 'identifiant': 'koffi.yao', 'matricule': '60606060',
            'promotion_id': cls.promo.id, 'course_ids': [(6, 0, [cls.maths.id, cls.info.id])]})

    def _evaluation(self, course, name, scores, weight=1.0, max_score=20.0, publish=True):
        ev = self.env['school.evaluation'].create({
            'name': name, 'course_id': course.id, 'weight': weight, 'max_score': max_score, 'date': date.today()})
        ev.action_generate_grades()
        for grade in ev.grade_ids:
            value = scores.get(grade.student_id.id)
            if value == 'abs':
                grade.is_absent = True
            elif value is not None:
                grade.score = value
        if publish:
            ev.action_publish()
        return ev


class TestResults(AcademicCase):

    def test_weighted_averages_with_coefficients(self):
        self._evaluation(self.maths, 'Devoir 1', {self.ama.id: 10, self.yao.id: 8})
        self._evaluation(self.maths, 'Examen', {self.ama.id: 16, self.yao.id: 12}, weight=2)
        self._evaluation(self.info, 'TP', {self.ama.id: 30, self.yao.id: 20}, max_score=40)
        res = self.ama.compute_results(self.period)
        maths = next(c for c in res['courses'] if c['course'] == self.maths)
        info = next(c for c in res['courses'] if c['course'] == self.info)
        self.assertEqual(maths['average'], 14.0)        # (10*1 + 16*2) / 3
        self.assertEqual(info['average'], 15.0)         # 30/40 ramené sur 20
        self.assertEqual(res['general'], 14.25)         # (14*3 + 15*1) / 4
        self.assertTrue(res['passed'])
        self.assertEqual(self.env['school.student'].promotion_rank(self.ama, self.period), (1, 2))

    def test_absence_policy_is_configurable(self):
        self._evaluation(self.maths, 'D1', {self.ama.id: 12})
        self._evaluation(self.maths, 'D2', {self.ama.id: 'abs'})
        self.assertEqual(self.ama.compute_results()['courses'][0]['average'], 6.0)
        self.env['ir.config_parameter'].sudo().set_param('school_attendance_qr.grade_absent_policy', 'exclude')
        self.assertEqual(self.ama.compute_results()['courses'][0]['average'], 12.0)

    def test_draft_and_ungraded_are_ignored(self):
        self._evaluation(self.maths, 'Brouillon', {self.ama.id: 2}, publish=False)
        self._evaluation(self.maths, 'Publiée', {self.ama.id: 18, self.yao.id: None})
        self.assertEqual(self.ama.compute_results()['general'], 18.0)
        self.assertIsNone(self.yao.compute_results()['general'])

    def test_publish_notifies_and_later_changes_are_audited(self):
        ev = self._evaluation(self.maths, 'Examen final', {self.ama.id: 11})
        self.assertTrue(self.env['school.notification'].search_count([
            ('user_id', '=', self.ama.user_id.id), ('title', 'ilike', 'Nouvelle note')]))
        ev.grade_ids.filtered(lambda g: g.student_id == self.ama).score = 15
        log = self.env['school.audit.log'].search([('event_type', '=', 'grade')], limit=1)
        self.assertIn('11.0 → 15.0', log.description)

    def test_score_above_scale_is_refused(self):
        with self.assertRaises(ValidationError):
            self._evaluation(self.maths, 'Trop', {self.ama.id: 25})

    def test_bulletin_pdf(self):
        self._evaluation(self.maths, 'D1', {self.ama.id: 12, self.yao.id: 9})
        pdf = (self.ama | self.yao).bulletin_pdf(self.period)
        self.assertTrue(pdf.startswith(b'%PDF'))


class TestCalendarAndDocuments(AcademicCase):

    def test_exam_appears_in_calendar_with_reminders(self):
        ev = self.env['school.evaluation'].create({
            'name': 'Partiel', 'course_id': self.maths.id, 'evaluation_type': 'partiel', 'date': date.today(),
            'time_start': fields.Datetime.now() + timedelta(hours=20)})
        self.assertEqual(ev.event_id.importance, 'high')
        events = self.env['school.academic.event'].for_student(
            self.ama, fields.Datetime.now(), fields.Datetime.now() + timedelta(days=2))
        self.assertIn(ev.event_id, events)
        self.env['school.academic.event']._cron_event_reminders()
        self.assertTrue(self.env['school.notification'].search_count([
            ('user_id', '=', self.ama.user_id.id), ('category', '=', 'reminder')]))
        self.assertIn('24', ev.event_id.reminders_sent)
        ev.unlink()
        self.assertFalse(self.env['school.academic.event'].search([('name', '=', 'Partiel : Maths')]))

    def test_event_audience(self):
        other = self.env['school.promotion'].create({'name': 'L2 Autre'})
        event = self.env['school.academic.event'].create({
            'name': 'Sortie', 'event_type': 'evenement', 'promotion_id': other.id,
            'date_start': fields.Datetime.now() + timedelta(days=1)})
        self.assertFalse(event.audience() & self.ama)
        event.promotion_id = self.promo
        self.assertIn(self.ama, event.audience())

    def test_documents_accept_only_pdf_and_images(self):
        doc = self.env['school.course.document'].create({
            'name': 'Chapitre 1', 'course_id': self.maths.id, 'file': base64.b64encode(PDF)})
        self.assertEqual(doc.mimetype, 'application/pdf')
        self.assertTrue(doc.filename.endswith('.pdf'))
        with self.assertRaises(ValidationError):
            self.env['school.course.document'].create({
                'name': 'Virus', 'course_id': self.maths.id, 'file': base64.b64encode(b'MZ\x90\x00 exe')})


@tagged('post_install', '-at_install')
class TestAcademicPortal(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        teacher = cls.env['school.teacher'].create({'name': 'Prof Portail', 'email': 'prof.portail@ecole.bj'})
        cls.course = cls.env['school.course'].create({'name': 'Chimie', 'teacher_id': teacher.id})
        other = cls.env['school.course'].create({'name': 'Secret', 'teacher_id': teacher.id})
        cls.env['school.student'].create({
            'nom': 'Portail', 'prenom': 'Edem', 'identifiant': 'edem.portail', 'matricule': '70707070',
            'course_ids': [(6, 0, [cls.course.id])], 'must_change_password': False})
        ev = cls.env['school.evaluation'].create({'name': 'Interro', 'course_id': cls.course.id, 'date': date.today()})
        ev.action_generate_grades()
        ev.grade_ids.score = 13
        ev.action_publish()
        cls.doc = cls.env['school.course.document'].create({
            'name': 'Cours chimie', 'course_id': cls.course.id, 'file': base64.b64encode(PDF)})
        cls.secret = cls.env['school.course.document'].create({
            'name': 'Cours secret', 'course_id': other.id, 'file': base64.b64encode(PDF)})

    def test_pages_render_and_documents_are_protected(self):
        self.authenticate('edem.portail', '70707070')
        for url, text in [('/presence/etudes', 'Mes notes'), ('/presence/notes', '13'),
                          ('/presence/calendrier', 'Calendrier'), ('/presence/documents', 'Cours chimie'),
                          ('/presence', 'Études')]:
            res = self.url_open(url)
            self.assertEqual(res.status_code, 200, url)
            self.assertIn(text, res.text, url)
        ok = self.url_open(self.doc.download_url())
        self.assertEqual(ok.status_code, 200)
        self.assertTrue(ok.content.startswith(b'%PDF'))
        self.assertEqual(self.url_open(self.secret.download_url()).status_code, 404)
