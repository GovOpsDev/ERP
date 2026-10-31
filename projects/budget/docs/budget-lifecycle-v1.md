# Budget Lifecycle v1 — frozen for the tested Procurement and Finance subset

Frozen 2026-10-29 and extended for the tested Finance subset as an interoperability boundary for the implemented subset, not a claim of full NSTDA/OCA parity, complete Budget migration, or production readiness. Changes to these semantics require contract review and regression tests. Unsupported cases below fail closed or remain unimplemented.

## VERIFIED UPSTREAM

- `budget.period.check_budget_precommit` simulates moves, checks, and removes them: it is not a persistent reservation. `budget_control_purchase_request` commits PR lines in approved/done, and recomputes after rejection/draft. NSTDA/OCA tier integration checks before applicable tier validation and on final approval.
- `budget_control_purchase_request/tests/test_budget_purchase_request.py` confirms that a PO linked to a PR line reverses the entire PR-line commitment even when the PO quantity is partial. Its PO commitment follows its own amount. PO cancellation restores the PR commitment.
- Source call-chain inference for multiple POs: each confirmed PO creates its own commitment; the PR line is fully reversed once while any confirmed PO remains, and is restored after the last confirmed PO is cancelled if the PR remains eligible.
- Legacy control checks an analytic/KPI level independently from a fund/analytic-dimension allocation level. KPI template lines map general-ledger accounts to KPIs.

## VERIFIED BY ODOO 20 TEST

- A real PR submits after a check-only simulation with no persistent precommit. Final tier approval creates per-line PR commitments; a later insufficient-budget approval rolls back reviews, state and moves. Rejection reverses approved PR commitments.
- Real native POs replace PR commitment with their own amounts. Cancellation restores PR when no other confirmed linked PO remains. Tests cover 30 → 50, PR 100 → PO 40 and PO 60, cancellation in sequence, and cancellation/draft amendment/reconfirmation.
- Real PO tests cover different fund, analytic account, analytic dimension, and general-ledger account/KPI from the PR. A PO using an underfunded alternate key is rejected without changing the PR commitment. A multiple-PO test covers distinct funds.
- Two concurrent real PR approvals of 80 against a 100 allocation: one committed, the other received PostgreSQL serialization failure; each control's effective total remained 80 and the rejected transaction's PR remained to_approve. Application/worker retry must not swallow such failures.

## REDESIGNED FOR ODOO 20

`erp.budget.control.service` resolves company, period, active OU, primary analytic account, fund, account-to-KPI mapping and exact additional analytic-account dimensions. It applies both analytic/KPI and fund/dimension controls. Each control's available amount is its allocation less signed ledger entries. Commitments and reversals are immutable ledger events; reconciliation compares the current document-derived target with existing events. A PR line and all current/historical PO keys are locked in deterministic order, and a row version is updated to prevent stale repeatable-read snapshots authorizing overspend. Source authorization and document states are enforced by the Procurement adapter; the internal service is not a public RPC API.

Procurement's initial ordered per-user threshold reviewer implementation is a narrow adaptation, not full OCA tier-validation parity. It checks budget before each review and on final approval. PO lines currently link to at most one PR line, while one PR line may link multiple POs.

## VERIFIED FINANCE SUBSET

Finance reconciles PO commitment and signed invoice-line actuals atomically through the Budget service. The service treats PR/PO and actual move types as distinct ownership sets, and PR/PO-only reconciliation preserves actuals. An actual carries accounting document, accounting line and PO line identities; reversals retain them. Actual uses the invoice subtotal; commitment reduction uses posted invoice quantity converted to PO UoM at PO price. Draft lines are excluded. With supported refunds linked to a posted bill, actual is negative and PO commitment is restored only when it was positive at the refund replay point. See `projects/finance/docs/finance-budget-lifecycle-v1.md` for the narrow tested rules and source limitations.

## DEFERRED TO FINANCE

Taxed and foreign-currency controlled documents, split analytics, discounts on POs, deposit and forward commitments, broader refund patterns and migration of pre-existing posted controlled bills remain unsupported or untested.

## NOT TESTED OR UNSUPPORTED

Foreign-currency and taxed linked PO lines, multiple analytic-distribution combinations/percentages, cancellation after control closure or period expiry, multi-PR-to-one-PO-line, full tier formulas/roles/delegation/comments, requisitions, production data migration, concurrency load, and browser workflow. The first three are rejected rather than silently miscomputed. A matching filestore was not supplied with the copied upgrade DB, so attachment preservation is not established. Budget, Procurement and Finance remain PARTIAL.

## VERIFIED CONTRACT SUBSET

`erp_contract` supports a distinct purchase Contract source family and signed `contract_commitment`/`contract_reversal` ledger events. Invoice actuals and remaining commitment reconcile atomically under the same Budget locks. Contract and PR/PO families are independent; a single invoice line cannot use both a purchase and contract source. Agreement references to POs do not create a second Budget commitment. Independent documents representing the same economic obligation still require business reconciliation. See `projects/contract/docs/contract-lifecycle-v1.md` for scope and limitations.

## Shared plan — PARTIAL extension

VERIFIED UPSTREAM: one control per analytic/period, KPI lines inside that control, and an OU derived from the analytic; allocation can populate the plan, and source plan revisions preserve versions. Source control transfer has its own submit/transfer/reverse workflow.

