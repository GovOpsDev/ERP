# NSTDA eGov user manuals

Documentation-only Odoo 20 Community addon. It adds a Thai **คู่มือการใช้งาน**
menu to each of the 15 applications in the integrated reference stack. Each menu
uses the normal `ir.actions.act_url` mechanism with `target=new`; a reader can keep
an unfinished business form open while reading the guide. There are no business
models, controllers, ACL overrides, scheduled jobs, or external web dependencies.

Open `/erp_user_manual/static/manual/index.html` for the guide directory. The 15
application guides provide Thai instructions, workflow diagrams, related guides,
local text search, responsive navigation and browser printing. Ten screenshots
come from the isolated synthetic test database, not from production records or
the user's active browser. `assets/screenshots.json` records image checksums and
provenance. Generic instructions and synthetic screenshots are static content;
they contain no credentials, session tokens or personal source-data exports.

This addon is a documentation bundle for the existing integrated ERP stack.
Its dependencies deliberately include the installed applications whose menus it
extends; it does not make these applications dependencies of `erp_core` itself.
Parent-menu visibility and ordinary internal-user/business groups govern menu
visibility. A static guide grants no access to referenced business records.

## Source and maintenance

The HTML pages are the editable sources. Update the appropriate page when a
workflow or label changes, keep related links relative, and update `guides.json`
and `views/manual_menus.xml` together when adding a guide. There is no hardcoded
numeric Odoo action ID or database name in the shipped manual pages. Screenshots
use sample values; their captions explicitly say they are illustrations.

Source anchors for the documented behavior:

| Guide | Existing source reviewed |
|---|---|
| organization / employees | `erp_organization`, `erp_user_role`, `erp_organization_hr`, `erp_organization_hr_employee` views and company/OU access behavior |
| budget | `erp_budget/views/*`, Budget lifecycle/source documentation |
| procurement / purchase | `erp_procurement/views/*`, native Purchase form, PR/PO tier and requisition integration |
| finance / expenses | `erp_finance/views/*`, native Accounting/Expense UI, advance/retention/source integrations |
| agreements / guarantees | `erp_contract/views/*`, legal snapshot/review and guarantee workflows |
| acceptance / stock_requests / warehouse | `erp_inventory/views/*`, native stock receipts/returns and provenance integration |
| assets | `erp_asset/views/*`, connected OCA depreciation/AUC engine behavior |
| chat / dashboards | installed native Discuss/Dashboard menu trees and read-only workflow |

The content distinguishes recording a review from activation, a draft from a
posted accounting move, and a planning amount from available budget. Currency
instructions do not relabel USD as THB. Screenshots and instructions are not tax
rates, statutory forms, evidence of production deployment readiness, or approval
to bypass roles and organizational scope.

## Checks

From the workspace root:

```bash
python3 ops/readiness/check_user_manual.py
node ops/readiness/manual_browser.cjs --base-url http://127.0.0.1:18070 --login TEST_LOGIN --password-file /path/to/protected/password --evidence-dir /path/outside/git
```

The browser check authenticates independently, clicks all 15 actual menu items,
verifies new-tab actions, opens all 16 HTML pages, checks images and search,
checks representative mobile/print layouts, and fails on browser runtime errors.
It does not approve, edit or post business records. Login credentials are read
from a protected file and are never included in retained traces or output.

## Currency FAQ (20.0.1.1.0)

All 15 application guides and the directory include a Thai currency FAQ with
company setup steps, the accounting-history lock, a separate THB trial company,
document-currency changes, multi-currency permissions and rates, dashboard
context, and the distinction between currency conversion and display symbols.
Each guide explains its own currency source, including applications with no
independent currency field. The FAQ is static HTML, searchable in the existing
page search and included when printing; it adds no business data or privileges.

The procedures were checked against the installed native company, accounting,
purchase and expense sources plus the ERP request, budget, contract, inventory
and asset currency fields. Menu URLs carry a new content revision to refresh
previously cached manual pages.
