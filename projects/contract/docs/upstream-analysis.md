# Contract upstream analysis — first slice

Inspected OCA/contract 15.0 `dd986a073c1ecfca3fbe35bdbc8c696ae5abefe8`, OCA invoice-plan patch `944dcbeaa513c242c7df31452c54801b764ebf54`, and Ecosoft/budgeting `08842c565308de3b7259a34b391164c6ce4d0605`. NSTDA merges multiple commits: their individual trees are evidence, not the final combined checkout. Odoo 20 upstream branch `368c02dbafe237f65706449a7038cb2da8f44e5a` has no contract addon at the time inspected.

| Source behavior | Odoo 20 migration implication | Status |
|---|---|---|
| `contract.contract` and `contract.line`; recurring invoice generation, termination and line states | Preserve actual source states and native accounting link; assess recurrence and scheduling before selecting scope | Partially implemented; see source mapping |
| Accounting line `contract_line_id` | Trace vendor bills/refunds to contract line, independent of `purchase_line_id` | Partially implemented; see source mapping |
| Invoice plan adds installments and plan dates | Assess required NSTDA usage and rounding | Partially implemented; see source mapping |
| Budget contract commitment on active purchase-journal contract with `commit_budget`; updated when contract lines change | Requires a new source-aware Budget reconciliation family; never reuse PR/PO identities | Partially implemented; see source mapping |
| Posted bill/refund can uncommit/return by converted quantity, subject to current contract commitment | Coordinate with Finance actuals and avoid double-counting if invoices link both PO and contract | Partially implemented; see source mapping |
| Multi-company and portal rules | Adapt to Odoo 20 `ir.access` and Organization contract; validate portal and OU isolation | Partially implemented; see test report |

The distinct Contract Budget adapter extends the Purchase-only Finance boundary without treating a PO as a Contract source. The implemented subset and remaining gaps are mapped in `source-mapping.md` and `contract-lifecycle-v1.md`.

Additional source evidence: NSTDA `egov_install` explicitly includes `agreement`, `agreement_legal`, `contract`, contract invoice plans and `l10n_th_gov_purchase_agreement_budget_control`. Thai agreement code requires agreement-type requisitions to have an agreement before PO confirmation and checks the RFQ/vendor relationship. Its Budget extension tags the purchase Budget move for agreement reporting; it does not create a separate Agreement commitment. OCA Agreement Legal retains separate three-value state and configurable stages, version copies, legal clauses and expiry review activities. The target intentionally implements only the documented subset.
