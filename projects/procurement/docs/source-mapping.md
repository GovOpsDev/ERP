# Procurement source mapping — MIGRATED

| Exact selected source | Target behavior | Decision |
|---|---|---|
| OCA purchase_request and account-budgeting approved/done commitments | Draft/submit/ordered approval/reject/done/reset; Done retains its commitment; reset reverses only unused commitment | MIGRATED |
| NSTDA egov_purchase_request and Thai request type/method/committees | Verification and approval actors/dates; company configurations; committee snapshots; requisition or native employee expense routing | MIGRATED |
| OCA PR and PO tier validation | Reuse company-scoped configured per-user thresholds, ordered decisions and immutable submission rounds; no competing generic approval engine | REDESIGNED |
| purchase_request_to_requisition and government purchase agreement | Native requisition and RFQ with protected PR/FX provenance; agreement PO type activates Contract gate | MIGRATED |
| budget_control_purchase_request/purchase | Canonical Budget simulation and commitment replacement; native bills/refunds/fiscal forwarding | REDESIGNED |
| Selected PR/manual currency | Captured document FX, original foreign estimate, company-currency review/commitment and conversion propagation | REDESIGNED |
| Invoice plan/deposit/retention | Native planned bills, final remainder and Finance integration | REDESIGNED |
| Operational presets, historical import, reports, browser and deployment | Configuration and production rehearsal | PRODUCTION READINESS |

Source revisions: purchase-workflow 7eed5d2dd34d, l10n-thailand 5ebe30a8be97,
ERP-Government 5a1722c4c6f6 and selected PR/manual-currency a3e92125a780.
Verification does not fabricate legacy actor history. Historical review rows gain
round 1 only; reset retains their original snapshot and recorded decisions.
Configured purchase tiers freeze RFQ terms; final native confirmation and Budget
posting are one transaction. Revoked OU access is rechecked when deciding.

Closure evidence: government-financial-61.log: 179 tests, 0 failures/errors;
government-62.log: 5 tests, 0 failures/errors; purchase-tier-race-03.log:
one commit, one SerializationFailure, safe retry, exactly one approved review and
60 company-currency commitment. These are runtime migration tests, not browser
or production-data acceptance. No push.
