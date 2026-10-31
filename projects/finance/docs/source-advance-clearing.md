# Employee advance and clearing migration

Exact upstream: OCA hr-expense pinned c15f5f4a31763882a62b411fb6a4ff47bbda683c, `hr_expense_advance_clearing`; NSTDA repos.yaml base 25ccd0820aec84c33644739626a95dfbe42931be. Budget adapters are `account-budgeting/budget_control_advance_clearing` at b447bab1678f, `budgeting/budget_activity_advance_clearing` and `budget_allocation_advance_clearing` at 08842c565308. NSTDA `egov_hr_expense` supplies configurable ordered approval as described in source-expense-migration.md.

## Financial lifecycle

The removed expense sheet is represented by native Odoo 20 expense documents. An advance is employee-paid and tax-free, posted to a configured reconcilable current-asset employee advance account. The dedicated source product/account combination is redesigned as an explicit account setting and advance flag. Source account identity becomes immutable once used. Posting its employee receipt creates no Budget actual: the advance remains a typed commitment.

Clearing can link several advances for the same company, employee and OU. Approval releases oldest advance commitments first and reserves the clearing as an expense. Native posting produces the actual expense. A linked protected settlement journal debits the employee payable and credits the advance account, then reconciles both native accounts. This is financially equivalent to the source's replacement of the payable credit with advance credit while retaining Odoo 20 receipt/payment processing. Excess clearing remains payable to the employee. Pending approved clearing amounts reduce the advance available for a return even before accounting posts.

Return documents post an inbound bank/cash debit and advance credit, using native currency conversion. Positive company amount, document currency precision, company, OU, native accounting rights and available balance are checked. A posted return reduces the advance commitment and reconciles the advance account. Repeated posting is idempotent. Cancelling a return restores the commitment atomically; if other real documents consumed the released capacity, cancellation rolls back with the original accounting still posted.

Resetting a clearing cancels its protected settlement before resetting its receipt. Source expenses, ledger reversals, settlement/return accounting and native origins remain available for audit. Direct reverse/refund of a clearing is replaced with its coordinated native reset/cancel route, which reverses its accounting and Budget together. Advances with posted clearings/returns cannot be reset or reversed first. Generated settlement/return entries and their financial identity cannot be created, edited, reposted or deleted directly through RPC. Ordinary native reconciliations remain native.

The ordinary Expense tier infrastructure is reused with the `advance` review kind. Prepare Clearing / Return actions supply scoped draft defaults, including fiscal forward routing, without copying stale native computed amounts from an approved expense.

## Source Advance KPI

`budget_activity_advance_clearing/models/budget_period.py` removes the Advance KPI from template lines. The base `_get_where_domain` treats an empty template list as the whole analytic, so this is a fallback to the analytic ceiling, not unlimited funds. Its control adapter also excludes Advance KPI from planning-date initialization.

The target explicitly marks an Advance reservation KPI. Its analytic tracking control has zero independent capacity and accepts only typed advance commitment/reversal nodes. A confirmed shared plan is mandatory; full advance consumption still counts against that plan and the fund allocation. It is excluded only from the per-KPI capacity check and commitment-based planning initialization. Existing KPI/period classifications are not rewritten. Removing a consumed reservation control is rejected, while retaining its zero-capacity row does not falsely block a planning successor. No extra bucket is created. Ordinary expenses/clearings cannot use the special KPI.

Forwarding the typed advance commitment uses the existing Budget fiscal origin routing. Next-year clearing uses the new period/analytic while the original posted advance accounting retains its historical analytic. Native settlement links both periods without rewriting old GL identities.

## Runtime evidence

All files below are under /tmp/erp-org-odoo20:

- closure-advance-03.log: 3 passed; full advance/clearing/return/reset, pending-clearing over-return rejection, excess payable, real PR consuming returned capacity and atomic rejection of cancellation, OU revocation and protected accounting.
- closure-advance-kpi-multi-02.log: multi-advance FIFO passed; its KPI fixture tried changing an effective period and was corrected to a new period.
- closure-advance-kpi-03.log: Advance KPI fallback passed. The later cross suite adds a parent-cap rejection while fund capacity remains available.
- closure-advance-fx-01.log: foreign-currency advance and bank return passed, native 80 foreign = 40 company, return 20 foreign = 10 company, remaining commitment and native asset residual both 30.
- closure-advance-forward-01.log: next-year commitment forward, clearing, native original/new analytic identities, reset and preserved ledger amounts passed.
- closure-advance-race-01.log: two real PostgreSQL cursors; return/return and clearing-approval/return each produce one commit and one SerializationFailure. Fresh retry rejects over-return; no duplicated return or clearing. Synthetic DB closure_advance_race_01 is preserved. Script: tests/advance_race_shell.py.
- closure-advance-cross-02.log: 173 cross-domain tests, 0 failures, 0 errors, no skips reported. Includes native draft preparation actions. Final provenance assertions and explicit special-activity validation are checked separately in closure-advance-provenance-01.log: 55 Finance tests passed, 0 failures/errors, no skips reported. New advance ledger snapshots include the exact approved clearing allocations and native return-line IDs; reversal nodes retain the original snapshot.

Earlier failures in closure-advance-01/02 were fixture errors: copying an approved native expense preserved its computed company total, so its receipt differed from the new clearing amount. Fresh native draft creation fixed the fixture and all financial effects were rerun. Other early KPI fixture errors are retained in their logs.

Production browser coverage, matching filestore, full historical production conversion, load and deployment are separate readiness work. Purchase deposit integration remains a separate required Budget dependency in this closure run.
