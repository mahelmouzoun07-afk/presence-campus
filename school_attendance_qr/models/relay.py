import random
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .helpers import icp, icp_int

PROOF_LEVELS = [
    ('A', "Téléphone de l'étudiant"),
    ('B', "Relayée par un responsable"),
    ('C', "Validée hors ligne"),
]


class SchoolStudentRelay(models.Model):
    _inherit = 'school.student'

    no_phone = fields.Boolean(
        string="Sans téléphone utilisable",
        help="Pas de téléphone, ou téléphone incapable de la vérification sécurisée (trop ancien). "
             "Seuls ces étudiants peuvent voir leur présence confirmée par un responsable.")
    is_delegate = fields.Boolean(string="Délégué(e)",
                                 help="Peut relayer la présence des étudiants sans téléphone de ses cours.")


class SchoolTeacherWebAuthn(models.Model):
    """L'enseignant confirme les présences relayées avec SA propre empreinte."""
    _inherit = 'school.teacher'

    webauthn_credential_id = fields.Char(readonly=True, copy=False, groups='school_base.group_school_admin')
    webauthn_public_key = fields.Char(readonly=True, copy=False, groups='school_base.group_school_admin')
    webauthn_sign_count = fields.Integer(readonly=True, default=0, copy=False, groups='school_base.group_school_admin')
    webauthn_registered_at = fields.Datetime(readonly=True, copy=False, string="Clé d'appareil enregistrée le")

    def action_reset_webauthn(self):
        self.sudo().write({'webauthn_credential_id': False, 'webauthn_public_key': False,
                           'webauthn_sign_count': 0, 'webauthn_registered_at': False})


