from odoo import http
from odoo.http import request

from .main import device_options, verify_device


class SchoolRelayController(http.Controller):
    """Interface du responsable (enseignant ou délégué) : confirmer, avec SA
    propre empreinte, la présence des étudiants sans téléphone utilisable."""

    def _records(self):
        return request.env['school.attendance.record'].sudo()

    @http.route('/presence/relais', type='http', auth='user', website=True)
    def relay_page(self, **kw):
        Record = self._records()
        user = request.env.user
        holder = Record.relay_holder(user)
        if not holder:
            return request.render('school_attendance_qr.portal_relay_denied', {})
        sessions = []
        for session in Record.relay_actor_sessions(user):
            phase, eligible = Record.relay_eligible_students(session)
            used, limit = Record.relay_quota(session, user)
            sessions.append({'session': session, 'phase': phase, 'students': eligible,
                             'used': used, 'limit': limit})
        return request.render('school_attendance_qr.portal_relay', {
            'sessions': sessions, 'holder': holder, 'active_nav': 'relay',
        })

    @http.route('/presence/relais/options', type='json', auth='user')
    def relay_webauthn_options(self):
        holder = self._records().relay_holder(request.env.user)
        if not holder:
            return {'error': "Vous n'êtes pas autorisé(e) à relayer des présences."}
        return device_options(holder)

    def _verify_holder(self, webauthn_mode, webauthn_credential):
        holder = self._records().relay_holder(request.env.user)
        if not holder:
            return "Vous n'êtes pas autorisé(e) à relayer des présences."
        return verify_device(holder, webauthn_mode, webauthn_credential)

    @http.route('/presence/relais/confirmer', type='json', auth='user')
    def relay_confirm(self, session_id, student_id, matricule, identifiant, latitude, longitude,
                      webauthn_mode, webauthn_credential, accuracy=0):
        error = self._verify_holder(webauthn_mode, webauthn_credential)
        if error:
            return {'error': error}
        env = request.env
        try:
            return self._records().register_relay(
                env['school.attendance.session'].sudo().browse(int(session_id)),
                env['school.student'].sudo().browse(int(student_id)),
                matricule, identifiant, float(latitude), float(longitude), accuracy, env.user)
        except Exception as e:
            return {'error': str(e)}

    @http.route('/presence/relais/comptage', type='json', auth='user')
    def relay_headcount(self, session_id, headcount):
        session = request.env['school.attendance.session'].sudo().browse(int(session_id))
        if session not in self._records().relay_actor_sessions(request.env.user) and not (
                session.exists() and session.teacher_id.user_id == request.env.user):
            return {'error': "Vous n'êtes pas responsable de cette séance."}
        try:
            return session.submit_headcount(headcount, request.env.user)
        except Exception as e:
            return {'error': str(e)}
