# Thai warehouse dashboard

Thai display labels for the standard Odoo warehouse metrics dashboard. KPI,
Lot/Serial, company and location names, product names and technical identifiers
are preserved. English users receive the original response unchanged.

The standard snapshot is localized only when it is read in `th_TH`. No spreadsheet,
stock, valuation, formula calculation, access rule is saved or
changed. Only chart labels, static cell headings and the quoted presentation
literals `No data` and ` out of ` are translated in the response. Other dashboard labels
are untouched. Sample dashboard responses follow the same behavior.

Install `erp_dashboard_th` in the existing ERP addon paths and select Thai in user
preferences. AGPL-3.0; GovOpsDev. This module extends Odoo Community source and
preserves its standard dashboard and access controls.

## Currency of the selected company

The dashboard HTTP response uses the same selected-company cookie as the Odoo
web client. This fixes invoice scorecards using the user’s default-company
currency while graphs use the currently selected company. The standard currency
formatter handles THB, USD and other currencies; no symbols, formulas, amounts
or currency records are rewritten. All selected company IDs are checked against
the user’s allowed companies. Without a company cookie, the normal user default
applies. Native sample dashboards retain their sample data and formatting.
