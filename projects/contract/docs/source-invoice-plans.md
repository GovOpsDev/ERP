# Contract invoice plans

Exact selected OCA Contract source `944dcbeaa513c242c7df31452c54801b764ebf54`:
`contract_invoice_plan` and `contract_invoice_plan_selection`. Target plans preserve
percentage/quantity/date semantics, final remainder, native invoice linkage and
optional manual out-of-sequence installment selection. Persisted selected contract
line quantities must match the installment amount and unbilled contract quantity.

`erp.contract.invoice.plan` reuses purchase-plan source locks, idempotency and
immutable used plans, with a separate contract source, company/OU rules and native
`erp_contract_line_id` accounting provenance. A contract plan cannot also link a PO.
No new capacity authority is created. Source executable matching server-action presets
are configuration; users may select the same source lines/quantities directly.

Runtime: `plans-retention-45.log` has 10 passing plan/retention cases, including
Contract quantity totals, Budget commitment-to-actual, manual selection, immutable
history and OU revocation. Final broad financial regression is recorded alongside
Finance evidence. Legal and recurring lifecycle remain separate required rows.
