# Organization source mapping — MIGRATED

| Selected source | Current Odoo 20 behavior | Decision |
|---|---|---|
| operating_unit c0a597931509: company, code/name, partner | Company-owned hierarchy, scoped partner, unique code/name and same-company parent checks | MIGRATED |
| operating_unit user/default unit and security | Explicit per-company user assignments/defaults; assigned-unit reads and active-company boundaries | REDESIGNED |
| hr_operating_unit 3c5f7c01727b: department unit | Native HR department relation, default selection, company/OU CRUD boundaries | MIGRATED |
| hr_operating_unit employee default/allowed units | Primary unit plus dated additional memberships; persistent scope history, no automatic user grants | REDESIGNED |
| HR visibility | Employee, public employee, version and selected HTTP/resource boundaries use effective membership; native HR ACLs still apply | REDESIGNED |
| base_user_role 0a493bf39e3e | Scoped role/group membership, provenance, expiry and delegated maintenance preserve direct grants | REDESIGNED |
| base_user_role_restrict_update 995ad9e9ef32 and base_model_restrict_update c10024bc0cac | Server-side effective update restrictions and explicit technical exceptions; no self/delegated escalation or stale grants after expiry/company switch | REDESIGNED |
| NSTDA role presets and employee/partner mappings | Deployment configuration and historical data conversion | PRODUCTION READINESS |
| Search facets and access-inspection presentation | Optional presentation improvements | ENHANCEMENT |
| Browser coverage, published/shared resources, filestore, load and production migration | Separate operational acceptance | PRODUCTION READINESS |

See [current status and evidence](migration-status.md) and the workspace closure
report for final all-domain clean/upgrade results. Earlier discovery documents
record historical implementation stages; they do not override this parity decision.
