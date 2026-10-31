from datetime import timedelta

from odoo import fields

from .common import SchoolCase


class TestGpsPrivacy(SchoolCase):
    """Minimisation des positions : hors de la salle, le téléphone n'envoie
    rien (None) ; le serveur refuse sans jamais stocker de coordonnées, et
    efface les positions anciennes passé le délai de conservation."""

    def test_position_not_sent_is_rejected_without_coordinates(self):
        res = self.scan(self.student, lat=None, lon=None)
        self.assertEqual(res['state'], 'rejected')
        self.assertIn('non transmise', res['flag_reason'])
        record = self.env['school.attendance.record'].search([('student_id', '=', self.student.id)])
        self.assertFalse(record.latitude or record.longitude)

    def test_retry_from_the_room_after_out_of_zone(self):
        self.scan(self.student, lat=None, lon=None)
        self.assertEqual(self.scan(self.student)['state'], 'valid')

    def test_position_sent_is_still_checked_by_server(self):
        # un téléphone modifié qui prétend être dans la salle en envoyant une
        # position lointaine est refusé : le serveur revérifie toujours
        self.assertEqual(self.scan(self.student, lat=6.40, lon=2.35)['state'], 'rejected')

    def test_purge_after_retention_delay(self):
        self.scan(self.student)
        record = self.env['school.attendance.record'].search([('student_id', '=', self.student.id)])
        Record = self.env['school.attendance.record']
        self.env['ir.config_parameter'].sudo().set_param('school_attendance_qr.gps_retention_days', 30)
        Record._cron_purge_gps()
        self.assertTrue(record.latitude, "position récente : conservée")
        record.scan_datetime = fields.Datetime.now() - timedelta(days=31)
        Record._cron_purge_gps()
        self.assertFalse(record.latitude or record.longitude)
        self.assertEqual(record.state, 'valid')

    def test_retention_zero_keeps_positions(self):
        self.scan(self.student)
        record = self.env['school.attendance.record'].search([('student_id', '=', self.student.id)])
        record.scan_datetime = fields.Datetime.now() - timedelta(days=400)
        self.env['ir.config_parameter'].sudo().set_param('school_attendance_qr.gps_retention_days', 0)
        self.env['school.attendance.record']._cron_purge_gps()
        self.assertTrue(record.latitude)

    def test_offline_zones_list_the_room(self):
        zones = self.env['school.offline.challenge'].offline_zones(self.student)
        self.assertEqual(zones, [{'lat': 6.3703, 'lng': 2.3912, 'radius': 30}])
