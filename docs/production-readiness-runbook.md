# Odoo 20 release operations

This runbook applies to the isolated reference deployment, not an existing production
service. The project originated as source code; no legacy production database was
supplied. Use a clean installation for greenfield deployment. Historical rehearsal
uses explicitly synthetic Odoo 20 target-schema history. Importing a future external
legacy dataset requires its own mapping and reconciliation acceptance.

## Reproduce the reference runtime

This publication contains the shared foundation and seven domain trees in one
repository. Use the published repository revision as the source identity. The
nine original repository identities and included working-tree changes are recorded
in `docs/source-snapshot.json`; `release-manifest.md` remains the historical release
reference. Addons are mounted read-only from the directories in this checkout,
without submodules. Preserve Odoo core and upstream notices. All three runtime
images are pinned in `ops/readiness/compose.yaml`.

From the workspace root:

```bash
python3 ops/readiness/stack.py --secrets-dir /tmp/erp-readiness-20261031/secrets -- up -d db
python3 ops/readiness/stack.py --secrets-dir /tmp/erp-readiness-20261031/secrets -- run --rm -T app -d erp_readiness -i erp_asset,erp_contract,erp_finance,erp_procurement,erp_budget,erp_inventory,erp_organization_hr_employee,erp_organization_hr,erp_organization,erp_user_role,erp_core --stop-after-init --workers=0 --no-http
python3 ops/readiness/stack.py --secrets-dir /tmp/erp-readiness-20261031/secrets -- up -d app proxy
```

The launcher creates initial credentials only in the external directory. If the DB volume already exists, missing secret files cause a refusal instead of silently generating replacement credentials. Retain
that directory securely with restoration configuration; never put it in Git or a
shared evidence archive. For a deployed host, replace `/tmp` with durable protected
secret storage and arrange off-host encrypted backup custody. Do not print the
runtime config: it contains credentials. Its permissions are 0600.

Reference configuration: Odoo 20.0-20260926 Community, PostgreSQL 16.15, two HTTP
workers, 32 DB connections per process, 4 GiB app / 2 GiB DB container limits,
explicit `10.251.44.0/24` bridge, localhost proxy port 18069; internal HTTP 8069 / websocket 8072. Select a
non-conflicting permitted 10.x subnet on another host. HTTP binds only localhost;
Caddy 2.11.4 routes `/websocket` to the evented worker and Odoo trusts only the internal proxy path; this reference does not expose an unauthenticated database manager. A public
installation must provide its normal TLS reverse proxy and retain the trusted
proxy boundary. Internet-facing exposure was not part of this local acceptance.

`ERP_DATABASE` selects an isolated `erp_*` database; `ERP_WORKERS` and
`ERP_CRON_THREADS` select runtime workers. Defaults keep cron disabled during
rehearsal. One-shot `run` commands disable HTTP health polling automatically.
The app volume is explicitly named and preserved. Never run `down -v`.

Browser dependencies are pinned by `package-lock.json`:

```bash
npm ci --ignore-scripts --prefix ops/readiness
ops/readiness/node_modules/.bin/playwright install chromium
```

The production server does not require Playwright or Node. Python dependency and
OS inventories are in the external release evidence. The upstream image emits an
optional markdown2 warning; Markdown rendering in mail is not a release dependency.
No Enterprise modules are installed.

## Backup, deploy and restore

Stop all application and one-shot writers before a DB + filestore backup. The
helper rejects running designated writers and rejects DB lifecycle changes during
collection. It validates archive structure and hashes before publishing a manifest.
Keep failed `.partial` files separate; they are not accepted backups.

```bash
python3 ops/readiness/stack.py --secrets-dir /tmp/erp-readiness-20261031/secrets -- stop app
python3 ops/readiness/backup_restore.py backup --database erp_readiness --archive /absolute/external/new-backup-directory
python3 ops/readiness/backup_restore.py restore --database erp_restored_release --archive /absolute/external/new-backup-directory
```

Restoration always creates a fresh database and refuses to overwrite an existing
one. It restores the matching filestore under the **target database name**, with
Odoo ownership. A PostgreSQL rename alone does not move a filestore. SHA-256
manifests must verify before restore. Keep configuration/repository revisions and
image digests with the backup record; secrets are recovered separately.

Before enabling traffic, run the explicit eleven-module upgrade with `-u`, then
read-only `reconcile.py` and `inspect_shell.py`, start the selected database, verify
login and authorized/denied attachment downloads, and run critical UI smoke tests.
Compare economic aggregates exactly; classify metadata/configuration changes.
Never infer missing OU/reviewer/financial history. The exact-file recovery helper
is solely for preserved synthetic fixtures: it copies only absent files whose
size and SHA-1 match DB metadata, recording provenance. It is not a generic repair
for an unknown production filestore.

Activate only inventoried jobs with appropriate company/OU service accounts.
The rehearsal enables scoped Contract recurrence/review/renewal and depreciation
jobs plus the designed administrator role-expiry job. Confirm scheduler `lastcall`,
`failure_count`, and the expected records; a manual method call alone is not the
activation gate. Outbound email and unrelated maintenance jobs remain disabled
on isolated copies. Configure organization mail delivery before using notifications
in a real deployment; no external mail was sent in this run.

