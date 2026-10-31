# Organization Contract v1

Frozen 2026-10-29 as the conceptual interoperability boundary for migration, based on Organization commit `d33af0458696ac27082d4b2505a00e15b35f69ff`. Freezing these semantics is not a claim of complete upstream feature parity or production readiness. Changes that would alter these semantics require a versioned contract and regression tests.

## Company and organizational scope

An `erp.organization.unit` belongs to one company and may have a same-company parent; its company is immutable. An `erp.organization.assignment` independently associates a user with a unit, whose company must be allowed for that user. A unit is usable only while active and its company is in the user's active companies. `default_unit_for_current_user()` returns the current company's active assigned default, if any. A default is a convenience, not a security grant.

A downstream model with an OU must validate its record company and target OU server-side. It must enforce its own company and OU record access, including direct reads and writes, imports, related records, reports and exposed controllers. Its authorization should require both the relevant business capability and appropriate active company/OU scope. Organization Manager does not implicitly obtain downstream business permissions. Any wider-scope exception must be explicit and independently authorized by the downstream module.

## Employee scope

`hr.employee.organization_unit_id` is the primary/home organization and provides the employee's default affiliation; changing it does not automatically add the former primary as an additional organization. Effective employee organizations comprise the active primary and active, date-effective additional assignments to active units. Assignment dates are inclusive and use the server-local date. Employee organization history is sticky: once scoped, no effective OU means hidden from scoped users; never-scoped employees retain standard Odoo compatibility. This policy does not automatically grant a linked user OU access.

Employee HR models and internal history/visibility helpers are implementation details of the optional HR bridge, not a required dependency for a business record whose own OU is known. Existing deleted history cannot be reconstructed from remaining data. Check the organization repository's employee design and security audit before relying on HR access surfaces.

## Roles and capability

`erp.user.role.assignment` identifies user, role, company, optional unit, active status and inclusive dates. OU-scoped assignments contribute only while the user retains the matching active organization assignment. Definitions and delegation are separately administered. `res.groups` grants are global to the user, not scoped by company or OU; each business module is responsible for record isolation. Role assignment and employee OU membership remain independent. Date transitions for role-group synchronization depend on the hourly scheduler and can be late if it is delayed.

## Explicit boundaries

This contract defines concepts and guarantees already implemented, not generic new Python methods or a promise that private model helpers are stable API. The caller must preserve company validation and native record access checks, avoid relying on client domains, avoid privilege-bypassing context flags, and verify any use of elevated access. The contract does not assert complete NSTDA parity, coverage of every HR surface, production migration readiness, browser behavior, concurrency or cross-application safety. See `employee-multi-organization-design.md`, `user-role-design.md`, `hr-access-surface-audit.md` and `test-report.md`.
