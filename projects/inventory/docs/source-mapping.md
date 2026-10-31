# Inventory source parity

Exact source inspection and runtime migration closure, Odoo 20 Community.

| Selected upstream responsibility | Target | Decision |
|---|---|---|
| purchase_work_acceptance: goods/services, partial work, accepted date and quantities | Scoped acceptance with locked aggregate quantity, native receipt/bill matching and manager-selected accepted date | MIGRATED |
| Enable/enforce groups and picking-type bypass | Explicit receipt enforcement group, manager-only bypass; unlinked bills stay optional, every linked document is validated | REDESIGNED |
| Accepted cancel/reset | Require cancellation of all live receipts, bills and fines; immutable snapshots retain prior accepted quantities, actors and results | REDESIGNED |
| purchase_work_acceptance_tier_validation | Reuse Procurement tiers/review records; company thresholds, ordered scoped reviewers, final acceptance and retained rounds | REDESIGNED |
| l10n_th_gov_work_acceptance | Paperless/paper mode, copied PR committees, roles, results, notes, completeness and reset semantics | MIGRATED |
| purchase_work_acceptance_evaluation | Company cases/scores, stage-specific results, configured acceptance requirement | MIGRATED |
| purchase_work_acceptance_invoice_plan | One live acceptance per regular installment, editable draft quantity, final remainder and native bills; deposit deductions are not delivered work | REDESIGNED |
| purchase_work_acceptance_late_fines | Days/rate/override amount, native customer invoice or vendor credit, cancel/recreate, partial reversal caps and foreign currency | MIGRATED |
| budget_control_purchase_work_acceptance_late_fines | Native fine accounting explicitly excluded from Budget | MIGRATED |
| stock_budget_allocation | Fund/analytic/dimension provenance on moves, details, returns and native valuation GL; valuation excluded from Budget | REDESIGNED |
| Source stock.scrap provenance | Odoo 20 removed stock.scrap; native stock.move scrap lifecycle uses the same move provenance adapter | NATIVE ODOO / REDESIGNED |
| stock_request, stock_request_submit, stock_request_tier_validation | Header/lines, submit/review/fulfill/cancel/reset/done; native stock.rule procurement, preserved history and strict company/OU scope | REDESIGNED |
| stock_request_analytic, stock_request_budget_allocation | Native analytic accounts/dimensions and fund propagated through procurement; requests do not authorize Budget | REDESIGNED |
| stock_request_purchase, stock_request_separate_picking | Native RFQ linkage and stock.reference separation; separate RFQ per request line prevents fund/OU mixing | REDESIGNED |
| l10n_th_gov_stock_request | Explicit company permission for virtual customer destinations | MIGRATED |
| stock_request_kanban | Barcode checksum/configuration, replenishment cards, scanned request approval and filtered card census with missing-card history | MIGRATED |
| stock_no_negative | Stored goods at internal/transit locations cannot become negative unless product/category/location allows it; no RPC test-context bypass | MIGRATED |
| Native returns and Asset handoff | Original stock/acceptance lineage retained; Asset and financial reversals tested across native documents | MIGRATED |
| Production roles, warehouses/routes, operational defaults and imported history | Configuration/data rehearsal, not another runtime engine | PRODUCTION READINESS |
| Report/label presentation, production notices, attachments, browser and load | Separate production-readiness phase | PRODUCTION READINESS |

Sources: OCA purchase-workflow **7eed5d2dd34d**, l10n-thailand
**5ebe30a8be97**, budgeting **08842c565308**; selected stock-logistics-warehouse
**3a15b9daa121dcc163a4b1cc6c1bebd47a37e126**, government stock-request source
**b7cd787e4aee25a4657f502c90e8b15900d5573a**, and stock-logistics-workflow
**c0cf073b531ad5b3e28b241df7aba558ca5d9035**. Canonical upstream trees were not edited.

Migration decisions preserve one Budget authority. Fine and stock valuation GL
are explicitly exempt as in the selected source. Stock-request tiers are
unconditional nonfinancial reviews. Financial allocation still belongs to Budget
and the PR/PO/Finance adapters. No capacity is created by a stock request, card,
committee, evaluation, acceptance or invoice plan.

Late-fine daily rates use document currency, matching the source's numeric company
default and explicit draft override. A positive accepted fine is required before
creating its native charge. Historical charge terms and revenue account are fixed;
reversals cannot exceed the posted original. Canceled charges remain auditable.

Runtime evidence outside Git: `test-evidence/closure-20261031/`:
`inventory-asset-72.log` 49 tests, zero failures/errors;
`stock-valuation-74.log` and `acceptance-deposit-75.log` one test each, zero failures/errors;
`fine-race-02.log` and `stock-request-race-01.log` each one committed transaction,
one serialization conflict, safe retry and exactly one native result.
Repeated-reviewer tiers and manual acceptance dates passed final-review-date-78.log: 21 tests, zero failures/errors. Existing accepted dates are preserved and no historical representative is fabricated. Final all-domain clean/upgrade gates are recorded in the workspace closure report.
These are not proof of historical source-data or filestore equivalence.
