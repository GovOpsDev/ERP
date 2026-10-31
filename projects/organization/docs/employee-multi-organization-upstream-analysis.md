# Employee multiple organizations: upstream analysis

NSTDA ERP-Government checkout `5a1722c4c6f6cfdf3ed59362a56e85777c58a383` selects OCA `operating-unit` base and merge inputs in `odoo/custom/src/repos.yaml`, including `3c5f7c01727bd784f29da9b215de387228f7ee86` for `hr_operating_unit`. The inspected files are from that exact commit; this is not a claim that every NSTDA merge input was reconstructed.

| Upstream behavior | Source | Required? | Odoo 20 design decision |
|---|---|---|---|
| Employee allowed operating units are M2M; separate default OU; both default from user | `hr_operating_unit/models/hr_employee_base.py` | Multiple workplaces and primary distinction | REDESIGN: authoritative existing primary field and dated additional assignment rows; no automatic user-access expansion. |
| OU has inverse employee M2M | `hr_operating_unit/models/hr_operating_unit.py` | Workplaces discoverable | REDESIGN: assignment records indexed by employee and unit. |
| Department has one defaulted OU | `hr_operating_unit/models/hr_department.py` | Department affiliation | MIGRATE already in `erp_organization_hr`; no automatic employee/department synchronization. |
| Employee read rule checks default OU, not the employee M2M; empty default is allowed | `hr_operating_unit/security/security.xml` | OU-aware employee read; unassigned compatibility | REDESIGN: employee/user effective OU overlap, including additional organizations. |
| Tree, form and search expose default and allowed OUs | `hr_operating_unit/views/hr_employee_views.xml` | Primary and additional visible to HR | REDESIGN: primary field and dated assignment list; extra search facets deferred. |
| HR extension depends on `hr` and `operating_unit` | `hr_operating_unit/__manifest__.py` | Community HR integration | MIGRATE concept using existing project dependencies. |
| Effective dates and assignment lifecycle | No employee OU assignment model or dates in those sources | Historical and temporary assignments | REDESIGN with inclusive dates and active status. |
| Employee membership to user-role or user OU synchronization | No such mechanism in inspected `hr_operating_unit/models` | Do not expand rights implicitly | DROP automatic cross-concept synchronization. |
| Company constraints on employee M2M | No explicit constraint in inspected employee model | Enforce employee and organization company | REDESIGN server validation. |

Actual `hr.employee` in Odoo 20 is company-owned; `hr.employee.public` is an SQL view with the same record IDs as private employees. Related models and controller paths require separate boundary checks; see `hr-access-surface-audit.md`. Upstream mapping data and business-domain rules are not migrated automatically.
