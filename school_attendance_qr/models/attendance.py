import base64
import io
import math
import secrets
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError

from .helpers import icp, icp_bool, icp_int, local_time

DEFAULT_TZ = 'Africa/Porto-Novo'


def _haversine_meters(lat1, lon1, lat2, lon2):
    """Distance en mètres entre deux points GPS."""
    r = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _is_on_campus_network(env, ip):
    """Vérifie que l'IP du scan appartient aux réseaux autorisés, si la
    liste a été configurée (sinon, aucune restriction n'est appliquée).

    Limite importante : sur un Wi-Fi d'établissement, tous les appareils
    partagent en général la MÊME adresse IP publique côté Internet (un
    seul routeur partage sa connexion). Ce contrôle confirme donc que le
    scan vient bien du réseau de l'école, mais ne peut PAS distinguer un
    étudiant d'un autre sur ce même réseau — c'est le rôle de
    `device_fingerprint`, pas de l'IP."""
    import ipaddress
    raw = env['ir.config_parameter'].sudo().get_param('school_attendance_qr.campus_ip_ranges', '')
    ranges = [r.strip() for r in raw.split(',') if r.strip()]
    if not ranges or not ip:
        return True
    try:
        ip_obj = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for r in ranges:
        try:
            if '/' in r:
                if ip_obj in ipaddress.ip_network(r, strict=False):
                    return True
            elif ip == r:
                return True
        except ValueError:
            continue
    return False


