# Finance Budget Lifecycle v1 — frozen for the tested subset

This contract is limited to approved PR-controlled POs, Odoo 20 Community vendor bills and linked vendor refunds. It is not complete OCA/NSTDA Finance parity or production readiness. See `test-report.md` for evidence and gaps.

## VERIFIED UPSTREAM

A draft bill has no actual; an eligible posted bill creates invoice-side actual. The purchase extension converts invoice quantity to PO UoM and uses PO unit price to reduce commitment; the invoice actual uses invoice price, quantity and discount. The OCA source checks existing PO `amount_commit` before processing a refund return. Tax, return-amount and forward-commitment options add cases not supported here. The 15.0 upstream test demonstrates PO 30 → bill actual 10 and PO 20 → bill cancellation PO 30, actual 0. Full refund ordering is derived from source, not directly established by an upstream refund test.

## VERIFIED ODOO 20

Controlled bill draft leaves the ledger unchanged. Posting 4 × 12 on PO 10 × 10 yields actual 48 and remaining PO 60; a second posted 6 × 10 yields actual 108 and PO 0. Native reset to draft reverses actual and restores the applicable target. Refund with an original posted bill is a signed negative actual; when a positive PO commitment exists at the refund's replay point, its quantity restores commitment, capped at the PO quantity. A full bill followed by a refund has zero PO commitment at that point and does not restore it. A partial bill of 4 followed by refund of 3 restores PO commitment from 60 to 90. These are the tested deterministic rules; refund order is replayed by line ID, and arbitrary legacy refund ordering is not claimed to match the merged upstream deployment.

Over-invoiced net quantity, over-refunded original amount/quantity, missing original bill, wrong dimensions and unsupported taxes/currency fail atomically. Re-running reconciliation preserves actuals. Unrelated bills and credit notes retain native accounting behavior. A linked PO cannot be reset or cancelled while a related bill remains posted. Source is checked after standard document permissions; controlled posting requires native Accounting permission plus access to the PR, PO, Budget and OU.

## REDESIGNED

The Finance adapter discovers all linked posted accounting lines, checks caller access including lines hidden by record rules, derives keys from the confirmed PO, and computes signed actuals separately from remaining commitment. Draft lines do not enter the computation: Odoo's `qty_invoiced` is not used. PO quantity conversion uses native UoM factor with a shared reference unit and Odoo Product Unit precision. Commitments and actuals are reconciled together through the private Budget service under sorted locks and version updates; immutable reversals retain document, accounting-line and PO-line provenance. PO/PR-only reconciliation owns only PR/PO move types and cannot reverse Finance actuals. Controlled posting goes through the Procurement guard's Finance hook, accounting posting and Budget reconciliation in one transaction; direct state writes do not bypass it.

## DEFERRED / NOT TESTED

Only a single matching 100% analytic combination, company currency, untaxed lines, non-discounted PO lines and positive invoice quantities/prices are supported. Taxed lines, foreign currency, split analytics, PO discounts, deposits, forward commitments, invoice/PO dimension changes and refunds not linked to an original posted controlled bill are rejected. Full production migration, historical posted bill backfill, browser workflow, filestore preservation and load/performance remain NOT TESTED. On Finance installation, any already posted controlled bill causes installation to fail; explicit reconciliation/migration and separate validation are required before production use. No automatic backfill is performed.
