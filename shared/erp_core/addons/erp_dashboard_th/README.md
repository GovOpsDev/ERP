# Thai warehouse dashboard

Thai display labels for the standard Odoo warehouse metrics dashboard. KPI,
Lot/Serial, company and location names, product names and technical identifiers
are preserved. English users receive the original response unchanged.

The standard snapshot is localized only when it is read in `th_TH`. No spreadsheet,
stock, valuation, formula calculation, company scope or access rule is saved or
changed. Only chart labels, static cell headings and the quoted presentation
literals `No data` and ` out of ` are translated in the response. Other dashboards
are untouched. Sample dashboard responses follow the same behavior.

Install `erp_dashboard_th` in the existing ERP addon paths and select Thai in user
preferences. AGPL-3.0; GovOpsDev. This module extends Odoo Community source and
preserves its standard dashboard and access controls.
