# Budget actual adjustment migration

Exact source: account-budgeting/budget_control/models/budget_move_adjustment.py and budgeting/budget_allocation/models/budget_move_adjustment.py at the revisions recorded in budget-parity-matrix.md.

The manager-owned draft/done/cancel/reset document, reason, date, positive consume/release lines and company/fund/analytic/account dimensions are migrated as erp.budget.adjustment. Source destructive recomputation is redesigned into paired immutable actual/reversal nodes through the existing Budget API. No additional tier engine is required by this source. Amounts use company currency. A confirmed document remains immutable after cancel/reset; copy creates a new correction. Reapplying the same effective document is idempotent. Cancelling a release checks final shared-plan and control capacity, including subsequent commitments, and fails atomically if capacity has since been consumed.

Access uses the existing Budget manager capability and company/OU rules. Document edits and economic transitions serialize through document and common Budget locks. History includes original amount, direction, reason and dimensions. Activity account edits recognize adjustment usage.

Runtime evidence: closure-budget-adjustment-01.log: 3 tests, 0 failures, 0 errors. Tests cover immutable apply/cancel/reset history, copies, idempotency, release reversal after consumption, insufficient funds, forged workflow metadata, company identity and manager capability. closure-adjustment-cross-01.log: 157 Budget/Procurement/Finance/Contract tests, 0 failures, 0 errors.
