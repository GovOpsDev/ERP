# Inventory dependencies

`erp_inventory` depends on native `purchase_stock` and `erp_finance`. Organization,
Budget, Procurement and HR committee visibility arrive through that dependency
chain. Work Acceptance consumes a confirmed scoped purchase order; Finance posts
native bills and reconciles Budget; Asset consumes the accepted bill provenance.
Stock requests use native `stock.rule`, stock moves, references and RFQs.

The selected source trees and full scope decisions are in [source parity](source-mapping.md).
The runtime contains Odoo 20's stock.move-based scrap implementation instead of
the old stock.scrap model. No core or upstream source was modified.

No acceptance, invoice installment, stock request or card creates an independent
Budget authorization. Fine charges and native stock valuation are explicitly
excluded from Budget as in the selected source adapters.
