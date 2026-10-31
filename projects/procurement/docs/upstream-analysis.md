# Procurement upstream analysis — PARTIAL

Sources inspected: NSTDA ERP-Government `5a1722c4c6f6cfdf3ed59362a56e85777c58a383`, `egov_purchase_request` and `egov_purchase`; OCA l10n-thailand `5ebe30a8be970d2d0b9504e18606a5d0b90df1e6`, `l10n_th_gov_purchase_request`. OCA purchase-workflow baseline `7eed5d2dd34d14edd74c6c80c235d0c75619f1d8` is checked out but its full dependency set has not been analyzed. NSTDA uses an odoo-repos multi-merge checkout: these individual commits are evidence of individual patches, not a reconstruction of the complete effective upstream checkout.

| Source | Behavior | Target | Status |
|---|---|---|---|
| l10n_th_gov_purchase_request | procurement/purchase types and methods, committees, request fields, verification and approval timestamps, request conversion and rejection rules | Not yet implemented | DEFERRED |
| egov_purchase_request | verified substate before tier validation; tier approval triggers budget precommit check; thresholds and rejection actions | Not yet implemented | DEFERRED |
| egov_purchase | tier actions approve/cancel purchase orders | Not yet implemented | DEFERRED |

Source dependencies include purchase request/requisition, exception handling, substates, tier validation, HR and budget control. Budget check-only submission and final commitment now have a narrow tested implementation; the remaining source workflow is not fully migrated. Source server actions use `sudo()` and rejection bypass context; authorization and record scope must be independently verified, not inherited blindly. Upstream source also calls `super().button_rejected()` from `button_draft`; treat as a potential upstream defect to evaluate rather than duplicate without tests. The implemented subset and its acceptance evidence are documented in the design and test report.

The initial `erp_procurement` implementation uses a limited ordered per-user reviewer adaptation and multi-key PR → native PO integration. It does not claim OCA tier parity or requisition/report migration; see `design.md` and `source-mapping.md` for deviations and fail-closed restrictions.
