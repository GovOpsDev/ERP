# Budget source parity matrix

Budget status: **MIGRATED**. Production readiness: **NO**.

This decision covers the required Budget lifecycle and its financially material
PR/PO, Contract, native accounting, Expense, Advance and Purchase Deposit adapters.
It does not declare the other six domain audits complete or certify production data.
Their business workflows use the same Budget authority and are audited separately.

Exact references inspected: Ecosoft `budgeting` 08842c565308, OCA
`account-budgeting` b447bab1678f, `server-ux` 2b10d770, `purchase-workflow`
7eed5d2dd34d, NSTDA `ERP-Government` 5a1722c4c6f6 and its egov_install/repos.yaml.
Additional exact pinned references retrieved separately: OCA hr-expense
c15f5f4a31763882a62b411fb6a4ff47bbda683c and l10n-thailand government Expense
f793617ebabe618969c119dd68017bb120c3453f. Existing upstream trees were preserved.
This is source-code migration parity with explicit redesigns, not a claim to have
reproduced a production merged deployment or imported its data.

| Upstream feature | Exact source scope | Target conclusion | Evidence | Status |
|---|---|---|---|---|
| Period, funds/groups, supplemental funds, analytic and account/dimension keys | budget_control, budget_allocation | Company/OU scoped master data; one analytic and one fund control resolved by the central API | master/control/template tests | REDESIGNED |
| Activity selects KPI independently of the GL account | budget_activity and document adapters | Activity/account bindings and immutable per-template mappings; native GL account can differ from the budget activity account | common_activity and real PO/Contract/Expense tests | REDESIGNED |
| Analytic total versus KPI control | budget_control period control_level and budget_activity period query | Explicit modes; legacy periods retain their original resolver | granularity, mapping and shared-parent tests | REDESIGNED |
| Allocation draft/done/cancel/reset | budget_allocation | Versioned allocation grants capacity only through canonical plan/control activation; consumed dimensions cannot disappear | allocation and cancellation suites | REDESIGNED |
| Add/remove/replace fund/analytic/tag dimensions | budget_allocation_revision | Additions and explicit exclusions; replacement is add plus exclude, preserving stable historical identities | dimension revision tests and real commitments | REDESIGNED |
| Plan/allocation/control revision chain | budget_plan_revision, budget_control_revision, base_revision | One anchored effective plan→allocation→reviewed planning graph; predecessor remains effective until joint activation | revision and legacy-adoption suites | REDESIGNED |
| Opening balance | budget_control initial_available + initial_commit | Minimum planning floor, never an extra spending bucket | floor/no-double-capacity and carry tests | REDESIGNED |
| Planning amount, KPI, dates and released amount | budget_control planning lines | Versioned date/KPI slices; canonical released total reconciles to the shared plan; no independent release authority | planning reconciliation tests | REDESIGNED |
| Transaction-date KPI subperiod filtering | base budget monitor/_check_budget_available and discovered activity/advance/deposit/OU overrides | Source does not select capacity by transaction date; planning dates retain reporting semantics | exact-source query review | NOT REQUIRED |
| Ordered planning/control and transfer approval | budget_control_tier_validation, base_tier_validation | Existing Budget review engine; ordered reviewers, immutable rounds, rejection/resubmission, final economic activation | wrong order/OU/company, duplicate and real transfer tests | REDESIGNED |
| Independent generic approval engine for every plan/allocation object | same tier adapter | No such source requirement; canonical planning reviews authorize the linked allocation successor | source model/tier inspection | NOT REQUIRED |
| Transfer document and reversal | budget_control transfer, budget_allocation | Reviewed canonical successors; inverse reviewed document; unchanged analytics also receive coherent successors | PO60 + transfer30 + consumption/reversal, real races | REDESIGNED |
| Allocation/control cancellation and restoration | budget_allocation, budget_control revisions | Reviewed zero-capacity successor and restoration; nonzero consumption rejects; excluded old rows stay excluded | cancellation/restore and concurrent commitment tests | REDESIGNED |
| Balance carry-forward | budget_control forward balance | Stable-origin review, forward/accumulate destinations, opening floor and prior-period seal; commitment excluded | real fiscal suites and return races | REDESIGNED |
| Commitment carry-forward | budget_control and PR/PO/Contract/Expense/Advance overrides | Typed immutable credit/debit pairs; central fiscal routing, stable origin, idempotency and PR fallback | multiyear PO/Contract/Expense/Advance and deposit tests | REDESIGNED |
| Applied forward cancellation | source latest-forward restriction and recomputation | Approved economic return withdraws destination capacity/opening and restores source safely; later forward or unsafe actual state rejects | commit/balance return tests and real races | REDESIGNED |
| Existing unanchored target state | target upgrade compatibility | Explicit labelled baseline, no invented dates/approvals; old partial releases and ledger survive until reviewed successor | real legacy conversion and historical fingerprints | REDESIGNED |
| Manager consume/release adjustment | budget_control/models/budget_move_adjustment.py | Manager document, immutable actual/inverse events, safe release cancellation | adjustment and cross-domain suites | REDESIGNED |
| Currency, manual rate, all/selected/no-tax budget policy | budget_control base amounts, budget_control_purchase_manual_currency | Captured commitment policy/rate; actuals use native signed company balances and rounded tax details | native FX/VAT/discount/refund tests | REDESIGNED |
| PR→PO→Bill and Contract→Bill | budget_control_purchase_request, purchase, contract; allocation/activity adapters | Stable source families, atomic mixed-source posting/reset, native fiscal analytic propagation | real partial bills/refunds, lifecycle and concurrency | REDESIGNED |
| Native direct accounting actual and explicit exemptions | budget_control account/account_move_line | Direct complete keys through the same actual ledger; no artificial commitment; privileged journal/document exemptions | direct bill/journal/refund/reset and real races | REDESIGNED |
| Expense approval, actual, review and reset | budget_control_expense, allocation/activity Expense, native hr.expense | Odoo20 individual native expenses replace removed sheets; ordered review and retained accounting history | Finance source-expense-migration.md | REDESIGNED |
| Employee advance, clearing, bank return and Advance KPI | budget_control_advance_clearing, budget_activity_advance_clearing, pinned hr_expense_advance_clearing | FIFO multi-advance settlement, pending clearing reservations, safe bank return; zero-capacity tracking KPI uses shared plan/fund | Finance source-advance-clearing.md | REDESIGNED |
| Purchase deposits and negative deductions | purchase_deposit, budget_allocation_purchase_deposit, budget_activity_purchase_deposit | Native down payments explicitly mapped to approved PO origin; its KPI retains responsibility instead of temporary deposit-KPI bypass | Finance source-purchase-deposit.md; fiscal and real concurrent deductions | REDESIGNED |
| Approved PR used for Expense/Advance | l10n_th_gov_hr_expense_budget_control and pinned l10n_th_gov_hr_expense | Atomic PR-line handoff, requester/OU/company checks, HR-authorized variance, duplicate claim protection, safe restoration | Finance source-request-expense.md; real duplicate-claim race | REDESIGNED |
| Requisition, invoice-plan and agreement Budget metadata | budget_control_purchase_requisition, allocation/activity requisition/contract_invoice_plan, l10n_th_gov_purchase_agreement_budget_control | Source requisition mixin carries keys without a separate commitment; schedules reuse actual PO/Contract sources; agreement marker is reporting classification | exact model overrides; central document APIs | REDESIGNED |
| Generated retention, WHT, late-fine, stock valuation and depreciation exclusions | account_invoice_payment_retention_budget_control, l10n_th_account_tax_expense_budget_allocation, budget_control_purchase_work_acceptance_late_fines, stock_budget_allocation, budget_control_account_asset_management | Generated entries have no automatic second Budget actual; complete explicit keys/privileged exemption govern direct entries. Fund/analytic provenance and each business workflow remain owned by Finance/Inventory/Asset | exact exemption overrides and direct-actual tests | REDESIGNED |
| Guarantee/payment/stock/asset fund and activity propagation | l10n_th_gov_purchase_guarantee_budget_allocation, account_payment_multi_deduction_budget_allocation, stock_request_budget_allocation, purchase_stock_budget_allocation, account_asset_fund/transfer_budget_allocation | These adapters carry provenance, not spending authority. Domain adapters use Budget keys; their document metadata is included in the mandatory domain audits | source model and hook inspection | REDESIGNED |
| Arbitrary independent percentage split capacity | source primary analytic plus tag dimensions | No separate source capacity engine for arbitrary native percentage distributions; explicit source lines retain their dimensions | budget docline and query inspection | NOT REQUIRED |
| Central Budget all-OU access | budget_control/allocation_operating_unit_access_all | Explicit cross-organization Budget group inside allowed companies, no Procurement/Finance/Contract access grant | role revoke/company and hidden-source tests | REDESIGNED |
| Executable extra asset-KPI server constraint | egov_config/data/budget_constraint_data.xml | Source record is inactive; activating a bespoke policy is configuration, not required authority | exact source active flag | NOT REQUIRED |
| Constraint exception module outside egov_install scope | budget_control_exception | No evidence it is part of the requested pinned deployment scope; no speculative bypass added | installation manifest | NOT REQUIRED |
| Source-format XLSX exchange and historical import mapping | egov_budget_allocation/control_excel_import_export | Real source dataset conversion/reconciliation belongs to production rehearsal; no claim native CSV import equals its format | separate conversion backlog | PRODUCTION READINESS |
| Department aggregation, activity keyword search, cosmetic monitor/report layout | budget_res_project_department, budget_allocation_department, activity/report helpers | No independent economic authority; reporting/search convenience remains optional | model/query review | ENHANCEMENT |
| Browser completeness, filestore, load, production deployment | operational acceptance | Not included in migration-complete code gate | separate readiness backlog | PRODUCTION READINESS |

