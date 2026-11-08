{
    'name': 'NSTDA eGov — คู่มือการใช้งาน',
    'version': '20.0.1.2.0',
    'summary': 'Thai HTML guides for the integrated government ERP applications',
    'author': 'GovOpsDev',
    'license': 'AGPL-3',
    'depends': [
        'erp_organization_hr_employee', 'erp_user_role', 'erp_asset',
        'erp_contract', 'spreadsheet_dashboard', 'project',
    ],
    'data': ['views/manual_menus.xml'],
    'installable': True,
    'application': False,
}
