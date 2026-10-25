"""Calcul des moyennes selon les règles propres à chaque école (Paramètres >
École > Notes) : barème, traitement des absences, arrondi, note de passage."""
from odoo import api, models

from odoo.addons.school_attendance_qr.models.helpers import icp


def _rules(env):
    get = lambda key, default: icp(env, key, default)  # noqa: E731
    return {
        'scale': float(get('grade_scale', '20') or 20),
        'absent': get('grade_absent_policy', 'zero'),       # 'zero' ou 'exclude'
        'rounding': int(get('grade_rounding', '2') or 2),
        'pass_mark': float(get('grade_pass_mark', '10') or 10),
        'use_coefficients': get('grade_use_coefficients', 'True') != 'False',
    }


class SchoolStudentResults(models.Model):
    _inherit = 'school.student'

    def compute_results(self, period=None, published_only=True):
        """Résultats d'UN étudiant : moyenne par cours puis moyenne générale.

        - Chaque note est ramenée au barème de l'école (ex. 15/40 → 7,5/20).
        - Moyenne d'un cours = moyenne des notes pondérée par le poids de chaque évaluation.
        - Moyenne générale = moyenne des cours pondérée par leur coefficient (si l'école les utilise).
        - Absence à une évaluation : comptée 0, ou ignorée, selon le réglage."""
        self.ensure_one()
        rules = _rules(self.env)
        domain = [('student_id', '=', self.id)]
        if published_only:
            domain.append(('state', '=', 'published'))
        if period:
            domain.append(('evaluation_id.period_id', '=', period.id))
        grades = self.env['school.grade'].sudo().search(domain)
        courses = []
        total, total_coef = 0.0, 0.0
        for course in grades.mapped('course_id').sorted('name'):
            lines, acc, weights = [], 0.0, 0.0
            for grade in grades.filtered(lambda g: g.course_id == course).sorted(lambda g: g.evaluation_id.date):
                ev = grade.evaluation_id
                if not grade.is_graded:
                    continue
                if grade.is_absent and rules['absent'] == 'exclude':
                    lines.append({'evaluation': ev, 'grade': grade, 'normalized': None})
                    continue
                normalized = 0.0 if grade.is_absent else grade.score / ev.max_score * rules['scale']
                acc += normalized * ev.weight
                weights += ev.weight
                lines.append({'evaluation': ev, 'grade': grade, 'normalized': round(normalized, rules['rounding'])})
            average = round(acc / weights, rules['rounding']) if weights else None
            coef = course.coefficient if rules['use_coefficients'] else 1.0
            if average is not None:
                total += average * coef
                total_coef += coef
            courses.append({'course': course, 'coefficient': coef, 'lines': lines, 'average': average})
        general = round(total / total_coef, rules['rounding']) if total_coef else None
        return {
            'courses': courses, 'general': general, 'scale': rules['scale'], 'pass_mark': rules['pass_mark'],
            'passed': general is not None and general >= rules['pass_mark'],
        }

    @api.model
    def promotion_rank(self, student, period=None):
        """Rang de l'étudiant dans sa promotion (sur la moyenne générale)."""
        if not student.promotion_id:
            return None, 0
        mates = self.sudo().search([('promotion_id', '=', student.promotion_id.id)])
        scores = []
        for mate in mates:
            general = mate.compute_results(period)['general']
            if general is not None:
                scores.append((general, mate.id))
        scores.sort(reverse=True)
        for rank, (_score, sid) in enumerate(scores, start=1):
            if sid == student.id:
                return rank, len(scores)
        return None, len(scores)