class SchoolAttendanceSession(models.Model):
    """Une occurrence concrète de cours : tel jour, telle heure, dans telle
    salle. Générée automatiquement depuis l'emploi du temps par une tâche
    planifiée, ou créée à la main pour un cas ponctuel."""
    _name = 'school.attendance.session'
    _description = 'Séance de cours'
    _order = 'time_start desc'

    name = fields.Char(compute='_compute_name', store=True)
    slot_id = fields.Many2one('school.timetable.slot', string="Créneau d'origine", readonly=True)
    course_id = fields.Many2one('school.course', required=True)
    teacher_id = fields.Many2one('school.teacher', required=True)
    room_id = fields.Many2one('school.room', required=True)
    date = fields.Date(required=True, default=fields.Date.context_today)
    time_start = fields.Datetime(required=True, default=fields.Datetime.now)
    duration_minutes = fields.Integer(default=90, help="Durée prévue du cours")
    checkin_window_minutes = fields.Integer(default=15, string="Fenêtre d'entrée (min)",
                                            help="Durée pendant laquelle le scan d'entrée est accepté après le début")
    checkout_window_minutes = fields.Integer(default=15, string="Fenêtre de sortie (min)",
                                             help="Durée, avant et après la fin du cours, pendant laquelle le scan de sortie est accepté")
    time_end = fields.Datetime(compute='_compute_time_end')
    record_ids = fields.One2many('school.attendance.record', 'session_id')
    present_count = fields.Integer(compute='_compute_present_count')
    full_attendance_count = fields.Integer(compute='_compute_present_count', string="Présences complètes")
    enrolled_count = fields.Integer(compute='_compute_absents', string="Inscrits")
    absent_count = fields.Integer(compute='_compute_absents', string="Absents")
    absent_student_ids = fields.Many2many('school.student', compute='_compute_absents',
                                          string="Absents (pas encore scannés)")
    live_status = fields.Selection([
        ('upcoming', 'À venir'), ('checkin', 'Entrée ouverte'), ('ongoing', 'En cours'),
        ('checkout', 'Sortie ouverte'), ('done', 'Terminée'),
    ], compute='_compute_live_status', string="Statut")

    _sql_constraints = [
        ('slot_date_uniq', 'unique(slot_id, date)',
         "Une séance existe déjà pour ce créneau et cette date."),
    ]

    @api.depends('course_id', 'date')
    def _compute_name(self):
        for rec in self:
            rec.name = f"{rec.course_id.name} - {rec.date}"

    @api.onchange('course_id')
    def _onchange_course_id(self):
        if self.course_id and not self.teacher_id:
            self.teacher_id = self.course_id.teacher_id

    @api.depends('time_start', 'duration_minutes')
    def _compute_time_end(self):
        for rec in self:
            rec.time_end = (rec.time_start + timedelta(minutes=rec.duration_minutes)) if rec.time_start else False

    @api.depends('record_ids.state', 'record_ids.checkout_state')
    def _compute_present_count(self):
        for rec in self:
            checked_in = rec.record_ids.filtered(lambda r: r.state != 'rejected')
            rec.present_count = len(checked_in)
            rec.full_attendance_count = len(checked_in.filtered(lambda r: r.checkout_state != 'not_done'))

    @api.constrains('room_id', 'time_start', 'duration_minutes')
    def _check_room_not_double_booked(self):
        """Filet de sécurité au niveau des séances elles-mêmes (en plus du
        contrôle sur l'emploi du temps) : utile pour une séance créée à la
        main, ou si deux créneaux génèrent malgré tout un chevauchement."""
        for rec in self:
            end = rec.time_end
            others = self.search([('id', '!=', rec.id), ('room_id', '=', rec.room_id.id)])
            for other in others:
                if rec.time_start < other.time_end and other.time_start < end:
                    raise ValidationError(
                        f"La salle « {rec.room_id.name} » est déjà occupée par « {other.course_id.name} » "
                        f"sur ce créneau horaire.")

    @api.depends('record_ids.state', 'course_id.student_ids')
    def _compute_absents(self):
        for rec in self:
            enrolled = rec.course_id.sudo().student_ids
            present = rec.record_ids.filtered(lambda r: r.state != 'rejected').mapped('student_id')
            absent = enrolled - present
            rec.enrolled_count = len(enrolled)
            rec.absent_count = len(absent)
            rec.absent_student_ids = absent

    def _compute_live_status(self):
        now = fields.Datetime.now()
        for rec in self:
            if not rec.time_start or now < rec.time_start:
                rec.live_status = 'upcoming'
            elif rec.is_within_checkin_window():
                rec.live_status = 'checkin'
            elif rec.is_within_checkout_window():
                rec.live_status = 'checkout'
            elif now <= rec.time_end:
                rec.live_status = 'ongoing'
            else:
                rec.live_status = 'done'

    @api.model
    def fmt_local(self, dt, fmt='%Hh%M'):
        """Pour les gabarits du portail : heure locale de l'école."""
        return local_time(self.env, dt, fmt)

    def action_view_records(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Présences',
            'res_model': 'school.attendance.record',
            'view_mode': 'list,form',
            'domain': [('session_id', '=', self.id)],
        }

    def action_start_now(self):
        """Ouvre la fenêtre d'entrée maintenant. Un enseignant ne peut démarrer que ses propres séances."""
        for rec in self:
            if not (self.env.su or self.env.user.has_group('school_base.group_school_admin')
                    or rec.teacher_id.user_id == self.env.user):
                raise AccessError(_("Vous ne pouvez démarrer que vos propres séances."))
        self.sudo().write({'time_start': fields.Datetime.now()})

    def is_within_checkin_window(self, at=None):
        """`at` : instant à tester (par défaut maintenant) — sert aux
        confirmations hors ligne, vérifiées après coup à leur heure réelle."""
        self.ensure_one()
        now = at or fields.Datetime.now()
        return self.time_start <= now <= self.time_start + timedelta(minutes=self.checkin_window_minutes)

    def is_within_checkout_window(self, at=None):
        self.ensure_one()
        now = at or fields.Datetime.now()
        end = self.time_end
        return (end - timedelta(minutes=self.checkout_window_minutes)) <= now <= (end + timedelta(minutes=self.checkout_window_minutes))

    # Conservé pour compatibilité : "une fenêtre quelconque est ouverte"
    def is_within_window(self):
        self.ensure_one()
        return self.is_within_checkin_window() or self.is_within_checkout_window()

    @api.model
    def _cron_flag_missing_checkouts(self):
        """Signale les étudiants entrés mais jamais sortis, une fois la
        fenêtre de sortie passée : ils ont probablement quitté le cours tôt."""
        now = fields.Datetime.now()
        sessions = self.search([('time_start', '>=', now - timedelta(days=2))])
        for session in sessions:
            if now <= session.time_end + timedelta(minutes=session.checkout_window_minutes):
                continue  # la fenêtre de sortie n'est pas encore terminée
            missing = session.record_ids.filtered(
                lambda r: r.state != 'rejected' and r.checkout_state == 'not_done')
            if missing:
                missing.write({'checkout_state': 'rejected',
                               'checkout_flag_reason': "N'a pas scanné la sortie"})
                for r in missing:
                    self.env['school.attendance.task'].create_unique(
                        'missing_checkout', r.student_id, f"Sortie non scannée : {r.student_id.name}",
                        f"Cours « {session.course_id.name} » du {session.date}.", record=r)

    @api.model
    def _cron_generate_sessions(self):
        """Crée les séances du jour à partir de l'emploi du temps. Pensée
        pour tourner plusieurs fois par jour (voir le cron) : elle ne crée
        jamais deux fois la même séance grâce à la contrainte slot+date."""
        tz_name = self.env['ir.config_parameter'].sudo().get_param('school_attendance_qr.timezone', DEFAULT_TZ)
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            tz = ZoneInfo(DEFAULT_TZ)

        now_local = datetime.now(tz)
        today = now_local.date()
        weekday = str(today.weekday())

        slots = self.env['school.timetable.slot'].sudo().search([
            ('active', '=', True), ('weekday', '=', weekday),
            '|', ('date_from', '=', False), ('date_from', '<=', today),
            '|', ('date_to', '=', False), ('date_to', '>=', today),
        ])
        created = self.browse()
        for slot in slots:
            if self.sudo().search_count([('slot_id', '=', slot.id), ('date', '=', today)]):
                continue
            hour, minute = divmod(int(round(slot.start_time * 60)), 60)
            start_local = datetime(today.year, today.month, today.day, hour, minute, tzinfo=tz)
            start_utc = start_local.astimezone(ZoneInfo('UTC')).replace(tzinfo=None)
            created |= self.sudo().create({
                'slot_id': slot.id,
                'course_id': slot.course_id.id,
                'teacher_id': (slot.teacher_id or slot.course_id.teacher_id).id,
                'room_id': slot.room_id.id,
                'date': today,
                'time_start': start_utc,
                'duration_minutes': slot.duration_minutes,
                'checkin_window_minutes': slot.checkin_window_minutes,
                'checkout_window_minutes': slot.checkout_window_minutes,
            })
        return created


