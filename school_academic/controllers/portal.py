import base64
from datetime import timedelta

from odoo import fields, http
from odoo.http import content_disposition, request

from odoo.addons.school_attendance_qr.controllers.portal import _format_date_fr, portal_gate
from odoo.addons.school_attendance_qr.models.helpers import icp_bool, local_time

from ..models.event import EVENT_TYPES


def _fmt_note(value):
    if value is None:
        return '—'
    return f"{value:.2f}".rstrip('0').rstrip('.').replace('.', ',')


class SchoolAcademicPortal(http.Controller):

    @http.route('/presence/etudes', type='http', auth='user', website=True)
    def studies(self, **kw):
        student, response = portal_gate()
        if response:
            return response
        now = fields.Datetime.now()
        upcoming = request.env['school.academic.event'].for_student(student, now, now + timedelta(days=14))
        results = student.compute_results(request.env['school.academic.period'].sudo().current())
        return request.render('school_academic.portal_studies', {
            'student': student, 'upcoming': upcoming[:5], 'general': _fmt_note(results['general']),
            'scale': results['scale'], 'doc_count': request.env['school.course.document'].sudo().search_count(
                [('course_id', 'in', student.sudo().course_ids.ids)]),
            'event_types': dict(EVENT_TYPES), 'fmt_date': _format_date_fr, 'active_nav': 'studies',
        })

    @http.route('/presence/notes', type='http', auth='user', website=True)
    def grades(self, period_id=None, **kw):
        student, response = portal_gate()
        if response:
            return response
        Period = request.env['school.academic.period'].sudo()
        periods = Period.search([])
        period = Period.browse(int(period_id)) if period_id and period_id.isdigit() else Period.current()
        results = student.compute_results(period if period.exists() else None)
        return request.render('school_academic.portal_grades', {
            'student': student, 'periods': periods, 'period': period, 'results': results, 'fmt': _fmt_note,
            'bulletin_allowed': icp_bool(request.env, 'bulletin_portal'), 'active_nav': 'studies',
        })

    @http.route('/presence/notes/bulletin', type='http', auth='user', website=True)
    def grades_bulletin(self, period_id=None, **kw):
        student, response = portal_gate()
        if response:
            return response
        if not icp_bool(request.env, 'bulletin_portal'):
            raise request.not_found()
        Period = request.env['school.academic.period'].sudo()
        period = Period.browse(int(period_id)) if period_id and str(period_id).isdigit() else Period.current()
        pdf = student.bulletin_pdf(period if period.exists() else None)
        return request.make_response(pdf, headers=[
            ('Content-Type', 'application/pdf'),
            ('Content-Disposition', content_disposition(f"Bulletin-{student.matricule}.pdf"))])

    @http.route('/presence/calendrier', type='http', auth='user', website=True)
    def calendar(self, **kw):
        student, response = portal_gate()
        if response:
            return response
        now = fields.Datetime.now()
        events = request.env['school.academic.event'].for_student(student, now - timedelta(days=7),
                                                                  now + timedelta(days=90))
        by_day = {}
        for event in events:  # regroupés par jour À L'HEURE DE L'ÉCOLE (pas en UTC)
            day = fields.Date.to_date(local_time(request.env, event.date_start, '%Y-%m-%d'))
            by_day.setdefault(day, []).append(event)
        today = fields.Date.to_date(local_time(request.env, now, '%Y-%m-%d'))
        return request.render('school_academic.portal_calendar', {
            'student': student, 'days': sorted(by_day.items()), 'today': today, 'fmt_date': _format_date_fr,
            'event_types': dict(EVENT_TYPES), 'active_nav': 'studies',
        })

    @http.route('/presence/documents', type='http', auth='user', website=True)
    def documents(self, **kw):
        student, response = portal_gate()
        if response:
            return response
        docs = request.env['school.course.document'].sudo().search(
            [('course_id', 'in', student.sudo().course_ids.ids)])
        by_course = {}
        for doc in docs:
            by_course.setdefault(doc.course_id, []).append(doc)
        return request.render('school_academic.portal_documents', {
            'student': student, 'courses': sorted(by_course.items(), key=lambda kv: kv[0].name),
            'active_nav': 'studies',
        })

    @http.route('/presence/documents/<int:doc_id>/<string:filename>', type='http', auth='user')
    def document_download(self, doc_id, filename=None, **kw):
        """Accès réservé aux étudiants inscrits au cours, à son enseignant et à
        l'administration. L'adresse reste sous /presence pour que l'application
        puisse garder le document hors ligne."""
        doc = request.env['school.course.document'].sudo().browse(doc_id)
        if not doc.exists():
            raise request.not_found()
        user = request.env.user
        allowed = (user.has_group('school_base.group_school_admin')
                   or doc.course_id.teacher_id.user_id == user
                   or doc.course_id.sudo().student_ids.filtered(lambda s: s.user_id == user))
        if not allowed:
            raise request.not_found()
        return request.make_response(base64.b64decode(doc.file), headers=[
            ('Content-Type', doc.mimetype or 'application/octet-stream'),
            ('Content-Disposition', content_disposition(doc.filename or 'document', disposition_type='inline')),
            ('Cache-Control', 'private, max-age=86400'), ('X-Content-Type-Options', 'nosniff')])
