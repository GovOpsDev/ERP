# Source mapping

No upstream implementation has been copied or ported. The `erp_core` manifest depends solely on Community `base`; its empty directories reserve future extension points and contain no modeled business behavior.

| Upstream source | Original behavior / evidence | Decision |
|---|---|---|
| `odoo/custom/src/private/egov_install/__manifest__.py` | Aggregates cross-domain dependencies including operating units and budget | Do not reproduce umbrella; separate domain modules and bridges. |
| `odoo/custom/src/private/egov_user_role/__manifest__.py` | Selects role and operating-unit access extensions | Investigate shared authorization; no inferred groups or rules implemented. |
| `odoo/custom/src/private/egov_config/__manifest__.py` and `data/` | Loads company, user, department, warehouse and other configuration | Do not copy tenant-specific configuration or records. |
| `odoo/custom/src/private/egov_coa/__manifest__.py` | Loads chart template data and post-init hook | Defer chart/accounting migration pending API and legal review. |

Every future port must add exact original file, behavior, decision, license, target and tests here before merge.


Organization-specific mapping lives in `projects/organization/docs/source-mapping.md`.
