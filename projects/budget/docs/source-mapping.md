# Budget source mapping — MIGRATED

The authoritative current feature-by-feature mapping is
[budget-parity-matrix.md](budget-parity-matrix.md). It supersedes the earlier
foundation-only mapping retained in Git history. Required Budget source migration
is closed; no core row remains PARTIAL, DEFERRED or UNKNOWN.

Exact source references, target models, tests and decisions cover allocation
add/remove/replace dimensions, the effective plan/allocation/control revision graph,
planning/KPI release, opening floors, ordered tiers, transfer/reversal, cancellation,
balance and commitment carry-forward/return, legacy successors and domain adapters.

The source OU extension's caller-controlled privileged context is not copied.
Company/assigned-OU checks and explicit cross-OU Budget roles are enforced by the
target. The source period lacks a company field; company scoping is an intentional
security redesign. Transaction-date KPI capacity filtering is NOT REQUIRED because
the selected source does not use transaction dates to select spending capacity.

Existing target history remains auditable without fabricated source approvals.
Real source-format XLSX/data conversion, reconciliation, filestore, browser, load
and deployment are PRODUCTION READINESS. Current final all-domain evidence is in
the workspace migration-closure-report.md; older test reports retain milestone
history and do not override this mapping.
