# Migration completeness audit

Fresh exact-source audit started immediately after Budget closure on 2026-10-30.
**MIGRATION COMPLETE. PRODUCTION READY = NO.** All seven domains have closed
required source implementation. Final clean-install validation passed 373 tests;
historical upgrade passed 371 tests, both with zero failures/errors and no reported
skips. There is no hard blocker or remaining required migration item. The final
closure report records exact evidence and the separate production-readiness boundary.

| Domain | Required upstream scope | Implemented | Remaining REQUIRED | Production readiness | Enhancements | Status |
|---|---|---|---|---|---|---|
| Organization | operating_unit, hr_operating_unit, base_user_role and selected restrict-update extension | Company hierarchy, assigned/default OU, dated multiple employee OU, native HR/public/version/HTTP boundaries, role membership/provenance/delegation | None | Source employee/role/partner mapping, shared-resource and published-attachment review, browser/load | Search facets and access-inspection UI | MIGRATED |
| Budget | Plan/allocation/control revisions, planning/activity/KPI, ordered tier, transfer/reversal, openings, forwards/returns and financial adapters | Canonical effective graph; immutable economic history; source-backed currency/tax, direct actual, Expense/Advance/Deposit and PR handoff | None | Historical source conversion, XLSX mapping, filestore/browser/load | Cosmetic monitors, activity search and department aggregation | MIGRATED |
| Procurement | PR/tier, government types/methods/committees, verified workflow, requisition and native PO | Approved PR→native requisition→PO; native invoice plans/deposit/retention; captured PR FX and requisition/PO propagation; company/OU and native money policy | None | Real procurement configuration and thresholds, historical import, browser | Report presentation | MIGRATED |
| Finance | Native accounting/FX/tax/refund, advance/deposit and fiscal commitment; Thai expense tax integration | Budget-aware actual/refund/FX/VAT/WHT; Expense/advance and PR handoff; native deposits, retention and planned deductions; fiscal routing | None | Posted-data reconciliation, statutory template verification, attachments, bank/export setup, load | Optional financial reporting layouts | MIGRATED |
| Contract | Agreement legal content/stages/versions, recurring contracts, invoice plans, guarantees | PO-referential agreements; independent Budget Contract and native bills/refunds; guarded guarantee receive/return; invoice plans/manual selection/FX; signed legal versions/reviews; recurring periods and amendment/renewal successors | None | Signed-document migration, scheduler operations and production notices | Cosmetic legal reports | MIGRATED |
| Inventory | Configurable WA, goods/services partial acceptance, receipt/bill/return, government WA and inventory source provenance | Scoped partial WA, configured receipt enforcement/bypass, retained cancel/reset history, committees/evaluations/tiers, native exempt fines, invoice installments/deposits, fund/return/valuation provenance, native stock requests/RFQs, Kanban cards/census and negative-stock policy | None | Legacy receipts/stock reconciliation, warehouse setup, browser/load | Report polish | MIGRATED |
| Asset | OCA acquisition/depreciation/removal/AUC, Thai day calculation/substates/low-value and refunds | WA/Expense acquisition, item/aggregate, OCA engine, Thai lifecycle, source fund/analytics, audited credit/reset generations and protected AUC lineage | None | Historical source depreciation/filestore, conversion, browser and production load | Unproven administrative custodian/location workflow is not required | MIGRATED |

## Exact fresh source evidence and decisions

Organization: re-read `operating_unit/models/{operating_unit,res_users}.py` at
c0a597931509, HR department/employee rules at the selected 3c5f7c source, and current
Organization/HR/role models and tests. Partner is a required upstream unit relation.
`base_user_role_restrict_update` at 995ad9e adds read-only/unrestricted-update flags,
propagated to users by onchange; its selected restriction-engine dependency requires
an actual runtime adaptation. NSTDA role presets and group membership choices are
configuration, not a second role engine. Current strict assigned-OU HR boundaries,
dated additional employee memberships and preserved direct group grants are explicit
redesigns. Broad untested browser/shared-resource surfaces are readiness, not proof
of missing source runtime behavior.

Procurement: re-read `purchase_request`, `purchase_request_tier_validation`,
`purchase_invoice_plan` at purchase-workflow 7eed5d2dd34d and Thai government request
models at 5ebe30a8be97 against target PR/PO/tier code. Source has done/reset,
verified/approved actor and date, configurable type/method/committees and conversion
routing. These fields/actions and immutable submission rounds are now implemented and tested. Native PO approval does not establish
parity with configured OCA tiers. Requisition is required where government conversion
selects it; unrelated optional OCA requisition extensions are not presumed required.
Invoice plans calculate percentages, final remainder, dates and native invoice links;
they do not create additional Budget capacity. Threshold presets are deployment data.

