{
    'name': 'School Attendance QR',
    'version': '18.0.7.1.0',
    'summary': "Présence par QR permanent (entrée + sortie), séances générées depuis l'emploi du temps",
    'category': 'Education',
    'depends': ['school_base', 'mail', 'portal'],
    'data': [
        'security/ir.model.access.csv',
        'views/scan_page_template.xml',
        'views/session_views.xml',
        'views/room_qr_views.xml',
        'views/stats_views.xml',
        'views/login_template.xml',
        'data/ir_cron_data.xml',
    ],
    'installable': True,
    'license': 'LGPL-3',
}
