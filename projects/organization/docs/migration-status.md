# Organization migration status: MIGRATED

The required runtime source scope is implemented. Production readiness remains NO.
This decision supersedes the preliminary partial descriptions in historical reports.

| Source scope | Decision | Target and evidence |
|---|---|---|
| operating_unit hierarchy/company/partner | MIGRATED / REDESIGNED | Company-scoped units and hierarchy; partner relation with reverse company guard. New units default to the existing company partner; explicit alternative must be shared or in the same company. Existing null partner rows remain unchanged for explicit historical mapping. |
| Allowed/default operating units | REDESIGNED | Explicit assignments and one optional default per user/company. No implicit grant or fabricated historic default. |
| Department/employee OU and multiple OUs | MIGRATED | Department bridge, primary employee unit and dated additional membership; private/public employee, version and tested related HR boundaries. |
| Role/group membership | REDESIGNED | Dated company/OU assignments, delegated administration and group provenance preserve independent direct grants. Role presets are configuration. |
| Read-only/restricted model update | MIGRATED / REDESIGNED | Source flags on roles and users; restrictions intersect native Odoo20 access domains. Read-only wins. Effective role grants remain scoped to active companies; all active companies require the unrestricted grant. User-level flags are explicit global administrator settings. |
| Source global-ACL technical exceptions | REDESIGNED | Explicit administrator-only model exception metadata replaces automatic inference from no-group ACLs: Odoo20 no-group `ir.access` records are restrictions, not the old global grants. Exceptions never supply missing ACL permissions or bypass record rules. |
| Search/access inspection presentation | ENHANCEMENT | Does not change authority or visibility. |
| Source employee/role/partner mapping; browser/load/filestore/production migration | PRODUCTION READINESS | Separate acceptance phase; no source data or production system was changed. |

Exact sources: operating-unit `c0a597931509`; selected HR/multiple-unit source in
existing source-analysis documents; server-backend
`995ad9e9ef32bc6b7ddddc7a01ddfc3235e8ad18` (`base_user_role_restrict_update`);
server-tools `c10024bc0cacabfc9a790055d2deb1304f13e886`
(`base_model_restrict_update`). Source onchange-only flag propagation becomes
server-side effective role policy, so API writes, expiry, revocation, and company
switching cannot retain an obsolete unrestricted grant. Direct user policy is not
destructively overwritten by role onchange.

Runtime evidence: `finance-organization-final-08.log`, isolated Odoo20 Community
20.0-20260926, **153 tests, 0 failures, 0 errors, 0 skips reported** across Finance,
Organization, HR, employee security and roles. Includes new partner/company checks,
CRUD denial, native `has_access` consistency, role expiry/OU revocation, active
multi-company grant boundaries, and denial of self/delegated escalation. Evidence
is in `/GovOpsDev/th-gov-erp/test-evidence/closure-20261031/`.
The final workspace clean-install/upgrade cross-domain gates follow closure of all
remaining domains. No production browser, source conversion or load acceptance is
claimed by these tests.
