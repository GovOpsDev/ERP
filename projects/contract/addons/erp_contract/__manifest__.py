{
    'name': 'Government ERP Purchase Agreements',
    'version': '20.0.1.10.0',
    'summary': 'Organization-scoped agreements linked to purchase orders',
    'license': 'AGPL-3',
    'depends': ['erp_finance'],
    'assets': {'web.assets_backend': ['erp_contract/static/src/js/thai_agreement_date.js', 'erp_contract/static/src/js/agreement_revision_snapshot.js', 'erp_contract/static/src/xml/agreement_revision_snapshot.xml']},
    'data': ['security/contract_security.xml', 'security/ir.access.csv', 'data/sequence.xml', 'views/agreement_views.xml', 'views/contract_views.xml', 'views/guarantee_views.xml', 'views/invoice_plan_views.xml', 'views/agreement_legal_views.xml', 'views/recurrence_views.xml'],
    'installable': True,
    'application': True,
}
