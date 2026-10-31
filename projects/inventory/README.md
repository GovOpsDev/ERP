# ERP Inventory

Odoo 20 Community migration of purchase Work Acceptance and selected stock-request
flows. Acceptance supports goods/services, partial quantities, government
committees, supplier evaluation, ordered reviews, invoice installments, late fines
and safe cancel/reset with retained evidence. Receipt enforcement remains
configurable; linked documents are always validated.

Native stock procurement handles requests, RFQs, transfers, backorders and returns.
Fund/analytic provenance survives fulfillment and valuation, while Budget remains
the sole spending authority. Kanban cards support replenishment and card census;
negative-stock policy follows the selected source configuration.

See [source parity](docs/source-mapping.md). Final clean-install, historical-upgrade
and cross-domain migration status is maintained by the workspace closure report.
Production data conversion, warehouses/routes, browser, filestore, load and deployment
remain separate readiness work.
