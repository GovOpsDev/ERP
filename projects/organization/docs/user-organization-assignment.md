# User organization assignment — initial migration

## Source and decision

Reference: OCA `operating-unit` commit `c0a59793150959eddd02d149e45e9fa39f94173b`, `operating_unit/models/res_users.py`, `models/operating_unit.py`, `security/operating_unit_security.xml`, `view/res_users_view.xml` (LGPL-3). NSTDA selects that repository and additional merge commits in `odoo/custom/src/repos.yaml`. The OCA source stores assigned and default operating units on users, exposes assigned-only unit reads and allows managers all units. The initial Odoo 20 design retains those concepts in a separate `erp.organization.assignment` model. No source code was copied; other merge commits and full assembled NSTDA behavior are not claimed equivalent.

An assignment links an internal user and a company-owned organization. A user can have one default per company, enforced by a partial unique index, and only one assignment to a given unit. The user's company authorization must include the unit company at assignment creation/change. Organization managers can administer assignments and see all units **within their active companies**. Internal users can read their own assignments and assigned units in their active companies; they cannot change assignments. Managers cannot select a unit outside their active companies when creating or updating assignments. Access checks on target units run before mutation as Odoo record permissions alone do not protect the destination of a write.

`default_unit_for_current_user()` returns the current user's assigned, active default for the current active company or an empty recordset; it never accepts an arbitrary user ID. Archived units cannot be newly assigned or made default. If a default unit is archived, it is not returned; a manager must clear its default flag before setting another default in that company. Assignments whose company is removed from a user's allowed companies remain as dormant data and do not grant access. They become usable again if the company is reauthorized; administrators should review assignments when restoring company access. Deleting an organization cascades its assignments. User/company membership and active-company selection remain controlled by Odoo.

## Upgrade and operational implications

Existing `erp_organization` data is retained, but **unit read access changes** from all units in active companies to assigned units only for ordinary users. No implicit assignments or default are generated. Before upgrading an existing database, review and approve an organization-to-user mapping; take and restore-test backups, rehearse on a copy, and provision assignments through an authorized manager. There is no production data migration script. Earlier `erp_base_organization` databases have the additional technical module rename issue documented in `module-rename.md`.

## Remaining boundaries

Assignments alone do not restrict purchase, budget, HR, accounting, inventory or other business records. The optional `erp_organization_hr` bridge restricts HR departments; the separate optional employee bridge adds restrictions to employee, public employee and linked version records. No external OCA role/group synchronization, reporting, automatic assignment, bulk import or production migration is implemented. This is not full NSTDA operating-unit parity. Browser and uninstall acceptance remain untested.
