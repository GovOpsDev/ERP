# Retention and purchase-plan financial integration

Exact upstream sources:
- OCA account-invoicing `82652f4b7747702c42cf5b3b95b9201fc427837e`,
  `account_invoice_payment_retention` (selected by ERP-Government repos.yaml).
- OCA purchase-workflow `7eed5d2dd34d14edd74c6c80c235d0c75619f1d8`, invoice plan;
  selected retention merge `4721ed2c2a6dd64b09ce55c2b3abb94ac51a829c` and deposit
  merge `2ce8d48946011cb38d25d15a6d876703a48eb1c3`.
- Budgeting `08842c565308`, retention release `not_affect_budget` bridge.

Retention preserves source percentage/fixed suggestions, positive-line untaxed/total
base, explicit payment opt-out, native payable/receivable write-off and company-currency
release invoice reconciliation. The original invoice books Budget actual once;
retention and release carry no direct/purchase/contract Budget dimensions and cannot
be changed to add them. An immutable retention record links original invoice, payment,
GL retained balance, company/OU and all cancelled or live release documents.

Source native Odoo 20 explicitly drops simultaneous write-offs and withholding lines.
The adaptation uses one atomic native WHT-only payment, then the retained cash payment.
For cost 100, WHT 3, retention 10: WHT-only settles 3; cash 87 plus retention 10 settles
the remaining 97. The WHT base stays 100; there is no fictional liquidity for WHT.
All steps roll back together. Ordinary payments keep native behavior.

Server-side redesigns: lock/write versions for payment and release, immutable
financial links/amounts, same company and assigned OU, no raw state/line/reconcile
forgery, and safe reset/cancel with native unreconciliation. A live release blocks
removal of its source payment/reconciliation. Native copies do not copy lock counters.
Full retention with zero cash and foreign-currency conversion uses native balanced GL.

PO plan retention terms propagate to each native invoice. Deposit plans use existing
native bill-to-PO matching, one explicitly approved purchase-line budget source per
deposit; additional deposits use separate plan rows (nonpositive installment numbers).
This preserves source multi-deposit semantics without merging different fund families.
Regular installments deduct their percentage of the deposit; the last takes the exact
remaining fraction. Plan amounts report the positive work value, excluding deductions.
No additional Budget capacity is created.

Runtime evidence (`th-gov-erp/test-evidence/closure-20261031/`):
- `plans-retention-45.log`: 10 tests, zero failures/errors; PO/Contract plans,
  deposit deductions, retention, foreign/zero-cash and native WHT.
- `retention-plan-race-01.log`: actual two-transaction release and plan races;
  each has one commit, one SerializationFailure, and an idempotent fresh retry.
  Database `closure_20261031_retention_plan_race_01` is retained.
- Broader affected-domain regression is recorded in `test-report.md`.

Production account selection, historical retention migration/reconciliation,
filestore, browser, scheduler operations and deployment remain separate readiness work.
