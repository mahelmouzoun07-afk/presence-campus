import base64
import io
import math
import secrets
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.http import request

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


def _get_base_url():
    """Adresse publique à utiliser dans les liens de QR : l'adresse de la
    requête en cours si on est dans une requête web (donc celle du domaine
    ou du tunnel utilisé), sinon web.base.url en repli."""
    try:
        if request and request.httprequest:
            return request.httprequest.host_url.rstrip('/')
    except Exception:
        pass
    from odoo import api as _api
    env = _api.Environment(request.env.cr, request.env.uid, {}) if request else None
    return ''


class SchoolRoomQr(models.Model):
    """Ajoute à la salle le QR permanent affiché au mur : un seul code par
    salle, qui ne change jamais (compatible avec un générateur externe
    comme EZQR, qui ne propose le code modifiable qu'en payant)."""
    _inherit = 'school.room'

    qr_token = fields.Char(default=lambda self: secrets.token_urlsafe(16), readonly=True, copy=False)
    scan_url = fields.Char(compute='_compute_scan_url',
                           help="Colle cette adresse dans un générateur de QR (ex. EZQR) pour obtenir "
                                "l'image à imprimer et coller au mur. Le code ne change jamais.")
    qr_image = fields.Binary(compute='_compute_qr_image', attachment=False, string="Aperçu du QR")

    @api.depends('qr_token')
    def _compute_scan_url(self):
        base = _get_base_url()
        for rec in self:
            rec.scan_url = f"{base}/school/attendance/scan/{rec.qr_token}" if rec.qr_token else False

    @api.depends('scan_url')
    def _compute_qr_image(self):
        import qrcode
        for rec in self:
            if not rec.scan_url:
                rec.qr_image = False
                continue
            buf = io.BytesIO()
            qrcode.make(rec.scan_url).save(buf, format='PNG')
            rec.qr_image = base64.b64encode(buf.getvalue())


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
        self.write({'time_start': fields.Datetime.now()})

    def is_within_checkin_window(self):
        self.ensure_one()
        now = fields.Datetime.now()
        return self.time_start <= now <= self.time_start + timedelta(minutes=self.checkin_window_minutes)

    def is_within_checkout_window(self):
        self.ensure_one()
        now = fields.Datetime.now()
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

        accuracy = max(float(accuracy or 0.0), 0.0)

        if session.is_within_checkin_window():
            return self._register_checkin(session, student, latitude, longitude, device_fingerprint, accuracy, client_ip)
        if session.is_within_checkout_window():
            return self._register_checkout(session, student, latitude, longitude, device_fingerprint, accuracy, client_ip)
        raise ValidationError(_("Aucune fenêtre de scan (entrée ou sortie) n'est ouverte actuellement pour ce cours."))

    @staticmethod
    def _check_device_binding(student, device_fingerprint):
        """Verrouille le compte sur le PREMIER appareil utilisé, de façon
        permanente. Les scans suivants avec un autre appareil sont refusés
        (voir _register_checkin/_register_checkout) tant que le secrétariat
        n'a pas réinitialisé l'appareil (changement de téléphone)."""
        if not student.device_fingerprint:
            student.write({'device_fingerprint': device_fingerprint, 'device_bound_at': fields.Datetime.now()})

    def _find_conflicting_session(self, session, student):
        """Un étudiant programmé à un cours ne peut pas être « présent »
        ailleurs tant que ce cours n'est pas terminé. Renvoie la séance en
        conflit, ou rien si l'étudiant est libre à cet instant."""
        now = fields.Datetime.now()
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

    def _register_checkin(self, session, student, latitude, longitude, device_fingerprint, accuracy, client_ip):
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
            raise ValidationError(_(
                "Ce compte est déjà associé à un autre appareil. Si vous avez changé de téléphone, "
                "demandez au secrétariat de réinitialiser l'appareil enregistré sur votre compte."))

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
            raise ValidationError(_(
                "Ce compte est déjà associé à un autre appareil. Si vous avez changé de téléphone, "
                "demandez au secrétariat de réinitialiser l'appareil enregistré sur votre compte."))

        distance, state, reason = self._evaluate_distance(session.room_id, latitude, longitude, accuracy)

        record.write({
            'checkout_scan_datetime': fields.Datetime.now(),
            'checkout_distance_meters': distance, 'checkout_accuracy': accuracy,
            'checkout_state': state, 'checkout_flag_reason': reason,
        })
        record._check_cross_student_device_conflict('checkout')
        return {
            'phase': 'checkout', 'state': record.checkout_state, 'flag_reason': record.checkout_flag_reason,
            'course_name': session.course_id.name,
        }

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
                             help="Taux de présence sous 70%, calculé à partir de 3 séances passées ou plus.")

    def _compute_attendance_stats(self):
        Session = self.env['school.attendance.session'].sudo()
        today = fields.Date.context_today(self)
        for student in self:
            sessions = Session.search([('course_id', 'in', student.course_ids.ids), ('date', '<=', today)])
            expected = len(sessions)
            attended = len(sessions.filtered(
                lambda s: s.record_ids.filtered(lambda r: r.student_id == student and r.state != 'rejected')))
            student.sessions_expected = expected
            student.sessions_attended = attended
            student.sessions_missed = expected - attended
            student.attendance_rate = round(attended / expected * 100, 1) if expected else 100.0
            student.at_risk = expected >= 3 and student.attendance_rate < 70.0
