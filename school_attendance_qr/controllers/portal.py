from odoo import fields, http
from odoo.addons.portal.controllers.portal import CustomerPortal
from odoo.addons.portal.controllers.web import Home
from odoo.http import request

_JOURS = ['Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi', 'Samedi', 'Dimanche']
_MOIS = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août',
        'septembre', 'octobre', 'novembre', 'décembre']


def _format_date_fr(d):
    """Évite de dépendre de la locale du serveur (souvent en anglais sur un
    serveur fraîchement installé) pour afficher une date en français."""
    return f"{_JOURS[d.weekday()]} {d.day} {_MOIS[d.month - 1]}"


def current_student():
    return request.env['school.student'].sudo().search([('user_id', '=', request.env.uid)], limit=1)


def portal_gate():
    """Contrôle commun à toutes les pages du portail étudiant. Renvoie
    (étudiant, réponse) : si la réponse n'est pas vide, la page doit la
    renvoyer telle quelle (pas de profil, ou mot de passe à changer d'abord)."""
    student = current_student()
    if not student:
        return student, request.render('school_attendance_qr.portal_no_student', {})
    if student.must_change_password:
        return student, request.redirect('/presence/mot-de-passe')
    return student, None


def _is_student(uid):
    return bool(uid) and bool(request.env['school.student'].sudo().search_count([('user_id', '=', uid)]))


class SchoolHome(Home):
    """Sans ça, Odoo envoie tout utilisateur portail sur son portail
    générique /my après connexion : c'était « l'ancienne interface » que
    voyaient les étudiants au lieu du portail de présence."""

    def _login_redirect(self, uid, redirect=None):
        if not redirect and _is_student(uid):
            redirect = '/presence'
        return super()._login_redirect(uid, redirect=redirect)


class SchoolCustomerPortal(CustomerPortal):

    @http.route()
    def home(self, **kw):
        # /, /odoo et /web renvoient les utilisateurs portail vers /my : on les rattrape ici
        if _is_student(request.env.uid):
            return request.redirect('/presence')
        return super().home(**kw)

    @http.route('/presence/mot-de-passe', type='http', auth='user', website=True, methods=['GET', 'POST'])
    def portal_change_password(self, **post):
        """Changement du mot de passe de départ (le matricule), obligatoire
        à la première connexion, et possible ensuite depuis le profil."""
        student = current_student()
        if not student:
            return request.render('school_attendance_qr.portal_no_student', {})
        values = {'student': student, 'forced': student.must_change_password, 'error': False, 'done': False}
        if request.httprequest.method == 'POST':
            old, new1, new2 = post.get('old', ''), post.get('new1', '').strip(), post.get('new2', '').strip()
            if len(new1) < 8:
                values['error'] = "Le nouveau mot de passe doit contenir au moins 8 caractères."
            elif new1.lower() in {student.matricule.lower(), student.identifiant.lower()}:
                values['error'] = "Le nouveau mot de passe ne doit pas être votre matricule ni votre identifiant."
            else:
                result = self._update_password(old, new1, new2)
                if result.get('errors'):
                    err = result['errors']['password']
                    # messages d'Odoo en anglais selon la langue du compte : on les reformule
                    if isinstance(err, dict) and 'old' in err:
                        values['error'] = "Le mot de passe actuel est incorrect : votre mot de passe n'a pas été changé."
                    elif isinstance(err, dict) and 'new2' in err:
                        values['error'] = "Les deux nouveaux mots de passe ne sont pas identiques."
                    else:
                        values['error'] = next(iter(err.values())) if isinstance(err, dict) else err
                else:
                    student.write({'must_change_password': False})
                    request.env['school.audit.log'].log('password_changed', "Mot de passe personnel choisi.",
                                                        student=student)
                    return request.redirect('/presence')
        return request.render('school_attendance_qr.portal_password', values)


class SchoolPortalController(http.Controller):

    @http.route('/presence', type='http', auth='user', website=True)
    def portal_dashboard(self, **kw):
        student, response = portal_gate()
        if response:
            return response
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
        student, response = portal_gate()
        if response:
            return response
        sessions = student.upcoming_week_sessions()
        by_day = {}
        for sess in sessions:
            by_day.setdefault(sess.date, []).append(sess)
        return request.render('school_attendance_qr.portal_timetable', {
            'student': student, 'days': sorted(by_day.items()), 'fmt_date': _format_date_fr,
        })

    @http.route('/presence/profil', type='http', auth='user', website=True)
    def portal_profile(self, **kw):
        student, response = portal_gate()
        if response:
            return response
        return request.render('school_attendance_qr.portal_profile', {
            'student': student, 'rate_label': f"{student.attendance_rate:.1f} %",
        })

    @http.route('/presence/mes-absences', type='http', auth='user', website=True)
    def portal_absences(self, **kw):
        student, response = portal_gate()
        if response:
            return response
        return request.render('school_attendance_qr.portal_absences', {
            'student': student, 'missed': student.missed_sessions(), 'fmt_date': _format_date_fr,
        })
