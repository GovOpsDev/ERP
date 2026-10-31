# Budget upstream analysis — in progress

NSTDA ERP-Government `5a1722c4c6f6cfdf3ed59362a56e85777c58a383`; OCA account-budgeting `b447bab1678f8bea86bb0a6fd92eaa23b5f0390c`; Ecosoft budgeting `08842c565308de3b7259a34b391164c6ce4d0605`. NSTDA repos.yaml references the account-budgeting baseline `a7bd266c8e7025296d7860a598bc2b7f80aff436` and patch `b447bab1678f8bea86bb0a6fd92eaa23b5f0390c`; the baseline is an ancestor of that patch. Budgeting has one pinned commit. Other dependency repositories use additional merges; the full effective combined dependency tree is not yet reconstructed. The table below inventories manifests, not a completed behavioral audit.

## Manifest inventory

| Repository | Module | Declared dependencies |
|---|---|---|
| account-budgeting | `budget_control` | `account`, `l10n_generic_coa`, `date_range`, `web_widget_x2many_2d_matrix` |
| account-budgeting | `budget_control_advance_clearing` | `budget_control_expense`, `hr_expense_advance_clearing` |
| account-budgeting | `budget_control_expense` | `budget_control`, `hr_expense` |
| account-budgeting | `budget_control_purchase` | `budget_control`, `purchase` |
| account-budgeting | `budget_control_purchase_request` | `budget_control_purchase`, `purchase_request` |
| account-budgeting | `budget_plan` | `budget_control` |
| budgeting | `account_asset_fund` | `budget_control_account_asset_management`, `budget_allocation` |
| budgeting | `account_asset_transfer_budget_allocation` | `account_asset_transfer`, `account_asset_fund` |
| budgeting | `account_invoice_payment_retention_budget_control` | `account_invoice_payment_retention`, `budget_control` |
| budgeting | `account_payment_multi_deduction_activity` | `account_payment_multi_deduction`, `budget_activity` |
| budgeting | `account_payment_multi_deduction_budget_allocation` | `account_payment_multi_deduction`, `budget_allocation` |
| budgeting | `base_tier_validation_check_budget` | `base_tier_validation`, `budget_control` |
| budgeting | `budget_activity` | `budget_control` |
| budgeting | `budget_activity_advance_clearing` | `budget_activity_expense`, `budget_control_advance_clearing` |
| budgeting | `budget_activity_contract` | `budget_activity`, `budget_control_contract` |
| budgeting | `budget_activity_contract_invoice_plan` | `budget_activity_contract`, `contract_invoice_plan` |
| budgeting | `budget_activity_expense` | `budget_activity`, `budget_control_expense` |
| budgeting | `budget_activity_purchase` | `budget_activity`, `budget_control_purchase` |
| budgeting | `budget_activity_purchase_deposit` | `purchase_deposit`, `budget_activity_purchase` |
| budgeting | `budget_activity_purchase_request` | `budget_activity_purchase`, `budget_control_purchase_request` |
| budgeting | `budget_activity_purchase_requisition` | `budget_activity_purchase_request`, `budget_control_purchase_requisition` |
| budgeting | `budget_allocation` | `budget_plan`, `analytic_tag_dimension_enhanced` |
| budgeting | `budget_allocation_advance_clearing` | `budget_allocation`, `budget_control_advance_clearing` |
| budgeting | `budget_allocation_contract` | `budget_allocation`, `budget_control_contract` |
| budgeting | `budget_allocation_contract_invoice_plan` | `budget_allocation_contract`, `contract_invoice_plan` |
| budgeting | `budget_allocation_department` | `budget_allocation`, `budget_res_project_department` |
| budgeting | `budget_allocation_expense` | `budget_allocation`, `budget_control_expense` |
| budgeting | `budget_allocation_operating_unit` | `budget_allocation`, `budget_control_operating_unit` |
| budgeting | `budget_allocation_operating_unit_access_all` | `budget_allocation_operating_unit`, `budget_control_operating_unit_access_all` |
| budgeting | `budget_allocation_purchase` | `budget_allocation`, `budget_control_purchase` |
| budgeting | `budget_allocation_purchase_deposit` | `purchase_deposit_analytic`, `budget_allocation_purchase` |
| budgeting | `budget_allocation_purchase_request` | `budget_allocation`, `budget_control_purchase_request` |
| budgeting | `budget_allocation_purchase_requisition` | `budget_allocation_purchase_request`, `budget_control_purchase_requisition` |
| budgeting | `budget_allocation_revision` | `budget_allocation`, `budget_plan_revision` |
| budgeting | `budget_control_account_asset_management` | `budget_control`, `account_asset_management` |
| budgeting | `budget_control_contract` | `budget_control`, `contract` |
| budgeting | `budget_control_exception` | `budget_control`, `base_exception` |
| budgeting | `budget_control_operating_unit` | `budget_control`, `analytic_operating_unit` |
| budgeting | `budget_control_operating_unit_access_all` | `budget_control_operating_unit` |
| budgeting | `budget_control_purchase_manual_currency` | `budget_control_purchase`, `purchase_manual_currency` |
| budgeting | `budget_control_purchase_requisition` | `budget_control_purchase_request`, `purchase_request_to_requisition` |
| budgeting | `budget_control_purchase_work_acceptance_late_fines` | `budget_control`, `purchase_work_acceptance_late_fines` |
| budgeting | `budget_control_revision` | `base_revision`, `budget_control` |
| budgeting | `budget_control_revision_lock_amount` | `budget_control_revision` |
| budgeting | `budget_control_tier_validation` | `budget_control`, `base_tier_validation` |
| budgeting | `budget_plan_revision` | `budget_control_revision`, `budget_plan` |
| budgeting | `budget_res_project_department` | `budget_control`, `res_project`, `analytic_base_department`, `hr_department_code` |
| budgeting | `l10n_th_account_tax_expense_budget_allocation` | `l10n_th_account_tax_expense`, `budget_allocation_advance_clearing` |
| budgeting | `l10n_th_gov_account_asset_management_budget_allocation` | `l10n_th_gov_account_asset_management`, `account_asset_fund` |
| budgeting | `l10n_th_gov_hr_expense_activity` | `budget_activity_advance_clearing`, `l10n_th_gov_hr_expense` |
| budgeting | `l10n_th_gov_hr_expense_budget_control` | `budget_control_expense`, `budget_control_purchase_request`, `l10n_th_gov_hr_expense` |
| budgeting | `l10n_th_gov_purchase_agreement_budget_control` | `budget_control_purchase`, `l10n_th_gov_purchase_agreement` |
| budgeting | `l10n_th_gov_purchase_guarantee_activity` | `l10n_th_gov_purchase_guarantee`, `budget_activity_purchase`, `budget_activity_purchase_requisition` |
| budgeting | `l10n_th_gov_purchase_guarantee_budget_allocation` | `l10n_th_gov_purchase_guarantee`, `budget_allocation_purchase_requisition`, `budget_allocation_purchase` |
| budgeting | `purchase_stock_budget_allocation` | `purchase_stock`, `stock_budget_allocation`, `budget_allocation_purchase` |
| budgeting | `stock_budget_allocation` | `stock_analytic`, `budget_allocation` |
| budgeting | `stock_request_budget_allocation` | `stock_request_analytic`, `stock_budget_allocation` |

