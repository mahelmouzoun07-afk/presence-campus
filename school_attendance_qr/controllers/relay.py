import json

from odoo import http
from odoo.http import request

from ..models import webauthn_helper as wa


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
        holder = holder.sudo()
        if holder.webauthn_credential_id:
            return {'mode': 'authenticate', 'options': json.loads(
                wa.build_authentication_options(request.session, request.httprequest, holder))}
        return {'mode': 'register', 'options': json.loads(wa.build_registration_options(
            request.session, request.httprequest, holder, request.env.company.name))}

    def _verify_holder(self, webauthn_mode, webauthn_credential):
        holder = self._records().relay_holder(request.env.user).sudo()
        if not holder:
            return "Vous n'êtes pas autorisé(e) à relayer des présences."
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