Finance: re-read actual target adapters/tests and source Budget amount/expense,
advance, deposit and fiscal extensions. The current closure runtime image Odoo20.0-20260926 contains
`l10n_th` and `l10n_account_withholding_tax` with withholding-only payments and 50 Tawi.
Ordinary native WHT can be NATIVE ODOO once exercised in integration. Source
`l10n_th_account_tax_expense/models/{hr_expense,hr_expense_sheet,account_move}.py`
adds vendor/reference/date and a clearing WHT journal: debit payable first, then
advance, credit WHT, reconcile, and guard reset. This is required integration;
merely having native taxes is insufficient. Native analytic distributions represent
source primary analytic plus dimension tags through explicit document lines; no
independent arbitrary split-capacity engine is source-required. Refund/FX/VAT/
Advance/Deposit/fiscal behavior is now verified, not left generically deferred.

Contract: freshly retrieved OCA agreement 8e18e0da1e27 and contract invoice-plan
944dcbeaa513 in separate temporary references. Re-read Agreement Legal fields,
stages, version copy and review-activity scheduler, contract recurrence generation,
termination/renewal hooks and invoice-plan quantity/date/last-remainder behavior.
These required workflows are now implemented and tested in the target Agreement,
Contract, guarantee, recurring and installment models. Thai `purchase.guarantee` at 5ebe30a8be97
tracks purchase/requisition source, methods/types and received/returned amounts via
reconciled native documents. Its financial workflow is required; report layout is
separate. Agreement itself must not add a second PO commitment.

Inventory: re-read source WA `work_acceptance`, `stock_picking`, `account_move`,
configured groups/picking bypass, government and Budget provenance adapters against
current acceptance/integration and tests. Source does not universally require WA
at a backend boundary: incoming requirement is group/picking-type driven and the
bill flag is conditional on an existing WA. The optional/enforced configuration
must be preserved, alongside validation of every linked document. Accepted reset
has related-receipt restrictions; the target now safely permits unconsumed cancellation/reset with retained snapshots.
Native returns preserve original receipt identity, but integration and metadata
are now runtime-tested, including financial late fines, stock valuation, installments/deposits and Asset handoff.

Asset: re-read target imported OCA engine and acquisition/transfer guards;
source l10n_th_account_asset_management computes Thai daily depreciation using
purchase minus salvage over inclusive actual days and adds parent/substate.
Government low-value uses expense account plus zero method years, zero residual,
open tracked state and removal without a new accounting entry. Source OCA refund
can create signed asset values and reset can remove draft acquisitions. The former
target blanket refund/reset rejection has been replaced with immutable audited
reversal and retained acquisition generations. Imported OCA engine remains reused,
not replaced. OU/custodian/location administrative transfer is NOT REQUIRED unless
an exact source action establishes it; a field alone is insufficient evidence.

## Execution priority followed during closure

1. Financial correctness: Expense/Advance WHT, asset reversal and Thai accounting,
   guarantee receive/return, recurring/installment invoices and retention.
2. Government workflow and dependencies: procurement types/methods/verification,
   requisition, committees, PO/WA tiers and inventory requests/fines.
3. Authorization: role read-only/restricted update, source scope/default/partner
   integration; preserve and rerun company/OU tests throughout financial work.
4. Required metadata and scheduling, then fresh cross-domain regression and final
   status reconciliation. Dependency order may move a prerequisite earlier.

No required row was waived because it was complex. The implementation/test/fix
loop closed all seven domains. No push or production changes occurred.

## Historical Budget baseline (superseded by final closure regression)

Budget closure commit `575ff0b`; Finance `cbe12cd`; Procurement `25cc95a`.
`closure-budget-final-clean-01.log`: 289 tests, failures0, errors0, skipped0 reported.
`closure-budget-final-history-upgrade-01.log`: 287 tests, failures0, errors0,
skipped0 reported. All38 selected old business-table fingerprints match. These
suites established the Budget baseline. The final all-domain closure report supersedes these counts.
See Budget parity matrix for canonical authority, concurrency and exact limitations.

Production browser, filestore, full load, source-data conversion, deployment and
monitoring are separate from migration completion. Original databases, volumes,
upstream checkouts and unrelated repositories remain preserved.

## Closure continuation, 2026-10-31

Organization `c519ef5` closes partner association/company reverse guards and role
read-only/restricted-model semantics. Source global-ACL technical exceptions are
explicit model metadata because Odoo20 global access rows are restrictions.
Effective company/OU/date roles cannot self-grant or retain revoked update rights.
Existing null partner identities are not backfilled; new units default to the
existing company contact. Organization = MIGRATED; see its current status matrix.

Finance `0f7c947` closes Expense/Advance WHT using native withholding payments,
untaxed receipt bases, gross Budget actuals, foreign currency, supplier VAT evidence,
company-paid net cash and protected reset/history/OU boundaries. Retention and
purchase/contract invoice plans were subsequently completed below.

