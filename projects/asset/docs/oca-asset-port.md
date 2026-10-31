# OCA Asset port — PARTIAL

Upstream `OCA/account-financial-tools`, `account_asset_management` 19.0, commit `3646ce0d304ec6eaae5b9b39ebc63b894599ab4b`, AGPL-3. Dependencies `OCA/reporting-engine` `report_xlsx` and `report_xlsx_helper` 19.0, commit `3aecc71449fb1ae2ab230c2e54364eb19b9a4c12`, AGPL-3. Source, license declarations and copyright notices are retained.

Cosmetic import cleanup: README heading underlines and trailing whitespace were normalized for Git checks. Compatibility adaptations: manifest version prefixes 20.0; reporting controller imports moved to `odoo.http.stream` and `odoo.http.dispatcher`; asset ACL/company rules converted to Odoo 20 `ir.access` and separate engine user/manager groups, loaded in the manifest. Original security files remain as provenance but are not loaded. Upstream test users are granted the dedicated engine manager group. ERP integration and OU rules reside in `erp_asset`; engine users have read-only access and managers manage assets. The full ERP restricts engine records to accessible linked acquisitions. Consequently standalone upstream tests and restricted ERP integration tests are run separately.

Standalone imported OCA tests: 26 tests, 0 failures/errors (`/tmp/erp-finance20/oca-project-02.log`). ERP integration and full-stack results are in `test-report.md`. This is a tested subset, not production approval.

OCA 18 `account_asset_transfer`, commit `090f19aa38c90bc211ef41e7e54613b7daa900f7`, AGPL-3, is imported with the compatibility changes documented in `transfer-architecture.md`. Standalone OCA management/transfer regression: 29 tests, 0 failures/errors. ERP restricts transfer to same-company, same-OU AUC assets and records immutable event lineage. It is not an administrative OU/custodian/location transfer.
