# Release candidate manifest

Candidate: **th-gov-erp-odoo20-v1.0.0-rc1**. Local tags only; no pushes.
All application repositories must be deployed at these revisions together. The
workspace operations/documentation revision is the final local candidate tag target;
its exact SHA is recorded outside Git in `release-state.json` to avoid self-reference.

| Repository | Canonical relative path | SHA |
|---|---|---|
| organization | `projects/organization` | `2de3b25e5e867f2120315c285646a68826790640` |
| budget | `projects/budget` | `ba8a93681f3a417b3cf8e69f8cd4034b7e5b9c44` |
| procurement | `projects/procurement` | `92113d3070e99b549e96bf289c292ecda890ae7a` |
| finance | `projects/finance` | `962330f4917872443e20645b27aa3b920f5debb7` |
| contract | `projects/contract` | `35c1d308b8df6d7e09a58e72186544ff1379df3d` |
| inventory | `projects/inventory` | `b20a35bf9609c05693b3abc74ec06ae4f5fcbb4f` |
| asset | `projects/asset` | `5a0e8993af19de7a75dd99a5493db178af2b68d3` |
| core | `shared/erp_core` | `c9e82538ec3dae13ff7329a689bfe91f6e8c7d58` |

The frozen migration baseline remains `migration-odoo20-v1` in all nine repositories.
Readiness changes are independent local commits; no history was rewritten.

## Runtime identity

- Odoo 20.0-20260926 Community, Ubuntu 24.04.5 base; no Enterprise modules.
- PostgreSQL 16.15 reference target; other major versions are not claimed tested.
- Caddy 2.11.4 for localhost HTTP and evented WebSocket routing.
- Two HTTP workers; one cron thread only for explicitly activated scoped jobs.
- Canonical addon mounts; no copied application sources, no custom image build required.
- Python/OS dependency inventory: `runtime-packages.txt` in external evidence.
- Playwright 1.63.0 and Chromium revision 1243; exact npm dependencies in the lockfile.

Images:

- `odoo@sha256:dc76c42d292af9c513de826620e5a5dbe8152383ce8767eb6ed1390a806eb32f`
- `postgres@sha256:cf78e76683b9ca8c5733cbbdce6c9262b45b6767934dd0a95e671f9a0fc20685`
- `caddy@sha256:de23def33b17fb5d1290b0f6c2add1d70780e52341896c00a4c8a2a2fe9d355e`

## Addon versions

| Addon | Version | License |
|---|---|---|
| `erp_core` | 20.0.1.0.0 | AGPL-3 |
| `erp_organization` | 20.0.2.1.0 | AGPL-3 |
| `erp_organization_hr` | 20.0.1.0.0 | AGPL-3 |
| `erp_organization_hr_employee` | 20.0.2.0.0 | AGPL-3 |
| `erp_user_role` | 20.0.1.1.0 | AGPL-3 |
| `erp_budget` | 20.0.2.27.0 | AGPL-3 |
| `erp_procurement` | 20.0.1.8.0 | AGPL-3 |
| `erp_finance` | 20.0.1.13.0 | AGPL-3 |
| `erp_inventory` | 20.0.1.3.0 | AGPL-3 |
| `erp_contract` | 20.0.1.10.0 | AGPL-3 |
| `account_asset_management` | 20.0.1.0.3 | AGPL-3 |
| `account_asset_transfer` | 20.0.1.0.1 | AGPL-3 |
| `erp_asset` | 20.0.1.3.0 | AGPL-3 |
| `report_xlsx` | 20.0.1.0.2 | AGPL-3 |
| `report_xlsx_helper` | 20.0.1.0.0 | AGPL-3 |

Configuration is versioned in `ops/readiness/compose.yaml`, `Caddyfile` and
`entrypoint.py`. Secrets are external, and neither DB/filestore data nor credentials
are release source artifacts. Browser/backup/reconciliation/deployment helpers are
under `ops/readiness`; evidence is outside every source repository.

Acceptance: `production-readiness.md`, `production-readiness-reconciliation.md`,
`production-readiness-performance.md`, `production-readiness-uat.md`, and
`production-readiness-runbook.md`. Final machine-readable counts, source/runtime
identities and artifact checksums are recorded in the external release evidence.

Boundary: source-only/greenfield release and representative synthetic historical
target-schema upgrade. No claim of converting an unavailable production DB, public
TLS-host deployment, organization-specific mail delivery, or an unmeasured peak SLA.
Those environment-specific settings must follow the runbook before actual exposure.