class SchoolAttendanceRecordRelay(models.Model):
    _inherit = 'school.attendance.record'

    proof_level = fields.Selection(PROOF_LEVELS, default='A', required=True, readonly=True,
                                   string="Niveau de preuve")
    relayed_by_user_id = fields.Many2one('res.users', readonly=True, string="Relayée par")
    relay_label = fields.Char(readonly=True, string="Responsable du relais")

    # ------------------------------------------------------------ relais
    @api.model
    def relay_actor_sessions(self, user):
        """Séances où `user` peut relayer MAINTENANT (fenêtre d'entrée ou de
        sortie ouverte), selon le réglage « qui peut relayer »."""
        mode = icp(self.env, 'relay_actor', 'both')
        Session = self.env['school.attendance.session'].sudo()
        sessions = Session.browse()
        now = fields.Datetime.now()
        if mode in ('teacher', 'both'):
            teacher = self.env['school.teacher'].sudo().search([('user_id', '=', user.id)], limit=1)
            if teacher:
                sessions |= Session.search([('teacher_id', '=', teacher.id), ('time_start', '<=', now),
                                            ('time_start', '>=', now - timedelta(hours=8))])
        if mode in ('delegate', 'both'):
            delegate = self.env['school.student'].sudo().search(
                [('user_id', '=', user.id), ('is_delegate', '=', True)], limit=1)
            if delegate:
                sessions |= Session.search([('course_id', 'in', delegate.course_ids.ids), ('time_start', '<=', now),
                                            ('time_start', '>=', now - timedelta(hours=8))])
        return sessions.filtered(lambda s: s.is_within_checkin_window() or s.is_within_checkout_window())

    @api.model
    def relay_holder(self, user):
        """L'enregistrement qui porte la clé WebAuthn du responsable."""
        teacher = self.env['school.teacher'].sudo().search([('user_id', '=', user.id)], limit=1)
        if teacher and icp(self.env, 'relay_actor', 'both') in ('teacher', 'both'):
            return teacher
        return self.env['school.student'].sudo().search(
            [('user_id', '=', user.id), ('is_delegate', '=', True)], limit=1)

    @api.model
    def relay_eligible_students(self, session):
        """Liste FERMÉE : uniquement les inscrits marqués « sans téléphone »
        par l'administration, jamais la liste complète du cours."""
        phase = 'checkout' if (session.is_within_checkout_window() and not session.is_within_checkin_window()) else 'checkin'
        students = session.course_id.sudo().student_ids.filtered('no_phone')
        records = session.sudo().record_ids
        if phase == 'checkin':
            done = records.filtered(lambda r: r.state != 'rejected').mapped('student_id')
        else:
            done = records.filtered(lambda r: r.checkout_state != 'not_done').mapped('student_id')
            students = students & records.filtered(lambda r: r.state != 'rejected').mapped('student_id')
        return phase, students - done

    @api.model
    def relay_quota(self, session, user):
        limit = icp_int(self.env, 'relay_max_per_session', 3)
        used = self.sudo().search_count([('session_id', '=', session.id), ('relayed_by_user_id', '=', user.id)])
        return used, limit

    @api.model
    def register_relay(self, session, student, matricule, identifiant, latitude, longitude, accuracy, user):
        """Enregistre une présence confirmée par un responsable pour un
        étudiant sans téléphone. La vérification WebAuthn du responsable est
        faite AVANT, par le contrôleur."""
        session = session.sudo()
        if session not in self.relay_actor_sessions(user):
            raise ValidationError(_("Vous n'êtes pas responsable de cette séance, ou elle n'est pas ouverte."))
        if session.relay_blocked:
            raise ValidationError(_("Les relais sont bloqués pour cette séance : le comptage des têtes était incohérent."))
        phase, eligible = self.relay_eligible_students(session)
        if student not in eligible:
            raise ValidationError(_("Cet étudiant n'est pas dans la liste des étudiants sans téléphone à confirmer."))
        if (matricule or '').strip() != student.matricule or (identifiant or '').strip().lower() != student.identifiant.lower():
            raise ValidationError(_("Le matricule ou l'identifiant saisi ne correspond pas à cet étudiant."))
        used, limit = self.relay_quota(session, user)
        if phase == 'checkin' and used >= limit:
            raise ValidationError(_("Quota atteint : %(limit)s relais maximum par séance.", limit=limit))

        accuracy = max(float(accuracy or 0.0), 0.0)
        distance, state, reason = self._evaluate_distance(session.room_id, latitude, longitude, accuracy)
        label = user.name
        now = fields.Datetime.now()
        if phase == 'checkin':
            record = self.sudo().search([('session_id', '=', session.id), ('student_id', '=', student.id)], limit=1)
            vals = {
                'session_id': session.id, 'student_id': student.id, 'scan_datetime': now,
                'device_fingerprint': f'relais-{user.id}', 'latitude': latitude, 'longitude': longitude,
                'accuracy': accuracy, 'distance_meters': distance, 'state': state, 'flag_reason': reason,
                'proof_level': 'B', 'relayed_by_user_id': user.id, 'relay_label': label,
            }
            if record:
                record.write(vals)
            else:
                record = self.sudo().create(vals)
        else:
            record = self.sudo().search([('session_id', '=', session.id), ('student_id', '=', student.id)], limit=1)
            record.write({
                'checkout_scan_datetime': now, 'checkout_latitude': latitude, 'checkout_longitude': longitude,
                'checkout_distance_meters': distance, 'checkout_accuracy': accuracy,
                'checkout_state': state, 'checkout_flag_reason': reason,
            })
        self._relay_controls(record, student, user)
        self.env['school.audit.log'].log(
            'presence_relayed', f"{'Entrée' if phase == 'checkin' else 'Sortie'} « {session.course_id.name} » "
                                f"relayée par {label}.", student=student, record=record)
        return {'phase': phase, 'state': record.state if phase == 'checkin' else record.checkout_state,
                'student': student.name}

    def _relay_controls(self, record, student, user):
        Task = self.env['school.attendance.task']
        rate = icp_int(self.env, 'relay_audit_rate', 20)
        if random.randint(1, 100) <= rate:
            task = Task.create_unique('relay_audit', student, f"Contrôle aléatoire : {student.name}",
                                      f"Présence relayée par {user.name} tirée au sort : vérifiez en personne que "
                                      "l'étudiant était bien en cours.", record=record)
            teacher_user = record.session_id.teacher_id.user_id
            if teacher_user and teacher_user != user and not task.assigned_user_id:
                task.assigned_user_id = teacher_user
        threshold = icp_int(self.env, 'relay_pattern_threshold', 5)
        recent = self.sudo().search_count([
            ('student_id', '=', student.id), ('relayed_by_user_id', '=', user.id),
            ('scan_datetime', '>=', fields.Datetime.now() - timedelta(days=30))])
        if recent >= threshold:
            Task.create_unique('relay_pattern', student, f"Relais répétés : {student.name}",
                               f"{recent} présences de cet étudiant relayées par {user.name} en 30 jours.")


