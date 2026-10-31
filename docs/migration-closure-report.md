# Migration closure report — 2026-10-31

## Overall

**MIGRATION COMPLETE**

**PRODUCTION READY = NO**

All seven required source migrations and the supported cross-domain runtime gate
are complete. No remaining REQUIRED MIGRATION item or hard blocker is known in
the audited selected-source scope. This is source-code migration acceptance, not
production data conversion, whole-database equivalence or deployment approval.

| Domain | Status | Remaining REQUIRED MIGRATION |
|---|---|---|
| Organization | MIGRATED | None |
| Budget | MIGRATED | None |
| Procurement | MIGRATED | None |
| Finance | MIGRATED | None |
| Contract | MIGRATED | None |
| Inventory | MIGRATED | None |
| Asset | MIGRATED | None |

## Budget closure

The canonical path is fiscal period → effective plan revision → effective
allocation revision → reviewed planning/control → approved transfers/returns →
shared parent cap → released child capacity → immutable ledger → available budget.
Procurement, Finance and Contract call Budget APIs instead of resolving capacity
independently.

Allocation successors add, exclude or replace dimensions without deleting economic
history; consumed dimensions cannot disappear. Plan, allocation and control changes
activate together after final required approval. Planning/KPI release reconciles to
one capacity authority. `initial_available + initial_commit` is a minimum planning
floor, never an additional spending bucket. Transaction-date KPI capacity filtering
is **NOT REQUIRED** by the inspected source; planning dates retain reporting meaning.

Ordered tiers, immutable review rounds, rejection/resubmission, transfer documents
and reviewed inverse transfers preserve final-approval semantics. Real PO60 against
capacity100, transfer30 and destination consumption exercise unsafe reversal
rejection. Balance and commitment carry-forward/return use stable origins, central
fiscal routing and idempotent locked transitions. Legacy target records retain their
history and adopt explicit canonical successors without invented source approvals.

Final parity: **MIGRATED**. The detailed
[Budget parity matrix](../projects/budget/docs/budget-parity-matrix.md) has decisive
classifications; source-data/XLSX conversion is readiness and cosmetic reporting is
enhancement. No core row remains unresolved.

## Fresh six-domain audit

The fresh [completeness audit](migration-completeness-audit.md) records source
models and decisions. Canonical upstream trees were read-only and preserved.
NSTDA ERP-Government reference is `5a1722c4c6f6`; selected configuration and exact
OCA/Ecosoft revisions are recorded in the domain source mappings.

- Organization: operating-unit `c0a597931509`, HR `3c5f7c01727b` and role restriction
  `995ad9e9ef32` establish hierarchy/partner, assigned/default OU, dated multiple
  employee memberships, HR/public/version/HTTP boundaries and effective role/update
  controls. Company/OU security redesigns and preserved direct group grants are tested.
- Procurement: purchase-workflow `7eed5d2dd34d` and Thai source `5ebe30a8be97`
  establish government type/method/committee configuration, verification, approved/
  done/reset actors and commitment, requisition/expense routing, captured FX and
  ordered native PO approval. Repeated reviewers can decide a later assigned tier.
- Finance: inspected Budget adapters and Thai Expense tax source require native
  Expense/advance WHT clearing, not merely tax installation. FX/VAT/WHT, analytic
  provenance, refund, advances, deposits, retention, plans and fiscal routing are
  migrated; native accounting is reused where it supplies source semantics.
- Contract: agreement `8e18e0da1e27`, contract `944dcbeaa513` and Thai guarantees
  supply legal stages/content/signed versions/reviews, amendments/renewals/termination,
  recurring bills, installments and financial guarantee settlement. Government
  requisitions activate the agreement gate; agreements add no duplicate PO commitment.
- Inventory: selected WA/Thai/Budget sources plus stock-warehouse
  `3a15b9daa121`, Thai stock request `b7cd787e4aee` and stock-workflow
  `c0cf073b531a` establish configurable receipt enforcement, partial goods/services,
  committees/evaluation/tiers, manual accepted date, fine accounting, installment
  acceptance, stock requests/returns/RFQs, Kanban census, provenance and negative-stock
  policy. Native Odoo20 move scrap replaces the removed stock.scrap API. Fine and
  valuation entries do not create duplicate Budget actuals.
- Asset: OCA acquisition/depreciation/removal/AUC and selected Thai extensions are
  migrated, including daily salvage, substates, low-value items, Expense/WA handoff
  and audited refund/reset value generations. Administrative custodian/location
  transfer has no proven required source workflow and is **NOT REQUIRED**.

## Cross-domain regression

Runtime tests use real Odoo documents and transactions, including:

- Approved PR → native requisition → PO → goods/services partial WA → receipt/bill →
  Asset acquisition/depreciation; stock returns and credits retain source lineage.
- Contract commitment → native partial bill/refund, recurring bills and installment
  plans; legal versions and guarantee receive/return use native financial settlement.
- PR → native Expense, advance/clearing, foreign currency, VAT/WHT, deposit deduction,
  retention and fiscal carry-forward; no duplicate capacity or commitment.
- Planned acceptance with deposit30 and subsequent35/35 bills resolves to actual100;
  fine invoice/vendor credit/reversal and stock valuation remain Budget-exempt.
