# Dependencies — PARTIAL

`erp_asset` uses `erp_inventory` (which uses Accounting, Purchase/Stock and Finance) and the existing Organization contract. It does not use Enterprise. Exact source dependency and Odoo 20 capability findings are in `upstream-analysis.md`. Depreciation and full Government Asset depend on the OCA 15 Asset source and Thai extensions, not yet migrated.
