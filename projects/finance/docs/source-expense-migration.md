# Expense migration onto Odoo 20

Source: `account-budgeting/budget_control_expense` at b447bab1678f, `budgeting` at 08842c565308, and `ERP-Government/odoo/custom/src/private/egov_hr_expense` at 5a1722c4c6f6. The pinned OCA hr-expense base is 25ccd0820aec84c33644739626a95dfbe42931be with the advance hook fix c15f5f4a31763882a62b411fb6a4ff47bbda683c from NSTDA repos.yaml; a separate temporary source checkout preserves the existing upstream trees.

The removed native hr.expense.sheet is redesigned onto Odoo 20 hr.expense approval. Submission simulates the combined budget and rolls candidate ledger nodes back; approval creates typed expense commitments. Native employee-paid receipts and company-paid entries replace the commitment with actual expenditure. Refund/reset/cancel use immutable paired ledger nodes. Historical accounting entries are cancelled and retained when native reset would otherwise delete them; expense identity and old accounting origins remain protected. Ordinary expenses with no selected Budget key retain native permissions and behavior.

Expense policy uses the native tax-included total, native company amount (including the native expense conversion), and configured expense tax selection. Actuals use the native GL balance and accounting tax policy. Native tax lines can inherit expense_id; only base expense lines are reconciled, so tax is counted once. The same line cannot combine direct Budget keys with a controlled expense source.

Native approver checks remain in force. NSTDA's configurable ordered tiers reuse `erp.budget.kpi.tier` (expense/advance kinds) and the protected `erp.budget.kpi.review` audit model through an expense-specific inherited review. A configured tier disables automatic approval; each reviewer is checked against current company/OU/Expense/Budget permissions. Every tier rechecks budget. Final approval alone creates accounting and commitment; rejection/reset/resubmission retains old review rounds. No tier configuration means native approval applies, as source tier domains/configuration determine whether review is required.

Expense commitment origins participate in the existing reviewed fiscal forward/return machinery. Native accounting analytics must match the approved fiscal destination; the declared historical expense keys are retained. Advance commitment types are implemented by the clearing integration in source-advance-clearing.md.

Evidence under /tmp/erp-org-odoo20:

- closure-expense-02.log: 3 passed, approval/post/reset, immutable history, insufficient submit/final approval, forged workflow and OU revocation.
- closure-expense-money-03.log: 2 passed, VAT/refund, protected historical repost, company-paid accounting, company scope.
- closure-expense-tier-01.log: 1 passed, wrong reviewer/order, duplicate approval, reject/resubmit, final capacity rollback, protected review audit.
- closure-expense-forward-01.log: fiscal forward passed; native uncontrolled permission regression failed and was corrected in closure-expense-native-02.log (1 passed).
- closure-expense-cross-01.log: 163 passed, 0 failures/errors; predates the last two tests and native permission fix. closure-expense-cross-02.log includes all final changes: 165 tests, 0 failures, 0 errors, no skipped tests reported.
- closure-expense-race-02.log: real two-cursor Expense/Expense and Expense/PR races, one commit and one SerializationFailure each, consumption 80 of 100, fresh retry rejected; successful expense reset preserves Budget history. Script: tests/expense_race_shell.py. Synthetic DB: closure_expense_race_02.

Earlier failed runs are retained as diagnostic evidence: initial reset attempted native deletion, submit simulation deferred the check until after rollback, native tax lines initially duplicated VAT, and native reversal cleared the expense link. Each was corrected and its affected flow rerun. The first race run did not approve anything because native duplicate detection opened its wizard; the corrected fixture uses distinct expense dates and asserts actual expenditure/state.

This covers ordinary Expense and tier/fiscal integration. Employee advance/clearing/returns and their accounting settlement are implemented and tested separately in source-advance-clearing.md. Production browser, conversion and filestore rehearsals are separate.
