# ERP Budget — MIGRATED

`erp_budget` provides the Odoo 20 Community canonical fiscal-period, plan,
allocation, planning/control, tier, transfer and carry-forward lifecycle.
Immutable ledger consumption resolves against one effective capacity graph;
Procurement, Finance and Contract use its APIs for commitments and actuals.
Allocation dimension changes preserve predecessors and reject removal of consumed
capacity. Opening balances are planning floors, not additional spending authority.

See [source parity](docs/budget-parity-matrix.md) for exact source decisions,
redesigns, runtime evidence and historical-data boundaries. The workspace closure
report records the final cross-domain clean-install and historical-upgrade gates.

Production readiness is **NO**. Real source-data conversion/reconciliation,
filestore, browser, load and deployment acceptance remain separate.
