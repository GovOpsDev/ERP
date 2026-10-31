{
    'name': 'Government ERP Work Acceptance',
    'version': '20.0.1.3.0',
    'license': 'AGPL-3',
    'depends': ['purchase_stock', 'erp_finance'],
    'data': ['security/security.xml', 'security/ir.access.csv', 'data/sequence.xml', 'views/acceptance.xml', 'views/integration.xml', 'views/fines.xml', 'views/workflow.xml', 'views/stock_provenance.xml', 'views/stock_request.xml', 'views/kanban.xml'],
    'installable': True,
    'application': True,
}
