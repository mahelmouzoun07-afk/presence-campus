{
    'name': 'School Base',
    'version': '18.0.3.0.0',
    'summary': "Étudiants, cours, salles et emploi du temps",
    'category': 'Education',
    'depends': ['base', 'portal'],
    'data': [
        'security/ir.model.access.csv',
        'views/school_views.xml',
        'views/room_timetable_views.xml',
        'views/teacher_promotion_views.xml',
    ],
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
