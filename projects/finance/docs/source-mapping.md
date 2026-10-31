# Finance source mapping — MIGRATED

| Exact source behavior | Target | Parity |
|---|---|---|
| Budgeting posted/draft/cancel actuals and PO quantity uncommit | Native GL amounts and canonical immutable Budget reconciliation | MIGRATED |
| Refunds and original existing-commitment condition | Original posted document, source provenance, capped quantity/value, safe reset | REDESIGNED |
| Source net/all/specific tax and native/manual FX | Frozen commitment policy; native company-currency actuals, tax and refund integration | MIGRATED |
| Analytic fund/activity/dimension provenance | Native distributions and explicit source lines; no competing split-capacity authority | REDESIGNED |
| Fiscal commitment forwarding | Budget service resolves the canonical successor; accounting preserves old actuals | MIGRATED |
| Native Expense, PR-to-Expense, ordered review, advance clearing/return | Real accounting documents and immutable settlement provenance, company/OU boundaries | MIGRATED |
| Thai Expense vendor VAT/reference/date and withholding | Native Thai invoice evidence and WHT-only/cash payments; advance net-cash versus gross Budget distinction | MIGRATED |
| Purchase deposit and invoice-plan deduction | Native bill matching, explicit approved source, proportional/final deduction and retained history | REDESIGNED |
| Payment retention and invoice-plan terms | Native retained payment and reconciled release, no second Budget actual, atomic WHT coexistence | REDESIGNED |
| Historical posted source conversion, statutory templates, bank/export configuration, attachments, browser/load | Separate deployment/data acceptance | PRODUCTION READINESS |

Sources and runtime evidence: `source-amount-policy.md`, `source-retention-plans.md`,
`test-report.md`, and the workspace migration completeness audit. No additional
accounting role is implicitly granted. Actual production data conversion is not
inferred from isolated runtime tests.

PR FX integration now compares expense limits and captures approved request snapshots in company currency via the canonical Procurement amount method. Real foreign-PR100/company50 rejects expense60 and permits posted expense40. `financial-contract-59.log`: all 147 Procurement/Finance/Contract tests pass, failures0/errors0, no skips reported.
