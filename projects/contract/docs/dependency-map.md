# Agreement and Contract dependencies

Organization effective company/OU and capabilities → Budget controls → Procurement PR/native PO → optional purchase Agreement. Source requisition `po_type` is not migrated; a PO agreement-required flag is the narrow replacement. Agreement confirmation requires an Agreement record but does not add a separate Budget commitment. PO-linked Finance bills continue through `erp_finance`.

Separately, OCA purchase Contract → contract line → Budget contract commitment → native account move line → actual/refund. `erp_contract` depends on `erp_finance`, which supplies Odoo Accounting, Purchase, Procurement, Budget and Organization dependencies. The Contract adapter calls Budget's private service; it does not directly write ledger rows. An invoice line with both PO and contract source is rejected. Independent documents may still represent the same spend and require business reconciliation; see source mapping.

Full upstream dependencies include Agreement legal stages/content, Purchase Requisition and invoice plan, Contract recurring generation and invoice plan, OU adapters, Budget allocation/activity and optional reporting/guarantee modules. These are not all implemented. Individual pinned commits are not a reconstructed merged checkout.
