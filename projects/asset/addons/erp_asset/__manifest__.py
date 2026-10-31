{
    'name': 'Government ERP Asset Acquisition',
    'version': '20.0.1.3.0',
    'license': 'AGPL-3',
    'depends': ['erp_inventory', 'account_asset_management', 'account_asset_transfer'],
    'data': ['security/security.xml', 'security/ir.access.csv', 'data/sequence.xml', 'views/asset_views.xml', 'views/thai_asset_views.xml'],
    'installable': True,
    'application': True,
}
