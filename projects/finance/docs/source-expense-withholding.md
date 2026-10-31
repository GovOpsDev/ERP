# Expense withholding source parity

Required Expense/Advance withholding integration is MIGRATED / REDESIGNED.
Finance still has the independent invoice-plan retention integration row to close.

Source: NSTDA-selected l10n-thailand `5ebe30a8be97`,
`l10n_th_account_tax_expense/models/{hr_expense,hr_expense_sheet,account_move}.py`.
The source assigns supplier tax reference/date and creates a clearing JV debiting
employee payable first, then advance, while crediting withholding. It reconciles
those accounts and protects cancellation of a clearing with an active WHT JV.

Target uses native Odoo20 Community `l10n_th` and
`l10n_account_withholding_tax`; no independent tax-rate or certificate engine.

* Employee-paid expense: a withholding-only native payment settles the employee
  payable; the supplier remains the payment/certificate beneficiary. Receipts with
  withholding remain separate per expense, preserving supplier identity on batch
  approval. Native HR unit prices include VAT: withholding is calculated through
  the native tax engine on the recorded untaxed receipt amount, including historical
  receipts. Foreign employee receipts use their original native company amount.
* Advance clearing: withholding is applied before the ordinary advance settlement.
  A gross expense of80 with3% WHT settles77.60 against the advance and leaves2.40
  returnable. Budget actual remains80. The return cannot reduce that actual or
  produce a second spending bucket. Pending clearings retain the conservative
  gross reservation until posting. Excess payable follows native reconciliation.
* Company-paid expense: native withholding lines are attached to its existing
  payment/expense entry and only the outstanding payment amount is reduced. The
  expense cost is unchanged. Native payment withholding and net amounts remain
  consistent; no second cash payment is introduced.
* Ordinary VAT/WHT and all-tax Budget policies: WHT is a liability/payment split,
  never an expense tax deduction from Budget actual. VAT follows the selected policy.
* Supplier tax invoices: native tax-invoice records carry source reference/date and
  captured supplier identity for expense receipts. Reset cancels and retains old
  evidence; repost creates successor evidence. Budget actual snapshots retain the
  supplier reference/date. These native records are evidence, not approval of a
  production statutory report template.
* Generated payment/accounting/tax identities cannot be supplied or edited via RPC.
  Native source reset cancels WHT and advance settlement atomically. Protected WHT
  reconciliation cannot be manually detached. Company/OU access applies to payment,
  withholding lines, journal items, partial reconciliation and tax evidence.

Real runtime evidence, `/home/patrixr/GovOpsDev/th-gov-erp/test-evidence/closure-20261031/`:

| Gate | Result |
|---|---|
| `finance-organization-final-08.log` | 153 tests, failures0, errors0, skips0 reported; affected Finance/Organization/HR suites |
| `wht-final-09.log` | 6 targeted tests, failures0, errors0, skips0 reported; final history/reset/VAT/FX/OU controls |
| `cross-clean-10.log` | Clean install, 301 tests, failures0, errors0, skips0 reported across all11 ERP modules, including foreign company payment |
| `wht-race-03.log` | Real two-cursor receipt posting and return-vs-return; one commit and one SerializationFailure in each race, fresh retry rejected, exactly one WHT payment, final advance residual0 and Budget consumption80 |

Runtime image in this execution: Odoo20.0-20260926. The previous temporary runtime
was absent; the isolated stack was recovered using the existing test-only
`erp-finance-test20` network and preserved volumes. No production data changed.
The failed early race fixtures are retained: first triggered native duplicate
expense approval instead of reaching a bill; second reused a stale setup snapshot.
The successful fixture asserts actual approval/accounting state before racing and
starts a fresh setup transaction between the two races.
