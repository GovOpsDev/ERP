{
    'name': 'GovOpsDev ERP Security Baseline',
    'version': '20.0.1.0.0',
    'summary': 'Invitation-only signup and native login throttling defaults',
    'author': 'GovOpsDev',
    'website': 'https://github.com/GovOpsDev/ERP',
    'license': 'AGPL-3',
    'depends': ['erp_core', 'auth_signup'],
    'data': ['data/security_defaults.xml'],
    'auto_install': True,
    'installable': True,
    'application': False,
}
