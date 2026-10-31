{
    'name': 'Government ERP Finance Budget Integration',
    'version': '20.0.1.13.0',
    'summary': 'Controlled vendor bill and purchase budget reconciliation',
    'license': 'AGPL-3',
    'depends': ['erp_procurement', 'hr_expense', 'l10n_th'],
    'data': ['views/request_conversion_views.xml', 'security/ir.access.csv', 'views/activity_views.xml', 'views/direct_actual_views.xml', 'views/expense_views.xml', 'views/advance_views.xml', 'views/purchase_deposit_views.xml', 'views/retention_views.xml'],
    'post_init_hook': 'post_init_hook',
    'installable': True,
}
