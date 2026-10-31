# Agreement and Contract Lifecycle v1 — frozen for the tested subset

This document covers a narrow Odoo 20 purchase subset, not complete OCA/NSTDA migration or production readiness. Changes to this subset require regression tests.

## VERIFIED UPSTREAM

OCA Agreement Legal stores `draft`, `active`, `inactive` separately from configurable stages, has version/revision history and a review cron. Thai government purchase agreement links each agreement to one draft/sent RFQ; multiple agreements can link one PO, partner must match, and agreement-type PO confirmation requires a linked agreement. The corresponding Budget extension marks the PO Budget move for agreement reporting, rather than creating an independent agreement commitment. OCA Contract is a separate recurring model; its Budget extension commits qualifying active purchase-journal contract lines and uses posted invoice/refund quantities to uncommit/return, subject to existing commitment and other hooks.

## VERIFIED ODOO 20

Agreement and its PO must share company, vendor and assigned active OU. Required agreement is checked on both PO confirm and approve; unmarked POs retain native behavior. Agreement version captures the prior name, dates, signature, PO untaxed amount and currency, then returns to draft; changing PO amounts while an agreement is active is blocked until a new version. Activation requires a signed and currently effective draft; termination makes it inactive without cancelling the PO or mutating Budget. Expiry is a computed indicator and no notification is sent.

A separate purchase Contract can enable Budget commitment for eligible lines, creating `contract_commitment` events. Posting a linked native vendor bill creates actual from invoice subtotal and reduces contract commitment by converted invoice quantity × contract price. A linked refund creates a signed negative actual; commitment restoration requires positive remaining commitment at replay point. Closing commitment reverses only commitment while preserving actual; native reset to draft reconciles actual. Posted lines are protected from direct state/source mutation. One invoice line cannot link both purchase and contract sources. Ledger family keys differ from PR/PO keys.

## REDESIGNED

Contract lines are immutable after they have Budget history; creating a new contract is required for a value amendment. Agreement version snapshots preserve the tested fields rather than all upstream legal content. The PO flag substitutes for missing requisition support. Agreement and Contract manager capabilities are separate from Organization manager; standard Accounting access, Budget access and assigned OU are still required for posting. Unrelated vendors and bills retain native rules.

## DEFERRED / NOT TESTED

Full agreement stages, clauses, legal reports, document attachments, notification cron, requisition/PO type, invoice plans, Contract recurrence/line-state automation, guarantees/deposits, Contract value amendments with full history, inter-document duplicate obligation detection, legacy migration, production data, browser, performance and filestore preservation remain NOT TESTED or unsupported. Contract bill date is checked against the Budget period but not independently against contract line end date. Controlled tax, foreign currency, split analytics, nonmatching account and unsupported refund sources fail closed.