## Verified behavior and pending audit

- `budget_control` controls analytic accounts optionally at KPI/account level; its period enables control by document type, and control sheets have draft, submit, done and cancel states. Budget availability is budget less commitments and actuals. The template maps KPI lines to accounts; transfer, adjustments, forward balances and financial reports are additional workflows.
- `budget_allocation` permits one allocation per budget period. Completing an allocation creates/updates a budget plan and sets released amounts to allocated amounts; fund and analytic dimensions are line inputs. Plan lines feed controls, and plan state is draft, confirm, done or cancel. Revision modules add versions and amount lock behavior.
- Purchase request submission invokes `check_budget_precommit`: it creates temporary budget moves, performs the check, then removes them. It is a check, not a persistent precommit reservation. An approved or done request generates actual commitment moves; reject or reset removes or recomputes them. Request line edits trigger recomputation and checks.
- Confirming a purchase order produces PO commitment and reverses the related PR commitment to prevent double-counting. Cancelling or reverting PO recomputes the PR commitment. Accounting move lifecycle subsequently recomputes PO commitments. Partial quantities, invoices, taxes, currency, multiple analytics and rounding need further analysis before a replacement contract is safe.
- `base_tier_validation_check_budget` can check before review validation. `budget_control_tier_validation` attaches approval tiers to budget control and transfers. `egov_purchase_request` also invokes precommit in its approval server action. Scope and all concrete approval configurations remain to be audited.
- Budget-control OU source has read-only OU rules with budget-manager bypass and context-controlled privileged reads. These are not sufficient for the requested independent read/write isolation and must not be copied unchanged. Organization Contract v1 is the target boundary.
- Legacy Excel import/export modules in NSTDA private source add allocation/control imports. Their full data formats, report output, integration behavior and security remain to be audited. Cross-domain modules listed above are not migrated merely because their manifest is inventoried.
- Scheduled actions and controllers: complete inventory and behavior review NOT COMPLETE. Native Odoo 20 analytic and accounting compatibility, referenced external dependency commits, full multi-merge upstream source, tests, reports, legacy-data upgrade and external interfaces remain to be inspected.

