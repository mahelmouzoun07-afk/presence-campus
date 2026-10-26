"""Suivi continu pendant une garde à l'hôpital.

1. Positions : dès l'entrée de garde, tant que l'application est ouverte, le
   téléphone envoie sa position toutes les N minutes (5 par défaut). Chaque
   position est comparée au rayon du site (même fonction que partout ailleurs).
   Limite technique assumée : une application web ne peut PAS suivre le GPS
   quand l'écran est verrouillé ou l'application fermée ; ces trous sont
   enregistrés comme « suivi interrompu », pas comme une fraude.
2. Contrôles de pause : aux heures prévues pour le site (ex. 12h00, 16h00),
   l'étudiant doit confirmer sa présence avec son empreinte + GPS dans une
   fenêtre donnée. Un contrôle manqué ou hors zone part dans « À traiter »."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from odoo.addons.school_attendance_qr.models.helpers import icp, icp_int, local_time


def _parse_times(raw):
    """« 12:00, 16h30 » → [(12, 0), (16, 30)] ; les valeurs illisibles sont ignorées."""
    out = []
    for part in (raw or '').replace('h', ':').split(','):
        try:
            hh, mm = (part.strip().split(':') + ['0'])[:2]
            out.append((int(hh), int(mm or 0)))
        except ValueError:
            continue
    return [t for t in out if 0 <= t[0] < 24 and 0 <= t[1] < 60]


class SchoolInternshipSiteTracking(models.Model):
    _inherit = 'school.internship.site'

    check_times = fields.Char(string="Heures de contrôle (pauses)", default="12:00, 16:00",
                              help="Heures locales, séparées par des virgules. À chacune, l'étudiant en garde doit "
                                   "confirmer sa présence avec son empreinte.")
    check_window_minutes = fields.Integer(default=30, string="Délai pour répondre (min)")

    @api.constrains('check_times')
    def _check_check_times(self):
        for rec in self:
            if rec.check_times and not _parse_times(rec.check_times):
                raise ValidationError(_("Heures de contrôle illisibles : écrivez par exemple « 12:00, 16:00 »."))


class SchoolInternshipPosition(models.Model):
    _name = 'school.internship.position'
    _description = 'Position GPS pendant une garde'
    _order = 'recorded_at desc'

    attendance_id = fields.Many2one('school.internship.attendance', required=True, ondelete='cascade', index=True)
    recorded_at = fields.Datetime(required=True)
    latitude = fields.Float(digits=(10, 7))
    longitude = fields.Float(digits=(10, 7))
    accuracy = fields.Float()
    distance_meters = fields.Float()
    inside = fields.Boolean(string="Dans la zone")


class SchoolInternshipCheck(models.Model):
    _name = 'school.internship.check'
    _description = 'Contrôle de présence pendant une garde'
    _order = 'due_at desc'

    attendance_id = fields.Many2one('school.internship.attendance', required=True, ondelete='cascade', index=True)
    student_id = fields.Many2one(related='attendance_id.student_id', store=True)
    site_id = fields.Many2one(related='attendance_id.site_id', store=True)
    due_at = fields.Datetime(required=True, string="Prévu à")
    deadline = fields.Datetime(required=True, string="À confirmer avant")
    state = fields.Selection([('pending', 'En attente'), ('done', 'Confirmé'), ('outside', 'Hors zone'),
                              ('missed', 'Manqué')], default='pending', required=True)
    confirmed_at = fields.Datetime(readonly=True)
    distance_meters = fields.Float(readonly=True)
    offline = fields.Boolean(readonly=True)


class SchoolInternshipAttendanceTracking(models.Model):
    _inherit = 'school.internship.attendance'

    position_ids = fields.One2many('school.internship.position', 'attendance_id', string="Positions")
    check_ids = fields.One2many('school.internship.check', 'attendance_id', string="Contrôles")
    last_position_at = fields.Datetime(readonly=True, string="Dernière position reçue")
    outside_alert_sent = fields.Boolean(readonly=True, copy=False)
    # Indicateurs non stockés (jamais de default_order dessus)
    tracking_inside_pct = fields.Float(compute='_compute_tracking', string="Positions dans la zone (%)")
    tracking_gaps = fields.Integer(compute='_compute_tracking', string="Interruptions du suivi")
    checks_missed = fields.Integer(compute='_compute_tracking', string="Contrôles manqués")

    @api.depends('position_ids.inside', 'position_ids.recorded_at', 'check_ids.state')
    def _compute_tracking(self):
        gap = timedelta(minutes=icp_int(self.env, 'internship_gap_minutes', 30))
        for rec in self:
            points = rec.position_ids.sorted('recorded_at')
            rec.tracking_inside_pct = (len(points.filtered('inside')) / len(points) * 100) if points else 0.0
            times = [rec.checkin_time] + points.mapped('recorded_at') + ([rec.checkout_time] if rec.checkout_time else [])
            times = [t for t in times if t]
            rec.tracking_gaps = sum(1 for a, b in zip(times, times[1:]) if b - a > gap)
            rec.checks_missed = len(rec.check_ids.filtered(lambda c: c.state in ('missed', 'outside')))

    # ------------------------------------------------------------- positions
    def record_positions(self, points):
        """Enregistre une série de positions (envoyées en direct, ou gardées sur
        le téléphone pendant une coupure réseau puis envoyées en bloc)."""
        self.ensure_one()
        shift = self.sudo()
        if not shift.checkin_time or shift.checkout_time:
            raise ValidationError(_("Aucune garde en cours."))
        Record = self.env['school.attendance.record'].sudo()
        now = fields.Datetime.now()
        vals, outside = [], 0
        for p in points[:500]:
            try:
                at = datetime.fromisoformat(str(p['at']).replace('Z', '+00:00')).astimezone(ZoneInfo('UTC'))
                at = at.replace(tzinfo=None, microsecond=0)
                lat, lon, acc = float(p['latitude']), float(p['longitude']), max(float(p.get('accuracy') or 0), 0)
            except (KeyError, TypeError, ValueError):
                continue
            if not (shift.checkin_time <= at <= now + timedelta(minutes=2)):
                continue  # heure incohérente (horloge du téléphone) : ignorée
            distance, state, _reason = Record._evaluate_distance(shift.site_id, lat, lon, acc)
            outside += state == 'rejected'
            vals.append({'attendance_id': shift.id, 'recorded_at': at, 'latitude': lat, 'longitude': lon,
                         'accuracy': acc, 'distance_meters': distance, 'inside': state != 'rejected'})
        if vals:
            self.env['school.internship.position'].sudo().create(vals)
            shift.last_position_at = max(shift.last_position_at or vals[0]['recorded_at'],
                                         max(v['recorded_at'] for v in vals))
        if outside >= icp_int(self.env, 'internship_outside_points', 3) and not shift.outside_alert_sent:
            reason = f"Positions hors du site pendant la garde ({outside} relevé(s))"
            shift.write({'outside_alert_sent': True, 'flag_reason': Record._join_reasons(shift.flag_reason, reason)})
            self.env['school.attendance.task'].create_internship(
                'internship_tracking', shift, f"Sortie du site pendant la garde : {shift.student_id.name}", reason)
        return {'saved': len(vals), 'outside': outside}

    # ------------------------------------------------------------- contrôles
    def pending_check(self):
        self.ensure_one()
        now = fields.Datetime.now()
        return self.check_ids.filtered(lambda c: c.state == 'pending' and c.due_at <= now <= c.deadline)[:1]

    def confirm_check(self, latitude, longitude, accuracy=0.0, at=None, offline=False):
        """L'étudiant répond au contrôle (empreinte vérifiée AVANT, par le
        contrôleur ou par la synchronisation hors ligne)."""
        self.ensure_one()
        shift = self.sudo()
        at = at or fields.Datetime.now()
        check = shift.check_ids.filtered(lambda c: c.state == 'pending' and c.due_at <= at <= c.deadline)[:1]
        if not check:
            raise ValidationError(_("Aucun contrôle de présence en attente à cette heure-là."))
        Record = self.env['school.attendance.record'].sudo()
        distance, state, _reason = Record._evaluate_distance(shift.site_id, float(latitude), float(longitude),
                                                             max(float(accuracy or 0), 0))
        check.write({'state': 'outside' if state == 'rejected' else 'done', 'confirmed_at': at,
                     'distance_meters': distance, 'offline': offline})
        if state == 'rejected':
            self._check_failed(check, f"Contrôle de {local_time(self.env, check.due_at)} confirmé hors du site "
                                      f"({int(distance)} m)")
        self.env['school.audit.log'].log(
            'internship', f"Contrôle de présence de {local_time(self.env, check.due_at)} : "
                          f"{dict(check._fields['state'].selection)[check.state]}{' (hors ligne)' if offline else ''}.",
            student=shift.student_id, record=shift)
        return {'ok': True, 'state': check.state, 'label': f"contrôle de {local_time(self.env, check.due_at)}"}

    def _check_failed(self, check, reason):
        shift = check.attendance_id.sudo()
        shift.write({'flag_reason': self.env['school.attendance.record']._join_reasons(shift.flag_reason, reason)})
        self.env['school.attendance.task'].create_internship(
            'internship_check', shift, f"Contrôle de présence non validé : {shift.student_id.name}", reason)

    @api.model
    def _cron_tracking(self):
        """Toutes les 5 minutes : ouvre les contrôles arrivés à l'heure (et
        prévient l'étudiant), clôt les contrôles expirés comme « manqués »."""
        now = fields.Datetime.now()
        try:
            tz = ZoneInfo(icp(self.env, 'timezone', 'Africa/Porto-Novo'))
        except Exception:
            tz = ZoneInfo('Africa/Porto-Novo')
        Check = self.env['school.internship.check'].sudo()
        for shift in self.sudo().search([('checkin_time', '!=', False), ('checkout_time', '=', False),
                                         ('checkin_state', '!=', 'rejected')]):
            local_now = now.replace(tzinfo=ZoneInfo('UTC')).astimezone(tz)
            window = timedelta(minutes=shift.site_id.check_window_minutes or 30)
            for hh, mm in _parse_times(shift.site_id.check_times):
                due_local = local_now.replace(hour=hh, minute=mm, second=0, microsecond=0)
                due = due_local.astimezone(ZoneInfo('UTC')).replace(tzinfo=None)
                if not (shift.checkin_time < due <= now < due + window):
                    continue
                if shift.check_ids.filtered(lambda c: c.due_at == due):
                    continue
                Check.create({'attendance_id': shift.id, 'due_at': due, 'deadline': due + window})
                self.env['school.notification'].notify(
                    shift.student_id.user_id, "Contrôle de présence",
                    f"Confirmez votre présence avec votre empreinte avant "
                    f"{local_time(self.env, due + window)}.", url='/presence/stages', category='security')
        for check in Check.search([('state', '=', 'pending'), ('deadline', '<', now)]):
            check.state = 'missed'
            self._check_failed(check, f"Contrôle de {local_time(self.env, check.due_at)} sans réponse")


class SchoolAttendanceTaskTracking(models.Model):
    _inherit = 'school.attendance.task'

    task_type = fields.Selection(selection_add=[
        ('internship_tracking', 'Stage : sortie du site pendant la garde'),
        ('internship_check', 'Stage : contrôle de présence non validé'),
    ], ondelete={'internship_tracking': 'cascade', 'internship_check': 'cascade'})
