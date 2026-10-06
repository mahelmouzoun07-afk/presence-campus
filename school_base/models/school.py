from odoo import api, fields, models
from odoo.exceptions import ValidationError

WEEKDAYS = [
    ('0', 'Lundi'), ('1', 'Mardi'), ('2', 'Mercredi'), ('3', 'Jeudi'),
    ('4', 'Vendredi'), ('5', 'Samedi'), ('6', 'Dimanche'),
]


def _hhmm(value):
    total = int(round((value or 0.0) * 60))
    return "%02d:%02d" % divmod(total, 60)


class SchoolTeacher(models.Model):
    """Répertoire des enseignants, séparé des comptes utilisateurs internes
    (secrétariat, administrateurs...) pour que les listes déroulantes
    d'assignation ne proposent que du personnel enseignant."""
    _name = 'school.teacher'
    _description = 'Enseignant'

    name = fields.Char(required=True)
    email = fields.Char()
    phone = fields.Char(string="Téléphone")
    user_id = fields.Many2one('res.users', string="Compte utilisateur",
                              help="Optionnel : relie l'enseignant à un compte Odoo, pour qu'il reçoive "
                                   "les alertes de présence (appareil suspect, etc.) et puisse se connecter "
                                   "consulter ses cours.")
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('email_uniq', 'unique(email)', "Un enseignant existe déjà avec cet e-mail."),
    ]


class SchoolPromotion(models.Model):
    """Une promotion / cohorte (ex : 'L1 Info 2026-2027'), pour regrouper
    les étudiants et sortir des statistiques d'absence par promotion."""
    _name = 'school.promotion'
    _description = 'Promotion'
    _order = 'name'

    name = fields.Char(required=True)

    _sql_constraints = [
        ('name_uniq', 'unique(name)', "Cette promotion existe déjà."),
    ]


class SchoolCourse(models.Model):
    _name = 'school.course'
    _description = 'Cours'

    name = fields.Char(required=True)
    teacher_id = fields.Many2one('school.teacher', string="Enseignant", required=True)
    student_ids = fields.Many2many('school.student', string="Étudiants inscrits")


class SchoolStudent(models.Model):
    _name = 'school.student'
    _description = 'Étudiant'
    _rec_name = 'name'

    # Champs obligatoires à la création
    nom = fields.Char(required=True, string="Nom")
    prenom = fields.Char(required=True, string="Prénom")
    identifiant = fields.Char(required=True, string="Identifiant",
                              help="Identifiant donné par l'établissement (ex : prenom.nom01). "
                                   "Sert aussi de nom d'utilisateur pour se connecter.")
    matricule = fields.Char(required=True, string="Matricule")
    name = fields.Char(compute='_compute_name', store=True, string="Nom complet")

    # Champs optionnels, utiles pour l'import Excel depuis la base de l'école
    email = fields.Char(string="E-mail")
    phone = fields.Char(string="Téléphone")
    photo = fields.Binary(string="Photo", attachment=True)
    birthdate = fields.Date()

    course_ids = fields.Many2many('school.course', string="Cours")
    promotion_id = fields.Many2one('school.promotion', string="Promotion")
    user_id = fields.Many2one('res.users', string="Compte portail", readonly=True,
                              help="Créé automatiquement à partir de l'identifiant et du matricule.")

    # Sécurité : un seul appareil autorisé par compte, fixé au premier scan
    device_fingerprint = fields.Char(readonly=True, string="Appareil enregistré")
    device_bound_at = fields.Datetime(readonly=True, string="Appareil enregistré le")
    last_login_ip = fields.Char(readonly=True, string="Dernière IP de connexion",
                                help="Information de diagnostic uniquement : sur un Wi-Fi d'établissement, "
                                     "tous les étudiants partagent souvent la MÊME adresse IP publique "
                                     "(le Wi-Fi ne fait qu'un seul routeur vers Internet). Ce champ ne peut "
                                     "donc pas servir à distinguer deux étudiants entre eux.")

    _sql_constraints = [
        ('identifiant_uniq', 'unique(identifiant)', "Cet identifiant est déjà utilisé par un autre étudiant."),
        ('matricule_uniq', 'unique(matricule)', "Ce matricule est déjà utilisé par un autre étudiant."),
    ]

    @api.depends('nom', 'prenom')
    def _compute_name(self):
        for rec in self:
            rec.name = f"{rec.prenom or ''} {rec.nom or ''}".strip() or rec.identifiant or "Étudiant"

    @api.model_create_multi
    def create(self, vals_list):
        students = super().create(vals_list)
        for student in students:
            if not student.user_id:
                student._create_portal_account()
        return students

    def _create_portal_account(self):
        """Crée le compte portail de l'étudiant : identifiant comme login,
        matricule comme mot de passe initial (ce sont les informations que
        l'étudiant connaît déjà pour se connecter au Wi-Fi de l'école)."""
        self.ensure_one()
        if self.env['res.users'].sudo().search_count([('login', '=', self.identifiant)]):
            raise ValidationError(
                f"Un compte existe déjà avec l'identifiant « {self.identifiant} ». "
                "Vérifiez qu'il ne s'agit pas d'un doublon, ou liez l'étudiant à ce compte manuellement.")
        portal_group = self.env.ref('base.group_portal')
        user = self.env['res.users'].sudo().create({
            'name': self.name, 'login': self.identifiant, 'password': self.matricule,
            'email': self.email or False,
            'groups_id': [(6, 0, [portal_group.id])],
        })
        self.sudo().user_id = user.id

    def action_reset_device(self):
        """À utiliser quand l'étudiant change de téléphone : son compte
        pourra à nouveau être associé au prochain appareil utilisé."""
        self.write({'device_fingerprint': False, 'device_bound_at': False})

    def action_reset_password(self):
        """Remet le mot de passe du compte au matricule (mot de passe de
        départ), pour un étudiant qui a oublié le mot de passe qu'il avait
        changé. À faire par le secrétariat après avoir vérifié l'identité
        de l'étudiant (en personne ou via son matricule physique)."""
        for student in self:
            if not student.user_id:
                raise ValidationError(f"{student.name} n'a pas encore de compte portail.")
            student.user_id.sudo().write({'password': student.matricule})


