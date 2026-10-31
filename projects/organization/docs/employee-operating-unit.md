# Employee access by organization unit — PARTIAL

## Upstream and target mapping

NSTDA selects OCA `operating-unit` commit `3c5f7c01727bd784f29da9b215de387228f7ee86`. `hr_operating_unit/models/hr_employee_base.py` adds a many-to-many list of operating units and a default operating unit. `security/security.xml` restricts `hr.employee` reads to the user's allowed units **or employees without a default unit**. `views/hr_employee_views.xml` exposes those fields. This code is AGPL-3 per source headers and manifest. The assembled NSTDA merge set was not reconstructed.

The optional Odoo 20 Community addon `erp_organization_hr_employee` depends on `erp_organization_hr`. It retains `organization_unit_id` on `hr.employee` as the primary unit and adds separate dated additional-organization assignment records. Employee-to-department unit consistency and automatic employee user assignments are not migrated. No upstream implementation was copied. User assignments remain separate from employee unit classification.

## Access and defaults

- Private `hr.employee`, `hr.employee.public` (used for ordinary-user fallback) and `hr.version` records linked to employees are restricted by overlap between the user's assigned active units and the employee's active primary or effective additional organizations. Organization Managers do not bypass employee organization restrictions and do not receive HR write rights. Unlike the upstream read-only employee rule, this addon applies the boundary to employee/version create, update and delete as well.
- Native HR company rules remain in force; a public employee company restriction is added for active companies. Destination units must be readable and active and match the employee company; an employee cannot be moved to an inactive company. HR version create/write validates a destination employee's read permission.
- **Only employees never organization-scoped remain visible under native Odoo access and active-company rules.** Previously scoped employees without an effective OU remain hidden. Existing employees are not automatically assigned. Unlinked `hr.version` records are likewise governed by native HR permissions and company rules.
- A new employee without an explicit unit receives the creator's active default only when the employee company is the current company. An explicit empty unit stays empty; another active company's record gets no automatic default. Archiving a unit stops its contribution; a different effective unit can still provide overlap. Managers remain subject to employee OU, active-company and native HR permissions.

## Operational risk and remaining boundaries

Before installation on an existing database, take and restore-test backups, review all employees and unit mappings, authorize and rehearse the data migration on an isolated copy, and assess access for users who lack assignments. This addon does **not** migrate production data or set units on existing employees. Since never-scoped employees remain visible, do not treat installation alone as protecting their records.

The tested boundary covers the three models above and selected ORM read/search, grouping and mutation paths. Other related models, HR reports, resource records, attachments, chatter, controllers, exports, external integrations and sudo code paths have **not** been comprehensively audited; do not claim HR-wide confidentiality. Department-unit consistency, user-facing bulk mapping, browser acceptance and uninstall remain pending. Employee multi-unit design and fail-closed history are described in `employee-multi-organization-design.md`. See `test-report.md`.

## Unassigned employee compatibility

The upstream rule permits employees whose unit is empty. Compatibility remains for employees with no organization history and is **not** a confidentiality guarantee: old employees are not auto-assigned. Previously scoped employees remain restricted even if no OU is effective. See `hr-access-surface-audit.md` for tested access paths and open risks.

## Production prerequisites

- Inventory employees with no unit, including archived employees, and plan reviewed legacy mappings without changing production automatically.
- Verify employee/unit/company consistency, user assignments, active companies and users requiring HR access.
- Review contacts, banks and resources shared with non-HR workflows; the new employee-linked restrictions may affect those workflows.
- Test representative HR and ordinary users, company switches, archived records, attachments, public links/tokens and applicable reports.
- Validate employee-related models, controllers and custom addons not covered by this audit; do not assume HR-wide confidentiality.
- Take a database and filestore backup, restore-test it, and rehearse the upgrade and reviewed mappings on an isolated copy with a rollback plan.
