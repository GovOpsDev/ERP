# Agreement & Contract test report — PARTIAL

On 2026-10-29 an isolated Odoo 20 Community/PostgreSQL 16 stack was reused, with no production DB. The final clean installation selected 148 tests, 0 failures, 0 errors and no skips reported (`/tmp/erp-finance20/contract-verified-clean.log`). Its log starts 23 Budget, 19 Procurement, 15 Finance, 13 Contract and 76 Organization/HR/role tests; two web suite entries account for the runner total. The seeded copied-DB upgrade selected 129 tests, 0 failures, 0 errors and no skips reported (`contract-verified-upgrade.log`). The latest focused Budget + Contract run selected 36 tests, 0 failures/errors (`contract-target9.log`).

Real-document tests cover PR → agreement-required RFQ → Agreement → PO → vendor bill and actual; two agreements on one PO; unauthorized manager action; PO vendor and source locking; date validation and expiration indicator; company switching and OU isolation; Agreement version snapshot, changed PO amount and termination without modifying PO/ledger; and direct PO approve bypass rejection. The separate real Contract tests cover contract commitment, partial bill at a different invoice price, refund, close while retaining actual, reset, native reversal carrying its source, over-invoice/insufficient budget rollback, mismatched dimensions, immutable history, and rejection of an invoice line using both Purchase and Contract sources. Moving a Contract line into an already posted unrelated bill is rejected. These are supported-subset tests, not full upstream Agreement Legal or recurring Contract parity.

The Finance milestone copy had a PR, PO, posted PO-linked bill, draft bill and actual. Full-row fingerprints before/after Contract installation matched with only the intentionally added `purchase_order.erp_agreement_required` and `account_move_line.erp_contract_line_id` excluded. The same copied DB was then seeded with an active Agreement, a separate committed Contract and a posted Contract-linked bill. Full-row fingerprints of Organization, Budget, Procurement, Purchase, Accounting, Agreement, revision, Contract and Contract line tables matched before/after the subsequent seeded upgrade. The DB copy had no matching filestore: attachment preservation NOT TESTED.

Targeted concurrency after installing Contract: two PRs against 100 yielded one committed 80 and one serialization failure, both controls 80 (`contract-pr-race.log`); two PO bills on one PO yielded one posted and one serialization failure, total 50 (`contract-bill-race.log`). These are not load/performance or exhaustive concurrency tests. Browser, production data/migration, full legal document/attachment access, tier workflows, scheduled notices, recurring invoices, installment plans and Contract value-amendment lifecycle remain NOT TESTED or deferred.

2026-10-30 allocation-dimension regression: the real allocation revision → Contract → Bill test now excludes the original unused fund and introduces a replacement fund through revision, then commits/posts using the new control. The old allocation amount is retained and effective parent capacity remains 120. Complete selected ERP clean/older-DB-copy suites passed 189/184 tests, 0 failures/errors, no test skips reported (`/tmp/erp-org-odoo20/closure-dimensions-{full-clean-02,upgrade-01}.log`); these are whole-run totals, not Contract-only counts.

2026-10-30 coordinated source-planning acceptance: a new real test builds formal allocation 100 and reviewed KPI planning, prepares allocation 120 with a planning successor, confirms approval has no economic effect until joint activation, then posts a Contract bill with remaining commitment 80 plus actual 40. Original planning remains historical at 100. Latest affected Budget/Finance/Contract suite passed 94 tests, 0 failures/errors (`closure-planning-cross-06.log`); complete clean passed 217 before the final shared-OU test (`closure-planning-full-clean-02.log`). No test skips reported. The earlier 189/184 runs omitted Contract and are subset results; corrected complete runs are recorded in Budget's test report. Whole-run totals are not Contract-only counts.

Real coordinated Contract/Bill acceptance also asserts allocation cancellation rejects remaining contract commitment plus posted actuals and leaves allocation done with consumption 120. Affected Budget/Finance/Contract regression passed 97 tests, 0 failures/errors, no test skips reported (`/tmp/erp-org-odoo20/closure-cancellation-cross-02.log`); this is a whole-run total.

2026-10-30 Activity-aware Contract budget keys: contract lines bind their budget account to activity, use Budget API for KPI selection, retain immutable source identity after commitment/history and expose the source activity on bills. A real two-activity case verifies distinct KPI ceilings for one budget account, GL accounts differing from budget accounts, actuals 40/30 and remaining Contract commitment 0/30 within parent 100. Latest four-domain regression passed 120 tests, complete clean 225 and seeded full upgrade 223, 0 failures/errors, no test skips reported (`/tmp/erp-org-odoo20/closure-activity-*`). Whole-run totals are not Contract-only counts. Other Contract lifecycle/guarantee/recurrence gaps remain.

## Source FX/tax amount policy — 2026-10-30

See `source-amount-policy.md` for exact source and scope. Runtime Odoo20: affected147, FX atomicity1, full clean253 and full upgrade251 tests, all0failures/0errors; no skips reported.38selected historical tables retain every old column. Artifacts `/tmp/erp-org-odoo20/closure-{budget-amount-cross-02,budget-amount-fx-atomic-01,amount-full-clean-01,amount-history-full-upgrade-01}.log` and `closure-amount-strict-{before,after}.txt`. This verifies the amount adapter, not the remaining direct journal/expense/advance/deposit integrations.

## Direct accounting actuals and shared document locking — 2026-10-30

`closure-direct-cross-02.log`:154tests,0failures,0errors,no skips reported across Budget/Procurement/Finance/Contract. Focused direct/refund/scope4, exemption2 and native manual-tax/journal1 tests passed. `closure-direct-actual-race-01.log`: native bill-vs-bill and bill-vs-real-PR each committed one transaction and rejected the other with SerializationFailure; consumed80/limit100, loser draft, fresh retry rejected. Finance `docs/direct-accounting-actual.md` records source, policy and fixture limitations. The last full clean253/upgrade251 gates predate this direct-actual extension; final closure requires refreshed full gates after the remaining migrations.

## Closure: native guarantee settlement (2026-10-31)

Seven guarantee cases cover partial/full receive/return, non-cash instruments,
requisition source, company/OU denial, payment/GL/reconciliation visibility,
forged links/state, immutable history, overpayment and payment-reset backing.
`retention-guarantee-36.log`: 10 tests total, 0 failures, 0 errors; no skips reported.
`guarantee-financial-regression-32.log`: 126 affected-domain tests, 0 failures,
0 errors. Real two-transaction return race passed in `guarantee-race-03.log`.
See `source-guarantee.md` for source identity, behavior and precise evidence.

## Closure: invoice plans and retention (2026-10-31)

`plans-financial-regression-47.log`: 159 Procurement/Finance/Contract/Asset tests,
0 failures, 0 errors, no skipped tests reported. This reran all six native reversal
failures from run 46 after excluding internal lock counters from copy operations.
`plans-retention-currency-48.log`: 9 targeted tests, 0 failures, 0 errors; includes
Contract plan FX and currency-level retention reconciliation caps.
`retention-plan-race-01.log`: actual concurrent retention-release and purchase-plan
creation both serialize; fresh retries return the one existing document. Test DBs,
volumes and logs remain preserved outside Git. No production deployment acceptance.
