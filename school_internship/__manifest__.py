{
    'name': 'School Internship',
    'version': '18.0.1.1.0',
    'summary': "Stages cliniques et gardes : double validation superviseur, heures cliniques, relevé",
    'category': 'Education',
    'depends': ['school_attendance_qr'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'security/rules.xml',
        'data/internship_data.xml',
        'views/internship_views.xml',
        'views/settings_views.xml',
        'views/portal_templates.xml',
    ],
    'installable': True,
    'license': 'LGPL-3',
}
