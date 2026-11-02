import io
import json

from odoo import fields, http
from odoo.exceptions import AccessError
from odoo.http import request, content_disposition

from ..models import webauthn_helper as wa
from ..models.helpers import client_ip, gps_float


def device_options(holder):
    """Options WebAuthn pour `holder` (étudiant ou enseignant) : enregistrer
    une nouvelle clé d'appareil, ou s'authentifier avec celle déjà enregistrée.
    Partagé par la présence aux cours, les relais et les stages."""
    holder = holder.sudo()
    if holder.webauthn_credential_id:
        return {'mode': 'authenticate', 'options': json.loads(
            wa.build_authentication_options(request.session, request.httprequest, holder))}
    return {'mode': 'register', 'options': json.loads(wa.build_registration_options(
        request.session, request.httprequest, holder, request.env.company.name))}


def verify_device(holder, webauthn_mode, webauthn_credential):
    """Vérifie la réponse WebAuthn de `holder` (et enregistre la clé au premier
    usage). Renvoie un message d'erreur, ou None si tout est bon."""
    holder = holder.sudo()
    credential_json = json.dumps(webauthn_credential)
    if webauthn_mode == 'register':
        result, error = wa.verify_registration(request.session, request.httprequest, credential_json)
        if error:
            return error
        wa.store_registration(holder, result)
        return None
    if webauthn_mode == 'authenticate':
        ok, error = wa.verify_authentication(request.session, request.httprequest, holder, credential_json)
        return None if ok else error
    return "Vérification de l'appareil manquante."


class AttendanceScanController(http.Controller):

    def _current_student(self):
        return request.env['school.student'].sudo().search(
            [('user_id', '=', request.env.user.id)], limit=1)

    @http.route('/school/attendance/scan/<string:token>', type='http', auth='user', website=True)
    def scan_page(self, token, **kw):
        """Page ouverte par l'étudiant en scannant le QR permanent collé
        dans la salle. Le QR identifie la salle ; la séance active du
        moment est retrouvée côté serveur."""
        room = request.env['school.room'].sudo().search([('qr_token', '=', token)], limit=1)
        session, phase_hint = False, 'checkin'
        if room:
            candidate = request.env['school.attendance.session'].sudo().search(
                [('room_id', '=', room.id), ('time_start', '<=', fields.Datetime.now())],
                order='time_start desc', limit=1,
            )
            if candidate and candidate.is_within_checkin_window():
                session, phase_hint = candidate, 'checkin'
            elif candidate and candidate.is_within_checkout_window():
                session, phase_hint = candidate, 'checkout'
        student = self._current_student()
        if student and student.must_change_password:
            return request.redirect('/presence/mot-de-passe')
        return request.render('school_attendance_qr.scan_page_template', {
            'token': token, 'room': room, 'session': session, 'phase_hint': phase_hint,
            'needs_webauthn_setup': bool(student and not student.webauthn_credential_id),
        })

    @staticmethod
    def _get_client_ip():
        return client_ip()

    # ------------------------------------------------------------ WebAuthn
    @http.route('/school/attendance/webauthn/options', type='json', auth='user')
    def webauthn_options(self):
        """Avant de confirmer : le navigateur demande ici s'il doit
        ENREGISTRER une nouvelle clé (premier scan jamais fait) ou
        AUTHENTIFIER avec celle déjà enregistrée."""
        student = self._current_student()
        if not student:
            return {'error': "Aucun profil étudiant associé à ce compte."}
        return device_options(student)

    @http.route('/school/attendance/confirm', type='json', auth='user')
    def confirm(self, token, latitude, longitude, device_fingerprint, webauthn_mode, webauthn_credential,
               accuracy=0):
        """Appelé en JS après géolocalisation ET vérification WebAuthn
        (empreinte / Face ID / code PIN du téléphone). L'étudiant est déduit
        de l'utilisateur connecté, jamais transmis par le client."""
        student = self._current_student()
        if not student:
            return {'error': "Aucun profil étudiant associé à ce compte."}
        if student.must_change_password:
            return {'error': "Choisissez d'abord votre mot de passe personnel (menu Profil)."}

        error = verify_device(student, webauthn_mode, webauthn_credential)
        if error:
            return {'error': error}

        try:
            return request.env['school.attendance.record'].sudo().register_scan(
                room_token=token,
                student_id=student.id,
                latitude=gps_float(latitude),
                longitude=gps_float(longitude),
                device_fingerprint=device_fingerprint,
                accuracy=accuracy,
                client_ip=self._get_client_ip(),
            )
        except Exception as e:
            request.env['school.audit.log'].log('presence_refused', str(e), student=student)
            return {'error': str(e)}

    # --------------------------------------------------- impressions (admin)
    def _check_admin(self):
        if not (request.env.user.has_group('school_base.group_school_admin')
                or request.env.user.has_group('school_base.group_school_teacher')):
            raise AccessError("Accès réservé au personnel de l'établissement.")

    @http.route('/school/qr/png/<int:room_id>', type='http', auth='user')
    def qr_png(self, room_id):
        self._check_admin()
        room = request.env['school.room'].browse(room_id)
        if not room.exists():
            raise request.not_found()
        png = room._render_qr_png(box_size=20)
        headers = [('Content-Type', 'image/png'),
                   ('Content-Disposition', content_disposition(f"QR-{room.name}.png"))]
        return request.make_response(png, headers=headers)

    @http.route('/school/qr/poster', type='http', auth='user')
    def qr_poster(self, ids):
        self._check_admin()
        room_ids = [int(i) for i in ids.split(',') if i.strip().isdigit()]
        rooms = request.env['school.room'].browse(room_ids).exists()
        if not rooms:
            raise request.not_found()
        pdf = rooms._render_posters_pdf()
        name = "Affiches-QR.pdf" if len(rooms) > 1 else f"Affiche-QR-{rooms.name}.pdf"
        headers = [('Content-Type', 'application/pdf'),
                   ('Content-Disposition', content_disposition(name))]
        return request.make_response(pdf, headers=headers)
