# Browser and visual UAT acceptance

Scope: synthetic reference company, actual ordinary-user sessions in Chromium,
Odoo 20 Community. This is engineering UAT, not an assertion of business-owner
signoff or government print-form certification. No production records were used.

| Check | Result | Evidence |
|---|---|---|
| Requester and assigned reviewer | PASS | Rendered PR form; submit/approve under separate sessions; requester cannot self-approve; reviewer and decision timestamp visible |
| Organization manager | PASS | OU name/code/parent/active fields render; cross-company context injection denied |
| Budget allocation/plan/release | PASS | Actual lifecycle buttons and separate reviewer; exact amount and release/reviewer records checked |
| Procurement → WA → bill → actual → Asset | PASS | Actual role transitions, PO and WA states, posted bill, two controlled actual entries, one acquisition and validated engine |
| Finance | PASS | WA field visible to accountant; native abnormal-amount confirmation followed; linked credit note posted and Contract capacity reconciled |
| Expense / advance | PASS | Native submit/approve, linked accounting move and posted state |
| Agreement | PASS | Activate, immutable version snapshot, reactivate and terminate |
| Stock request / return | PASS | Submit/approve, receipt validation, native direct return creation and returned delivered quantity zero |
| Depreciation / disposal | PASS | Depreciation-board action, removal policy and reason, removal move explicitly posted |
| AUC transfer | PASS | Expense-origin acquisition, scoped AUC engine, actual transfer dialog, posted journal and conserved destination value |
| Unauthorized/direct URL | PASS | Forbidden forms/actions, source IDs and attachments denied over authenticated HTTP |
| Role-manager escalation | PASS | System-group injection, self-delegation and mapping-delegation creation denied |
| Employee controller | PASS | Hidden OU employee and foreign-company IDs not disclosed by org-chart endpoint |
| Attachments/image | PASS | Five representative nonempty files downloaded with exact sizes/SHA-256; company logo bytes returned |
| Visual form review | PASS | PR reviewer table, OU form, Thai WA labels, Finance bill, Agreement history, Asset lifecycle; no broken assets or blocking layout overlap at 1440×1000 |

Visual review confirmed document sequences (PR/WA/Asset), monetary precision,
Bangkok timestamps, reviewer rows and workflow controls. The synthetic company
uses USD and English locale with existing Thai government field labels. This does
not validate a configured THB production chart, Thai tax localization, custom
printed forms or an organization-specific date-display policy. Those are deployment
configuration choices, not automatic conversion of historical currency.

Some inherited screens retain technical display names and English labels. These
are nonblocking presentation limitations of the preserved migration baseline;
this run does not redesign the UI. Screenshots immediately after actions can show
a transient old status while the RPC state already changed; final screenshots
reload the record where the status itself is being accepted.

Failure traces are retained only for failed test attempts and stop before login
credentials are entered. Passing tests retain no trace archive. Evidence is outside
Git. Earlier failures caused by stale selectors, missing wizard confirmation,
wrong fixture fields and duplicate synthetic expenses are superseded by focused
passes and the final full browser suite; they are not silently erased.

## Final combined acceptance

`browser-final-restored/browser-results.json` reports **25 passed, zero failed,
zero skipped, zero flaky**, with zero retries, on the restored populated database.
It includes eight transaction/lifecycle cases, nine role forms, five dedicated
negative security cases, authorized attachment/image integrity, separate requester
and approver transitions, and an authenticated WebSocket handshake through Caddy.
Security cases are a subset of 25, not additional tests to add to that total.
Final Budget release, Agreement termination/version history and Asset removal
screenshots were visually reviewed after reload; their displayed states agree with
workflow assertions. The distinct final archive restore smoke repeats sixteen
read-only form/security/file/WebSocket cases on a fresh restored database.
