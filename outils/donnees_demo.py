"""Données de démonstration « devant le client ».

À exécuter dans le shell Odoo d'une base de DÉMO (jamais celle d'une vraie école) :
    DEMO_LAT=6.3703 DEMO_LNG=2.3912 odoo-bin shell -d demo_clients < outils/donnees_demo.py
ou, plus simple : bash outils/demo.sh 6.3703 2.3912

DEMO_LAT / DEMO_LNG = position de la salle où la démo a lieu (clic droit sur Google Maps).
Tous les noms, e-mails et matricules sont inventés. Les mots de passe ci-dessous
sont des mots de passe de démonstration : ne les réutilisez nulle part.
"""
import os
from datetime import date, timedelta

from odoo import fields

LAT = float(os.environ.get('DEMO_LAT', '6.3703'))
LNG = float(os.environ.get('DEMO_LNG', '2.3912'))
PWD = {'awa': 'Demo-Awa-2026', 'koffi': 'Demo-Koffi-2026', 'prof': 'Demo-Prof-2026',
       'superviseur': 'Demo-Superviseur-2026'}

if env['school.student'].search([('identifiant', '=', 'demo.awa')]):
    print("DEMO DÉJÀ PRÉSENTE : recréez la base avec outils/demo.sh")
else:
    # --- structure de l'école -------------------------------------------------
    env['school.academic.period'].create({
        'name': 'Semestre 1 2026-2027', 'date_from': date.today() - timedelta(days=50),
        'date_to': date.today() + timedelta(days=80)})
    fil = env['school.filiere'].create({'name': 'Soins infirmiers', 'code': 'SI'})
    promo = env['school.promotion'].create({'name': 'L2 Soins infirmiers 2026', 'filiere_id': fil.id})
    room = env['school.room'].create({'name': 'Amphi A (démo)', 'latitude': LAT, 'longitude': LNG,
                                      'radius_meters': 30, 'capacity': 80})

    # --- enseignant (avec compte) ---------------------------------------------
    teacher = env['school.teacher'].create({'name': 'Mme Adjovi', 'email': 'prof.demo@demo.bj'})
    teacher.action_create_user()
    teacher.user_id.password = PWD['prof']
    anat = env['school.course'].create({'name': 'Anatomie', 'teacher_id': teacher.id, 'coefficient': 3})
    hyg = env['school.course'].create({'name': 'Hygiène hospitalière', 'teacher_id': teacher.id, 'coefficient': 2})

    # --- étudiants ------------------------------------------------------------
    def student(nom, prenom, identifiant, matricule, **extra):
        st = env['school.student'].create({
            'nom': nom, 'prenom': prenom, 'identifiant': identifiant, 'matricule': matricule,
            'promotion_id': promo.id, 'course_ids': [(6, 0, [anat.id, hyg.id])], **extra})
        st.user_id.password = PWD.get(identifiant.split('.')[-1], matricule)
        st.must_change_password = False
        return st

    awa = student('Agbodjan', 'Awa', 'demo.awa', '90000001')
    koffi = student('Kpadonou', 'Koffi', 'demo.koffi', '90000002')
    fatou = student('Sossou', 'Fatou', 'demo.fatou', '90000003', no_phone=True)
    for nom, prenom, ident, mat in (('Tchibozo', 'Moussa', 'demo.moussa', '90000004'),
                                    ('Hounkpatin', 'Sènami', 'demo.senami', '90000005')):
        student(nom, prenom, ident, mat)

    # --- séance en cours (fenêtre d'entrée ouverte) + une demain -------------
    Session = env['school.attendance.session']
    Session.create({'course_id': anat.id, 'teacher_id': teacher.id, 'room_id': room.id,
                    'time_start': fields.Datetime.now() - timedelta(minutes=3), 'duration_minutes': 120})
    Session.create({'course_id': hyg.id, 'teacher_id': teacher.id, 'room_id': room.id,
                    'time_start': fields.Datetime.now() + timedelta(days=1), 'duration_minutes': 90})

    # --- notes et calendrier --------------------------------------------------
    for course, name, scores in ((anat, 'Devoir 1', (15, 9, 12, 14, 8)), (hyg, 'TP asepsie', (17, 11, 13, 10, 16))):
        ev = env['school.evaluation'].create({'name': name, 'course_id': course.id, 'date': date.today()})
        ev.action_generate_grades()
        for grade, score in zip(ev.grade_ids.sorted('id'), scores):
            grade.score = score
        ev.action_publish()
    env['school.academic.event'].create({
        'name': 'Rendre le dossier de soins', 'event_type': 'devoir', 'importance': 'normal',
        'course_id': hyg.id, 'date_start': fields.Datetime.now() + timedelta(days=2)})

    # --- stage clinique : superviseur, site, historique de gardes -------------
    sup = env['school.teacher'].create({'name': 'Dr Gbaguidi', 'email': 'gbaguidi@demo.bj'})
    sup.action_create_user()
    sup.user_id.write({'password': PWD['superviseur'],
                       'groups_id': [(4, env.ref('school_internship.group_internship_supervisor').id)]})
    site = env['school.internship.site'].create({
        'name': 'CHU de démonstration — Urgences', 'specialty': 'Urgences', 'latitude': LAT, 'longitude': LNG,
        'radius_meters': 80, 'check_times': '12:00, 16:00', 'supervisor_ids': [(6, 0, [sup.id])]})
    period = env['school.internship.period'].create({
        'student_id': awa.id, 'site_id': site.id, 'required_hours': 120,
        'date_start': date.today() - timedelta(days=7), 'date_end': date.today() + timedelta(days=21)})
    # Deux gardes passées : l'une validée par le superviseur, l'autre en attente.
    # Un faux appareil sert à les créer, puis il est retiré : Awa enregistrera le sien en direct.
    Shift = env['school.internship.attendance']
    awa.device_fingerprint = 'demo-historique'
    for hours_ago, length in ((60, 12), (30, 10)):
        t0 = fields.Datetime.now() - timedelta(hours=hours_ago)
        Shift.register_student_scan(awa, LAT, LNG, 'demo-historique', 8, at=t0)
        Shift.register_student_scan(awa, LAT, LNG, 'demo-historique', 8, at=t0 + timedelta(hours=length))
    period.attendance_ids.sorted('checkin_time')[:1].validate_by_supervisor(sup, rating=5, comment="Très impliquée")
    awa.action_reset_device()
    env.cr.commit()
    print("DEMO PRÊTE : étudiants", awa.identifiant, koffi.identifiant, fatou.identifiant)
