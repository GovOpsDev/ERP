# Agreement and Contract source mapping — MIGRATED

| Upstream source behavior | Target mapping | Status |
|---|---|---|
| OCA `agreement` + `agreement_legal`: code, party, signature/dates, `draft`/`active`/`inactive`, stage and versions | `erp.contract.agreement`, sequence, states and version snapshots; manager actions and effective-date checks are a security redesign | REDESIGNED |
| OCA legal stages, clauses, recitals, appendices and review activities | Versioned legal content, signed attachments, guarded stages and scoped idempotent native review activities | MIGRATED |
| Thai `l10n_th_gov_purchase_agreement`: one RFQ per agreement, many agreements per RFQ; partner must match; agreement-type RFQ requires an agreement before PO confirmation | Native `purchase.order`, one-to-many agreements; manager-controlled `erp_agreement_required` or native requisition `erp_po_type=agreement`. Both confirm and approve check it | REDESIGNED |
| `l10n_th_gov_purchase_agreement_budget_control` | Source flags the existing PO Budget move for agreement reporting, not a second agreement commitment; target uses the existing PO ledger without duplicate moves, but agreement-specific reporting is absent | REDESIGNED; report layout is PRODUCTION READINESS |
| OCA `contract.contract`/`contract.line`, purchase journal, active and `commit_budget` | `erp.contract.contract` and `erp.contract.line`, source-derived product/account/analytic/fund/period; manager enables/closes Budget | REDESIGNED |
| `budget_control_contract` and `budget_allocation_contract` | Budget service owns immutable contract commitments/reversals and posted invoice actuals; converted bill quantity reduces commitment at contract price | REDESIGNED |
| Contract invoice relation | Native `account.move.line.erp_contract_line_id`; a line cannot also link a purchase line, avoiding two Budget sources on the same line; native reversal copies contract link | REDESIGNED |
| Thai purchase guarantee receive/return and instrument custody | Native paid invoices/bills, immutable settlement history, company/OU and concurrency guards; see source-guarantee.md | MIGRATED |
| Contract invoice plans and manual quantity/line selection | Native bills, final remainder, selected quantity checks, FX, immutable links and source locks | REDESIGNED |
| Recurring invoice generation and amendments/renewal | Immutable periods, native direct actuals, successors, renewal and termination; see source-recurrence.md | REDESIGNED |
| Report layouts, source attachments and historical data conversion | Production rehearsal remains separate from runtime migration | PRODUCTION READINESS |

Contract and Agreement are distinct upstream models. A PO-linked agreement is referential; a separate committed purchase contract is a distinct source document. There is no automatic detection of two separate documents representing the same economic obligation. Only the one-invoice-line/two-source case is rejected. No Enterprise modules are used.

Legal agreement stages/content/signatures/reviews are closed; see [source-legal-agreement.md](source-legal-agreement.md). Recurring and amendment/renewal scope is closed; see source-recurrence.md. Government requisition PO-type activation of the agreement gate is runtime-tested together with Procurement. Cross-domain government-financial-61.log: 179 tests, 0 failures, 0 errors.
