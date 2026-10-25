from datetime import timedelta

from odoo import fields
from odoo.tests.common import TransactionCase


class SchoolCase(TransactionCase):
    """Jeu de données minimal partagé par les tests : une salle, un cours,
    un enseignant, deux étudiants et une séance dont la fenêtre d'entrée
    est ouverte maintenant."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.room = cls.env['school.room'].create({
            'name': 'Salle A', 'latitude': 6.3703, 'longitude': 2.3912, 'radius_meters': 30})
        cls.teacher = cls.env['school.teacher'].create({'name': 'Prof Test', 'email': 'prof.test@ecole.bj'})
        cls.course = cls.env['school.course'].create({'name': 'Algèbre', 'teacher_id': cls.teacher.id})
        cls.student = cls.env['school.student'].create({
            'nom': 'Etudiant', 'prenom': 'Un', 'identifiant': 'prenom.nom01',
            'matricule': '10000001', 'course_ids': [(6, 0, [cls.course.id])]})
        cls.student2 = cls.env['school.student'].create({
            'nom': 'Dossou', 'prenom': 'Afi', 'identifiant': 'afi.dossou12',
            'matricule': '10000002', 'course_ids': [(6, 0, [cls.course.id])]})
        cls.session = cls.env['school.attendance.session'].create({
            'course_id': cls.course.id, 'teacher_id': cls.teacher.id, 'room_id': cls.room.id,
            'time_start': fields.Datetime.now() - timedelta(minutes=2), 'duration_minutes': 90})

    def scan(self, student, lat=6.3703, lon=2.3912, fp=None, accuracy=5.0, ip=False):
        return self.env['school.attendance.record'].sudo().register_scan(
            room_token=self.room.qr_token, student_id=student.id, latitude=lat, longitude=lon,
            device_fingerprint=fp or f'dev-{student.id}', accuracy=accuracy, client_ip=ip)
