from odoo.tests.common import TransactionCase


class TestFiliere(TransactionCase):

    def setUp(self):
        super().setUp()
        self.info = self.env['school.filiere'].create({'name': 'Informatique de gestion', 'code': 'IG'})
        self.gc = self.env['school.filiere'].create({'name': 'Génie civil', 'code': 'GC'})
        self.l1 = self.env['school.promotion'].create({'name': 'L1 IG 2026', 'filiere_id': self.info.id})

    def _student(self, **vals):
        base = {'nom': 'Kpadé', 'prenom': 'Jean', 'identifiant': 'jean.kpade', 'matricule': '100200'}
        base.update(vals)
        return self.env['school.student'].create(base)

    def test_student_inherits_filiere_from_promotion(self):
        student = self._student(promotion_id=self.l1.id)
        self.assertEqual(student.filiere_id, self.info)
        self.assertEqual(self.info.student_count, 1)

    def test_filiere_can_be_overridden_per_student(self):
        student = self._student(promotion_id=self.l1.id)
        student.filiere_id = self.gc
        self.assertEqual(student.filiere_id, self.gc)

    def test_promotion_change_updates_filiere(self):
        student = self._student(promotion_id=self.l1.id)
        self.l1.filiere_id = self.gc
        self.assertEqual(student.filiere_id, self.gc)
