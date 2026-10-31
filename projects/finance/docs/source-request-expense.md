# Approved purchase request to Expense/Advance

Status: **REDESIGNED** on Odoo 20's individual expense approval.

Exact source: NSTDA-pinned OCA l10n-thailand commit
`f793617ebabe618969c119dd68017bb120c3453f`,
`l10n_th_gov_hr_expense/models/{hr_expense,purchase_request}.py` and Ecosoft
`budgeting/l10n_th_gov_hr_expense_budget_control` at `08842c565308`.
The public reference was retrieved into a separate temporary checkout; the existing
upstream source tree was not changed.

Source requires the employee's approved PR, creates expense or advance lines,
checks requested untaxed amount (explicit HR manager override), releases the PR
commitment on expense approval, and blocks PR reset/rejection while an active
expense uses it. Advance clearing uses its advance rather than a second PR.

The target assigns one PR line to one approved native expense/advance. Submission
simulates the release and replacement in a savepoint; final approval atomically
releases the entire PR line commitment and creates the expense/advance commitment.
The new expense amount can be smaller, releasing the unused difference. Distinct PR
lines can be processed individually, replacing the obsolete sheet-level all-lines
conversion. Duplicate approved claims and mixed PO/Expense conversion are rejected.
The original PR remains approved and its claim is derived from the linked approved
expense, rather than creating another capacity-bearing status or ledger.

Requester, company, OU, fund, analytic and extra dimensions must match the approved
PR's fiscal destination. Budget resolves carried PRs through its existing API.
Expense/advance activity still selects its own authorized KPI, including the special
Advance reservation. Reset/refusal restores the PR only if current budget allows;
if another real request consumed the released variance, restoration rolls back.
Posted expense accounting and historical identities remain immutable/reversible.

All related PR, expense, advance and carry controls are collected and locked in
sorted order before document locks. Invoice posting includes the same full scope.
Scope/manager overrides cannot be forged through client defaults or RPC. Captured
amount snapshots retain the PR line, approved amount and explicit override flag.
The Expense form selects its PR line and copies native/budget defaults.

Runtime evidence under `/tmp/erp-org-odoo20`:
- `closure-request-expense-01.log`: 2 tests, 0 failures/errors.
- `closure-request-expense-cross-01.log`: 183 Budget/Procurement/Finance/Contract
  tests, 0 failures/errors, including PR-funded advance clearing/return, source
  permissions and atomic rejection of an unsafe restoration.
- `closure-request-expense-forward-02.log`: fiscal-forward handoff/post/reset passes.
  The first fixture used today's native accounting date against a future period;
  it correctly failed and was rerun with the destination-year accounting date.
- `closure-request-expense-race-01.log`: two real approval transactions claim one
  PR line; one commits, one serializes; a fresh retry rejects the duplicate.
  Consumption80 remains one expense, and winner reset restores the PR100.

No skipped tests reported. Production conversion, browser and historical attachment
rehearsal are separate readiness work. The final full suites also cover the last
snapshot and explicit default-context override protections.
