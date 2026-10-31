{
    'name': 'Organization User Roles',
    'version': '20.0.1.1.0',
    'license': 'AGPL-3',
    'depends': ['erp_organization'],
    'data': ['security/security.xml', 'security/ir.access.csv', 'views/role_views.xml', 'views/restriction_views.xml', 'data/cron.xml'],
    'installable': True,
}
