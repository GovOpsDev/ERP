# GitHub publication package

This directory is a consolidated source snapshot of the original `org` workspace,
prepared on 31 October 2026. It includes current tracked file contents and
non-ignored new source files from all nine original repositories, including work
that had not yet been committed there. The original worktrees are preserved.

## Included

- Shared foundation and all seven ERP domains, including vendored addon source and
  existing third-party notices.
- Thai translations, recent Agreement UI/date/history improvements, and all 15
  HTML user guides with 10 synthetic screenshots.
- Workspace documentation, reference Compose configuration and readiness tools.
- The upstream AGPL-3.0 license text and project attribution.

The source snapshot initially contains 702 files from the original worktrees.
Publication metadata and documentation are additional files. The source revision
and dirty-tree state of each original repository are in `source-snapshot.json`.
`source-checksums.sha256` records SHA-256 values of the original 702 file contents,
before the packaging-only edits listed in the snapshot metadata. It is a provenance
record, not a checksum list to run against the adjusted publication files.

## Publication adjustments

The root `.gitignore` now allows `shared/` and `projects/` to be tracked. The root
README, layout documentation and the opening source instructions in the runbook
explain the consolidated repository. Business addon source is copied byte for byte.
The original Git histories are not merged: their commit IDs and statuses are
retained as provenance in this single-repository snapshot.

After the initial snapshot commit, nine Markdown documents were updated at the
publisher's request to normalize the local home-directory prefix to `/`. These
are documentation-only publication adjustments; the original checksum record
continues to describe the initial source contents.

## Excluded

Nested `.git` directories, installed `node_modules`, Python caches, database dumps,
filestores, sessions, local passwords/secrets and external runtime/test-evidence
archives are not part of this source package. Screenshots shipped with manuals
are deliberately synthetic documentation assets and are included.

## Working with the publication

Use this directory as the repository root for GitHub. The source trees are normal
tracked directories, not submodules. Follow the README and runbook to prepare a new
runtime and configure its own secrets and database. Historical release reports
refer to the original source layout and external evidence; copying source does not
re-run those acceptance suites or include an already configured database.

The root LICENSE was copied from the inspected upstream checkout and verified
byte-for-byte. Existing licenses in addon manifests and file headers are preserved.

## Thai warehouse dashboard follow-up

`erp_dashboard_th` was added after the initial source snapshot, together with its
read-only acceptance script and documentation. It localizes the standard warehouse
dashboard response for Thai users and preserves the stored workbook and access
controls. See [dashboard-th.md](dashboard-th.md) for scoped runtime evidence.
The initial source checksums remain a historical provenance record.

## THB defaults follow-up

ERP Core `20.0.1.1.0` adds new-company THB defaults and guarded Thailand/THB
initialization of Odoo's pristine placeholder. Explicit and parent currencies,
configured companies and existing economic records are preserved. See
[thb-defaults.md](thb-defaults.md) for clean-install, local upgrade and separate
THB-company acceptance. The initial source checksum file remains provenance for
the original snapshot, before these documented follow-up source changes.

## Budget settings tab follow-up

ERP Budget `20.0.2.27.2` consolidates its two duplicate Settings tabs into one,
retaining both setting blocks and all company values. See
[budget-settings.md](budget-settings.md) for scoped upgrade acceptance.
