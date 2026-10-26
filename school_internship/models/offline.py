"""Hors ligne pour les stages (blocs opératoires, radiologie en sous-sol...).

Aucun nouveau mécanisme : on branche les stages sur la file d'attente hors
ligne existante (school_attendance_qr/models/offline.py) via deux nouvelles
cibles :
- 'internship' : entrée/sortie de garde de l'étudiant ;
- 'internship_validation' : validation d'une garde par le superviseur, dont
  la clé d'appareil (school.teacher) signe un défi préchargé."""
from odoo import _, api, models
from odoo.exceptions import ValidationError


class SchoolOfflineChallengeInternship(models.Model):
    _inherit = 'school.offline.challenge'

    @api.model
    def holder_for_user(self, user):
        holder = super().holder_for_user(user)
        if not holder:
            holder = self.env['school.internship.attendance'].supervisor_for_user(user)
        return holder


class SchoolAttendanceRecordInternshipSync(models.Model):
    _inherit = 'school.attendance.record'

    @api.model
    def sync_offline_item(self, user, item, httprequest):
        target = item.get('target')
        Challenge = self.env['school.offline.challenge'].sudo()
        Shift = self.env['school.internship.attendance'].sudo()
        if target == 'internship':
            student = self.env['school.student'].sudo().search([('user_id', '=', user.id)], limit=1)
            if not student:
                raise ValidationError(_("Aucun profil étudiant associé à ce compte."))
            captured = Challenge.consume(student, item, httprequest)
            return Shift.register_student_scan(
                student, float(item.get('latitude') or 0), float(item.get('longitude') or 0),
                item.get('device_fingerprint') or 'hors-ligne', item.get('accuracy') or 0,
                at=captured, offline=True)
        if target == 'internship_validation':
            teacher = Shift.supervisor_for_user(user)
            if not teacher:
                raise ValidationError(_("Vous n'êtes superviseur d'aucun site de stage."))
            captured = Challenge.consume(teacher, item, httprequest)
            shift = Shift.browse(int(item.get('attendance_id') or 0)).exists()
            if not shift:
                raise ValidationError(_("Garde introuvable."))
            return shift.validate_by_supervisor(teacher, item.get('rating'), item.get('comment'),
                                                at=captured, offline=True)
        return super().sync_offline_item(user, item, httprequest)
