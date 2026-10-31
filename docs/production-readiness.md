# Production readiness — closed

**MIGRATION COMPLETE — PRODUCTION READY = YES** for the tested source-only,
greenfield/reference deployment scope. Release candidate:
**th-gov-erp-odoo20-v1.0.0-rc1**, local tags only, no pushes.

The user confirmed that migration began from source code; no original production
DB/filestore existed in this project. Acceptance therefore covers clean installation
and upgrade/restore of representative synthetic Odoo 20 history. It does not claim
conversion of an unavailable legacy production database, deployment to a public
production host, business-owner signoff, Thai tax/print-form certification or an
unmeasured workforce SLA. No live production system was accessed.

Evidence root: `/GovOpsDev/th-gov-erp/test-evidence/production-readiness-20261031/`.
Machine-readable final results: `validation-summary.json`; exact final Git/runtime
state and artifact checksums: `release-state.json` and `release-evidence-sha256.json`.

## Readiness gates

All fifteen critical gates pass within that explicit scope. No unresolved financial,
security, restore or rollback defect remains. Each artifact below is under the
external evidence root unless it is a repository document/script.

| Gate | Status | Evidence | Blocking issue |
|---|---|---|---|
| 1. Reproducible environment | PASS | Pinned Odoo20.0-20260926, PostgreSQL16.15 and Caddy2.11.4; canonical read-only addons; clean install; explicit 10.251.44.0/24; compose.yaml and release-runtime.json | None |
| 2. DB + filestore restore | PASS | release-final-backup restored into fresh erp_restored_final_verified; UUID/counts and 71 attachment contents verified | None |
| 3. Data migration rehearsal | PASS | Representative synthetic target-schema historical upgrade: final-upgrade-02.log, 380 tests; no production source conversion claimed | None |
| 4. Reconciliation / data quality | PASS | 238 historical tables/original columns, exact economic aggregates; 341 restored tables; classified post-UAT changes; reconciliation-acceptance.json | None |
| 5. Browser / visual UAT | PASS | browser-final-restored: 25/25; real role transitions and eight lifecycle flows; visual checklist in production-readiness-uat.md | None |
| 6. Security | PASS | Five dedicated browser security cases within 25; full ACL/source/company/OU regressions; 299 privileged calls classified, zero unexplained | None |
| 7. Performance / concurrency | PASS | performance.json, domain-concurrency.json: 1,000 employees, eight concurrent workers, eight domain races; retry/throughput limits explicitly documented | None within measured reference scope |
| 8. Scheduled jobs | PASS | cron.json repeated execution/date boundaries/failure recovery; deployed-cron-result.json: all five actual scheduled jobs ran, failure_count=0 | None |
| 9. Backup / restore | PASS | Final verified DB/filestore archive; fresh restore and 16/16 smoke; corrupt archive rejected before DB creation | None |
| 10. Deployment rehearsal | PASS | Fresh stack, installed/upgraded/restored application, proxy/WebSocket, actual scheduler activation, final 16-case smoke and ten healthy checks | None |
| 11. Rollback | PASS | Actual app outage detected; prior DB/files/source tags restored; rollback-restored.json: 341 unchanged tables/zero financial differences; seven domains/files/WebSocket passed | None |
| 12. Monitoring / operations | PASS | release-final-health.json: ten checks, no alerts; actual outage/cron failure and DB/backup/disk/corruption alert probes; runbook | None |
| 13. Release artifact | PASS | release-manifest.md, nine local candidate tags, pinned image/dependency identities, release-state.json; no secret/data artifacts in Git | None |
| 14. Final full-stack regression | PASS | Clean382, historical380, restored380, browser25, final archive smoke16; zero failures/errors/reported test skips | None |
| 15. Go-Live readiness decision | PASS | All preceding gates accepted for the reference/greenfield release; environment-specific public deployment is not represented as performed | None within stated scope |

## Final validation

| Suite | Tests | Failures | Errors | Reported skips |
|---|---:|---:|---:|---:|
| Clean install | 382 | 0 | 0 | 0 |
| Historical upgrade | 380 | 0 | 0 | 0 |
| Populated restored DB | 380 | 0 | 0 | 0 |
| Combined browser | 25 | 0 | 0 | 0 |
| Dedicated browser security (included in 25) | 5 | 0 | 0 | 0 |
| Final archive restore smoke | 16 | 0 | 0 | 0 |

Browser retries: zero. Flaky cases: zero. Passing trace archives: zero. Earlier
failed attempts are preserved and explicitly superseded by these final runs.
The optional missing-addon-directory log warning is not a skipped test.

The full financial path is Budget → PR → requisition → PO → WA → posted bill →
Budget actual → validated Asset, under separate requester/reviewer/domain roles.
Additional cases cover plan/allocation/release, bill refund and Contract capacity,
Agreement version/termination, expense/advance posting, stock return, depreciation,
posted disposal and AUC transfer. Revision/carry-forward and source invariants
remain in the full module suites.

