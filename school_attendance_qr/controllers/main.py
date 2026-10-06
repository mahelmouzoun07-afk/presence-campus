from odoo import fields, http
from odoo.http import request


class AttendanceScanController(http.Controller):

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
        return request.render('school_attendance_qr.scan_page_template', {
            'token': token, 'room': room, 'session': session, 'phase_hint': phase_hint,
        })

    @staticmethod
    def _get_client_ip():
        """IP réelle du visiteur. Derrière un proxy (nginx, Cloudflare,
        tunnel...), request.httprequest.remote_addr donne l'IP du proxy,
        pas celle du téléphone : on lit donc X-Forwarded-For en priorité,
        en ne gardant que le PREMIER maillon (le plus proche du visiteur) -
        les suivants peuvent être ajoutés par n'importe quel relais et ne
        sont pas dignes de confiance."""
        xff = request.httprequest.headers.get('X-Forwarded-For')
        if xff:
            return xff.split(',')[0].strip()
        return request.httprequest.remote_addr

    @http.route('/school/attendance/confirm', type='json', auth='user')
    def confirm(self, token, latitude, longitude, device_fingerprint, accuracy=0):
        """Appelé en JS après géolocalisation. L'étudiant est déduit de
        l'utilisateur connecté, jamais transmis par le client."""
        student = request.env['school.student'].sudo().search(
            [('user_id', '=', request.env.user.id)], limit=1
        )
        if not student:
            return {'error': "Aucun profil étudiant associé à ce compte."}

        try:
            return request.env['school.attendance.record'].sudo().register_scan(
                room_token=token,
                student_id=student.id,
                latitude=float(latitude),
                longitude=float(longitude),
                device_fingerprint=device_fingerprint,
                accuracy=accuracy,
                client_ip=self._get_client_ip(),
            )
        except Exception as e:
            return {'error': str(e)}
