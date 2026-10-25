{
    'name': 'School Academic',
    'version': '18.0.1.0.0',
    'summary': "Examens et notes, calendrier académique, documents de cours",
    'category': 'Education',
    'depends': ['school_attendance_qr'],
    'data': [
        'security/ir.model.access.csv',
        'security/rules.xml',
        'data/academic_data.xml',
        'views/academic_views.xml',
        'views/settings_views.xml',
        'views/portal_templates.xml',
    ],
    'installable': True,
    'license': 'LGPL-3',
}
