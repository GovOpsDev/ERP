# Purchase deposit source migration

Status: **REDESIGNED** on native Odoo 20 purchase down payments.

Inspected sources: NSTDA's pinned `purchase-workflow` purchase_deposit,
`budgeting/budget_allocation_purchase_deposit/models/{purchase,account_move_line}.py`,
and `budget_activity_purchase_deposit`. Native runtime: Odoo 20.0-20261015
`purchase/wizard/bill_to_po_wizard.py`, purchase order down-payment construction,
and native down-payment tests.

Source uses zero-quantity deposit PO lines, invoice quantity for the deposit actual,
negative final-bill deductions, and redistributes outstanding deposit consumption
against ordinary PO commitments. Deposit activity excludes its KPI from the planning
lookup, falling back to the shared analytic ceiling.

Target uses the native matching wizard, native deposit line and final invoice
construction. A deposit explicitly selects an approved ordinary PO budget source
(automatic only for a single source). Separate bill lines represent separate sources.
Its original bill line and PO source remain immutable. Budget uses that approved
source's fund/activity/KPI and canonical shared plan, rather than introducing a
separate deposit KPI or distributing consumption implicitly across unrelated PRs.
Consequently the originating KPI retains responsibility for the deposit actual;
this intentionally prevents a temporary deposit from freeing that KPI for unrelated
spending. Legacy source deposit-KPI rows must be mapped to their approved PO source
in the production conversion mapping, not imported as additional capacity.

Posting/matching atomically replaces part of the remaining PO commitment with the
native company-currency actual. Final deductions offset the deposit actual, while
ordinary delivery quantities release the remaining commitment. Partial deductions,
native refunds, taxes through the captured accounting policy, foreign currency,
reset and cancellation retain ledger reversal history. Deduction/refund net foreign
currency cannot exceed the original posted deposit. Refunds require a posted native
origin. Original account/currency, company, vendor and fiscal analytic are validated.

Native posting guards also apply to direct state writes and all posted accounting
line mutations. The wizard cannot attach an Expense, Contract or direct-budget line.
Whole accounting documents and every line use the source OU access restriction,
including related lines hidden by ordinary record rules. No client context enables
internal matching authority. PO cancellation requires posted deposits to be reset.

Fiscal forwarding remains owned by Budget: the ordinary outstanding PO key is
carried; previous deposit actuals keep their original year/GL analytic. New-year
ordinary bills and deductions use the carried analytic and consume only the carried
net amount. No additional fiscal authority is created by the deposit adapter.

Runtime evidence in `/tmp/erp-org-odoo20`:
- `closure-deposit-finance-01.log`: 59 Finance tests, 0 failures, 0 errors.
- `closure-deposit-forward-01.log`: 1 fiscal-forward test, 0 failures, 0 errors.
- `closure-deposit-race-02.log`: two real transactions deduct 30 each from a deposit
  of 40; one commits, one receives SerializationFailure; fresh retry rejects the
  excessive deduction. Final consumption100 = commitment40 + actual60.
- `closure-deposit-03.log`: both full/partial native invoice lifecycle cases pass.

No test skips were reported. Browser, production conversion and filestore rehearsal
remain production readiness work. The isolated race DB preserves synthetic history.