- `budget_allocation/models/base_budget_move.py` validates the funding-source balance by analytic account, fund and dynamic analytic dimension fields; it requires a matching allocation and sums signed monitoring amounts. A single balance per OU or fund would not reproduce this behavior.
- `budget_control` allows control by analytic or analytic plus KPI, with account-to-KPI mapping and period date ranges. Its report aggregates budget, commitments and accounting actuals; source `check_budget` uses a caller context flag to bypass checks and elevated reads. A replacement must authorize independently and protect both levels of control.
- The two NSTDA Excel extensions depend on `excel_import_export` and Python packages pandas, numpy and openpyxl; they supply template/actions for control sheet and allocation import/export. Individual data formats and authorization have not yet been reviewed.
- OCA account-analytic `d7c2bf3d29c717f1b146a9684cdd63b3b1e6719c`, referenced in NSTDA repos.yaml, adds dynamically configured analytic dimensions, required-dimension validation, references to other records and ordered tag selection. A migration must decide how these map to Odoo 20 analytic distributions and preserve distinct allocation dimensions; it is not sufficient to assume a single analytic account.
- OCA server-ux `2b10d7707b747696fe41dd76bb84f2d85924074f` provides the 15.0 tier-validation mixin, company rules, ordered reviews and approver checks. It uses old UI APIs/assets; Odoo 20 compatibility and the additional Ecosoft server-action merge are not yet established.
- Read-only inspection of the local `odoo:20.0` Community image found `account.analytic.account.plan_id` required, optional analytic company and JSON `analytic_distribution` on `account.move.line`. A direct replacement of the old tag model or one scalar analytic field would need careful treatment of multiple distributions and shared analytics. Native `purchase_requisition` is present in that image; presence alone does not establish NSTDA workflow compatibility.
- On 2026-10-29, `OCA/server-ux` branch heads checked through Git were `20.0` `d952d4dfbe65e7b67c6999c94c9dbb8e69c441c2` and `19.0` `2e040168c4ed27ac6e732c68516ca47781eb1a0f`: neither tree contains `base_tier_validation`. The 18.0 head `3abc366f5c41698105de433407cffbbabcc699f9` does contain it (version 18.0.3.5.2, AGPL-3, dependency `mail`). Porting and security/runtime acceptance are still required; these observations are not proof that no other Community implementation exists.

## Lifecycle trace and mapping work

See `budget-lifecycle-v1.md` for the source call chain, Odoo 20 plan/distribution mapping, KPI mapping, upstream-tested full PR-line release on partial PO and remaining multiple-PO ambiguity, invoice behavior and nonbinding proposed contract. Odoo 20 `analytic.mixin` parses comma-separated account IDs in JSON keys and validates percentage totals by mandatory root plan; the Odoo 20 source was inspected in the test image. The target design has not been tested or frozen.

- `budget_control_purchase_request/tests/test_budget_purchase_request.py` explicitly tests a PR line with quantity 3 and commitment 30 converted to a PO quantity 2 at unit price 25: PR commitment becomes 0 and PO commitment 50; cancel restores PR 30. Its two-line partial case also releases both linked PR line commitments completely. This is stronger evidence than the earlier inference from the reversal call.

`budget_control/models/budget_template.py` maps a template KPI to multiple general-ledger accounts. `_get_kpi_by_control_key` rejects missing or ambiguous mappings. The new target template represents the same mapping as one row per account and prevents duplicate mappings within a template; period association and financial control are pending. Source `purchase.order.write` recomputes linked PR lines on `purchase` and `cancel`; each PR line deletes/recreates its moves and processes its linked POs, reversing only while the PR's computed commitment remains nonzero. See the lifecycle document for the inferred multi-PO behavior and its testing limitation.