Historical financial aggregates (controls, net ledger, posted GL, acquisitions,
engine depreciation/residual value) match exactly. Post-browser additions are
identified by source IDs; original economic history was not overwritten. No
unexplained rounding delta or guessed OU/reviewer/allocation backfill is accepted.
Detailed boundaries and backup hashes are in production-readiness-reconciliation.md.

## Performance and operating boundary

Serial p95 PR approval 0.224 s, PO 0.221 s, bill posting 0.343 s, Asset creation
0.026 s; batched 80-control availability 0.100 s/five queries. These are measured
business transactions, not an HTTP-load SLA. Eight same-period requests can exhaust
native five-attempt serialization retries; failed transactions remain uncommitted,
and explicit refresh/state-check/resubmission succeeds after contention. No budget
overspend, duplicate active ledger, duplicate acquisition or corrupted state was
observed. Different-period approvals all committed in the measured burst. See the
performance document for all outcomes, including initial conflicts.

## Git, runtime and retained data

Nine independent repositories remain on master, clean, with the migration baseline
preserved as migration-odoo20-v1 and this release as local candidate tags. Application
SHAs are in release-manifest.md; release-state.json includes exact root and all
application SHAs, paths and commit subjects. Nothing was pushed or rewritten.

The dedicated app/proxy/DB stack is stopped after successful final health acceptance
to conserve RAM. The source finance DB was only started for backup and stopped again.
All databases, both readiness volumes, original source volumes and the dedicated
network are preserved. Unrelated Leaves services were not stopped or modified.
Recovery commands and protected external credential custody are in the runbook.

## Non-blocking follow-up options

- Capacity sizing for a larger workforce or stricter first-response SLA than the
  measured reference load.
- Organization-specific Thai chart/tax/printed-form certification and additional
  presentation/localization, if selected for a deployment.
- Host-specific TLS, mail delivery, off-host encrypted custody and integration into
  the organization's existing monitoring runner before that host is exposed.

These are scoped deployment choices or enhancements, not claims that public
production rollout or business-owner approval occurred during this engineering run.

## Defects and corrections


- PRODUCTION READINESS FIX: dedicated WA users could not read PR committee source.
  Inventory now grants read-only source access under existing company/OU rules;
  it does not grant Procurement write access.
- PRODUCTION READINESS FIX: dedicated accountants could not read Asset profile or
  linked WA provenance. Read-only dependencies now preserve scope and deny WA/Asset
  management. Focused combined suite: 2 tests, zero failures/errors.
- OPERATIONS FIX: a restore-created volume had root-owned top directories. The
  restore procedure now sets Odoo ownership for the data/filestore roots, without
  modifying preserved source volumes.
- Fixture configuration: synthetic company enrichment is explicitly disabled to
  avoid native external IAP calls; automatic OCA account profiles are cleared in
  favor of the explicit acquisition/depreciation handoff required by existing policy.

- SECURITY FIX: source OU restrictions now propagate to native PO/Contract bills,
  journal lines, payments and reconciliations. Native attachment access therefore
  enforces the same boundary. Browser other-OU download regression now passes.
- SECURITY FIX: Asset depreciation/transfer journal lines retain source OU scope.
  The ERP override avoids the vendored helper completing recompute triggers from
  unrelated companies and retains incomplete company scopes for later processing.
- Fixture correction: Odoo20 ignores legacy attachment `datas`; representative
  files now use `BinaryBytes` through `raw`, with byte length and SHA-256 checked
  both in the filestore and over authenticated HTTP. Earlier empty-file inspection
  was insufficient and is superseded by inspection-03 and browser-02.
- Fixture correction: account codes are company-dependent in Odoo20. Additional
  expense setup now resolves codes under the synthetic company, not root company.
- OPERATIONS FIX: one-shot shell/test containers disable service health polling;
  polling during registry shutdown previously generated irrelevant teardown errors.

- PRODUCTION READINESS FIX: dedicated Finance users now read scoped Contract/line/invoice-plan/cycle sources and see the optional source field, without Contract write/lifecycle rights. Dedicated-role regression and bill/refund browser flow pass.
- Readiness fixes committed independently: Finance `962330f`, Contract `35c1d30`, Inventory `b20a35b`, Asset `0b88847`. No pushes.

- OPERATIONS FIX: multiworker WebSocket traffic originally reached HTTP workers and raised tracebacks. Pinned Caddy now routes `/websocket` to 8072, with only localhost proxy exposure; authenticated handshake and ten healthy checks pass.
- PRODUCTION READINESS FIX: Asset profile duplication no longer copies internal lock state (`copy=False`); configuration-role regression passed, commit `5a0e899`. Final clean/historical/restored suites include this change.
