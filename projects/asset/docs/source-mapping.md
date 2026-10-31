# Asset source parity — MIGRATED

Source references: NSTDA ERP-Government `5a1722c4c6f6`, Thai localization
`5ebe30a8be97`, budgeting `08842c565308`, selected OCA financial-tools
`3bd0064b002af78f0d56745c6480d1f3c4fe0d76`, and its explicit expense bridge merge
`f0acb32cdd917f29bdec4b7f9af43a7ddca76606`. Imported OCA engine/transfer provenance
remains in `oca-asset-port.md` and `transfer-architecture.md`.

| Source behavior | Decision | Current implementation |
|---|---|---|
| Account/profile eligibility | REDESIGNED | One active ERP company/account profile; duplicate automatic OCA creation rejected. |
| Posted bill, accepted PO and acquisition date | MIGRATED | Native GL company balance, accepted WA date, immutable origin and item snapshots. |
| Product item expansion | REDESIGNED | Whole-number quantity produces per-item acquisitions without multiplying GL; final item receives currency remainder. |
| Expense acquisition | MIGRATED | Native own-account receipts and company-payment entries; profile/account/OU validation, native GL value, item splitting and accounting date. Advance is not acquisition; clearing can acquire. |
| Analytic and fund provenance | MIGRATED | Source snapshots copied to the engine; depreciation expense line receives fund and analytics. Company option propagates analytics/fund to all asset accounting lines. Fund is reporting provenance, not a second acquisition Budget actual. |
| OCA depreciation and posting | NATIVE ODOO / REDESIGNED | Imported OCA engine, explicit manager link, posted balanced moves, one posting per depreciation line and company/OU scope. |
| Thai daily depreciation and residual | MIGRATED | Inclusive days use purchase minus salvage; completion at salvage closes the asset. Native fiscal-period engine and currency precision remain. |
| Parent, image, substatus and rate | MIGRATED | Parent sequence/search, image attachment, company-aware lifecycle substatuses, rate and server-side consistency guards. |
| Low-value tracking | MIGRATED | Expense account plus zero years: residual zero, running tracked state, no depreciation or disposal GL. Historical target AUC classification is explicitly preserved. |
| Disposal and batch removal | MIGRATED | Native removal and posting; removal reason; one-company/homogeneous-category batch, date and state validation, atomic batch rollback. |
| AUC transfer/reclassification | REDESIGNED | Existing same-company/OU split/merge, locked sources, balanced journal and immutable lineage. A common fund is carried to destinations; ambiguous multiple source funds stay distinguishable in source history, not guessed as one fund. |
| Asset-backed credit | REDESIGNED | Original posted bill identity and source line resolution; proportional company-currency reductions, nonnegative per-item remainder, no over-credit. Native financial actual/refund is unchanged. |
| Reset/cancel/repost | REDESIGNED | Original acquisition and valuation events retained; credit reset appends inverse events; acquisition reset cancels that generation; repost creates a new numbered generation. |
| Active/depreciated/transferred acquisition reversal | NATIVE ODOO / REDESIGNED | Upstream deletes only eligible draft assets without posted depreciation. Target requires that boundary and retains history; active or economic depreciation/disposal/transfer prevents source reset/credit. |
| Goods return | NATIVE ODOO / REDESIGNED | Native picking return records physical return. Its linked credit records financial capital reduction; returning stock alone does not invent a credit or change original acquisition history. |
| OU/custodian/location administrative transfer | NOT REQUIRED | Exact inspected scope establishes accounting AUC transfer and organization fields, not a separate administrative transfer workflow. |
| Templates, historical import, filestore, browser/load, production deployment | PRODUCTION READINESS | Separate from runtime source parity; not represented as completed. |

No remaining REQUIRED MIGRATION row. Reporting presentation is an enhancement;
statutory template verification and source-data conversion are readiness.

## Preserved historical state

Upgrade `20.0.1.1.0` marks pre-existing zero-year expense-account assets as
`erp_legacy_auc`. The previous target treated them as AUC, so the migration must
not silently zero their residual or fabricate an upstream low-value classification.
New assets use the source low-value rule. Existing acquisition snapshots are not
backfilled; an explicitly requested new engine link can read the preserved source
line for its analytic/fund provenance. Existing economic and accounting history is
not replaced with fabricated source events.

## Valuation invariant

`current acquisition value = original purchase value + immutable valuation events`.
A credit adjusts only a draft depreciation plan and its initial carrying amount;
it never rewrites posted GL or depreciation. Original acquisition snapshots remain
unchanged. Original bill reset is rejected while unreversed credits exist. Credit
reset and acquisition reset use the native accounting transaction, including Budget
reconciliation, in one savepoint. State RPC writes cannot bypass those actions.

Two-transaction tests cover competing excess credits and activation versus credit.
Acquisition/account/engine version locks force a stale transaction to retry; a fresh
retry validates the remaining value/state and refuses unsafe changes.
