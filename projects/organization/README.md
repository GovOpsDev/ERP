# ERP Organization

Company-scoped organization hierarchy for Odoo 20 Community. Upstream reference: [NSTDA ERP-Government](https://github.com/NSTDA/ERP-Government), OCA operating-unit and role source; see [discovery](docs/organization-discovery.md) and [mapping](docs/source-mapping.md). Addons: `erp_organization`, optional `erp_organization_hr`, optional `erp_organization_hr_employee`, and `erp_user_role`. Dependencies: independent `erp_core` project and Odoo Community `hr` for the optional bridge.

Migration status: **MIGRATED**. Production readiness: **NO**. Company hierarchy,
assigned/default OU, department and employee integration, dated additional employee
memberships, native HR visibility and role/update restriction policies are implemented.
See [current status](docs/migration-status.md) and [source parity](docs/source-mapping.md).
Historical source mapping, browser/load/filestore and deployment remain separate readiness.
