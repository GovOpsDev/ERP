# Asset handoff

`erp_asset` consumes accepted work, purchase and bill lines, company, assigned OU,
quantity and acceptance date. Native signed accounting value determines acquisition;
the account/company profile controls eligibility. Aggregate and per-item acquisition,
Expense acquisition, OCA depreciation, Thai dates/salvage/substates/low-value,
credit/reset generations and immutable AUC transfer lineage are implemented.

Acceptance alone creates no Asset. Historical posted bills are not automatically
backfilled. Native stock returns retain source provenance and do not silently
rewrite acquisitions; the native accounting credit/reset flow changes the Asset
through its explicit audit history. Repeated invoice posting cannot duplicate it.

Inventory/Asset runtime regression and all-domain clean/upgrade evidence are in
the workspace closure report. Source-data reconciliation, attachments, browser,
load and deployment remain production readiness.