class SchoolAttendanceRecord(models.Model):
    """Une confirmation de présence scannée par l'étudiant."""
    _name = 'school.attendance.record'
    _description = 'Présence confirmée par QR'
    _order = 'scan_datetime desc'

    session_id = fields.Many2one('school.attendance.session', required=True, ondelete='cascade')
    student_id = fields.Many2one('school.student', required=True)
    # Champs recopiés depuis la séance/l'étudiant, pour permettre les statistiques
    # (regroupement par cours, promotion, enseignant) sans jointure coûteuse.
    course_id = fields.Many2one('school.course', related='session_id.course_id', store=True, string="Cours")
    teacher_id = fields.Many2one('school.teacher', related='session_id.teacher_id', store=True, string="Enseignant")
    promotion_id = fields.Many2one('school.promotion', related='student_id.promotion_id', store=True, string="Promotion")
    filiere_id = fields.Many2one('school.filiere', related='student_id.filiere_id', store=True, string="Filière")
    session_date = fields.Date(related='session_id.date', store=True, string="Date du cours")
    scan_datetime = fields.Datetime(default=fields.Datetime.now, readonly=True)
    device_fingerprint = fields.Char(required=True)
    client_ip = fields.Char(readonly=True, string="IP du scan")
    latitude = fields.Float(digits=(10, 7))
    longitude = fields.Float(digits=(10, 7))
    accuracy = fields.Float(string="Précision GPS (m)", readonly=True)
    distance_meters = fields.Float(readonly=True)
    state = fields.Selection([
        ('valid', 'Présent - validé'),
        ('flagged', 'À vérifier'),
        ('rejected', 'Rejeté'),
    ], default='valid', readonly=True, string="Entrée")
    flag_reason = fields.Char(readonly=True)

    checkout_scan_datetime = fields.Datetime(readonly=True)
    checkout_latitude = fields.Float(digits=(10, 7), readonly=True)
    checkout_longitude = fields.Float(digits=(10, 7), readonly=True)
    checkout_distance_meters = fields.Float(readonly=True)
    checkout_accuracy = fields.Float(readonly=True)
    checkout_state = fields.Selection([
        ('not_done', 'Pas encore sorti'),
        ('valid', 'Sortie validée'),
        ('flagged', 'À vérifier'),
        ('rejected', 'Parti sans scanner / hors zone'),
    ], default='not_done', readonly=True, string="Sortie")
    checkout_flag_reason = fields.Char(readonly=True)
    attendance_complete = fields.Boolean(compute='_compute_attendance_complete', store=True,
                                         string="Présence complète (entrée + sortie)")

    _sql_constraints = [
        ('session_student_uniq', 'unique(session_id, student_id)',
         "Cet étudiant a déjà confirmé sa présence pour cette séance."),
    ]

    @staticmethod
    def _join_reasons(*reasons):
        return " | ".join(r for r in reasons if r)

    @api.depends('state', 'checkout_state')
    def _compute_attendance_complete(self):
        for rec in self:
            rec.attendance_complete = rec.state != 'rejected' and rec.checkout_state == 'valid'

    def _evaluate_distance(self, room, latitude, longitude, accuracy):
        """Renvoie (distance, state, reason) pour un scan, qu'il s'agisse
        de l'entrée ou de la sortie : même règle de tolérance GPS."""
        distance = _haversine_meters(room.latitude, room.longitude, latitude, longitude)
        if distance > room.radius_meters + accuracy:
            return distance, 'rejected', f"Hors zone ({int(distance)} m de la salle)"
        if distance > room.radius_meters:
            return distance, 'flagged', f"Position limite ({int(distance)} m, précision ±{int(accuracy)} m)"
        return distance, 'valid', False

    @api.model
    def register_scan(self, room_token, student_id, latitude, longitude, device_fingerprint, accuracy=0.0, client_ip=False):
        """Point d'entrée du contrôleur portail : le QR identifie une SALLE
        (code permanent). Selon le moment du scan, il compte comme une
        entrée (début du cours) ou une sortie (fin du cours) ; aucune des
        deux fenêtres n'étant ouverte, le scan est refusé."""
        if not _is_on_campus_network(self.env, client_ip):
            raise ValidationError(_("Vous devez être connecté au Wi-Fi de l'établissement pour confirmer votre présence."))

        room = self.env['school.room'].sudo().search([('qr_token', '=', room_token)], limit=1)
        if not room:
            raise ValidationError(_("QR code invalide."))

        now = fields.Datetime.now()
        session = self.env['school.attendance.session'].sudo().search([
            ('room_id', '=', room.id), ('time_start', '<=', now),
        ], order='time_start desc', limit=1)
        if not session:
            raise ValidationError(_("Aucun cours en présence n'est ouvert dans cette salle en ce moment."))

        student = self.env['school.student'].sudo().browse(student_id)
        student.write({'last_login_ip': client_ip})
        self._check_device_binding(student, device_fingerprint)
        payment_reason = self._payment_policy_check(student)

        accuracy = max(float(accuracy or 0.0), 0.0)

        if session.is_within_checkin_window():
            return self._register_checkin(session, student, latitude, longitude, device_fingerprint, accuracy,
                                          client_ip, payment_reason)
        if session.is_within_checkout_window():
            return self._register_checkout(session, student, latitude, longitude, device_fingerprint, accuracy, client_ip)
        raise ValidationError(_("Aucune fenêtre de scan (entrée ou sortie) n'est ouverte actuellement pour ce cours."))

    def _payment_policy_check(self, student):
        """Applique le réglage « scolarité impayée » (Paramètres > École).
        Renvoie un motif à signaler en mode « signaler », lève une erreur en mode « bloquer »."""
        policy = icp(self.env, 'payment_policy', 'off')
        if policy == 'off':
            return False
        status = student.payment_status
        if not (status == 'unpaid' or (status == 'partial' and icp_bool(self.env, 'payment_include_partial'))):
            return False
        if policy == 'block':
            self.env['school.attendance.task'].create_unique(
                'payment', student, f"Scan bloqué, scolarité impayée : {student.name}",
                "L'étudiant a tenté de confirmer sa présence mais sa scolarité n'est pas à jour.")
            raise ValidationError(_(
                "Votre scolarité n'est pas à jour. Présentez-vous à la comptabilité pour régulariser votre "
                "situation : votre présence n'est pas enregistrée en attendant."))
        return "Scolarité impayée"

    def _log_device_attempt(self, student):
        self.env['school.attendance.task'].create_unique(
            'device_attempt', student, f"Autre appareil détecté : {student.name}",
            "Un scan a été refusé car ce compte est lié à un autre téléphone. S'il a changé de téléphone, "
            "autorisez le nouvel appareil ; sinon quelqu'un utilise peut-être son compte.")

    @staticmethod
    def _check_device_binding(student, device_fingerprint):
        """Verrouille le compte sur le PREMIER appareil utilisé, de façon
        permanente. Les scans suivants avec un autre appareil sont refusés
        (voir _register_checkin/_register_checkout) tant que le secrétariat
        n'a pas réinitialisé l'appareil (changement de téléphone)."""
        if not student.device_fingerprint:
            student.write({'device_fingerprint': device_fingerprint, 'device_bound_at': fields.Datetime.now()})

    def _find_conflicting_session(self, session, student, at=None):
        """Un étudiant programmé à un cours ne peut pas être « présent »
        ailleurs tant que ce cours n'est pas terminé. Renvoie la séance en
        conflit, ou rien si l'étudiant est libre à cet instant."""
        now = at or fields.Datetime.now()
        other_courses = student.course_ids - session.course_id
        if not other_courses:
            return False
        candidates = self.env['school.attendance.session'].sudo().search([
            ('id', '!=', session.id), ('course_id', 'in', other_courses.ids), ('time_start', '<=', now),
        ])
        for candidate in candidates:
            if candidate.time_end and candidate.time_end >= now:
                return candidate
        return False

    def _register_checkin(self, session, student, latitude, longitude, device_fingerprint, accuracy, client_ip,
                          payment_reason=False):
        if student not in session.course_id.student_ids:
            raise ValidationError(_("Vous n'êtes pas inscrit à ce cours."))

        conflict = self._find_conflicting_session(session, student)
        if conflict:
            raise ValidationError(_(
                "Vous êtes déjà programmé(e) pour « %(course)s » dans la salle « %(room)s » jusqu'à %(end)s. "
                "Terminez cette séance (et scannez votre sortie) avant de confirmer une présence ailleurs.",
                course=conflict.course_id.name, room=conflict.room_id.name, end=conflict.time_end,
            ))

        existing = self.sudo().search([('session_id', '=', session.id), ('student_id', '=', student.id)], limit=1)
        if existing and existing.state != 'rejected':
            raise ValidationError(_("Entrée déjà enregistrée pour ce cours. Scannez à nouveau en fin de cours pour confirmer votre sortie."))

        distance, state, reason = self._evaluate_distance(session.room_id, latitude, longitude, accuracy)

        if state != 'rejected' and device_fingerprint != student.device_fingerprint:
            self._log_device_attempt(student)
            raise ValidationError(_(
                "Ce compte est déjà associé à un autre appareil. Si vous avez changé de téléphone, "
                "demandez au secrétariat de réinitialiser l'appareil enregistré sur votre compte."))

        if payment_reason and state != 'rejected':
            state = 'flagged'
            reason = self._join_reasons(reason, payment_reason)

        vals = {
            'session_id': session.id, 'student_id': student.id,
            'scan_datetime': fields.Datetime.now(), 'device_fingerprint': device_fingerprint, 'client_ip': client_ip,
            'latitude': latitude, 'longitude': longitude, 'accuracy': accuracy,
            'distance_meters': distance, 'state': state, 'flag_reason': reason,
        }
        if existing:
            existing.write(vals)
            record = existing
        else:
            record = self.sudo().create(vals)

        record._check_cross_student_device_conflict('checkin')
        record._run_fraud_detections('checkin')
        self.env['school.audit.log'].log(
            'presence', f"Entrée « {session.course_id.name} » : {dict(record._fields['state'].selection)[record.state]}"
                        f"{' — ' + record.flag_reason if record.flag_reason else ''}", student=student, record=record)
        Task = self.env['school.attendance.task']
        if record.state == 'flagged':
            Task.create_unique('flagged_entry', student, f"Entrée à vérifier : {student.name}",
                               record.flag_reason or '', record=record)
        if payment_reason and record.state != 'rejected':
            Task.create_unique('payment', student, f"Scolarité impayée : {student.name}",
                               "Présence enregistrée mais signalée (réglage « signaler »).", session=session)
        return {
            'phase': 'checkin', 'state': record.state, 'flag_reason': record.flag_reason,
            'course_name': session.course_id.name,
        }

    def _register_checkout(self, session, student, latitude, longitude, device_fingerprint, accuracy, client_ip):
        record = self.sudo().search([('session_id', '=', session.id), ('student_id', '=', student.id)], limit=1)
        if not record or record.state == 'rejected':
            raise ValidationError(_("Vous devez d'abord scanner l'entrée au début du cours avant de pouvoir confirmer votre sortie."))
        if record.checkout_state != 'not_done':
            raise ValidationError(_("Sortie déjà confirmée pour ce cours."))

        if device_fingerprint != student.device_fingerprint:
            self._log_device_attempt(student)
            raise ValidationError(_(
                "Ce compte est déjà associé à un autre appareil. Si vous avez changé de téléphone, "
                "demandez au secrétariat de réinitialiser l'appareil enregistré sur votre compte."))

        distance, state, reason = self._evaluate_distance(session.room_id, latitude, longitude, accuracy)

        record.write({
            'checkout_scan_datetime': fields.Datetime.now(),
            'checkout_latitude': latitude, 'checkout_longitude': longitude,
            'checkout_distance_meters': distance, 'checkout_accuracy': accuracy,
            'checkout_state': state, 'checkout_flag_reason': reason,
        })
        record._check_cross_student_device_conflict('checkout')
        record._run_fraud_detections('checkout')
        self.env['school.audit.log'].log(
            'presence', f"Sortie « {session.course_id.name} » : "
                        f"{dict(record._fields['checkout_state'].selection)[record.checkout_state]}"
                        f"{' — ' + record.checkout_flag_reason if record.checkout_flag_reason else ''}",
            student=student, record=record)
        if record.checkout_state == 'flagged':
            self.env['school.attendance.task'].create_unique(
                'flagged_exit', student, f"Sortie à vérifier : {student.name}",
                record.checkout_flag_reason or '', record=record)
        return {
            'phase': 'checkout', 'state': record.checkout_state, 'flag_reason': record.checkout_flag_reason,
            'course_name': session.course_id.name,
        }

    # ------------------------------------------------- détections de fraude
    def _flag(self, phase, reason):
        """Passe l'entrée (ou la sortie) « à vérifier » en ajoutant le motif,
        sans jamais rétrograder une présence déjà rejetée."""
        for rec in self:
            if phase == 'checkout':
                if rec.checkout_state in ('valid', 'flagged') and reason not in (rec.checkout_flag_reason or ''):
                    rec.write({'checkout_state': 'flagged',
                               'checkout_flag_reason': self._join_reasons(rec.checkout_flag_reason, reason)})
            elif rec.state in ('valid', 'flagged') and reason not in (rec.flag_reason or ''):
                rec.write({'state': 'flagged', 'flag_reason': self._join_reasons(rec.flag_reason, reason)})

    def _position(self, phase):
        self.ensure_one()
        if phase == 'checkout':
            return self.checkout_latitude, self.checkout_longitude, self.checkout_scan_datetime
        return self.latitude, self.longitude, self.scan_datetime

    def _run_fraud_detections(self, phase='checkin'):
        """Trois contrôles a posteriori, qui signalent sans bloquer :
        - position GPS strictement identique à celle d'un autre étudiant (signe
          typique d'une application de fausse position) ;
        - confirmations groupées : plusieurs téléphones confirmés en quelques
          secondes depuis le même point (une personne qui « pointe » pour d'autres) ;
        - déplacement impossible : vitesse irréaliste depuis la confirmation
          précédente du même étudiant."""
        Task = self.env['school.attendance.task']
        Audit = self.env['school.audit.log']
        cluster_seconds = icp_int(self.env, 'cluster_seconds', 20)
        cluster_min = icp_int(self.env, 'cluster_min', 3)
        max_speed = icp_int(self.env, 'max_speed_kmh', 50) / 3.6
        for rec in self:
            lat, lon, when = rec._position(phase)
            if not when or (not lat and not lon):
                continue
            same_session = self.sudo().search([('session_id', '=', rec.session_id.id), ('id', '!=', rec.id)])

            twins = same_session.filtered(lambda o: any(
                round(olat, 6) == round(lat, 6) and round(olon, 6) == round(lon, 6)
                for olat, olon, _w in (o._position('checkin'), o._position('checkout')) if olat or olon))
            if twins:
                reason = "Position GPS identique à celle d'un autre étudiant"
                (rec | twins)._flag(phase, reason)
                for r in rec | twins:
                    Task.create_unique('gps_identical', r.student_id, f"GPS identique : {r.student_id.name}",
                                       f"Même position exacte que {', '.join(((rec | twins) - r).mapped('student_id.name'))}.",
                                       record=r)
                Audit.log('fraud', reason, student=rec.student_id, record=rec)

            group = same_session.filtered(lambda o: (lambda p: p[2] and abs((p[2] - when).total_seconds()) <= cluster_seconds
                                                     and _haversine_meters(lat, lon, p[0], p[1]) <= 3)(o._position(phase)))
            if len(group) + 1 >= cluster_min:
                reason = f"Confirmations groupées ({len(group) + 1} en {cluster_seconds} s au même endroit)"
                (rec | group)._flag(phase, reason)
                for r in rec | group:
                    Task.create_unique('scan_cluster', r.student_id, f"Confirmations groupées : {r.student_id.name}",
                                       reason, record=r)
                Audit.log('fraud', reason, student=rec.student_id, record=rec)

            previous = rec._previous_position(when)
            if previous:
                plat, plon, pwhen = previous
                seconds = max((when - pwhen).total_seconds(), 1)
                distance = _haversine_meters(plat, plon, lat, lon)
                if distance > 200 and distance / seconds > max_speed:
                    reason = (f"Déplacement impossible : {int(distance)} m en {int(seconds // 60)} min "
                              f"depuis la confirmation précédente")
                    rec._flag(phase, reason)
                    Task.create_unique('impossible_speed', rec.student_id,
                                       f"Déplacement impossible : {rec.student_id.name}", reason, record=rec)
                    Audit.log('fraud', reason, student=rec.student_id, record=rec)

    def _previous_position(self, before):
        """Dernière position connue de l'étudiant (entrée ou sortie, tous cours
        confondus) dans les 6 heures précédant `before`."""
        self.ensure_one()
        since = before - timedelta(hours=6)
        candidates = []
        for other in self.sudo().search([('student_id', '=', self.student_id.id),
                                          '|', ('scan_datetime', '>=', since), ('checkout_scan_datetime', '>=', since)]):
            for phase in ('checkin', 'checkout'):
                lat, lon, when = other._position(phase)
                if when and (lat or lon) and since <= when < before:
                    candidates.append((lat, lon, when))
        return max(candidates, key=lambda c: c[2]) if candidates else None

    def _check_cross_student_device_conflict(self, phase='checkin'):
        """Repère si l'appareil qui vient de scanner (entrée ou sortie) a
        aussi servi, dans les dernières 24h, pour un AUTRE étudiant - que ce
        soit à l'entrée ou à la sortie d'un cours quelconque."""
        window_start = fields.Datetime.now() - timedelta(hours=24)
        for rec in self:
            by_checkin = self.sudo().search([
                ('id', '!=', rec.id), ('student_id', '!=', rec.student_id.id),
                ('device_fingerprint', '=', rec.device_fingerprint),
                ('scan_datetime', '>=', window_start),
            ])
            by_checkout = self.sudo().search([
                ('id', '!=', rec.id), ('student_id', '!=', rec.student_id.id),
                ('checkout_state', '!=', 'not_done'),
                ('checkout_scan_datetime', '>=', window_start),
            ]).filtered(lambda o: o.device_fingerprint == rec.device_fingerprint)
            others = by_checkin | by_checkout
            if not others:
                continue
            if rec.state == 'valid':
                rec.write({'state': 'flagged', 'flag_reason': "Même appareil utilisé par plusieurs étudiants (24 h)"})
            if phase == 'checkout' and rec.checkout_state == 'valid':
                rec.write({'checkout_state': 'flagged',
                           'checkout_flag_reason': "Même appareil utilisé par plusieurs étudiants (24 h)"})
            for o in others:
                if o.state == 'valid':
                    o.write({'state': 'flagged', 'flag_reason': "Même appareil utilisé par plusieurs étudiants (24 h)"})
                if o.checkout_state == 'valid':
                    o.write({'checkout_state': 'flagged',
                             'checkout_flag_reason': "Même appareil utilisé par plusieurs étudiants (24 h)"})
            Task = self.env['school.attendance.task']
            for r in (rec | others):
                Task.create_unique(
                    'device_shared', r.student_id, f"Appareil partagé : {r.student_id.name}",
                    "Le même téléphone a servi pour plusieurs étudiants dans les dernières 24 h.", record=r)
            rec._notify_teacher(_("Incohérence détectée : le même appareil a servi pour %s et un autre étudiant.",
                                  rec.student_id.name))

    def _notify_teacher(self, message):
        partner = self.session_id.teacher_id.user_id.partner_id
        if partner:
            self.env['bus.bus'].sudo()._sendone(partner, 'simple_notification', {
                'title': _("Présence à vérifier"), 'message': message,
                'type': 'warning', 'sticky': True,
            })


