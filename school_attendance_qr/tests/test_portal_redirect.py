from odoo import http
from odoo.tests import HttpCase, tagged
from odoo.tests.common import HOST, Opener, get_db_name


@tagged('post_install', '-at_install')
class TestPortalRedirect(HttpCase):
    """Bug v11 : après connexion, Odoo envoyait les étudiants sur son portail
    générique (/my) au lieu du portail de présence (/presence)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        teacher = cls.env['school.teacher'].create({'name': 'Prof', 'email': 'prof.redirect@ecole.bj'})
        course = cls.env['school.course'].create({'name': 'Cours', 'teacher_id': teacher.id})
        cls.student = cls.env['school.student'].create({
            'nom': 'Test', 'prenom': 'Redirect', 'identifiant': 'redirect.test',
            'matricule': 'mat-redirect-1', 'course_ids': [(6, 0, [course.id])],
            'must_change_password': False})

    def test_my_redirects_student_to_presence(self):
        self.authenticate('redirect.test', 'mat-redirect-1')
        res = self.url_open('/my', allow_redirects=False)
        self.assertIn(res.status_code, (301, 302, 303))
        self.assertTrue(res.headers['Location'].endswith('/presence'))

    def test_login_lands_on_presence(self):
        # même préparation de session que les tests de connexion d'Odoo (web/tests/test_login.py)
        self.session = http.root.session_store.new()
        self.session.update(http.get_default_session(), db=get_db_name())
        self.opener = Opener(self.env.cr)
        self.opener.cookies.set('session_id', self.session.sid, domain=HOST, path='/')
        res = self.url_open('/web/login', data={
            'login': 'redirect.test', 'password': 'mat-redirect-1',
            'csrf_token': http.Request.csrf_token(self)}, allow_redirects=False)
        self.assertIn('/presence', res.headers.get('Location', ''))

    def test_presence_dashboard_renders(self):
        self.authenticate('redirect.test', 'mat-redirect-1')
        res = self.url_open('/presence')
        self.assertEqual(res.status_code, 200)
        self.assertIn('Bonjour', res.text)
