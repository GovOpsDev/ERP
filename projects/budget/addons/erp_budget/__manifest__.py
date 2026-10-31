{
    'name': 'Government ERP Budget Foundation',
    'version': '20.0.2.27.0',
    'summary': 'Company-scoped budget periods and funds',
    'license': 'AGPL-3',
    'depends': ['erp_organization', 'account'],
    'data': ['security/budget_security.xml', 'security/ir.access.csv', 'views/budget_views.xml', 'views/budget_amount_views.xml', 'views/budget_adjustment_views.xml', 'views/budget_control_views.xml', 'views/budget_plan_views.xml', 'views/budget_allocation_views.xml', 'views/budget_allocation_revision_views.xml', 'views/budget_transfer_views.xml', 'views/budget_balance_forward_views.xml', 'views/budget_commit_forward_views.xml'],
    'installable': True,
    'application': True,
}
