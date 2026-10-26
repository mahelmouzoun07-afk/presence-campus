from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from odoo.addons.school_attendance_qr.models.relay import PROOF_LEVELS

STATES = [('valid', 'Validée'), ('flagged', 'À vérifier'), ('rejected', 'Refusée')]


class SchoolInternshipAttendance(models.Model):
    """Une garde : entrée + sortie confirmées par l'étudiant (GPS + WebAuthn),
    puis validées par un superviseur du site (WebAuthn du superviseur)."""
    _name = 'school.internship.attendance'
    _description = 'Garde de stage'
    _order = 'checkin_time desc'

    period_id = fields.Many2one('school.internship.period', required=True, ondelete='cascade', index=True)
    student_id = fields.Many2one(related='period_id.student_id', store=True, string="Étudiant")
    site_id = fields.Many2one(related='period_id.site_id', store=True, string="Site")
    checkin_time = fields.Datetime(readonly=True, string="Entrée")
    checkin_lat = fields.Float(digits=(10, 7), readonly=True)
    checkin_lng = fields.Float(digits=(10, 7), readonly=True)
    checkin_accuracy = fields.Float(readonly=True)
    checkin_distance = fields.Float(readonly=True)
    checkin_device_id = fields.Char(readonly=True)
    checkin_state = fields.Selection(STATES, readonly=True, string="État entrée")
    checkout_time = fields.Datetime(readonly=True, string="Sortie")
    checkout_lat = fields.Float(digits=(10, 7), readonly=True)
    checkout_lng = fields.Float(digits=(10, 7), readonly=True)
    checkout_accuracy = fields.Float(readonly=True)
    checkout_distance = fields.Float(readonly=True)
    checkout_state = fields.Selection(STATES, readonly=True, string="État sortie")
    flag_reason = fields.Char(readonly=True, string="Motif")
    student_confirmed = fields.Boolean(readonly=True, string="Confirmée par l'étudiant")
    supervisor_id = fields.Many2one('school.teacher', readonly=True, string="Superviseur")
    supervisor_confirmed = fields.Boolean(readonly=True, string="Validée par le superviseur")
    supervisor_confirmed_at = fields.Datetime(readonly=True)
    proof_level = fields.Selection(PROOF_LEVELS, default='A', readonly=True, string="Niveau de preuve")
    offline = fields.Boolean(readonly=True, string="Confirmée hors ligne")
    duration_hours = fields.Float(compute='_compute_duration', store=True, string="Durée (h)")
    is_validated = fields.Boolean(compute='_compute_duration', store=True, string="Comptée")
    evaluation_ids = fields.One2many('school.internship.evaluation', 'attendance_id', string="Évaluation")
    reminder_sent = fields.Boolean(readonly=True, copy=False)
    unvalidated_alert_sent = fields.Boolean(readonly=True, copy=False)

    @api.depends('checkin_time', 'checkout_time', 'student_confirmed', 'supervisor_confirmed',
                 'checkin_state', 'checkout_state')
    def _compute_duration(self):
        for rec in self:
            if rec.checkin_time and rec.checkout_time:
                rec.duration_hours = round((rec.checkout_time - rec.checkin_time).total_seconds() / 3600, 2)
            else:
                rec.duration_hours = 0.0
            rec.is_validated = bool(rec.student_confirmed and rec.supervisor_confirmed
                                    and rec.checkin_state != 'rejected' and rec.checkout_state != 'rejected')

    @api.model
    def register_student_scan(self, student, latitude, longitude, device_fingerprint, accuracy=0.0, at=None,
                              offline=False):
        """Entrée ou sortie de garde, selon qu'une garde est déjà ouverte.
        Réutilise TELS QUELS les contrôles des cours (school.attendance.record) :
        distance GPS, appareil lié au compte, politique de scolarité."""
        Record = self.env['school.attendance.record'].sudo()
        now = at or fields.Datetime.now()
        period = student.current_internship_period()
        if not period:
            raise ValidationError(_("Aucune période de stage en cours pour vous aujourd'hui."))
        payment_reason = Record._payment_policy_check(student)
        accuracy = max(float(accuracy or 0.0), 0.0)
        Record._check_device_binding(student, device_fingerprint)
        distance, state, reason = Record._evaluate_distance(period.site_id, latitude, longitude, accuracy)
        if state != 'rejected' and device_fingerprint != student.device_fingerprint:
            Record._log_device_attempt(student)
            raise ValidationError(_("Ce compte est associé à un autre appareil."))
        if state == 'rejected':
            other = self._site_at(latitude, longitude, accuracy, exclude=period.site_id)
            if other:  # présent sur un AUTRE site de stage que celui prévu
                state, reason = 'flagged', f"Confirmée sur « {other.name} » au lieu de « {period.site_id.name} »"
        if payment_reason and state != 'rejected':
            state, reason = 'flagged', Record._join_reasons(reason, payment_reason)
        shift = period.open_shift()
        if not shift:
            shift = self.sudo().create({
                'period_id': period.id, 'checkin_time': now, 'checkin_lat': latitude, 'checkin_lng': longitude,
                'checkin_accuracy': accuracy, 'checkin_distance': distance, 'checkin_device_id': device_fingerprint,
                'checkin_state': state, 'flag_reason': reason or False,
                'proof_level': 'C' if offline else 'A', 'offline': offline})
            phase = 'checkin'
        else:
            shift.write({
                'checkout_time': now, 'checkout_lat': latitude, 'checkout_lng': longitude,
                'checkout_accuracy': accuracy, 'checkout_distance': distance, 'checkout_state': state,
                'flag_reason': Record._join_reasons(shift.flag_reason, reason) or False,
                'student_confirmed': state != 'rejected',
                'proof_level': 'C' if (offline or shift.offline) else shift.proof_level,
                'offline': offline or shift.offline})
            phase = 'checkout'
        shift._after_scan(phase)
        return {'phase': phase, 'state': state, 'flag_reason': reason, 'course_name': period.site_id.name}

    @api.model
    def _site_at(self, latitude, longitude, accuracy, exclude=None):
        Record = self.env['school.attendance.record'].sudo()
        for site in self.env['school.internship.site'].sudo().search([('id', '!=', exclude.id if exclude else 0)]):
            if site.latitude or site.longitude:
                if Record._evaluate_distance(site, latitude, longitude, accuracy)[1] != 'rejected':
                    return site
        return self.env['school.internship.site']

    # ------------------------------------------------------ superviseur
    @api.model
    def supervisor_for_user(self, user):
        """Le superviseur (school.teacher) lié à cet utilisateur, s'il supervise
        au moins un site de stage."""
        teacher = self.env['school.teacher'].sudo().search([('user_id', '=', user.id)], limit=1)
        if teacher and self.env['school.internship.site'].sudo().search_count(
                [('supervisor_ids', 'in', teacher.id)]):
            return teacher
        return self.env['school.teacher']

    @api.model
    def pending_for_supervisor(self, teacher):
        """Gardes terminées et confirmées par l'étudiant, sur les sites de ce
        superviseur, qui attendent sa validation."""
        return self.sudo().search([
            ('site_id.supervisor_ids', 'in', teacher.id), ('student_confirmed', '=', True),
            ('supervisor_confirmed', '=', False), ('checkout_state', '!=', 'rejected')], order='checkout_time')

    def validate_by_supervisor(self, teacher, rating=False, comment=False, at=None, offline=False):
        """Double validation : le superviseur confirme la garde avec SA propre
        empreinte (vérifiée avant, par le contrôleur), et peut l'évaluer."""
        self.ensure_one()
        shift = self.sudo()
        if teacher not in shift.site_id.supervisor_ids:
            raise ValidationError(_("Vous n'êtes pas superviseur du site « %s ».", shift.site_id.name))
        if not shift.student_confirmed or shift.checkout_state == 'rejected':
            raise ValidationError(_("Cette garde n'a pas été terminée et confirmée par l'étudiant."))
        if shift.supervisor_confirmed:
            raise ValidationError(_("Cette garde est déjà validée."))
        shift.write({'supervisor_id': teacher.id, 'supervisor_confirmed': True,
                     'supervisor_confirmed_at': at or fields.Datetime.now(), 'proof_level': 'D'})
        if rating or (comment or '').strip():
            self.env['school.internship.evaluation'].sudo().create({
                'attendance_id': shift.id, 'supervisor_id': teacher.id,
                'rating': str(rating) if rating else False, 'comment': comment or False})
        self.env['school.audit.log'].log(
            'internship', f"Garde du {shift.checkin_time} ({shift.duration_hours:g} h, {shift.site_id.name}) "
                          f"validée par {teacher.name}{' hors ligne' if offline else ''}.",
            student=shift.student_id, record=shift)
        self.env['school.attendance.task'].sudo().search([
            ('internship_attendance_id', '=', shift.id), ('task_type', '=', 'internship_unvalidated'),
            ('state', '=', 'open')]).action_done()
        return {'ok': True, 'label': f"garde de {shift.student_id.name} validée"}

    def write(self, vals):
        """Seule l'administration peut corriger une garde à la main (les droits
        d'accès l'imposent) ; chaque correction manuelle est tracée."""
        watched = {'checkin_time', 'checkout_time', 'checkin_state', 'checkout_state', 'student_confirmed',
                   'supervisor_confirmed', 'period_id'} & set(vals)
        if watched and not self.env.su:
            for rec in self:
                self.env['school.audit.log'].log(
                    'internship', f"Correction manuelle de la garde du {rec.checkin_time} : "
                                  f"{', '.join(sorted(watched))}.", student=rec.student_id, record=rec)
        return super().write(vals)

    def _after_scan(self, phase):
        """Hook : contrôles d'anomalies et journal d'audit (voir anomalies.py)."""
        return True
