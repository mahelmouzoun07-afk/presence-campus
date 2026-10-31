"""Hors ligne pour les stages (blocs opératoires, radiologie en sous-sol...).

Aucun nouveau mécanisme : on branche les stages sur la file d'attente hors
ligne existante (school_attendance_qr/models/offline.py) via deux nouvelles
cibles :
- 'internship' : entrée/sortie de garde de l'étudiant ;
- 'internship_validation' : validation d'une garde par le superviseur, dont
  la clé d'appareil (school.teacher) signe un défi préchargé."""
from odoo import _, api, models
from odoo.exceptions import ValidationError

from odoo.addons.school_attendance_qr.models.helpers import gps_float, zone_of


class SchoolOfflineChallengeInternship(models.Model):
    _inherit = 'school.offline.challenge'

    @api.model
    def holder_for_user(self, user):
        holder = super().holder_for_user(user)
        if not holder:
            holder = self.env['school.internship.attendance'].supervisor_for_user(user)
        return holder

    @api.model
    def offline_zones(self, holder):
        """Ajoute les sites de stage : celui de la période en cours, et les
        autres sites connus (une confirmation sur un autre site que celui prévu
        est signalée, pas refusée : il faut donc pouvoir la transmettre)."""
        zones = super().offline_zones(holder)
        if holder._name == 'school.student' and holder.current_internship_period():
            sites = self.env['school.internship.site'].sudo().search([])
            zones += [zone_of(site) for site in sites if site.latitude or site.longitude]
        return zones


class SchoolAttendanceRecordInternshipSync(models.Model):
    _inherit = 'school.attendance.record'

    @api.model
    def sync_offline_item(self, user, item, httprequest):
        lat, lon = gps_float(item.get('latitude')), gps_float(item.get('longitude'))
        target = item.get('target')
        Challenge = self.env['school.offline.challenge'].sudo()
        Shift = self.env['school.internship.attendance'].sudo()
        if target == 'internship':
            student = self.env['school.student'].sudo().search([('user_id', '=', user.id)], limit=1)
            if not student:
                raise ValidationError(_("Aucun profil étudiant associé à ce compte."))
            captured = Challenge.consume(student, item, httprequest)
            return Shift.register_student_scan(
                student, lat, lon,
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
        if target == 'internship_check':
            student = self.env['school.student'].sudo().search([('user_id', '=', user.id)], limit=1)
            if not student:
                raise ValidationError(_("Aucun profil étudiant associé à ce compte."))
            captured = Challenge.consume(student, item, httprequest)
            shift = Shift.search([('student_id', '=', student.id), ('checkin_time', '<=', captured),
                                  '|', ('checkout_time', '=', False), ('checkout_time', '>=', captured)], limit=1)
            if not shift:
                raise ValidationError(_("Aucune garde en cours à l'heure de ce contrôle."))
            return shift.confirm_check(lat, lon,
                                       item.get('accuracy') or 0, at=captured, offline=True)
        return super().sync_offline_item(user, item, httprequest)