REDESIGNED / VERIFIED TESTED SUBSET: optional period plan, company/period/analytic parent cap shared across OU and KPI; both parent and existing analytic/fund controls must pass. A plan starts draft and may be cancelled/reset before confirmation. Confirmed/done plans stay enforced. Manager adjustments create immutable increase/decrease/atomic transfer events; decreases cannot fall below ledger consumption or allocated child budgets. The signed analytic ledger is authoritative for capacity. Company-currency precision is enforced. `limits` and stricter `allocated` modes are described in `budget-control-design.md`.

GUARDED / UNSUPPORTED: confirmed plan cancellation, adding new analytic plan lines after confirmation, cross-company/period transfer, source plan/control revision parity, source tier validation, tiered transfer-document lifecycle, exact source KPI/date-range allocation equality, source fund/analytic allocation-document release, source carry-forward and production backfill are not implemented; the later revision/release extension describes the narrower implemented substitutes. Unconfigured periods preserve legacy behavior and are not automatically capped. This extension does not establish full upstream Budget parity.

## Revision/release extension — PARTIAL

VERIFIED UPSTREAM: source revisions copy full plan versions and control revisions; source fund/analytic allocation is separate from KPI planning. OCA control transfer has submit/transfer/reverse, with tier-validation extension.

REDESIGNED / VERIFIED SUBSET: explicit numbered plan snapshots, stale-version protection, immutable baseline/event provenance, one effective version, and consumption-safe activation; formal KPI release with ordered distinct reviewer approvals, OU/company checks and atomic child opening; guarded release and transfer reversal with retained history. The source allocation document, control-version creation, and tiered version/transfer document lifecycle are not yet migrated. Existing periods remain compatibility mode until explicit configuration. No reviewer history is backfilled.

## Snapshot boundary — PARTIAL extension

REDESIGNED: newly activated snapshots record a period event boundary; the effective cap starts at the snapshot amount and includes only later events. For effective snapshots created before the boundary existed, the resolver remains initial amount plus all events until a new revision is explicitly activated. This is compatibility, not a claim of source revision/control parity. Prior snapshot and ledger records remain untouched; no historic reviewers are invented.

## Initial fund allocation — PARTIAL extension

A fresh-period allocation document can create a protected draft plan and matching draft fund controls. Done does not itself open controls; confirmation and opening follow separately. The fund control amounts are backed by immutable allocation lines, while KPI control release remains a separate target stage. Existing periods, source dimensions, allocation revision and completed-document reversal are not supported by this subset. Full source lifecycle is not frozen.

## Allocation revision — PARTIAL extension

Target allocation revisions preserve the original fund/analytic allocation and copy existing line amounts into drafts linked to plan snapshots. A manager activates the revision after fund/parent consumption checks; plan and operational fund limits change atomically, and the ledger retains its historical controls. Target keeps prior capacity effective during draft revision preparation; source `base.revision` archives the prior record during copy. This is a deliberate safety adaptation and not complete source control-version, tier, dimension-change or cancellation parity.

## Source-backed formal KPI reconciliation — PARTIAL

In formal periods backed by initial fund allocation, target KPI release requires the sum of analytic controls to equal the current shared plan cap at submission and final release. A later allocation revision cannot change this total while released KPI controls remain at a different nonzero total. Existing allocation dimensions may be reduced to zero if all consumption and parent checks pass, leaving an auditable inactive economic capacity rather than deleting its ledger identity. Source KPI/date-range matrix, initial-balance checking, coordinated KPI revision, new dimensions and full control versions remain outstanding.

Allocation revision now supports adding fund/analytic/additional dimensions and explicit exclusion with zero net consumption. Pending dimensions have no control or capacity until atomic activation; new analytics enter the linked plan snapshot with base zero, without modifying predecessor snapshots. Excluded identities and all ledger history remain. This is a tested dimension-revision adaptation, not completion of source control/KPI versions or tier/carry-forward workflows.

Opening Reconciliation records source initial available plus initial commitment as a planning minimum, with company/OU access and stable origin reference. Confirmation, revision activation, decreases, transfer reversal and formal KPI release enforce that minimum. It never changes parent capacity or creates ledger consumption. Real carried commitments require their separate provenance-preserving ledger workflow.

The effective planning/control version is a KPI release with immutable amount/date snapshots, predecessor/root/version identity and a plan-version link. Prepare Planning Revision can select a draft allocation revision. Ordered reviewers approve the proposed planning; allocation-linked planning then waits in Approved state until the allocation action atomically activates the plan, fund and KPI amounts. The preceding control version remains effective throughout review. Current control rows are the operational projection of these approved versions and retain immutable ledger identity. New plan confirmation records a baseline at the real confirmation time; pre-existing target history is retained as compatibility state until an explicit successor is reviewed. Planning dates do not filter transaction-date availability. Source tier adapters cover control and transfer, not an additional plan/allocation engine.

Completed allocation Cancel prepares an explicit zero-capacity revision after zero net consumption is verified for every control. Formal child planning requires ordered review before activation closes previously open controls and marks the allocation cancelled. Reset/Restore creates a new successor and keeps the cancellation effective until activation; restoration uses the last effective dimensions, preserving earlier exclusions and every old snapshot/ledger ID. Direct plan edits/increases and new control opening remain blocked for cancelled allocation-backed plans. Scope controls are locked in sorted order before the period lock, preventing an inverse analytic/fund lock order in coordinated revisions.

Activity-configured templates select the KPI by activity rather than account alone. Activity binds the budget account; posted source documents retain that key even when the native invoice GL account differs. Activity is optional for legacy account-only templates. Source adapters pass it to Budget APIs; activity itself never grants additional capacity. Effective activity mappings and used accounts are protected, source document fields become immutable with commitment/posting, and ordered activity locking precedes control/period locking in multiline workflows.
