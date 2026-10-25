from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

EVALUATION_TYPES = [
    ('devoir', 'Devoir'), ('interrogation', 'Interrogation'), ('tp', 'Travaux pratiques'),
    ('partiel', 'Partiel'), ('examen', 'Examen'), ('oral', 'Oral'), ('projet', 'Projet'),
]


class SchoolEvaluation(models.Model):
    """Une évaluation (devoir, examen...) d'un cours. Les notes restent
    invisibles des étudiants tant qu'elle n'est pas publiée."""
    _name = 'school.evaluation'
    _description = 'Évaluation'
    _order = 'date desc, id desc'

    name = fields.Char(required=True, string="Intitulé")
    course_id = fields.Many2one('school.course', required=True, string="Cours", index=True)
    teacher_id = fields.Many2one('school.teacher', related='course_id.teacher_id', store=True, string="Enseignant")
    evaluation_type = fields.Selection(EVALUATION_TYPES, required=True, default='devoir', string="Type")
    date = fields.Date(required=True, default=fields.Date.context_today)
    time_start = fields.Datetime(string="Début (date et heure)",
                                 help="Pour un examen : apparaît dans le calendrier des étudiants, avec rappels.")
    room_id = fields.Many2one('school.room', string="Salle")
    period_id = fields.Many2one('school.academic.period', compute='_compute_period_id', store=True,
                                readonly=False, string="Période")
    weight = fields.Float(default=1.0, string="Poids dans la moyenne du cours")
    max_score = fields.Float(default=20.0, string="Noté sur")
    state = fields.Selection([('draft', 'Brouillon'), ('published', 'Publiée')], default='draft', required=True,
                             string="État")
    grade_ids = fields.One2many('school.grade', 'evaluation_id', string="Notes")
    average = fields.Float(compute='_compute_stats', string="Moyenne de la classe")
    graded_count = fields.Integer(compute='_compute_stats', string="Notes saisies")
    event_id = fields.Many2one('school.academic.event', readonly=True, copy=False, ondelete='set null')
    description = fields.Text()

    @api.depends('date')
    def _compute_period_id(self):
        Period = self.env['school.academic.period']
        for rec in self:
            rec.period_id = Period.period_for(rec.date) if rec.date else rec.period_id

    @api.depends('grade_ids.score', 'grade_ids.is_absent', 'max_score')
    def _compute_stats(self):
        for rec in self:
            graded = rec.grade_ids.filtered(lambda g: g.is_graded and not g.is_absent)
            rec.graded_count = len(graded)
            rec.average = (sum(graded.mapped('score')) / len(graded)) if graded else 0.0

    @api.constrains('weight', 'max_score')
    def _check_numbers(self):
        for rec in self:
            if rec.weight <= 0 or rec.max_score <= 0:
                raise ValidationError(_("Le poids et le barème d'une évaluation doivent être positifs."))

    # ---------------------------------------------------------------- actions
    def action_generate_grades(self):
        """Crée une ligne de note vide pour chaque étudiant inscrit au cours."""
        for rec in self:
            existing = rec.grade_ids.mapped('student_id')
            missing = rec.course_id.sudo().student_ids - existing
            self.env['school.grade'].create([{'evaluation_id': rec.id, 'student_id': s.id} for s in missing])

    def action_publish(self):
        for rec in self:
            if not rec.grade_ids:
                raise UserError(_("Saisissez au moins une note avant de publier « %s ».", rec.name))
            rec.state = 'published'
            users = rec.grade_ids.mapped('student_id.user_id')
            self.env['school.notification'].notify(
                users, f"Nouvelle note : {rec.course_id.name}", f"« {rec.name} » est disponible.",
                url='/presence/notes', category='result')

    def action_unpublish(self):
        self.write({'state': 'draft'})

    # ------------------------------------------- examen → calendrier des étudiants
    def _event_vals(self):
        self.ensure_one()
        start = self.time_start or fields.Datetime.to_datetime(self.date).replace(hour=8)
        return {
            'name': f"{dict(EVALUATION_TYPES)[self.evaluation_type]} : {self.course_id.name}",
            'event_type': 'devoir' if self.evaluation_type == 'devoir' else 'examen',
            'importance': 'high' if self.evaluation_type in ('partiel', 'examen') else 'normal',
            'date_start': start, 'course_id': self.course_id.id, 'all_day': not self.time_start,
            'description': (f"{self.name}" + (f" — salle {self.room_id.name}" if self.room_id else '')),
        }

    def _needs_event(self):
        """Au calendrier : les partiels et examens, et toute évaluation dont
        l'heure est annoncée à l'avance. Un devoir noté après coup n'y va pas."""
        self.ensure_one()
        return self.evaluation_type in ('partiel', 'examen') or bool(self.time_start)

    def _sync_event(self):
        for rec in self:
            if not rec._needs_event():
                rec.event_id.sudo().unlink()
                continue
            if rec.event_id:
                rec.event_id.sudo().write(rec._event_vals())
            else:
                rec.event_id = self.env['school.academic.event'].sudo().create(rec._event_vals())

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._sync_event()
        return records

    def write(self, vals):
        res = super().write(vals)
        if {'name', 'date', 'time_start', 'room_id', 'evaluation_type', 'course_id'} & set(vals):
            self._sync_event()
        return res

    def unlink(self):
        self.mapped('event_id').sudo().unlink()
        return super().unlink()


