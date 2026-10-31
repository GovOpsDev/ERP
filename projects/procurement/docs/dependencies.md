# Procurement dependencies — PARTIAL

`erp_procurement` depends on native Purchase and `erp_budget`, which depends on Organization. The optional `erp_finance` addon depends on Procurement and provides its supported posted-bill actual reconciliation. Without that addon, the Procurement Finance guard remains active. Full source dependencies and migration gaps are in `source-mapping.md` and `upstream-analysis.md`.