## Canonical authority

Fiscal period → effective anchored plan revision → effective allocation revision →
reviewed planning/control state → approved successor transfer/return → shared plan
cap and released child capacity → immutable consumption → available budget.

Control IDs and ledger history remain stable. Forward/opening metadata is not
additional capacity. Document domains call Budget resolution/reconciliation APIs;
they do not reconstruct this graph. Simulations roll back candidate entries and
explicitly check final shared totals before returning. Economic transitions use
savepoints and ordered control/period locks. A failed native posting, reset or
approval does not leave partial accounting or consumption.

## Runtime closure gate

| Suite | Tests | Failures | Errors | Skipped |
|---|---:|---:|---:|---|
| `closure-budget-final-clean-01.log` — clean install, all domains | 289 | 0 | 0 | 0 reported |
| `closure-budget-final-history-upgrade-01.log` — explicitly upgrade all 11 addons | 287 | 0 | 0 | 0 reported |
| `closure-request-expense-cross-01.log` — Budget/Procurement/Finance/Contract | 183 | 0 | 0 | 0 reported |

Both final full suites include all final code, snapshot and default-context guards.
`closure-budget-final-history-{before,after}.txt` match exactly across all 38
selected historical tables. Runtime Odoo20.0-20261015 loaded 79 modules including
native hr_expense. The benign absent `/mnt/extra-addons` path warning is not a test skip.

