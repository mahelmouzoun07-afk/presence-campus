from odoo import fields, http
from odoo.http import request

_JOURS = ['Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi', 'Samedi', 'Dimanche']
_MOIS = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août',
        'septembre', 'octobre', 'novembre', 'décembre']


def _format_date_fr(d):
    """Évite de dépendre de la locale du serveur (souvent en anglais sur un
    serveur fraîchement installé) pour afficher une date en français."""
    return f"{_JOURS[d.weekday()]} {d.day} {_MOIS[d.month - 1]}"


class SchoolPortalController(http.Controller):

    def _current_student(self):
        return request.env['school.student'].sudo().search(
            [('user_id', '=', request.env.user.id)], limit=1)

    @http.route('/presence', type='http', auth='user', website=True)
    def portal_dashboard(self, **kw):
        student = self._current_student()
        if not student:
            return request.render('school_attendance_qr.portal_no_student', {})
        current = student.find_current_session()
        next_session = False if current else student.find_next_session()
        phase_hint = 'checkin'
        if current and current.is_within_checkout_window() and not current.is_within_checkin_window():
            phase_hint = 'checkout'
        return request.render('school_attendance_qr.portal_dashboard', {
            'student': student, 'session': current, 'next_session': next_session,
            'token': current.room_id.qr_token if current else False, 'phase_hint': phase_hint,
            'today_label': _format_date_fr(fields.Date.context_today(request.env.user)),
            'rate_label': f"{student.attendance_rate:.1f} %",
        })

    @http.route('/presence/emploi-du-temps', type='http', auth='user', website=True)
    def portal_timetable(self, **kw):
        student = self._current_student()
        if not student:
            return request.render('school_attendance_qr.portal_no_student', {})
        sessions = student.upcoming_week_sessions()
        by_day = {}
        for sess in sessions:
            by_day.setdefault(sess.date, []).append(sess)
        return request.render('school_attendance_qr.portal_timetable', {
            'student': student, 'days': sorted(by_day.items()), 'fmt_date': _format_date_fr,
        })

    @http.route('/presence/profil', type='http', auth='user', website=True)
    def portal_profile(self, **kw):
        student = self._current_student()
        if not student:
            return request.render('school_attendance_qr.portal_no_student', {})
        return request.render('school_attendance_qr.portal_profile', {
            'student': student, 'rate_label': f"{student.attendance_rate:.1f} %",
        })

    @http.route('/presence/mes-absences', type='http', auth='user', website=True)
    def portal_absences(self, **kw):
        student = self._current_student()
        if not student:
            return request.render('school_attendance_qr.portal_no_student', {})
        return request.render('school_attendance_qr.portal_absences', {
            'student': student, 'missed': student.missed_sessions(), 'fmt_date': _format_date_fr,
        })
