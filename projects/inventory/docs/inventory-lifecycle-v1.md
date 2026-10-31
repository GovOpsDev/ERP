# Inventory lifecycle v1 — DRAFT / PARTIAL

- VERIFIED UPSTREAM: confirmed PO → work acceptance → linked goods receipt and/or bill. Service acceptance does not require stock.
- VERIFIED UPSTREAM: acceptance and receipt are distinct. The source checks equality on a linked receipt or bill, with UI configuration controlling selection. It does not create budget moves. Return does not automatically reverse acceptance in the inspected module.
- VERIFIED ODOO 20: an accepted quantity of 4 can be associated with a native partial incoming receipt and backorder of 6; picked move-line quantities determine the receipt check. A native return can be created without copying the WA; the accepted document remains unchanged. Direct edits/deletion of quantities on a completed linked receipt are rejected; native completion/backorder remains available. Stock return valuation, billing and asset effects are not covered.
- REDESIGNED: current implementation requires an active OU and confirmed request-linked PO, positive quantities in PO units, and derives totals from accepted documents; PO scope locking rejects concurrent over-acceptance. Draft cancellation does not consume quantity; accepted cancellation and PO cancellation/reset after acceptance are blocked until reversal semantics exist.
- REDESIGNED: linked receipts and vendor bills require accepted WA, same company, PO line, product and compatible unit, exact linked quantities and no reuse on completed/posted documents. Unlinked receipts and bills retain their existing native behavior. The source's optional enforce/bypass groups and wizard are not implemented.
- NOT TESTED: all return and refund combinations, attachment access, production upgrade, full-scale concurrency, browser and Asset creation.
- DEFERRED: rejected quantity, committee, full enforcement configuration, reports, full metadata and Asset implementation.

This document remains draft. The addon is a partial subset, not a complete replacement for upstream.
