# Procurement test report — PARTIAL

- Clean installation with Organization, Budget and Procurement: 106 selected tests, 0 failures/errors, no skips reported (`/tmp/erp-org-odoo20/procurement-clean2.log`).
- Upgrade on a copied Budget test DB after seeding an approved PR, confirmed PO and ledger: 104 selected tests, 0 failures/errors, no skips reported (`procurement-upgrade-final.log`). Full-row counts and fingerprints for requests, request lines, reviews, purchase orders, PO lines and Budget moves matched before/after. Copied database lacked matching filestore; attachments are NOT TESTED.
- Latest Procurement-only regression: 10 tests, 0 failures/errors, no skips reported (`procurement-final-targeted.log`). It adds multi-line approval atomicity and native unlinked PO visibility to the earlier clean/upgrade tests.
- Tests use actual PR and native PO records for check-only submission, insufficient budget, ordered review, approval, rejection, PO replacement, cancellation/restoration, and multiple POs; they also cover OU isolation and unrelated contact access. Foreign currencies, taxed lines and multi-combination analytic distributions remain explicitly rejected and are not acceptance passes.
- Budget two-transaction concurrency script was rerun after Procurement install: one 80 commitment succeeded against 100, the other got serialization failure, each control had 80 (`procurement-budget-concurrency.log`). This did not test two concurrent PR approvals.
- Browser, full OCA tier compatibility, requisitions, reports, load, production data and attachment preservation: NOT TESTED.

- Final integration after cross-key support: 111 selected clean-install tests and 109 selected upgrade tests, 0 failures/errors, no skips reported (`procurement-multi-clean.log`, `procurement-multi-upgrade.log`). Database fingerprints of PRs, lines, reviews, POs, PO lines (excluding the intentionally added nullable period field), and ledger matched before/after upgrade. The copied DB did not include its filestore.
- Latest Budget + Procurement focused regression: 38 tests, 0 failures/errors (`procurement-multipokey.log`). It adds real-document tests for changed fund, analytic, dimension and account/KPI, multiple POs with different funds, and cancel/amend/reconfirm.
- Two actual PRs of 80 against allocation 100 were concurrently approved in isolated Odoo transactions: one committed, the other raised `SerializationFailure`; each Budget control remained 80 and states were approved/to_approve (`procurement-pr-concurrency.log`). The reproducible `tests/concurrency_shell.py` commits synthetic data and must only be used on a fresh isolated test DB.

- Final clean install after the Finance boundary guard: 117 selected tests, 0 failures, 0 errors, no skips reported (`procurement-final-clean.log`); the log starts 20 Budget tests, 19 Procurement tests, and 76 Organization/HR/role tests, within the 117 total selected by the Odoo runner. The upgrade run selected 98 tests, 0 failures, 0 errors, no skips reported (`procurement-final-upgrade.log`). The previously reported 109-test upgrade covered the wider selection before the guard. Request, line, review, PO, PO line (excluding the previously added nullable period field) and ledger row counts and fingerprints matched the previous upgrade snapshot. Organization and Budget master preservation is based on the earlier upgrade evidence, not this fingerprint. Filestore remains unverified.
- The guard test blocks a linked bill via normal posting and direct posted-state write, retains the PO commitment, and successfully posts an unrelated vendor bill. At that prior milestone Finance actuals were not yet tested.

- With `erp_finance` installed, the cross-domain clean install selected 134 tests and the upgrade selected 115 tests, both with 0 failures/errors and no skips reported. The log starts 19 Procurement tests in the clean run; see `projects/finance/docs/test-report.md` for Finance cases, test and filestore limitations. Procurement guard remains the fallback when Finance is absent.

2026-10-30 Budget Activity adapter: PR and PO store activity, derive/validate its budget account and pass selection to Budget API. POs preserve the request activity by default and protect it after confirmation; activity-backed keys support a budget account distinct from product/GL expense account. Multiline scope prelocks every activity ID in sorted order. Latest Budget/Procurement/Finance/Contract suite passed 120 tests; complete clean 225 and seeded full upgrade 223, all 0 failures/errors, no test skips reported (logs under `/tmp/erp-org-odoo20/closure-activity-*`). Actual PR concurrency probes are documented in Budget's test report. These are whole-run totals and do not close other Procurement parity gaps.

## Source FX/tax amount policy — 2026-10-30

See `source-amount-policy.md` for exact source and scope. Runtime Odoo20: affected147, FX atomicity1, full clean253 and full upgrade251 tests, all0failures/0errors; no skips reported.38selected historical tables retain every old column. Artifacts `/tmp/erp-org-odoo20/closure-{budget-amount-cross-02,budget-amount-fx-atomic-01,amount-full-clean-01,amount-history-full-upgrade-01}.log` and `closure-amount-strict-{before,after}.txt`. This verifies the amount adapter, not the remaining direct journal/expense/advance/deposit integrations.

## Closure: invoice plans and retention (2026-10-31)

`plans-financial-regression-47.log`: 159 Procurement/Finance/Contract/Asset tests,
0 failures, 0 errors, no skipped tests reported. This reran all six native reversal
failures from run 46 after excluding internal lock counters from copy operations.
`plans-retention-currency-48.log`: 9 targeted tests, 0 failures, 0 errors; includes
Contract plan FX and currency-level retention reconciliation caps.
`retention-plan-race-01.log`: actual concurrent retention-release and purchase-plan
creation both serialize; fresh retries return the one existing document. Test DBs,
volumes and logs remain preserved outside Git. No production deployment acceptance.
