{
    "name": "Government ERP Organization Structure",
    "version": "20.0.2.1.0",
    "summary": "Company-scoped organizational units",
    "license": "AGPL-3",
    "depends": ["erp_core"],
    "data": [
        "security/organization_security.xml",
        "security/ir.access.csv",
        "views/organization_unit_views.xml",
        "views/organization_assignment_views.xml",
    ],
    "installable": True,
    "application": False,
}