class SchoolAttendanceSessionRelay(models.Model):
    _inherit = 'school.attendance.session'

    relayed_count = fields.Integer(compute='_compute_relayed_count', string="Présences relayées")
    headcount_declared = fields.Integer(readonly=True, string="Têtes comptées")
    headcount_by = fields.Many2one('res.users', readonly=True, string="Comptées par")
    headcount_mismatch = fields.Boolean(readonly=True, string="Comptage incohérent")
    relay_blocked = fields.Boolean(readonly=True, string="Relais bloqués")

    def _compute_relayed_count(self):
        for rec in self:
            rec.relayed_count = len(rec.record_ids.filtered(lambda r: r.proof_level == 'B'))

    def submit_headcount(self, headcount, user):
        """Conservation des têtes : l'effectif réel compté dans la salle ne peut
        pas être inférieur au nombre de présents enregistrés (téléphones +
        relais). Sinon : blocage des relais, présences relayées « à vérifier »
        et signalement à la direction."""
        self.ensure_one()
        session = self.sudo()
        if headcount is None or int(headcount) < 0:
            raise UserError(_("Indiquez le nombre de personnes réellement présentes dans la salle."))
        headcount = int(headcount)
        present = session.record_ids.filtered(lambda r: r.state != 'rejected')
        vals = {'headcount_declared': headcount, 'headcount_by': user.id}
        mismatch = len(present) > headcount
        if mismatch:
            vals.update({'headcount_mismatch': True, 'relay_blocked': True})
            reason = f"Comptage incohérent : {len(present)} présents enregistrés pour {headcount} têtes comptées"
            present.filtered(lambda r: r.proof_level == 'B')._flag('checkin', reason)
            self.env['school.attendance.task'].create_unique(
                'headcount', self.env['school.student'], f"Comptage incohérent : {session.course_id.name} ({session.date})",
                reason + f" (compté par {user.name}).", session=session)
        session.write(vals)
        self.env['school.audit.log'].log(
            'headcount', f"« {session.course_id.name} » : {headcount} têtes comptées par {user.name}, "
                         f"{len(present)} présents enregistrés.", record=session)
        return {'mismatch': mismatch, 'present': len(present), 'headcount': headcount}

    @api.model
    def _cron_missing_headcounts(self):
        """Une séance avec des présences relayées doit être clôturée par un
        comptage des têtes ; sinon, elle part dans « À traiter »."""
        now = fields.Datetime.now()
        for session in self.sudo().search([('time_start', '>=', now - timedelta(days=2)),
                                           ('headcount_by', '=', False)]):
            if session.relayed_count and now > session.time_end + timedelta(minutes=session.checkout_window_minutes):
                relayed = session.record_ids.filtered(lambda r: r.proof_level == 'B')
                self.env['school.attendance.task'].create_unique(
                    'headcount', self.env['school.student'], f"Comptage des têtes manquant : {session.course_id.name}",
                    f"Séance du {session.date} : {len(relayed)} présence(s) relayée(s) sans comptage final.",
                    session=session)
