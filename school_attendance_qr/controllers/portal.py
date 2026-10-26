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
        today = fields.Date.context_today(request.env.user)
        close_at = False
        if current:
            from datetime import timedelta as _td
            close = current.time_start + _td(minutes=current.checkin_window_minutes) if phase_hint == 'checkin' \
                else current.time_end + _td(minutes=current.checkout_window_minutes)
            close_at = close.isoformat() + 'Z'
        return request.render('school_attendance_qr.portal_dashboard', dict(
            self._home_values(student), session=current, next_session=next_session,
            token=current.room_id.qr_token if current else False, phase_hint=phase_hint,
            today_label=_format_date_fr(today), close_at=close_at,
            rate_label=f"{student.attendance_rate:.1f} %",
            student=student,
        ))

    def _home_values(self, student):
        """Données supplémentaires de l'accueil (moyenne, dernière note, échéances,
        nombre de cours du jour). Les modules Études et Stages n'étant pas
        toujours présents, on reste tolérant si leurs modèles sont absents."""
        env = request.env
        today = fields.Date.context_today(env.user)
        count_today = env['school.attendance.session'].sudo().search_count([
            ('course_id', 'in', student.sudo().course_ids.ids), ('date', '=', today)])
        values = {
            'today_count': count_today, 'moyenne': None, 'moyenne_scale': 20, 'moyenne_link': '/presence/profil',
            'latest_note': False, 'upcoming_events': [],
        }
        Grade = env.get('school.grade')
        if Grade is not None:
            Period = env['school.academic.period']
            period = Period.sudo().current() if 'current' in dir(Period) else Period
            try:
                res = student.compute_results(period or None) if hasattr(student, 'compute_results') else None
            except Exception:
                res = None
            if res and res.get('general') is not None:
                moy = res['general']
                values['moyenne'] = f"{moy:.2f}".rstrip('0').rstrip('.').replace('.', ',')
                values['moyenne_scale'] = res['scale']
                values['moyenne_link'] = '/presence/notes'
            latest = Grade.sudo().search([('student_id', '=', student.id), ('state', '=', 'published'),
                                           ('is_graded', '=', True)], order='write_date desc', limit=1)
            if latest:
                values['latest_note'] = f"{latest.evaluation_id.name} {latest.score:g}".replace('.', ',')
        Event = env.get('school.academic.event')
        if Event is not None:
            from datetime import timedelta as _td
            now = fields.Datetime.now()
            events = Event.sudo().for_student(student, now, now + _td(days=14))[:3]
            _days = ['LUN', 'MAR', 'MER', 'JEU', 'VEN', 'SAM', 'DIM']
            for ev in events:
                day = fields.Date.to_date(
                    env['school.attendance.session'].fmt_local(ev.date_start, '%Y-%m-%d'))
                values['upcoming_events'].append({
                    'day_label': _days[day.weekday()], 'day_num': day.day,
                    'title': ev.name,
                    'sub': f"{dict(ev._fields['event_type'].selection).get(ev.event_type, '')}"
                           + (f" · {ev.course_id.name}" if ev.course_id else ''),
                    'level': {'high': 'bad', 'normal': 'warn', 'low': 'muted'}.get(ev.importance, 'muted'),
                })
        return values

    @http.route('/presence/emploi-du-temps', type='http', auth='user', website=True)
    def portal_timetable(self, **kw):
        student, response = portal_gate()
        if response:
            return response
        return request.render('school_attendance_qr.portal_timetable', dict(
            self._timetable_values(student), student=student))

    def _timetable_values(self, student):
        """Semaine courante (lundi → dimanche) et liste des cours par jour, avec
        pour chaque cours son statut (présent/absent/à venir/en cours/examen)."""
        from datetime import timedelta as _td
        today = fields.Date.context_today(request.env.user)
        monday = today - _td(days=today.weekday())
        _labels = ['Lun', 'Mar', 'Mer', 'Jeu', 'Ven', 'Sam', 'Dim']
        _titles = ['LUNDI', 'MARDI', 'MERCREDI', 'JEUDI', 'VENDREDI', 'SAMEDI', 'DIMANCHE']
        _months = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août',
                   'septembre', 'octobre', 'novembre', 'décembre']
        Session = request.env['school.attendance.session'].sudo()
        now = fields.Datetime.now()
        week = []
        for i in range(7):
            day = monday + _td(days=i)
            sessions = Session.search([
                ('course_id', 'in', student.sudo().course_ids.ids), ('date', '=', day),
            ], order='time_start')
            items = []
            for s in sessions:
                color = 'var(--muted)'
                status = 'À venir'
                record = s.record_ids.filtered(lambda r: r.student_id == student)[:1]
                if s.time_start <= now <= (s.time_end or s.time_start):
                    color, status = 'var(--accent)', 'En cours'
                elif record and record.state == 'rejected':
                    color, status = 'var(--bad)', 'Refusée'
                elif record and record.attendance_complete:
                    color, status = 'var(--ok)', 'Présent'
                elif s.time_end and s.time_end < now:
                    color, status = 'var(--bad)', 'Absent'
                items.append({
                    'start': Session.fmt_local(s.time_start, '%Hh%M'),
                    'end': Session.fmt_local(s.time_end, '%Hh%M') if s.time_end else '',
                    'name': s.course_id.name,
                    'place': f"{s.room_id.name} · {s.teacher_id.name}" if s.teacher_id else s.room_id.name,
                    'status': status, 'color': color,
                })
            key = day.strftime('%Y-%m-%d')
            week.append({
                'key': key, 'label': _labels[i], 'num': day.day, 'today': day == today,
                'has': bool(items), 'items': items,
                'title': f"{_titles[i]} {day.day} {_months[day.month - 1].upper()}",
            })
        return {'week': week}

    @http.route('/presence/profil', type='http', auth='user', website=True)
    def portal_profile(self, **kw):
        student, response = portal_gate()
        if response:
            return response
        # scolarité : visible seulement si l'étudiant doit encore quelque chose
        payment_status, payment_color = False, 'var(--muted)'
        try:
            balance = student.sudo().fees_balance
            if balance and balance > 0 and not student.sudo().fees_exempt:
                payment_status = f"Reste {balance:,.0f} {student.currency_id.symbol or ''}".replace(',', ' ')
                payment_color = 'var(--warn)'
        except Exception:
            pass
        return request.render('school_attendance_qr.portal_profile', dict(
            self._home_values(student), student=student,
            rate_label=f"{student.attendance_rate:.1f} %",
            payment_status=payment_status, payment_color=payment_color,
        ))

    @http.route('/presence/attestations', type='http', auth='user', website=True)
    def portal_certificates(self, **kw):
        """Liste des attestations déjà émises pour cet étudiant."""
        student, response = portal_gate()
        if response:
            return response
        certs = request.env['school.attendance.certificate'].sudo().search(
            [('student_id', '=', student.id)], order='issue_date desc')
        return request.render('school_attendance_qr.portal_certificates', {'student': student, 'certs': certs})

    @http.route('/presence/mes-absences', type='http', auth='user', website=True)
    def portal_absences(self, **kw):
        student, response = portal_gate()
        if response:
            return response
        return request.render('school_attendance_qr.portal_absences', {
            'student': student, 'missed': student.missed_sessions(), 'fmt_date': _format_date_fr,
        })
