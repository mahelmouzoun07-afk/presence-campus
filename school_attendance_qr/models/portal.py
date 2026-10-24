from odoo import api, fields, models


class SchoolStudentPortal(models.Model):
    """Ce dont le portail étudiant (tableau de bord, emploi du temps,
    historique) a besoin, calculé pour l'étudiant connecté."""
    _inherit = 'school.student'

    def find_current_session(self):
        """La séance où CET étudiant doit confirmer sa présence maintenant
        (entrée ou sortie ouverte), déduite automatiquement de ses
        inscriptions — sans qu'il ait besoin de scanner un QR. Grâce à la
        règle anti-conflit d'emploi du temps, il ne peut y en avoir qu'une."""
        self.ensure_one()
        now = fields.Datetime.now()
        Session = self.env['school.attendance.session'].sudo()
        candidates = Session.search([
            ('course_id', 'in', self.sudo().course_ids.ids), ('time_start', '<=', now),
        ], order='time_start desc')
        for session in candidates:
            if session.is_within_checkin_window() or session.is_within_checkout_window():
                return session
        return Session

    def find_next_session(self):
        """Le prochain cours à venir (information seulement, pas d'action possible)."""
        self.ensure_one()
        now = fields.Datetime.now()
        return self.env['school.attendance.session'].sudo().search([
            ('course_id', 'in', self.sudo().course_ids.ids), ('time_start', '>', now),
        ], order='time_start asc', limit=1)

    def upcoming_week_sessions(self):
        """Les séances de la semaine en cours, pour l'écran « Emploi du temps »."""
        self.ensure_one()
        from datetime import timedelta
        today = fields.Date.context_today(self)
        week_start = today - timedelta(days=today.weekday())
        week_end = week_start + timedelta(days=6)
        return self.env['school.attendance.session'].sudo().search([
            ('course_id', 'in', self.sudo().course_ids.ids), ('date', '>=', week_start), ('date', '<=', week_end),
        ], order='time_start asc')

    def missed_sessions(self, limit=200):
        """La liste des séances manquées par cet étudiant (pour l'onglet
        « Mes absences » du profil) : séances passées de ses cours, sans
        présence valide enregistrée."""
        self.ensure_one()
        today = fields.Date.context_today(self)
        Session = self.env['school.attendance.session'].sudo()
        sessions = Session.search([
            ('course_id', 'in', self.sudo().course_ids.ids), ('date', '<=', today),
        ], order='time_start desc', limit=limit)
        return sessions.filtered(
            lambda s: not s.record_ids.filtered(lambda r: r.student_id == self and r.state != 'rejected'))