Additional real two-cursor evidence includes allocation cancellation/restoration,
activity edits versus PR approval, transfer versus PR, balance/commitment forward
and return versus PR, direct actual versus actual/PR, Expense versus Expense/PR,
Advance return versus return/clearing, deposit deduction versus deduction and two
Expense claims against the same PR. Each asserts final ledger/document state and
fresh-retry behavior, not merely a thread exception.

Historical comparison uses all pre-existing columns in 38 selected business tables
of the preserved fiscal-return fixture. New columns are outside the comparison.
Only synthetic reviewer logins are namespaced in the copied test database to avoid
test fixture collisions; original reviewer IDs/history and source DB remain intact.
This is selected business-history preservation, not whole-database or filestore
equivalence. Original DBs and named volumes are retained.

## Further evidence

See `source-amount-policy.md`, `source-budget-adjustment.md`, Budget tests and the
Finance source Expense/Advance/Deposit/Request documents. Older test-report entries
are historical milestones; this matrix supersedes their prior incomplete parity
statements. Production source data conversion, browser, filestore, load and deployment
remain separate. The mandatory fresh six-domain audit follows this Budget decision.

### Historical-database test identity correction (2026-10-31)

Synthetic ledger tests now use `test.actual:1` instead of `account.move.line:1`.
The latter accidentally resolved a real foreign-company accounting row in a preserved
Asset database and invoked its tax snapshot. Test arithmetic and assertions are
unchanged; real PR/PO/Contract/Expense tests still exercise actual source records.
This changes no runtime authority, historical data or fiscal accounting policy.
The corrected tests pass in `budget-fixture-23.log` (2 targeted tests) and the
complete preserved-history regression `cross-history-24.log` (309 tests, failures
0, errors 0, no skips reported). No runtime business rule was changed.