class SchoolRoom(models.Model):
    _name = 'school.room'
    _description = 'Salle de cours'

    name = fields.Char(required=True)
    building = fields.Char(string="Bâtiment / campus")
    latitude = fields.Float(digits=(10, 7), help="Coordonnées de la salle (clic droit sur Google Maps).")
    longitude = fields.Float(digits=(10, 7))
    radius_meters = fields.Integer(default=30, string="Rayon toléré (m)")
    capacity = fields.Integer()
    active = fields.Boolean(default=True)


class SchoolTimetableSlot(models.Model):
    """Un créneau hebdomadaire récurrent : tel cours, telle salle, tel jour, telle heure."""
    _name = 'school.timetable.slot'
    _description = "Créneau d'emploi du temps"
    _order = 'weekday, start_time'

    name = fields.Char(compute='_compute_name')
    course_id = fields.Many2one('school.course', required=True)
    room_id = fields.Many2one('school.room', required=True)
    teacher_id = fields.Many2one('school.teacher', string="Enseignant")
    weekday = fields.Selection(WEEKDAYS, required=True, default='0')
    start_time = fields.Float(required=True, default=8.0, help="Heure locale de début (ex : 8,5 = 8h30)")
    duration_minutes = fields.Integer(default=120)
    checkin_window_minutes = fields.Integer(default=15, string="Fenêtre d'entrée (min)",
                                            help="Durée pendant laquelle le scan d'entrée est accepté après le début du cours")
    checkout_window_minutes = fields.Integer(default=15, string="Fenêtre de sortie (min)",
                                             help="Durée, avant et après la fin du cours, pendant laquelle le scan de sortie est accepté")
    date_from = fields.Date(string="Du")
    date_to = fields.Date(string="Au")
    active = fields.Boolean(default=True)

    @api.depends('course_id', 'weekday', 'start_time')
    def _compute_name(self):
        labels = dict(WEEKDAYS)
        for rec in self:
            rec.name = "%s - %s %s" % (rec.course_id.name or '', labels.get(rec.weekday, ''), _hhmm(rec.start_time))

    @api.onchange('course_id')
    def _onchange_course_id(self):
        if self.course_id and not self.teacher_id:
            self.teacher_id = self.course_id.teacher_id

    @api.constrains('start_time', 'duration_minutes', 'checkin_window_minutes', 'checkout_window_minutes')
    def _check_times(self):
        for rec in self:
            if not 0 <= rec.start_time < 24:
                raise ValidationError("L'heure de début doit être comprise entre 0 h et 24 h.")
            if rec.duration_minutes <= 0 or rec.checkin_window_minutes <= 0 or rec.checkout_window_minutes <= 0:
                raise ValidationError("La durée du cours et la fenêtre de présence doivent être positives.")

    @api.constrains('room_id', 'weekday', 'start_time', 'duration_minutes', 'date_from', 'date_to', 'active')
    def _check_room_not_double_booked(self):
        """Deux cours ne peuvent pas avoir lieu dans la même salle au même moment."""
        for rec in self:
            if not rec.active:
                continue
            end = rec.start_time + rec.duration_minutes / 60.0
            others = self.search([
                ('id', '!=', rec.id), ('room_id', '=', rec.room_id.id),
                ('weekday', '=', rec.weekday), ('active', '=', True),
            ])
            for other in others:
                other_end = other.start_time + other.duration_minutes / 60.0
                # Chevauchement si les deux intervalles [start, end] se croisent...
                if rec.start_time < other_end and other.start_time < end:
                    # ...et que leurs périodes de validité (date_from/date_to) se recoupent aussi
                    if (not rec.date_to or not other.date_from or rec.date_to >= other.date_from) and \
                       (not other.date_to or not rec.date_from or other.date_to >= rec.date_from):
                        raise ValidationError(
                            f"La salle « {rec.room_id.name} » est déjà occupée par « {other.course_id.name} » "
                            f"à ce moment-là (créneau « {other.name} »). Choisissez une autre salle ou un autre horaire.")