- Stock request → ordered review → native stock procurement/RFQ/transfer/return,
  with OU/company visibility and fund/analytic provenance through native records.
- Unauthorized/wrong-company/wrong-OU/revoked-role operations, wrong reviewer order,
  reset/cancellation guards and immutable historical records across domain adapters.

## Definitive final tests

Runtime: image `odoo:20.0`, Odoo **20.0-20260926**, image ID
`sha256:dc76c42d292af9c513de826620e5a5dbe8152383ce8767eb6ed1390a806eb32f`.
Final suites select all eleven custom addons, including the four Organization/role
addons and shared Core. Counts below are Odoo's final `odoo.tests.result` totals;
module statistics include class setup accounting and are not summed separately.

| Final suite | Database | Tests | Failures | Errors | Skipped |
|---|---|---:|---:|---:|---|
| `final-clean-80.log` | closure_20261031_final_clean_04 | 373 | 0 | 0 | 0 reported |
| `final-history-79.log` | closure_20261031_final_history_01 | 371 | 0 | 0 | 0 reported |
| `final-review-date-78.log` | closure_20261031_wht_01 | 21 | 0 | 0 | 0 reported |

Both complete suite processes exited **0**. No final test was excluded to conceal
a failure. Earlier failed development runs remain in evidence; corrections were
rerun in these final suites. Synthetic mail-address warnings do not establish
production notification delivery.

Three final two-transaction races pass on the final implementation:
`final-purchase-tier-race.log`, `final-stock-request-race.log` and
`final-fine-race.log`. Each proves one commit, one serialization conflict and a
fresh idempotent retry with one resulting review/fulfillment/charge. Earlier real
Budget, WHT, credit, guarantee, retention and recurrence races are retained in the
domain evidence and are not substitutes for these final full suites.

All original columns in **14 selected historical tables** have identical SHA-256
fingerprints before and after the final upgrade. Historical WA accepted dates are
unchanged; newly introduced representative/manual-date fields remain null for old
records. This is selected-history preservation, not whole-database, source-data or
filestore equivalence. Original source databases were not modified or dropped.

Evidence directory (outside Git):
`/home/patrixr/GovOpsDev/th-gov-erp/test-evidence/closure-20261031/`.
Machine-readable summary: `final-validation-summary.json`; fingerprints:
`final-history-{columns,before,final}.json`; retained DB inventory:
`preserved-databases.txt`. The final report and domain tests are committed; logs and
temporary test infrastructure remain local evidence.

## Production-readiness backlog

**NO**: browser acceptance with real roles/company switching, matching DB/filestore
restore and attachment verification, real source-data conversion/reconciliation,
representative performance/load, production accounting/warehouse/tier/scheduler
configuration, deployment/rollback and monitoring remain untested operational gates.
See [production-readiness.md](production-readiness.md). These are separate from the
completed source-code migration; no production service/data was deployed or changed.

## Git

All repositories are independent. All branches are `master`; no pushes occurred.
Source implementation commits were followed only by documentation reconciliation.
The root row refers to the commit containing this report to avoid a self-referential
commit hash; obtain its SHA with `git log -1` in the workspace root.

| Repository | Branch | Latest commit | Message | Working tree at closure | Pushed |
|---|---|---|---|---|---|
| Workspace | master | This report's commit | docs: close seven-domain Odoo 20 source migration | Clean after commit | NO |
| Organization | master | 2de3b25 | docs: reconcile Organization entry points with migrated source parity | Clean | NO |
| Budget | master | ba8a936 | docs: reconcile Budget entry points with completed source parity | Clean | NO |
| Procurement | master | 92113d3 | docs: describe completed government procurement migration | Clean | NO |
| Finance | master | 92acf06 | feat: route government requests to native expenses and preserve Done commitments | Clean | NO |
| Contract | master | fc4ec63 | docs: record completed requisition agreement integration | Clean | NO |
| Inventory | master | 01249f1 | fix: preserve manual acceptance dates and repeated reviewer decisions | Clean | NO |
| Asset | master | 4993357 | feat: close Thai asset lifecycle and audited acquisition reversals | Clean | NO |
| Shared Core | master | c9e8253 | feat: initialize shared ERP core for Odoo 20 | Clean | NO |

Relevant implementation heads underneath documentation commits include Budget
`637fcea`, Organization `c519ef5`, Procurement `4dfcb69`, Finance `92acf06`,
Contract `965173c`, Inventory `01249f1` and Asset `4993357`.

## Docker

Reused the preserved test database container `erp-finance-test20-db-1` and external
volumes `erp-finance-test20_finance_test_db` and
`erp-finance-test20_finance_test_odoo`. Temporary Odoo containers were created with
`docker compose run --rm` under project `erp-closure20`, canonical read-only addon
mounts and explicit `10.248.43.0/24` network `erp-finance-test20_default`.

All temporary Odoo containers exited and were removed. The closure-started database
container was stopped after successful tests and history checks. Both named volumes,
the network, original databases and all isolated closure databases are preserved;
no `down -v` or database deletion occurred. The unrelated
`govopsdev-leaves-test-titlc-security-worker-1` remains running and untouched.