Fresh isolated Odoo20.0-20260926 runtime: `cross-clean-10.log`, clean installation,
301 tests, failures0, errors0, skips0 reported. Affected suites previously passed153,
then final withholding cases6. `wht-race-03.log` proves real two-cursor duplicate
posting and over-return serialization, fresh retry rejection and invariant Budget80.
Logs are retained outside Git under `th-gov-erp/test-evidence/closure-20261031/`.
Previous temporary infrastructure and its later test volumes were unavailable;
this execution recovered the preserved `erp-finance-test20` test-only stack on
10.248.43.0/24 without deleting any database or volume. Prior test claims above
remain prior-run evidence, not a claim that their temporary logs still exist.

The subsequent implementation closed Asset refund/reset, Thai lifecycle and
Expense acquisition/source analytics, as recorded below.


Asset closure `4993357` migrates Thai daily salvage/substatus/parent/low-value,
Expense acquisition and fund/analytics, plus audited partial/full credits and reset
with retained acquisition generations. Original purchase values remain immutable;
current value derives from append-only valuation events. Active/depreciated/AUC
history remains protected. Upgrade explicitly preserves old target zero-year
expense-account AUC semantics instead of silently zeroing them.

Intermediate cross-domain clean `cross-clean-21.log`: 311 tests, failures0, errors0,
no skips reported. Historical copied depreciation DB `cross-history-24.log`: 309
tests, failures0, errors0, no skips reported. Budget `637fcea` isolates synthetic
ledger identities from real old accounting IDs; no runtime rule changed and no
test was excluded. Asset-focused suite25 and real stock-return/credit test1 pass.
Two real transaction races pass (competing credits and activation versus credit).
Seven old-table business projections match; three tables change only write metadata.
A separate old AUC transfer copy retains its original values/states. These checks
are not complete source-data conversion or filestore equivalence.

Evidence: `/home/patrixr/GovOpsDev/th-gov-erp/test-evidence/closure-20261031/`.
Procurement, Contract, Finance retention and Inventory were subsequently closed.
No hard blocker, push or production operation occurred.

## Financial closure evidence: guarantees, invoice plans and retention

Contract `feca41c` closes guarantee financial settlement; Procurement `48afdd9`
adds native purchase installments; Finance `5d239aa` closes retention and planned
deposits; Contract `51220d2` closes contract invoice plans/manual quantities/FX.
`plans-financial-regression-47.log` has 159 tests, 0 failures, 0 errors;
`plans-retention-currency-48.log` has 9 targeted tests, 0 failures, 0 errors.
No skips reported. Guarantee and retention/plan two-transaction races passed with
one commit, one serialization failure and idempotent fresh retry. Durable evidence
and preserved isolated databases are recorded in the respective source/test docs.

Native Odoo 20 does not combine WHT and write-offs: retention uses one atomic
WHT-only payment plus the retained cash payment, preserving gross tax base and
Budget actual. Native credit regressions were fixed by excluding internal lock
counters from copy, then all affected financial suites were rerun successfully.

This closed Finance runtime source parity. Legal/recurrence and government
Procurement/Inventory implementation was subsequently completed. Historical
source data conversion, filestore/browser/load and production deployment remain
readiness work, not reasons to defer the runtime closure.

## Contract lifecycle and PR currency closure

Contract `971fa16` migrates signed legal content/stages/versions/review activities;
`1fb705a` adds recurring native bills, immutable period history and successors;
`8f4a7a3` scopes reset checks so ordinary Finance users need no Contract ACL.
Procurement `315dfe1` captures PR FX and preserves requisition/PO currency; Finance
`df5c617` uses company-currency request limits for expense claims.
`contract-55.log`: 38 tests, failures0/errors0. `recurrence-race-01.log`: one
commit/one serialization failure; retry returns one bill and actual10/no duplicate
commitment. `financial-contract-59.log`: 147 tests, failures0/errors0, no skips
reported. Government workflow and Inventory were subsequently completed; no hard blocker.

## Government Procurement and Contract closure

Procurement 7a37899, Finance 92acf06 and Contract 965173c close the configured
government request verification, types/methods/committees, native expense routing,
Done/reset commitments, immutable review rounds, PO tiers and requisition legal gate.
Government financial regression: 179 tests, zero failures/errors. Further targeted
Procurement security regression: five tests, zero failures/errors. The purchase-tier
two-cursor race commits once; the stale transaction fails serialization and retry
preserves one review and one commitment. No push.

Inventory 3668c5e closes selected WA/stock workflows. Exact source decisions are in
projects/inventory/docs/source-mapping.md. The initial complete-code clean suite
passed 370 tests and historical upgrade passed 368, with zero failures/errors.
Inventory 01249f1 covers repeat reviewers and manual acceptance dates;
targeted regression passed 21 tests. Final clean-install-80 passed 373 tests and
historical-upgrade-79 passed 371, zero failures/errors and no skips reported.
The closure report contains exact log names and final Git state. All three final PO/stock/fine races have one commit, one
serialization failure and an idempotent retry. Selected original-column fingerprints
match across 14 historical tables; this is not full source-data/filestore equivalence.
