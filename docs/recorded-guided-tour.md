# Recorded Guided Tour validation

Validated 1 November 2026. Run ID: `20261101T100742907Z`.

Architecture: real Odoo → Playwright UI capture and authenticated read assertions → manifest/steps/screenshots/video → Python builder → static Shepherd.js 15.2.3 replay. The former independent mock workflow and simulated access rules have been replaced by generated recorded evidence.

The selected evidence is a **read-only walkthrough of persisted PROJECT70 transactions**, not a demonstration that creates every transaction from scratch. Primary login: `interactive-demo`. Security logins: `uat_other_ou`, `uat_foreign`, `uat_unauthorized`; protected request is from the separate synthetic UAT security fixture. Actual Odoo dialogs prove read-access denials. Approval/posting-denial action tests are not claimed by this recording.

| Check | Result |
| --- | --- |
| Real Odoo Playwright run | PASS, 13 main checkpoints + 3 security checkpoints |
| Before/after PROJECT70 data | Identical for projects, budgets, orders, requests, acceptances, bills, assets, stock quantities, contracts |
| Canonical screenshot / video viewport | 1920 × 1080 |
| Selected screenshots | 16 PNGs, all hashes and dimensions checked |
| Raw video | 5 valid WebM sessions, positive duration, 1920 × 1080; not published |
| Static build | PASS, validates metadata, references, hashes, privacy review, financial/quantity totals |
| Builder rejection tests | 8 PASS, including invalid hotspot, modified screenshot, missing review, duplicate ID, unknown reference, traversal and bad financial totals |
| Desktop browser | PASS at 1440 × 1000 |
| Mobile browser | PASS at 390 × 844; hotspot scales with screenshot, no document-level horizontal overflow |
| Static browser interaction | Start, Next, Back, Finish, Exit, Restart, document navigation, relationships and security tour PASS |
| Console / page errors in static browser | None |
| Odoo unhandled page errors | None |
| External requests from static replay | None; static server only |
| Restore rehearsal / fresh installation | NOT TESTED in this work; uses existing demo DB |
| YouTube upload / synthesized voice / deployment | Not performed |

PROJECT70 has 2 projects, 15 tasks and 4 milestones, with total allocated budget 1,800,000 THB. Digital-project budget reconciles as 1,000,000 = 222,000 actual + 60,000 committed + 718,000 remaining. The computer PO is confirmed, acceptance quantity is 6 and the vendor bill is posted. Six assets total 210,000 THB; ERP asset state is draft while the depreciation records are open. Material balances are 80 at main stock plus 20 at the service location.

Published source and selected evidence:

- [Recorder instructions](../playwright-demo/README.md)
- [Generated manifest](../guided-tour/generated/manifest.json)
- [Final state](../guided-tour/generated/final-state.json)
- [Relationships](../guided-tour/generated/relationships.json)
- [Narration](../guided-tour/generated/narration.json)
- [Generated storyboard](../guided-tour/generated/video-storyboard.md)
- [Subtitle timing hints](../guided-tour/generated/subtitle-hints.json)

Private local evidence remains in `playwright-demo/output/20261101T100742907Z/`; it is ignored by Git. Successful-run traces are discarded. Login occurs outside recording contexts, and no storageState file is written. Failure traces and raw recordings must remain private even when the synthetic screenshots have been reviewed for publication.

Local example URLs: real Odoo `http://localhost:18069`; static tour `http://localhost:18765/guided-tour/`. GitHub Pages placeholder: `https://<username>.github.io/<repository>/guided-tour/`. No push or publishing performed by the pipeline.
