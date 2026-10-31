# Native requisition migration

Required source: purchase-workflow `7eed5d2dd34d` module
`purchase_request_to_requisition`, especially
`wizard/purchase_request_line_make_purchase_requisition.py`; government routing
at Thai `5ebe30a8be97`, `l10n_th_gov_purchase_request`.

Odoo20 native `purchase.requisition` replaces the Odoo15 tender type with its
purchase-template agreement. ERP source lines remain separate so each retains one
canonical PR/Budget family; source aggregation by product never merges independent
fund/account dimensions. The agreement adds no commitment. Native RFQ preparation
copies original request, fund, analytic, activity and dimension identities; native
PO approval and Finance bill posting retain existing Budget APIs.

Approved request conversion is version-locked and repeatable without duplication.
Company/OU visibility applies to agreements and lines. Confirmed-source checks,
positive quantities/prices and server provenance checks reject forged or detached
RFQ sources. Native uncontrolled agreements retain native behavior.

`procurement-requisition-28.log` in the workspace durable closure evidence directory
reports 22 tests, failures0, errors0, no skips reported: all21 Procurement tests
plus a real Finance PR→agreement→PO→partial bill→reset/cancel test. Commitment moves
50 PR→70 PO→35 PO+35 actual→50 PR; no additional agreement capacity is introduced.

Procurement remains PARTIAL: government type/method/committee/verified metadata,
source PR currency semantics, done/reset review rounds, PO tiers, invoice plans and
retention integration remain required. Guarantee accounting uses this native
agreement scope as a dependency. Production configuration and historical import
remain separate readiness work.