class SchoolStudentAttendanceStats(models.Model):
    """Statistiques de présence, calculées à la demande : combien de
    séances un étudiant devait avoir, combien il a manquées, et si ça
    justifie une alerte (absences répétées)."""
    _inherit = 'school.student'

    sessions_expected = fields.Integer(compute='_compute_attendance_stats', string="Séances attendues")
    sessions_attended = fields.Integer(compute='_compute_attendance_stats', string="Séances présentes")
    sessions_missed = fields.Integer(compute='_compute_attendance_stats', string="Séances manquées")
    attendance_rate = fields.Float(compute='_compute_attendance_stats', string="Taux de présence (%)")
    at_risk = fields.Boolean(compute='_compute_attendance_stats', string="Absences répétées",
                             help="Taux de présence sous le seuil réglé dans Paramètres > École "
                                  "(70 % à partir de 3 séances par défaut).")

    def _compute_attendance_stats(self):
        Session = self.env['school.attendance.session'].sudo()
        today = fields.Date.context_today(self)
        min_sessions = icp_int(self.env, 'alert_min_sessions', 3)
        threshold = icp_int(self.env, 'alert_rate', 70)
        is_admin = self.env.su or self.env.user.has_group('school_base.group_school_admin')
        for student in self:
            courses = student.sudo().course_ids
            if not is_admin:  # un enseignant ne voit que les cours qu'il enseigne
                courses = courses.filtered(lambda c: c.teacher_id.user_id == self.env.user)
            sessions = Session.search([('course_id', 'in', courses.ids), ('date', '<=', today)])
            expected = len(sessions)
            attended = len(sessions.filtered(
                lambda s: s.record_ids.filtered(lambda r: r.student_id == student and r.state != 'rejected')))
            student.sessions_expected = expected
            student.sessions_attended = attended
            student.sessions_missed = expected - attended
            student.attendance_rate = round(attended / expected * 100, 1) if expected else 100.0
            student.at_risk = expected >= min_sessions and student.attendance_rate < threshold

    def action_reset_device(self):
        """En plus de libérer l'appareil, clôt les alertes « autre appareil » devenues sans objet."""
        res = super().action_reset_device()
        self.env['school.attendance.task'].sudo().search([
            ('student_id', 'in', self.ids), ('task_type', '=', 'device_attempt'), ('state', '=', 'open')]).action_done()
        return res
