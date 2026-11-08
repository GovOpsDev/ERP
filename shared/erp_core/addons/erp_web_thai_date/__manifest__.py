{
    'name': 'GovOpsDev Thai Buddhist Dates',
    'version': '20.0.1.0.0',
    'summary': 'Full Thai dates with Buddhist years across backend forms',
    'author': 'GovOpsDev',
    'website': 'https://github.com/GovOpsDev/ERP',
    'license': 'AGPL-3',
    'depends': ['erp_core', 'web'],
    'assets': {
        'web.assets_backend': [
            'erp_web_thai_date/static/src/thai_date.js',
            'erp_web_thai_date/static/src/backend.js',
        ],
    },
    'auto_install': True,
    'installable': True,
    'application': False,
}
