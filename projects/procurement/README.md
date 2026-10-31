# ERP Procurement — MIGRATED

`erp_procurement` migrates the Odoo 20 Community government purchase-request
lifecycle, types/methods/committees, verification, ordered approval and retained
review rounds. It integrates captured request currency, native requisitions,
PO tiers, expense conversion and purchase invoice plans with the canonical Budget
APIs. Done/reset preserves the appropriate commitment and downstream history.

See `docs/source-mapping.md` and the workspace closure report for exact source
scope and final runtime evidence. Production readiness is **NO**: real configuration,
source-data conversion, browser, filestore, load and deployment remain separate.
