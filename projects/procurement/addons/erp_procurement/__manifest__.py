{
    'name': 'Government ERP Procurement',
    'version': '20.0.1.8.0',
    'summary': 'Organization-scoped purchase requests and budget integration',
    'license': 'AGPL-3',
    'depends': ['purchase', 'purchase_requisition', 'erp_budget', 'erp_organization_hr_employee'],
    'data': ['security/procurement_security.xml', 'security/ir.access.csv', 'data/sequence.xml', 'views/request_views.xml', 'views/purchase_order_views.xml', 'views/requisition_views.xml', 'views/invoice_plan_views.xml', 'views/government_views.xml'],
    'installable': True,
    'application': True,
}
