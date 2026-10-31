# HR Department / Organization integration — PARTIAL

## Upstream evidence and mapping

NSTDA `repos.yaml` selects OCA operating-unit commit `3c5f7c01727bd784f29da9b215de387228f7ee86`. At that commit, `hr_operating_unit/models/hr_department.py` adds `operating_unit_id` to `hr.department` with the current user's default operating unit. `security/security.xml` restricts department reads to assigned units or departments without a unit, and separately restricts employee reads. `views/hr_department_views.xml` exposes the field in form, list and search. `__manifest__.py` depends on `hr` and `operating_unit`, and declares AGPL-3; source headers retain AGPL-3. This implementation is a new Odoo 20 bridge rather than a copy; full assembled NSTDA merge behavior has not been reconstructed.

`erp_organization_hr` depends only on `erp_organization` and Odoo 20 Community `hr`. It adds optional `organization_unit_id` to native `hr.department`, form and list views, and a department security restriction. No HR model or code is moved into `erp_core` or `erp_organization`. The existing native HR groups and company rules remain in force; Organization Manager alone does not grant HR write/create rights.

## Department rules

- A linked department must have the same company as its organization unit. A unit must be readable by the caller and active when linked. Company and parent changes validate the affected department hierarchy, including archived descendants. A target company must be active and a target parent readable.
- Internal/HR users see linked departments only for active units assigned to them within active companies. Organization Managers may see all units' departments within active companies, subject to native HR permissions. Unlike upstream's read-only rule, this bridge also restricts department write, create and delete to the same organization boundary. Target-unit and destination-company access are checked explicitly for mutations.
- Departments without an organization remain governed by native HR permissions and company rules; they are not restricted to assigned units. This matches the upstream unlinked-department concept. An archived unit hides its linked department from ordinary users; managers can still inspect it.
- If a department is created without an explicit organization, the creator's active default in the **current company** is selected only when that company matches the department's effective company. An explicitly empty organization remains empty. A department created in another active company has no automatic unit unless that company is current. A parent supplies the company when not explicitly specified.

## Installation and limitations

Installing the bridge leaves existing departments unlinked; they remain accessible under native HR permissions until explicitly mapped. Before rollout, review that behavior with data owners, verify unit assignments and HR rights, back up and restore-test database and filestore, and rehearse mapping/security with a copy. This does not migrate production data.

This bridge constrains only `hr.department`. The separate optional `erp_organization_hr_employee` addon scopes employee/private/public and linked versions; job, report, search, API and other model access may expose related HR information under existing Odoo permissions. Neither bridge is a complete HR confidentiality boundary. Browser UI, uninstall, production data mapping, role synchronization and cross-domain security remain untested or deferred. See `test-report.md`.
