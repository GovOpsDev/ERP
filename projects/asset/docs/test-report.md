# Asset test report — MIGRATED

The current result is in the closure validation section below. Earlier results
are retained as historical evidence and do not describe current feature gaps.

## Earlier migration runs

Odoo 20 Community imported OCA engine standalone: 26 tests, 0 failures/errors, no skips reported (`/tmp/erp-finance20/oca-project-02.log`). Full-stack clean: 171 tests, 0 failures/errors (`asset-full-clean-03.log`); copied-DB upgrade: 169 tests, 0 failures/errors (`asset-full-upgrade-03.log`); no skips reported. These cover selected Organization, HR, role, Budget, Procurement, Finance, Contract, Inventory and ERP Asset suites; upstream OCA tests run separately because full ERP deliberately restricts unlinked engine records.

Targeted ERP tests (`asset-integrate-09.log`, 14 tests) cover link and provenance, board and posted balanced depreciation, duplicate post rejection, OCA/ERP creation conflict, company/OU and role restrictions, 4 individual assets, manager-only lifecycle, and disposal followed by explicit journal posting. Existing acquisition flows include service, goods, 4+6, unprofiled lines and guarded refunds. Native stock return preserves the acquisition snapshot but does not establish return/accounting reconciliation.

A copied DB with an existing acquisition was upgraded without changing its prior-field fingerprint. A further copied DB was explicitly linked, activated and had a depreciation journal posted; subsequent upgrades passed 14 ERP tests and fingerprints of 12 selected business tables matched when excluding newly added default fields (`asset-lifecycle-upgrade-04.log`, `asset-lifecycle-before.txt`, `asset-lifecycle-after-final.txt`). This is not a filestore or production migration.

Targeted two-transaction probes: same bill yielded one acquisition and one serialization failure (`asset-race-05.log`); profile edit versus link, profile deactivation versus posting and profile creation versus posting each yielded one commit and one serialization failure (`asset-profile-race-01.log`, `asset-profile-post-01.log`, `asset-profile-create-01.log`). These are narrow contention checks, not load testing. Profile locks apply to vendor-bill posting and may affect throughput.

The imported OCA management and transfer standalone regression passed 29 tests, 0 failures/errors (`transfer-oca-regression-01.log`). ERP transfer tests exercised split 100 to 40/60 then merge to 100, balanced journal, scoped OU and history, source state, duplicate/reopen/reversal guards, unauthorized access, and currency-rounding comparison (`transfer-integrate-06.log`: 15 tests, 0 failures/errors; includes date and rounding guards). Full-stack clean passed 172 tests (`transfer-full-clean-02.log`) and full-stack upgrade passed 170 tests (`transfer-full-upgrade-03.log`), both 0 failures/errors; selected upgraded ERP tests passed 15 on separate databases with a posted AUC transfer and with existing posted depreciation (`transfer-seed-upgrade-01.log`, `transfer-depr-upgrade-01.log`). Fifteen selected transfer/business-table fingerprints matched across the transfer upgrade and twelve existing-table fingerprints matched across the depreciation upgrade after excluding new fields. The targeted race committed one transfer; the other transaction got SerializationFailure and one destination remained (`transfer-race-02.log`). These checks do not establish transfer of already-depreciated assets or OU/custodian/location changes. Asset-backed refund/reset remain rejected. Browser, filestore, production data, full concurrency scale, Thai extensions, wider transfer scope and return accounting are NOT TESTED.

## Closure validation, 2026-10-31 (supersedes the partial boundaries above)

ERP Asset `20.0.1.1.0`: `asset-final-20.log` reports 25 tests, failures 0,
errors 0, no skips reported. It covers the original acquisition/engine/transfer
suite plus Thai daily salvage, substatus/company consistency, low-value removal,
Expense own/company payment, analytic/fund provenance, item rounding, native
Expense credit/reset, partial/full/excess credits, draft engine reconciliation,
retained reset/repost generations and active/posted-depreciation rejection.

`asset-race-02.log` reports ASSET_CONCURRENCY_PASSED. Competing 60 credits against
100 capital commit once; the stale transaction gets SerializationFailure and a
fresh retry rejects excess. Activating the remaining 40 asset against another
credit also commits once and rejects the fresh credit retry. The fixture uses a
real PR/PO/WA/bill and isolated committed test records. The first attempt lacked
a synthetic warehouse and was corrected; it did not reach the race.

`asset-history-upgrade-18.log` upgrades a copy of historical posted depreciation.
Seven selected old tables were compared using every pre-existing column. Four
match byte-for-byte; account_asset/account_move/account_move_line differ only in
write_uid/write_date from dependency recomputations. All old business values match;
this is not full database or filestore equivalence. The detailed field differences
are retained in `asset-history-diff.json`.

`asset-auc-history-upgrade-19.log` upgrades a separate old AUC transfer copy. Existing
assets 44 and 45 retain removed/draft states and purchase/residual 10/10 respectively;
both have erp_legacy_auc=true and low_value=false. New low-value behavior therefore
does not erase historical target AUC semantics.

Current durable evidence directory:
`/GovOpsDev/th-gov-erp/test-evidence/closure-20261031/`.
Original databases and volumes are preserved. Browser, filestore, production source
conversion, deployment and full load remain NOT TESTED readiness items.

Fresh cross-domain clean installation `cross-clean-21.log`: 311 tests, failures 0,
errors 0, no skips reported. The historical full-suite first attempt identified two
synthetic Budget keys accidentally resolving real accounting line ID 1; the test
keys were corrected without weakening assertions or changing runtime code. See the
subsequent historical full-suite result below.

Final historical cross-domain regression `cross-history-24.log`: 309 tests,
failures 0, errors 0, no skips reported. No synthetic test was excluded.
Focused `asset-return-25.log`: 1 test, failures 0, errors 0, no skips reported;
real goods receipt → stock return → credit changes current capital/actual from
40 to 30 while retaining the original acquisition at 40.