## Plan and shared control scope — source review

OCA `budget_plan/models/budget_plan.py` confirms plan lines by analytic account, checks proposed amount against consumed value, and generates/updates control sheets. `budget_control/models/budget_control.py` constrains active control uniqueness by analytic account and period; it holds released allocation, with KPI/date-range lines and an approval check that their planned sum equals the released amount. `budget_control_operating_unit/models/budget_control.py` derives OU from the analytic account and rejects an analytic with more than one OU; it is not an additional independent financial ceiling key. Ecosoft `budget_allocation/models/budget_allocation.py` aggregates allocation lines into plan lines. `budget_plan_revision` creates versioned plans/controls, and `budget_control/models/budget_transfer{,_item}.py` has a draft/submit/transfer/reverse lifecycle, adjusts released values, and checks source availability. Tier extensions add approval. Source carry-forward and all supplement/reallocation variants are not yet fully audited.

Target deliberately scopes plan ceilings to company + period + analytic, independent of KPI, fund, analytic dimensions and OU; company is a target multi-company security boundary. OU on the plan line is ownership/access metadata. If target permits the same analytic in more than one OU, all those controls share the ceiling. KPI and fund/dimension target controls remain independent checks. The optional allocated mode enforces sum of child analytic controls <= parent; upstream's exact equality/period-line generation and full transfer/approval lifecycle are not yet parity. Independent-limit mode permits overlapping child limits but enforces the parent aggregate at every posting.

## Revision, release and approval source detail

`upstream/server-ux/base_revision/models/base_revision.py` copies the document and lines into a new numbered full snapshot, archives the old record and links it to the current revision. `budget_plan_revision` requires related controls and propagates the revision to them; the source revision is not merely a delta event. `budget_allocation` is a separate fund/analytic allocation document in draft/done/cancel whose done action creates/updates a plan and released amounts; its detailed allocation dimensions and version chain are not reproduced by the KPI release subset. `budget_control` separately checks the sum of planned KPI/date-range lines against released control amount. `budget_control_tier_validation` uses OCA `tier.validation` from submit to transfer; its broader definition/review/restart semantics are not the same as Procurement's narrow per-user tiers.

The target retains its existing plan and immutable delta ledger, with optional explicit full plan snapshot versions. Activation requires the previous effective version and unchanged baseline amounts; changes are applied as linked delta events after consumption checks, retaining economic ledger identity. The first explicit revision creates a labelled current-state baseline with no invented reviewer. Later independent events can change the current cap after a snapshot; newly anchored snapshots include only subsequent events, while old unanchored snapshots retain the legacy event resolver. The target does not yet produce source control versions or full upstream allocation documents.

A new formal KPI release is a target-specific document, not a claim that source `budget.allocation` is KPI-based. It ties declared released amount to the sum of the controlled KPI amounts and opens those controls only after ordered Budget-specific reviewers approve. Procurement's current review model is request-specific and Procurement depends on Budget; directly depending on it here would form a cycle and reuse its unrelated Procurement-manager configuration for Budget. The target follows its ordered-review pattern with separate settings-admin-configured Budget tiers. Release reversal closes children only after their net consumption is zero; transfer reversal creates one immutable inverse event and rejects insufficient destination capacity. Version activation and existing plan-transfer events still use Budget manager authorization rather than the full source tier-validation workflow.

## Allocation, carry-forward and imports — additional source inspection

At `budgeting` 08842c5, `budget_allocation` contains a period/company header and analytic/fund/tag lines; `action_done` creates or updates a plan, sums allocations into analytic plan lines, copies allocated to released on each allocation line, and sets done. Its base states are draft/done/cancel, not a guessed tiered release workflow. `budget_allocation_revision` copies released amounts into the new allocation's allocated amounts and creates a related plan revision. `budget_plan_revision` requires existing controls and requires the controls selected for revision to be cancelled; it creates their revisions when updating controls. `budget_control_revision` filters planned amounts by revision number. Further merged-extension behavior requires inspection.

