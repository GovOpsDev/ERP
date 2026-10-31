# ERP Finance — MIGRATED

Odoo 20 Community runtime migration covers native Budget-aware accounting, tax/FX,
refunds, Expense and advance clearing, PR handoff, deposits, Thai VAT/WHT, payment
retention and invoice-plan integration. Canonical Budget APIs own commitments and
actuals; financial settlement never creates a second capacity bucket.

See `docs/source-mapping.md`, `docs/source-retention-plans.md` and
`docs/test-report.md` for exact source decisions and real runtime evidence.
Production readiness is NO: historical source conversion/reconciliation, filestore,
browser/load, statutory templates, bank/export configuration and deployment remain
separate. No historical actuals or approvals are fabricated.
