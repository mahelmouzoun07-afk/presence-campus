from datetime import timedelta

from odoo import fields
from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestPortalPages(HttpCase):
    """Chaque page du portail s'affiche sans erreur (les erreurs de gabarit
    n'apparaissent qu'à l'affichage réel)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        room = cls.env['school.room'].create({'name': 'Salle P', 'latitude': 6.37, 'longitude': 2.39})
        cls.teacher = cls.env['school.teacher'].create({'name': 'Prof Pages', 'email': 'prof.pages@ecole.bj'})
        cls.teacher.action_create_user()
        cls.teacher.user_id.password = 'Prof-Pages-2026'
        cls.course = cls.env['school.course'].create({'name': 'Physique', 'teacher_id': cls.teacher.id})
        cls.student = cls.env['school.student'].create({
            'nom': 'Pages', 'prenom': 'Kofi', 'identifiant': 'kofi.pages', 'matricule': '30303030',
            'course_ids': [(6, 0, [cls.course.id])], 'must_change_password': False, 'is_delegate': True})
        cls.no_phone = cls.env['school.student'].create({
            'nom': 'Sans', 'prenom': 'Tel', 'identifiant': 'tel.sans', 'matricule': '40404040',
            'course_ids': [(6, 0, [cls.course.id])], 'must_change_password': False, 'no_phone': True})
        cls.env['school.attendance.session'].create({
            'course_id': cls.course.id, 'teacher_id': cls.teacher.id, 'room_id': room.id,
            'time_start': fields.Datetime.now() - timedelta(minutes=2), 'duration_minutes': 90})

    def _get(self, url):
        res = self.url_open(url)
        self.assertEqual(res.status_code, 200, url)
        return res.text

    def test_student_pages(self):
        self.authenticate('kofi.pages', '30303030')
        self.assertIn('Physique', self._get('/presence'))
        self._get('/presence/emploi-du-temps')
        self.assertIn('Relayer la présence', self._get('/presence/profil'))
        self._get('/presence/mes-absences')

    def test_student_without_phone_dashboard(self):
        self.authenticate('tel.sans', '40404040')
        self.assertIn('confirmée par le responsable', self._get('/presence'))

    def test_relay_page_for_teacher_and_delegate(self):
        self.authenticate('prof.pages@ecole.bj', 'Prof-Pages-2026')
        page = self._get('/presence/relais')
        self.assertIn('Tel Sans', page)
        self.assertNotIn('Kofi Pages', page)  # liste fermée : seulement les « sans téléphone »
        self.authenticate('kofi.pages', '30303030')
        self.assertIn('Tel Sans', self._get('/presence/relais'))

    def test_relay_page_refused_to_regular_student(self):
        self.authenticate('tel.sans', '40404040')
        self.assertIn('Seuls les responsables', self._get('/presence/relais'))