At `account-budgeting` b447bab, `budget.balance.forward` reviews prior analytic balances, excludes already forwarded analytics in review/done documents, supports forwarding or accumulation, and updates destination initial available; it does not itself prove prior-year capacity is closed. `budget.commit.forward` is separate: it stores source document identity, amount, original and forward date/analytic, updates the document's forward fields, recomputes moves and restricts cancelling an older forward after later ones. Neither is implemented by target ledger. Source `budget.control.line` holds KPI, date_from/date_to and amount; monitor `_select_budget` reports it at `date_to`. More of the query must be traced before asserting per-transaction date behavior.

NSTDA `egov_budget_allocation_excel_import_export` and `egov_budget_control_excel_import_export` provide XLSX templates and import/export; allocation import resolves analytic names and periods. Source-format import is a production-data exchange requirement when that format is needed, not evidence that a separate convenience UI is universally required. See `budget-parity-matrix.md` for current classification.

Target now anchors newly activated snapshots to an explicit period-event boundary and applies only subsequent effects; previously stored effective snapshots without this boundary continue the legacy resolver. This makes the target snapshot authoritative for its boundary without inventing an ordering for historical data, but it does not implement source allocation/control version lifecycle or eliminate all unapproved target adjustment events.

Tracing the base validation further: `_check_budget_available` invokes `_get_budget_avaiable`, which sums the monitor query for analytic and optionally KPI. The base monitor joins dates to the configured date-range type and budget period, but that validation query does not itself add a cutoff at the document date. Thus the inspected base source does not establish that a March transaction is restricted to January–June allocation; do not introduce that behavior without an applicable extension or tested source fixture. Extensions and effective merged configuration remain to be reviewed.

## Initial fund allocation subset

The target now provides an initial company/period fund and analytic allocation document with draft/done/cancel and a generated draft plan whose analytic amounts are sums of its lines. Done stores the released line amount and creates draft fund controls backed by those lines; plan confirmation and control opening remain separate steps. This is a constrained target adaptation: it applies only when the period has no plan or controls, has no source tag/dimension mapping or full allocation revision lifecycle, and rejects cancelling a done allocation. Its immutable generated controls and blocked unbacked fund controls prevent this subset from creating an independent fund authority. Allocation-backed plan adjustments fail closed; the amount-only linked revision subset is described below. It is not complete `budget.allocation` parity.

Final targeted override search for `_get_budget_avaiable`, `_get_budget_monitor_report` and monitor `_get_where_clause` in the inspected budgeting, account-budgeting and NSTDA private trees found advance/deposit KPI exclusions and OU filtering, but no document-date cutoff. A per-document subperiod capacity cutoff is therefore NOT PRESENT / NOT REQUIRED by these inspected sources; KPI/date-range planning lines and equality to released amount remain required source behavior. This conclusion is limited to the checked source trees, not an unverified merged deployment.

## Allocation revision subset

`server-ux/base_revision/models/base_revision.py` copies the whole record, numbers the revision, archives the predecessor during revision creation and links old records to the new current record. `budget_allocation_revision` copies released values into allocated values and, on done, creates the corresponding plan revision; `budget_plan_revision` requires control revisions and cancelled source controls. The target subset instead keeps its completed allocation and effective capacity while a successor draft is prepared, then atomically activates a linked plan snapshot and adjusts the existing operational fund controls. Original allocation lines and historical revision snapshots are immutable; fund controls retain ledger identity. This is a deliberate safety adaptation, not complete source control-revision, approval or lifecycle parity. Target revisions currently retain existing allocation dimensions and require all fund controls to be active and not closed; adding/removing dimensions and revising released KPI controls are not implemented. There is no upstream-derived reviewer approval for this subset; a Budget manager activates it.

## Planning reconciliation and economic removal

`account-budgeting/budget_control/models/budget_control.py` `_check_budget_amount` requires total planned KPI/date-range amount to equal control `released_amount` at both submit and done; it also rejects planning below initial balance. `prepare_budget_control_matrix` generates a row per configured date range and template/KPI. The target formal KPI release on a source-backed allocation now requires its total open/planned KPI controls to equal the parent released amount at submit and final release. A revision cannot change that total while released KPI controls remain at a different total. This is a narrower aggregate check: source date-range matrix, initial balance, coordinated KPI/control revision, legacy periods and standard OCA tier parity remain incomplete. The checked base monitoring query and overrides have no transaction-date subperiod cutoff.

An existing allocation revision line may now be reduced to zero only when its fund consumption and parent constraints permit it. The original line, control identity and ledger remain; the zero-valued control cannot authorize new expenditure. This is economic deactivation, not full source add/remove dimension revision or source control-version parity.
