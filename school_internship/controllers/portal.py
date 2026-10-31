import base64
import json

from odoo import http
from odoo.http import content_disposition, request

from odoo.addons.school_attendance_qr.controllers.main import device_options, verify_device
from odoo.addons.school_attendance_qr.controllers.portal import portal_gate
from odoo.addons.school_attendance_qr.models.helpers import gps_float, icp_int, zone_of


class SchoolInternshipPortal(http.Controller):

    def _shifts(self):
        return request.env['school.internship.attendance'].sudo()

    # ------------------------------------------------------------ étudiant
    @http.route('/presence/stages', type='http', auth='user', website=True)
    def my_internships(self, **kw):
        student, response = portal_gate()
        if response:
            return response
        period = student.current_internship_period()
        shift = period.open_shift() if period else self._shifts()
        periods = request.env['school.internship.period'].sudo().search([('student_id', '=', student.id)])
        return request.render('school_internship.portal_internships', {
            'student': student, 'period': period, 'shift': shift, 'periods': periods,
            'recent': period.attendance_ids.sorted('checkin_time', reverse=True)[:10] if period else [],
            'phase_hint': 'checkout' if shift else 'checkin', 'active_nav': 'internships',
            'check': shift.pending_check() if shift else False,
            'ping_minutes': icp_int(request.env, 'internship_ping_minutes', 5),
            # sites de stage seulement : hors de ces zones, la position reste sur le téléphone
            'zones_json': json.dumps([zone_of(site) for site in request.env['school.internship.site'].sudo().search([])
                                      if site.latitude or site.longitude]),
        })

    @http.route('/presence/stages/confirmer', type='json', auth='user')
    def confirm_shift(self, latitude, longitude, device_fingerprint, webauthn_mode, webauthn_credential,
                      accuracy=0, token=None):
        """Entrée ou sortie de garde : même vérification d'appareil (WebAuthn)
        que la présence en cours, puis contrôles GPS sur le site de stage."""
        student, response = portal_gate()
        if response or not student:
            return {'error': "Aucun profil étudiant associé à ce compte, ou mot de passe à changer."}
        error = verify_device(student, webauthn_mode, webauthn_credential)
        if error:
            return {'error': error}
        try:
            return self._shifts().register_student_scan(
                student, gps_float(latitude), gps_float(longitude), device_fingerprint, accuracy)
        except Exception as e:
            request.env['school.audit.log'].log('internship', f"Garde refusée : {e}", student=student)
            return {'error': str(e)}

    @http.route('/presence/stages/releve/<int:period_id>', type='http', auth='user')
    def statement(self, period_id, **kw):
        """Relevé d'heures d'une période VALIDÉE par l'administration."""
        student, response = portal_gate()
        if response:
            return response
        period = request.env['school.internship.period'].sudo().browse(period_id)
        if not period.exists() or period.student_id != student or period.status != 'validated':
            raise request.not_found()
        cert = request.env['school.attendance.certificate'].sudo().search([
            ('internship_period_id', '=', period.id), ('certificate_type', '=', 'internship_hours')],
            order='id desc', limit=1)
        if not cert:
            period.action_generate_statement()
            cert = request.env['school.attendance.certificate'].sudo().search(
                [('internship_period_id', '=', period.id)], order='id desc', limit=1)
        # Envoyé directement : l'étudiant n'a pas (et ne doit pas avoir) accès aux attestations en général
        return request.make_response(base64.b64decode(cert.pdf_file), headers=[
            ('Content-Type', 'application/pdf'), ('Content-Disposition', content_disposition(cert.pdf_filename))])

    # --------------------------------------------------------- superviseur
    @http.route('/presence/stages/validation', type='http', auth='user', website=True)
    def supervisor_page(self, **kw):
        teacher = self._shifts().supervisor_for_user(request.env.user)
        if not teacher:
            return request.render('school_internship.portal_supervisor_denied', {})
        return request.render('school_internship.portal_supervisor', {
            'teacher': teacher, 'pending': self._shifts().pending_for_supervisor(teacher),
        })

    @http.route('/presence/stages/superviseur/options', type='json', auth='user')
    def supervisor_options(self):
        teacher = self._shifts().supervisor_for_user(request.env.user)
        if not teacher:
            return {'error': "Vous n'êtes superviseur d'aucun site de stage."}
        return device_options(teacher)

    @http.route('/presence/stages/valider', type='json', auth='user')
    def supervisor_validate(self, attendance_id, webauthn_mode, webauthn_credential, rating=None, comment=None):
        teacher = self._shifts().supervisor_for_user(request.env.user)
        if not teacher:
            return {'error': "Vous n'êtes superviseur d'aucun site de stage."}
        error = verify_device(teacher, webauthn_mode, webauthn_credential)
        if error:
            return {'error': error}
        shift = self._shifts().browse(int(attendance_id)).exists()
        if not shift:
            return {'error': "Garde introuvable."}
        try:
            return shift.validate_by_supervisor(teacher, rating, comment)
        except Exception as e:
            return {'error': str(e)}

    # ----------------------------------------------- suivi continu pendant la garde
    @http.route('/presence/stages/positions', type='json', auth='user')
    def shift_positions(self, points):
        """Positions envoyées par le téléphone pendant la garde (en direct, ou
        gardées pendant une coupure réseau puis envoyées en bloc)."""
        student, response = portal_gate()
        if response or not student:
            return {'error': "Aucun profil étudiant."}
        period = student.current_internship_period()
        shift = period.open_shift() if period else None
        if not shift:
            return {'error': "Aucune garde en cours.", 'stop': True}
        res = shift.record_positions(points or [])
        check = shift.pending_check()
        return dict(res, check=bool(check))

    @http.route('/presence/stages/controle', type='json', auth='user')
    def shift_check(self, latitude, longitude, webauthn_mode, webauthn_credential, accuracy=0):
        """Réponse à un contrôle de présence : empreinte + position."""
        student, response = portal_gate()
        if response or not student:
            return {'error': "Aucun profil étudiant."}
        error = verify_device(student, webauthn_mode, webauthn_credential)
        if error:
            return {'error': error}
        period = student.current_internship_period()
        shift = period.open_shift() if period else None
        if not shift:
            return {'error': "Aucune garde en cours."}
        try:
            return shift.confirm_check(latitude, longitude, accuracy)
        except Exception as e:
            return {'error': str(e)}