class SchoolGrade(models.Model):
    _name = 'school.grade'
    _description = 'Note'
    _order = 'evaluation_id, student_id'

    evaluation_id = fields.Many2one('school.evaluation', required=True, ondelete='cascade', index=True)
    student_id = fields.Many2one('school.student', required=True, ondelete='cascade', index=True, string="Étudiant")
    matricule = fields.Char(related='student_id.matricule', string="Matricule")
    course_id = fields.Many2one(related='evaluation_id.course_id', store=True, string="Cours")
    teacher_id = fields.Many2one(related='evaluation_id.teacher_id', store=True)
    max_score = fields.Float(related='evaluation_id.max_score')
    state = fields.Selection(related='evaluation_id.state', store=True, string="Publication")
    score = fields.Float(string="Note", digits=(5, 2))
    is_absent = fields.Boolean(string="Absent(e)")
    is_graded = fields.Boolean(readonly=True, string="Saisie",
                               help="Distingue un vrai 0 d'une note pas encore saisie.")
    comment = fields.Char(string="Appréciation")

    _sql_constraints = [
        ('evaluation_student_uniq', 'unique(evaluation_id, student_id)', "Cet étudiant a déjà une note pour cette évaluation."),
    ]

    @api.constrains('score', 'evaluation_id')
    def _check_score(self):
        for rec in self:
            if rec.score < 0 or rec.score > rec.evaluation_id.max_score:
                raise ValidationError(_("La note de %(student)s doit être comprise entre 0 et %(max)s.",
                                        student=rec.student_id.name, max=rec.evaluation_id.max_score))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if 'score' in vals or vals.get('is_absent'):
                vals['is_graded'] = True
        return super().create(vals_list)

    def write(self, vals):
        """Une note modifiée APRÈS publication laisse une trace dans le journal d'audit."""
        watched = {'score', 'is_absent'} & set(vals)
        before = {g.id: (g.score, g.is_absent) for g in self if g.state == 'published'} if watched else {}
        if watched:
            vals = dict(vals, is_graded=True)
        res = super().write(vals)
        Audit = self.env['school.audit.log']
        for grade in self.filtered(lambda g: g.id in before):
            old_score, old_abs = before[grade.id]
            if (old_score, old_abs) != (grade.score, grade.is_absent):
                Audit.log('grade', f"« {grade.evaluation_id.name} » ({grade.course_id.name}) : "
                                   f"{'absent' if old_abs else old_score} → {'absent' if grade.is_absent else grade.score}",
                          student=grade.student_id, record=grade)
        return res