## Rollback

Record the exact pre-deployment source revisions, pinned images, and verified DB +
filestore pair. On a failed health/reconciliation/smoke gate: stop the target, retain
its DB/files for diagnosis, restore the pre-deployment pair into a fresh database,
select the prior source revisions in the canonical repositories, start that DB,
and verify all seven domains, financial fingerprints and attachment bytes. Do not
run new code's upgrade against the restored prior baseline. Do not combine an old
DB with a new filestore. Subsequent writes after the backup require explicit
business reconciliation; automatic replay is not claimed.

The executed rollback evidence is referenced by the readiness matrix. Baseline
tags are local only. Return each repo to `master` after the isolated rehearsal;
never discard dirty changes or rewrite migration history.

## Operations and contention

`health.py` is read-only and emits JSON plus exit 0/2. Check HTTP, PostgreSQL,
connection use (<80%), available disk (default >=5 GiB), backup age (<=24 h), archive
size/hash, active cron failures, Budget source/control consistency and negative capacity (excluding designed shared advance-KPI controls), posted GL
balance, recent tracebacks/retry exhaustion, and filestore bytes. Schedule it with
the host's existing monitoring runner and retain its JSON/exit code. Alert on exit
2; do not treat HTTP 200 alone as health. Application logs and cron failure state
remain necessary to investigate rejected postings and scheduler errors.

```bash
python3 ops/readiness/health.py --database erp_readiness --backup /absolute/verified-backup --output /absolute/external/health.json
```

A missing DB/HTTP endpoint, stale/incomplete/corrupt backup, low disk, active cron
failure, unbalanced posted entry, orphan Budget linkage, or recent traceback needs
operator attention. Queue jobs are not installed; queue monitoring is not applicable.
Keep disk/filestore trends and successful backup timestamps in the host monitor.

Native Odoo HTTP transaction handling retries serialization conflicts at most five
times with rollback/reset and backoff. Eight simultaneous approvals in one Budget
period can exhaust that bound, even for different parents, because the period lock
protects consistent economic capacity. The transaction stays uncommitted; refresh
and explicitly resubmit the failed action after contention falls. Verify document
state before resubmission. Do not retry an uncertain successful response blindly.
Separate periods progressed without this exhaustion in the measured run. The
implementation does not swallow serialization errors or weaken financial locks.

Same-Asset duplicate creation is safely rejected as already linked; it is not an
idempotent successful response. All eight-domain concurrency scenarios verified
no overspend, duplicate active ledger or duplicate acquisition. Measurements are
capacity evidence for this reference host/dataset, not an unmeasured SLA for a
larger workforce or different host. Higher peak loads require additional sizing.

## Audit and access

Maintain explicit OU assignments and scoped role delegation. Finance read-only
source dependencies do not confer Contract, WA or Asset lifecycle management.
Global company/OU restrictions also cover native accounting, attachments,
payments and reconciliation records. Asset recompute triggers are completed only
for a fully visible company scope. Keep the role reconciliation job enabled under
its designed administrator identity. Privileged-call inventory and negative HTTP
security tests are in the release evidence; they are not an independent pentest.

Economic workflows preserve source keys, reviewer/decider timestamps, posting
state, immutable revision/transfer history and audit chatter where defined by the
model. No fabricated historical reviewers, allocations or old acquisitions were
introduced. Synthetic failed-attempt fixtures are retained and clearly identified.

## Completed reference release recovery

The final populated pair is `release-final-backup` in the external evidence root.
It includes the browser transactions and executed scheduler history. It restored
into `erp_restored_final_verified`; 341 selected tables/original columns matched
exactly before startup, and all 71 binary attachment metadata/content hashes,
database UUID and domain counts matched. Final read-only UI/security/file/WebSocket
smoke is recorded separately from the complete 25-case transaction suite.

A verified recovery copy of the synthetic test credentials is retained separately
at `/home/patrixr/GovOpsDev/th-gov-erp/.readiness-secrets-20261031` (directory 0700,
files 0400), outside Git and the evidence/backup archives. The live rehearsal used
`/tmp/erp-readiness-20261031/secrets`; if it is lost, recreate that directory as 0700,
copy these three files there, and make the individual runtime files 0444 for the
read-only Compose mounts. Do not print or commit them. This is local reference
recovery custody, not an off-host production backup service.

To resume the preserved final database without scheduled writes:

```bash
ERP_DATABASE=erp_restored_final_verified ERP_CRON_THREADS=0 python3 ops/readiness/stack.py --secrets-dir /tmp/erp-readiness-20261031/secrets -- up -d db app proxy
python3 ops/readiness/wait_http.py
```

The five activated jobs were already observed running successfully with one cron
worker on `erp_restored_acceptance` before the final backup. Their active flags and
history survive restore; the final read-only smoke disables the worker intentionally.
Set `ERP_CRON_THREADS=1` and recreate the app only when scheduled writes are intended.
The test stack is stopped after acceptance to conserve memory; all databases,
volumes and the dedicated network are retained. No unrelated service is stopped.
