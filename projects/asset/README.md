# ERP Asset — Odoo 20 Community

Migration status: **MIGRATED**. Production readiness: **NO**.

The domain combines immutable, organization-scoped acquisition records with the
ported OCA depreciation and AUC-transfer engines. It supports accepted purchase
bills, native Expenses, item/aggregate acquisition, Thai daily depreciation and
low-value tracking, disposal, fund/analytic provenance, and audited credit/reset
without deleting original acquisition history.

See [source parity](docs/source-mapping.md) for exact source references and decisions,
[test evidence](docs/test-report.md) for runtime and historical-upgrade validation,
and [OCA provenance](docs/oca-asset-port.md) for the reused engine.

Historical source-data conversion, filestore/browser coverage, production load and
deployment remain separate readiness work. This repository has not been pushed.
