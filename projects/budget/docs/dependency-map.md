# Budget dependency map — partial

The upstream manifest direction is `budget_control` → `budget_plan` → `budget_allocation` (arrows here mean prerequisite to dependent). `budget_control_purchase` adds native purchase to control; `budget_control_purchase_request` requires that extension and purchase requests; `budget_control_purchase_requisition` adds request-to-requisition; the allocation extensions add analytic dimensions and funding-source propagation. `base_tier_validation_check_budget` combines OCA tiers and budget control. NSTDA request tier definitions and server actions use this chain.

The business lifecycle differs from a simple persistent reservation chain:

1. A period and template configure controls, analytic accounts and optional KPI/account granularity. Allocation lines have funding sources and analytic dimensions; completed allocation updates a plan, which feeds controlled budget sheets.
2. Request submission and configured tier approvals perform a temporary precommit check. PR approval creates PR commitment; confirmed PO creates PO commitment and offsets linked PR commitments. Posted accounting moves consume actual amounts and cause linked PO amounts to be recomputed.
3. Rejection/reset and PO cancellation recalculate or reverse related commitments. Transfers, revisions, forward balances, invoice/expense, procurement agreement and activity dimensions add further paths.

The requested persistent precommit, if implemented, would be a **redesign**, not a faithful claim about the source method. It needs explicit rules for when reservation is acquired, resized, converted and released, including partial PO and invoice flows; locks must cover every affected budget scope and no direct record creation may bypass the service. Document the deviation and test its effect against NSTDA workflows before calling the contract stable.

Unresolved: effective source after remaining NSTDA dependency repo merges; complete KPI/analytic, tax/currency, reporting, data security and multiple-PO replacement semantics; Odoo 20 Community dependency availability; external interfaces. These are investigation tasks, not evidence that Procurement or Budget is migrated.

Detailed target mapping and unresolved multiple-PO conversion semantics: `budget-lifecycle-v1.md` (draft, not frozen).
