{
    'name': 'GovOpsDev Project Budget BI',
    'version': '20.0.1.0.1',
    'category': 'Accounting/Accounting',
    'summary': 'Project budget dashboards, pivot analysis and ledger drill-down',
    'author': 'GovOpsDev',
    'website': 'https://github.com/GovOpsDev/ERP/',
    'license': 'AGPL-3',
    'depends': ['erp_budget', 'project', 'spreadsheet_dashboard'],
    'data': ['security/ir.access.csv', 'views/budget_report_views.xml', 'data/dashboard.xml'],
    'assets': {'spreadsheet.o_spreadsheet': ['erp_budget_dashboard/static/src/budget_chart_display.js']},
    'installable': True,
    'application': False,
}
